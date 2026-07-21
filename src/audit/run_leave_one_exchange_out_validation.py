# -*- coding: utf-8 -*-
"""
Leave-one-exchange-out validation using already processed minute data.

This script rebuilds all exchange-weighted objects from processed per-exchange
CSV files under dv_ready_2021_2022. It does not download Kaggle data and does
not redo raw-data cleaning. For each scenario (FULL plus one excluded venue),
it recomputes valid minutes, dollar-volume shares, max_share, HHI, dominant
exchange, VWAP, LWMP, pivot exchange, lock-in, VWAP proximity, DV-only LWMP
pivot switchability, and fixed-weight dominant-price pass-through.

Math notes used in diagnostics and README:
    VWAP = m p_d + (1 - m) p_non_dom, so
    VWAP - p_d = (1 - m)(p_non_dom - p_d).
    In the fixed-weight dominant-price displacement audit,
    kappa_VWAP = max_share.

    LWMP is the first price whose cumulative dollar-volume weight reaches 0.5.
    If max_share > 0.5, the dominant exchange must be the LWMP pivot, so under
    lock-in the dominant-price displacement pass-through for LWMP should be
    close to 1 for small price shocks.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


EXCHANGES = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
SCENARIOS = [("FULL", None)] + [(f"EXCL_{ex}", ex) for ex in EXCHANGES]

TIME_CANDIDATES = ["time_utc_dt", "time_utc", "timestamp", "datetime", "date"]
PRICE_CANDIDATES = ["p_usd_scaled", "p_usd", "price_usd", "price", "close", "Close"]
DV_CANDIDATES = ["DV_usd", "dollar_volume", "dv_usd"]

DELTA_W_VALUES = [-0.5, 0.5, 1.0, 2.0]
SHOCK_TYPES = ["inflate_only", "reallocate_total_fixed"]
LAMBDA_VALUES = [-0.001, 0.001, -0.01, 0.01]


@dataclass
class ScenarioState:
    scenario: str
    excluded_exchange: str
    exchanges: list[str]
    times: pd.DatetimeIndex
    prices: np.ndarray
    weights: np.ndarray
    shares: np.ndarray
    valid_mask: np.ndarray
    vwap: np.ndarray
    lwmp: np.ndarray
    pivot_idx: np.ndarray
    dominant_idx: np.ndarray
    max_share: np.ndarray
    hhi: np.ndarray
    lock_in: np.ndarray
    n_exchanges_valid: np.ndarray
    weight_sum_error: np.ndarray
    calendar_minutes: int
    valid_minutes_before_min_venues: int


def norm_col(c: str) -> str:
    return str(c).strip().lower().replace(" ", "_")


def pick_column(columns: Iterable[str], candidates: list[str]) -> str | None:
    norm_map = {norm_col(c): c for c in columns}
    for cand in candidates:
        hit = norm_map.get(norm_col(cand))
        if hit is not None:
            return hit
    return None


def infer_exchange_name(path: Path) -> str | None:
    name = path.stem.lower()
    for ex in EXCHANGES:
        if ex.lower() in name:
            return ex
    return None


def detect_price_rule(columns: list[str]) -> tuple[str, list[str]]:
    primary = pick_column(columns, PRICE_CANDIDATES)
    if primary is not None:
        return f"column:{primary}", [primary]

    open_col = pick_column(columns, ["open", "Open"])
    high_col = pick_column(columns, ["high", "High"])
    low_col = pick_column(columns, ["low", "Low"])
    close_col = pick_column(columns, ["close", "Close"])

    if open_col and high_col and low_col and close_col:
        return "OHLC4", [open_col, high_col, low_col, close_col]
    if high_col and low_col:
        return "HL2", [high_col, low_col]

    raise ValueError(f"Cannot detect a usable price column or OHLC/HL2 columns from: {columns}")


def compute_price(df: pd.DataFrame, rule: str, cols: list[str]) -> pd.Series:
    if rule.startswith("column:"):
        return pd.to_numeric(df[cols[0]], errors="coerce")
    if rule == "OHLC4":
        o, h, l, c = cols
        return (
            pd.to_numeric(df[o], errors="coerce")
            + pd.to_numeric(df[h], errors="coerce")
            + pd.to_numeric(df[l], errors="coerce")
            + pd.to_numeric(df[c], errors="coerce")
        ) / 4.0
    if rule == "HL2":
        h, l = cols
        return (pd.to_numeric(df[h], errors="coerce") + pd.to_numeric(df[l], errors="coerce")) / 2.0
    raise RuntimeError(f"Unexpected price rule: {rule}")


def load_one_exchange(path: Path) -> tuple[str, pd.Series, pd.Series, dict]:
    exchange = infer_exchange_name(path)
    if exchange is None:
        raise ValueError(f"Cannot infer supported exchange name from {path.name}")

    columns = list(pd.read_csv(path, nrows=0).columns)
    time_col = pick_column(columns, TIME_CANDIDATES)
    dv_col = pick_column(columns, DV_CANDIDATES)
    price_rule, price_cols = detect_price_rule(columns)

    if time_col is None or dv_col is None:
        raise ValueError(f"{path.name} missing required columns: time={time_col}, dv={dv_col}")

    usecols = list(dict.fromkeys([time_col, dv_col] + price_cols))
    raw_rows = 0
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    raw_rows = int(len(df))

    t = pd.to_datetime(df[time_col], errors="coerce", utc=True).dt.floor("min")
    price = compute_price(df, price_rule, price_cols)
    dv = pd.to_numeric(df[dv_col], errors="coerce")

    tmp = pd.DataFrame({"time_utc": t, "price": price, "dv": dv})
    invalid_time = int(tmp["time_utc"].isna().sum())
    tmp = tmp.dropna(subset=["time_utc"]).copy()

    duplicate_rows = int(tmp.duplicated("time_utc").sum())
    tmp = tmp.sort_values("time_utc").drop_duplicates("time_utc", keep="last")

    price_missing_or_nonpositive = int((~np.isfinite(tmp["price"].to_numpy(float)) | (tmp["price"].to_numpy(float) <= 0)).sum())
    dv_missing_or_nonpositive = int((~np.isfinite(tmp["dv"].to_numpy(float)) | (tmp["dv"].to_numpy(float) <= 0)).sum())
    negative_dv = int((tmp["dv"].to_numpy(float) < 0).sum())

    price_series = tmp.set_index("time_utc")["price"].astype("float64")
    dv_series = tmp.set_index("time_utc")["dv"].astype("float64")

    meta = {
        "exchange": exchange,
        "file": path.name,
        "path": str(path),
        "raw_rows": raw_rows,
        "rows_after_time_drop": int(len(tmp) + duplicate_rows),
        "unique_minutes": int(len(tmp)),
        "time_col": time_col,
        "price_rule": price_rule,
        "price_cols": ",".join(price_cols),
        "dv_col": dv_col,
        "invalid_time_rows": invalid_time,
        "duplicate_timestamp_rows": duplicate_rows,
        "price_missing_or_nonpositive_rows": price_missing_or_nonpositive,
        "dv_missing_or_nonpositive_rows": dv_missing_or_nonpositive,
        "negative_dv_rows": negative_dv,
    }
    return exchange, price_series, dv_series, meta


def load_processed_wide(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    files = sorted(input_dir.glob("*.csv"))
    found: dict[str, Path] = {}
    for fp in files:
        ex = infer_exchange_name(fp)
        if ex in EXCHANGES:
            found[ex] = fp

    missing = [ex for ex in EXCHANGES if ex not in found]
    if missing:
        raise FileNotFoundError(f"Missing processed files for exchanges: {missing}. Input dir: {input_dir}")

    price_series = {}
    weight_series = {}
    metas = []
    for ex in EXCHANGES:
        exchange, p, w, meta = load_one_exchange(found[ex])
        print(
            f"[LOAD] {exchange:9s} minutes={len(p):,} "
            f"price={meta['price_rule']} dv={meta['dv_col']} duplicates={meta['duplicate_timestamp_rows']:,}"
        )
        price_series[exchange] = p.rename(exchange)
        weight_series[exchange] = w.rename(exchange)
        metas.append(meta)

    prices = pd.concat(price_series.values(), axis=1).sort_index()
    weights = pd.concat(weight_series.values(), axis=1).sort_index()
    prices = prices[EXCHANGES]
    weights = weights[EXCHANGES]
    return prices, weights, pd.DataFrame(metas)


def weighted_median_with_pivot(prices: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n, _ = prices.shape
    valid = np.isfinite(prices) & (prices > 0) & np.isfinite(weights) & (weights > 0)
    w = np.where(valid, weights, 0.0)
    key = np.where(valid, prices, np.inf)

    order = np.argsort(key, axis=1, kind="mergesort")
    p_sorted = np.take_along_axis(prices, order, axis=1)
    w_sorted = np.take_along_axis(w, order, axis=1)
    cumw = np.cumsum(w_sorted, axis=1)
    totalw = w_sorted.sum(axis=1)
    cutoff = 0.5 * totalw
    hit = cumw >= cutoff[:, None]
    idx_sorted = hit.argmax(axis=1)

    lwmp = p_sorted[np.arange(n), idx_sorted]
    pivot = order[np.arange(n), idx_sorted].astype(int)
    no_weight = totalw <= 0
    lwmp = np.where(no_weight, np.nan, lwmp)
    pivot = np.where(no_weight, -1, pivot)
    return lwmp.astype(float), pivot.astype(int)


def compute_state(
    scenario: str,
    excluded_exchange: str | None,
    prices_wide: pd.DataFrame,
    weights_wide: pd.DataFrame,
    min_venues: int,
) -> ScenarioState:
    exchanges = [ex for ex in EXCHANGES if ex != excluded_exchange]
    p_all = prices_wide[exchanges].to_numpy(dtype=float)
    w_all = weights_wide[exchanges].to_numpy(dtype=float)

    valid = np.isfinite(p_all) & (p_all > 0) & np.isfinite(w_all) & (w_all > 0)
    w_clean = np.where(valid, w_all, 0.0)
    p_clean = np.where(valid, p_all, np.nan)
    n_valid = valid.sum(axis=1).astype(int)
    total = w_clean.sum(axis=1)
    before_min_venues = int((total > 0).sum())
    keep = (n_valid >= min_venues) & (total > 0)

    times = pd.DatetimeIndex(prices_wide.index[keep])
    p = p_clean[keep]
    w = w_clean[keep]
    valid_keep = valid[keep]
    n_valid_keep = n_valid[keep]
    total_keep = w.sum(axis=1)

    shares = np.divide(w, total_keep[:, None], out=np.zeros_like(w), where=total_keep[:, None] > 0)
    weight_sum_error = np.abs(shares.sum(axis=1) - 1.0)
    vwap = np.nansum(p * shares, axis=1)
    lwmp, pivot_idx = weighted_median_with_pivot(p, shares)
    dominant_idx = shares.argmax(axis=1).astype(int)
    max_share = shares[np.arange(len(shares)), dominant_idx]
    hhi = (shares ** 2).sum(axis=1)
    lock_in = max_share > 0.5

    return ScenarioState(
        scenario=scenario,
        excluded_exchange=excluded_exchange or "",
        exchanges=exchanges,
        times=times,
        prices=p,
        weights=w,
        shares=shares,
        valid_mask=valid_keep,
        vwap=vwap,
        lwmp=lwmp,
        pivot_idx=pivot_idx,
        dominant_idx=dominant_idx,
        max_share=max_share,
        hhi=hhi,
        lock_in=lock_in,
        n_exchanges_valid=n_valid_keep,
        weight_sum_error=weight_sum_error,
        calendar_minutes=int(len(prices_wide)),
        valid_minutes_before_min_venues=before_min_venues,
    )


def q(x: np.ndarray, prob: float) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.quantile(x, prob)) if x.size else np.nan


def median(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(np.median(x)) if x.size else np.nan


def scenario_summary(state: ScenarioState) -> tuple[dict, pd.DataFrame]:
    dom_names = np.array(state.exchanges, dtype=object)[state.dominant_idx]
    valid_minutes = int(len(state.times))
    lockin_minutes = int(state.lock_in.sum())
    dom_counts = pd.Series(dom_names).value_counts(dropna=True)
    top_dom = str(dom_counts.index[0]) if len(dom_counts) else ""
    top_share = float(dom_counts.iloc[0] / valid_minutes) if valid_minutes else np.nan

    row = {
        "scenario": state.scenario,
        "excluded_exchange": state.excluded_exchange,
        "n_exchanges_used": len(state.exchanges),
        "valid_minutes": valid_minutes,
        "share_valid_minutes_relative_to_full_calendar": valid_minutes / state.calendar_minutes if state.calendar_minutes else np.nan,
        "lockin_minutes": lockin_minutes,
        "lockin_share": lockin_minutes / valid_minutes if valid_minutes else np.nan,
        "median_max_share": median(state.max_share),
        "p90_max_share": q(state.max_share, 0.90),
        "p95_max_share": q(state.max_share, 0.95),
        "median_HHI": median(state.hhi),
        "p95_HHI": q(state.hhi, 0.95),
        "top_dominant_exchange": top_dom,
        "top_dominant_exchange_share": top_share,
        "n_dominant_exchanges_observed": int(dom_counts.size),
    }

    dist = dom_counts.rename_axis("dominant_exchange").reset_index(name="minutes")
    dist.insert(0, "excluded_exchange", state.excluded_exchange)
    dist.insert(0, "scenario", state.scenario)
    dist["share"] = dist["minutes"] / valid_minutes if valid_minutes else np.nan
    return row, dist


def spell_summary(state: ScenarioState) -> dict:
    valid_minutes = int(len(state.times))
    lockin_share = float(state.lock_in.mean()) if valid_minutes else np.nan
    locked_times = pd.DatetimeIndex(state.times[state.lock_in])
    if len(locked_times) == 0:
        durations = np.array([], dtype=float)
    else:
        diffs = locked_times.to_series(index=np.arange(len(locked_times))).diff()
        starts = diffs.ne(pd.Timedelta(minutes=1)).to_numpy(copy=True)
        starts[0] = True
        spell_id = np.cumsum(starts)
        durations = pd.Series(spell_id).value_counts(sort=False).to_numpy(dtype=float)

    return {
        "scenario": state.scenario,
        "excluded_exchange": state.excluded_exchange,
        "lockin_share": lockin_share,
        "n_spells": int(durations.size),
        "median_spell_min": median(durations),
        "p90_spell_min": q(durations, 0.90),
        "p95_spell_min": q(durations, 0.95),
        "max_spell_min": float(np.max(durations)) if durations.size else np.nan,
        "share_spells_ge_60": float(np.mean(durations >= 60)) if durations.size else np.nan,
        "share_spells_ge_360": float(np.mean(durations >= 360)) if durations.size else np.nan,
        "share_spells_ge_1440": float(np.mean(durations >= 1440)) if durations.size else np.nan,
    }


def vwap_proximity_bins(state: ScenarioState, nbins: int) -> pd.DataFrame:
    dom_price = state.prices[np.arange(len(state.times)), state.dominant_idx]
    gap = np.abs(state.vwap - dom_price) / state.vwap
    gap_bps = 10000.0 * gap
    tmp = pd.DataFrame({"max_share": state.max_share, "gap_bps": gap_bps})
    tmp = tmp[np.isfinite(tmp["max_share"]) & np.isfinite(tmp["gap_bps"])].copy()
    if tmp.empty:
        return pd.DataFrame()

    unique = int(tmp["max_share"].nunique())
    if unique <= 1:
        tmp["bin"] = 1
    else:
        qbins = min(int(nbins), unique)
        tmp["bin"] = pd.qcut(tmp["max_share"], q=qbins, labels=False, duplicates="drop") + 1

    rows = []
    for b, g in tmp.groupby("bin", observed=True):
        x = g["max_share"].to_numpy(float)
        y = g["gap_bps"].to_numpy(float)
        lo = float(np.min(x))
        hi = float(np.max(x))
        rows.append({
            "scenario": state.scenario,
            "excluded_exchange": state.excluded_exchange,
            "bin": int(b),
            "n": int(len(g)),
            "max_share_min": lo,
            "max_share_max": hi,
            "max_share_mid": 0.5 * (lo + hi),
            "median_max_share": median(x),
            "mean_gap_bps": float(np.mean(y)) if y.size else np.nan,
            "median_gap_bps": median(y),
            "q90_gap_bps": q(y, 0.90),
            "q95_gap_bps": q(y, 0.95),
            "q99_gap_bps": q(y, 0.99),
        })
    return pd.DataFrame(rows)


def wilson_ci(success: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    phat = success / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    margin = z * np.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n) / denom
    return float(max(0.0, center - margin)), float(min(1.0, center + margin))


def build_sample_events(state: ScenarioState, sample_events: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, int]:
    flat_valid = np.flatnonzero(state.valid_mask.ravel())
    total_candidates = int(flat_valid.size)
    if sample_events <= 0 or sample_events >= total_candidates:
        chosen = flat_valid
    else:
        chosen = rng.choice(flat_valid, size=int(sample_events), replace=False)
    ncols = state.valid_mask.shape[1]
    return (chosen // ncols).astype(int), (chosen % ncols).astype(int), total_candidates


def append_event_rows(
    event_path: Path,
    rows_idx: np.ndarray,
    shocked_idx: np.ndarray,
    state: ScenarioState,
    shock_type: str,
    delta_w: float,
    new_pivot: np.ndarray,
    ok: np.ndarray,
    write_header: bool,
) -> None:
    fieldnames = [
        "scenario",
        "excluded_exchange",
        "time_utc",
        "exchange_shocked",
        "shock_type",
        "delta_w",
        "original_pivot",
        "new_pivot",
        "pivot_changed",
        "original_dominant_exchange",
        "original_max_share",
        "lock_in",
    ]
    event_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with event_path.open(mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        exchanges = state.exchanges
        for i in np.flatnonzero(ok):
            r = int(rows_idx[i])
            original_pivot = int(state.pivot_idx[r])
            npiv = int(new_pivot[i])
            writer.writerow({
                "scenario": state.scenario,
                "excluded_exchange": state.excluded_exchange,
                "time_utc": state.times[r].isoformat(),
                "exchange_shocked": exchanges[int(shocked_idx[i])],
                "shock_type": shock_type,
                "delta_w": float(delta_w),
                "original_pivot": exchanges[original_pivot] if original_pivot >= 0 else "",
                "new_pivot": exchanges[npiv] if npiv >= 0 else "",
                "pivot_changed": int(npiv != original_pivot and original_pivot >= 0 and npiv >= 0),
                "original_dominant_exchange": exchanges[int(state.dominant_idx[r])],
                "original_max_share": float(state.max_share[r]),
                "lock_in": int(state.lock_in[r]),
            })


def run_pivot_switchability(
    state: ScenarioState,
    sample_events: int,
    rng: np.random.Generator,
    event_path: Path,
    write_event_level: bool,
    event_header_state: dict,
) -> tuple[pd.DataFrame, list[dict]]:
    rows_idx, shocked_idx, total_candidates = build_sample_events(state, sample_events, rng)
    diagnostics = [{
        "scenario": state.scenario,
        "check": "sampled_candidate_events",
        "status": "PASS",
        "value": int(len(rows_idx)),
        "detail": f"total_candidates={total_candidates}",
    }]

    if len(rows_idx) == 0:
        return pd.DataFrame(), diagnostics

    p0 = state.prices[rows_idx].copy()
    w0 = state.weights[rows_idx].copy()
    s0 = state.shares[rows_idx].copy()
    pivot0 = state.pivot_idx[rows_idx]
    max_share0 = state.max_share[rows_idx]
    lock0 = state.lock_in[rows_idx]
    n = len(rows_idx)
    ar = np.arange(n)

    summary_rows = []
    for shock_type in SHOCK_TYPES:
        for delta_w in DELTA_W_VALUES:
            if shock_type == "inflate_only":
                w_new = w0.copy()
                factor = 1.0 + float(delta_w)
                ok = factor > 0
                if ok:
                    w_new[ar, shocked_idx] = w_new[ar, shocked_idx] * factor
                    _, new_pivot = weighted_median_with_pivot(p0, w_new)
                    ok_mask = new_pivot >= 0
                else:
                    new_pivot = np.full(n, -1, dtype=int)
                    ok_mask = np.zeros(n, dtype=bool)
            elif shock_type == "reallocate_total_fixed":
                s_i = s0[ar, shocked_idx]
                s_i_new = s_i * (1.0 + float(delta_w))
                ok_mask = (s_i_new > 0) & (s_i_new < 1) & (s_i < 1)
                s_new = s0.copy()
                scale = np.ones(n)
                scale[ok_mask] = (1.0 - s_i_new[ok_mask]) / (1.0 - s_i[ok_mask])
                s_new = s_new * scale[:, None]
                s_new[ar, shocked_idx] = s_i_new
                s_new[~ok_mask, :] = 0.0
                _, new_pivot = weighted_median_with_pivot(p0, s_new)
                ok_mask = ok_mask & (new_pivot >= 0)
            else:
                continue

            changed = (new_pivot != pivot0) & (pivot0 >= 0) & ok_mask
            for lock_value in [0, 1]:
                sel = ok_mask & (lock0 == bool(lock_value))
                n_events = int(sel.sum())
                successes = int(changed[sel].sum()) if n_events else 0
                low, high = wilson_ci(successes, n_events)
                summary_rows.append({
                    "scenario": state.scenario,
                    "excluded_exchange": state.excluded_exchange,
                    "shock_type": shock_type,
                    "delta_w": float(delta_w),
                    "lock_in": int(lock_value),
                    "n_events": n_events,
                    "pivot_change_rate": successes / n_events if n_events else np.nan,
                    "wilson_ci_low": low,
                    "wilson_ci_high": high,
                    "median_max_share": median(max_share0[sel]),
                    "mean_max_share": float(np.mean(max_share0[sel])) if n_events else np.nan,
                })

            diagnostics.append({
                "scenario": state.scenario,
                "check": "valid_event_shocks",
                "status": "PASS" if int(ok_mask.sum()) > 0 else "WARN",
                "value": int(ok_mask.sum()),
                "detail": f"shock_type={shock_type}; delta_w={delta_w}; sampled_events={n}",
            })

            if write_event_level:
                append_event_rows(
                    event_path=event_path,
                    rows_idx=rows_idx,
                    shocked_idx=shocked_idx,
                    state=state,
                    shock_type=shock_type,
                    delta_w=float(delta_w),
                    new_pivot=new_pivot,
                    ok=ok_mask,
                    write_header=not event_header_state.get("written", False),
                )
                event_header_state["written"] = True

    return pd.DataFrame(summary_rows), diagnostics


def run_price_displacement(state: ScenarioState) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    rows = []
    sanity_rows = []
    diagnostics = []
    n = len(state.times)
    ar = np.arange(n)
    dom_price = state.prices[ar, state.dominant_idx]

    for lam in LAMBDA_VALUES:
        p_new = state.prices.copy()
        p_new[ar, state.dominant_idx] = dom_price * (1.0 + float(lam))
        vwap_new = np.nansum(p_new * state.shares, axis=1)
        lwmp_new, _ = weighted_median_with_pivot(p_new, state.shares)

        denom = float(lam) * dom_price
        ok = np.isfinite(denom) & (denom != 0)
        k_vwap = np.full(n, np.nan, dtype=float)
        k_lwmp = np.full(n, np.nan, dtype=float)
        k_vwap[ok] = (vwap_new[ok] - state.vwap[ok]) / denom[ok]
        k_lwmp[ok] = (lwmp_new[ok] - state.lwmp[ok]) / denom[ok]

        diff = np.abs(k_vwap - state.max_share)
        max_abs = float(np.nanmax(diff)) if np.isfinite(diff).any() else np.nan
        mean_abs = float(np.nanmean(diff)) if np.isfinite(diff).any() else np.nan
        sanity_rows.append({
            "scenario": state.scenario,
            "excluded_exchange": state.excluded_exchange,
            "lambda": float(lam),
            "max_abs_kappa_vwap_minus_max_share": max_abs,
            "mean_abs_kappa_vwap_minus_max_share": mean_abs,
        })
        diagnostics.append({
            "scenario": state.scenario,
            "check": "vwap_kappa_equals_max_share",
            "status": "PASS" if (np.isfinite(max_abs) and max_abs < 1e-8) else "WARN",
            "value": max_abs,
            "detail": f"lambda={lam}; mean_abs={mean_abs}",
        })

        for lock_value in [0, 1]:
            sel = ok & (state.lock_in == bool(lock_value)) & np.isfinite(k_vwap) & np.isfinite(k_lwmp)
            n_sel = int(sel.sum())
            kv = k_vwap[sel]
            kl = k_lwmp[sel]
            rows.append({
                "scenario": state.scenario,
                "excluded_exchange": state.excluded_exchange,
                "lambda": float(lam),
                "lock_in": int(lock_value),
                "n": n_sel,
                "vwap_kappa_mean": float(np.mean(kv)) if n_sel else np.nan,
                "vwap_kappa_median": median(kv),
                "vwap_kappa_q05": q(kv, 0.05),
                "vwap_kappa_q95": q(kv, 0.95),
                "lwmp_kappa_mean": float(np.mean(kl)) if n_sel else np.nan,
                "lwmp_kappa_median": median(kl),
                "lwmp_kappa_q05": q(kl, 0.05),
                "lwmp_kappa_q95": q(kl, 0.95),
                "lwmp_zero_share": float(np.mean(np.isclose(kl, 0.0, atol=1e-12))) if n_sel else np.nan,
                "median_max_share": median(state.max_share[sel]),
                "mean_max_share": float(np.mean(state.max_share[sel])) if n_sel else np.nan,
            })

    return pd.DataFrame(rows), pd.DataFrame(sanity_rows), diagnostics


def scenario_diagnostics(state: ScenarioState) -> list[dict]:
    diag = []
    max_weight_error = float(np.max(state.weight_sum_error)) if len(state.weight_sum_error) else np.nan
    diag.append({
        "scenario": state.scenario,
        "check": "weight_sums_close_to_one",
        "status": "PASS" if np.isfinite(max_weight_error) and max_weight_error < 1e-10 else "WARN",
        "value": max_weight_error,
        "detail": "max abs(sum(normalized weights)-1) among valid minutes",
    })
    diag.append({
        "scenario": state.scenario,
        "check": "valid_minutes",
        "status": "PASS" if len(state.times) > 0 else "FAIL",
        "value": int(len(state.times)),
        "detail": f"before_min_venues={state.valid_minutes_before_min_venues}; min_venues filtered={state.valid_minutes_before_min_venues - len(state.times)}",
    })
    diag.append({
        "scenario": state.scenario,
        "check": "n_exchanges_used",
        "status": "PASS" if len(state.exchanges) >= 3 else "FAIL",
        "value": int(len(state.exchanges)),
        "detail": ",".join(state.exchanges),
    })
    if state.lock_in.any():
        ratio = float(np.mean(state.pivot_idx[state.lock_in] == state.dominant_idx[state.lock_in]))
        status = "PASS" if ratio > 0.999 else "WARN"
    else:
        ratio = np.nan
        status = "WARN"
    diag.append({
        "scenario": state.scenario,
        "check": "lockin_pivot_equals_dominant_ratio",
        "status": status,
        "value": ratio,
        "detail": "Expected to be near 1 when max_share > 0.5; exact ties can lower it.",
    })
    neg = int((state.weights < 0).sum())
    diag.append({
        "scenario": state.scenario,
        "check": "negative_weights_after_cleaning",
        "status": "PASS" if neg == 0 else "FAIL",
        "value": neg,
        "detail": "Scenario arrays set invalid/nonpositive weights to zero before normalization.",
    })
    return diag


def metadata_diagnostics(meta: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in meta.iterrows():
        rows.append({
            "scenario": "INPUT",
            "check": "duplicate_timestamps",
            "status": "PASS" if int(r["duplicate_timestamp_rows"]) == 0 else "WARN",
            "value": int(r["duplicate_timestamp_rows"]),
            "detail": f"{r['exchange']} file={r['file']}",
        })
        drop_total = int(r["price_missing_or_nonpositive_rows"]) + int(r["dv_missing_or_nonpositive_rows"])
        rows.append({
            "scenario": "INPUT",
            "check": "missing_or_nonpositive_price_dv",
            "status": "PASS" if drop_total == 0 else "WARN",
            "value": drop_total,
            "detail": (
                f"{r['exchange']} price_missing_or_nonpositive={r['price_missing_or_nonpositive_rows']}; "
                f"dv_missing_or_nonpositive={r['dv_missing_or_nonpositive_rows']}"
            ),
        })
        rows.append({
            "scenario": "INPUT",
            "check": "negative_dv_in_processed_file",
            "status": "PASS" if int(r["negative_dv_rows"]) == 0 else "WARN",
            "value": int(r["negative_dv_rows"]),
            "detail": f"{r['exchange']} file={r['file']}",
        })
    return rows


def make_main_contrast(
    scenario_df: pd.DataFrame,
    pivot_df: pd.DataFrame,
    pass_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    rows = []
    diagnostics = []
    for _, srow in scenario_df.iterrows():
        scenario = srow["scenario"]
        ex = srow["excluded_exchange"]
        psub = pivot_df[pivot_df["scenario"] == scenario]
        baseline = psub[(psub["shock_type"] == "reallocate_total_fixed") & (np.isclose(psub["delta_w"], 1.0))]
        use = baseline
        source = "reallocate_total_fixed_delta_1p0"
        if baseline.empty or baseline["n_events"].fillna(0).min() <= 0:
            use = psub[(psub["shock_type"] == "inflate_only") & (np.isclose(psub["delta_w"], 1.0))]
            source = "inflate_only_delta_1p0_fallback"
            diagnostics.append({
                "scenario": scenario,
                "check": "main_contrast_pivot_baseline_source",
                "status": "WARN",
                "value": source,
                "detail": "Reallocate total fixed delta_w=1.0 had insufficient sample.",
            })
        else:
            diagnostics.append({
                "scenario": scenario,
                "check": "main_contrast_pivot_baseline_source",
                "status": "PASS",
                "value": source,
                "detail": "Using requested baseline pivot-change definition.",
            })

        def pivot_rate(lock_value: int) -> float:
            g = use[use["lock_in"] == lock_value]
            return float(g["pivot_change_rate"].iloc[0]) if len(g) else np.nan

        piv_non = pivot_rate(0)
        piv_lock = pivot_rate(1)
        ratio = piv_lock / piv_non if np.isfinite(piv_lock) and np.isfinite(piv_non) and piv_non != 0 else np.nan

        ptd = pass_df[(pass_df["scenario"] == scenario) & (np.isclose(pass_df["lambda"], 0.001))]

        def pass_val(col: str, lock_value: int) -> float:
            g = ptd[ptd["lock_in"] == lock_value]
            return float(g[col].iloc[0]) if len(g) else np.nan

        vwap_non = pass_val("vwap_kappa_median", 0)
        vwap_lock = pass_val("vwap_kappa_median", 1)
        lwmp_non = pass_val("lwmp_kappa_median", 0)
        lwmp_lock = pass_val("lwmp_kappa_median", 1)

        direction = (
            np.isfinite(piv_non) and np.isfinite(piv_lock) and piv_lock < piv_non
            and np.isfinite(lwmp_lock) and np.isfinite(vwap_lock) and np.isfinite(vwap_non)
            and vwap_lock > vwap_non
        )
        if direction and abs(lwmp_lock - 1.0) <= 0.10 and (piv_non - piv_lock) >= 0.02:
            verdict = "Main contrast preserved"
        elif direction and abs(lwmp_lock - 1.0) <= 0.25:
            verdict = "Weaker but preserved"
        else:
            verdict = "Mechanism altered"

        rows.append({
            "scenario": scenario,
            "excluded_exchange": ex,
            "valid_minutes": int(srow["valid_minutes"]),
            "lockin_share": float(srow["lockin_share"]),
            "median_max_share": float(srow["median_max_share"]),
            "lwmp_pivot_change_nonlockin_baseline": piv_non,
            "lwmp_pivot_change_lockin_baseline": piv_lock,
            "lwmp_pivot_change_ratio_lockin_to_nonlockin": ratio,
            "vwap_kappa_median_nonlockin_lambda_0p001": vwap_non,
            "vwap_kappa_median_lockin_lambda_0p001": vwap_lock,
            "lwmp_kappa_median_nonlockin_lambda_0p001": lwmp_non,
            "lwmp_kappa_median_lockin_lambda_0p001": lwmp_lock,
            "verdict": verdict,
        })
    return pd.DataFrame(rows), diagnostics


def dataframe_to_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_excel(
    out_xlsx: Path,
    tables: dict[str, pd.DataFrame],
    readme: pd.DataFrame,
) -> None:
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        readme.to_excel(writer, index=False, sheet_name="README")
        for name, df in tables.items():
            df.to_excel(writer, index=False, sheet_name=name[:31])


def build_readme(
    args: argparse.Namespace,
    meta: pd.DataFrame,
    run_ts: str,
    script_path: Path,
) -> pd.DataFrame:
    items = [
        ("run_timestamp_utc", run_ts),
        ("root_path", str(Path(args.root))),
        ("input_directory", str(Path(args.input_dir))),
        ("output_directory", str(Path(args.out_dir))),
        ("exchanges_used", ", ".join(EXCHANGES)),
        ("min_venues", args.min_venues),
        ("sample_events_per_scenario", args.sample_events),
        ("seed", args.seed),
        ("delta_w_values", ", ".join(map(str, DELTA_W_VALUES))),
        ("shock_types", ", ".join(SHOCK_TYPES)),
        ("lambda_values", ", ".join(map(str, LAMBDA_VALUES))),
        ("nbins", args.nbins),
        ("script_path", str(script_path)),
        ("vwap_note", "P_vwap = m p_d + (1-m) p_non_dom, so P_vwap - p_d = (1-m)(p_non_dom - p_d)."),
        ("vwap_displacement_note", "With fixed weights and dominant price displacement, kappa_VWAP = max_share."),
        ("lwmp_note", "LWMP is the first price whose cumulative weight reaches 0.5."),
        ("lwmp_lockin_note", "If max_share > 0.5, the dominant exchange must be the LWMP pivot; lock-in LWMP pass-through should be close to 1."),
        ("vwap_bins_note", "VWAP proximity bins are max_share quantile bins computed independently within each scenario."),
    ]
    for _, r in meta.iterrows():
        items.append((f"{r['exchange']}_price_rule", r["price_rule"]))
        items.append((f"{r['exchange']}_price_columns", r["price_cols"]))
        items.append((f"{r['exchange']}_dv_column", r["dv_col"]))
        items.append((f"{r['exchange']}_time_column", r["time_col"]))
    return pd.DataFrame(items, columns=["item", "value"])


def parse_args() -> argparse.Namespace:
    root_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run leave-one-exchange-out validation from processed DV data.")
    parser.add_argument("--root", default=str(root_default), help="Project root.")
    parser.add_argument("--input-dir", default=None, help="Processed per-exchange CSV directory.")
    parser.add_argument("--out-dir", default=None, help="Output directory.")
    parser.add_argument("--min-venues", type=int, default=3)
    parser.add_argument("--sample-events", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20260604)
    parser.add_argument("--nbins", type=int, default=10)
    parser.add_argument("--write-event-level", dest="write_event_level", action="store_true", default=True)
    parser.add_argument("--no-event-level", dest="write_event_level", action="store_false")
    args = parser.parse_args()

    root = Path(args.root)
    if args.input_dir is None:
        args.input_dir = str(root / "dv_ready_2021_2022")
    if args.out_dir is None:
        args.out_dir = str(root / "outputs" / "robustness" / "leave_one_exchange_out")
    return args


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    tables_dir = out_dir / "tables"
    event_dir = out_dir / "event_level"
    diagnostics_dir = out_dir / "diagnostics"
    runinfo_dir = out_dir / "runinfo"
    for d in [tables_dir, event_dir, diagnostics_dir, runinfo_dir]:
        d.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now(timezone.utc).isoformat()
    script_path = Path(__file__).resolve()

    print(f"[INFO] root: {root}")
    print(f"[INFO] input: {input_dir}")
    print(f"[INFO] output: {out_dir}")
    prices_wide, weights_wide, meta = load_processed_wide(input_dir)
    rng = np.random.default_rng(args.seed)

    event_path = event_dir / "lwmp_pivot_events_sample.csv"
    event_header_state = {"written": False}

    scenario_rows = []
    dominant_dist_frames = []
    spell_rows = []
    vwap_bins_frames = []
    pivot_frames = []
    pass_frames = []
    sanity_frames = []
    diagnostics_rows = metadata_diagnostics(meta)

    for scenario, excluded in SCENARIOS:
        print(f"[SCENARIO] {scenario}")
        state = compute_state(scenario, excluded, prices_wide, weights_wide, args.min_venues)

        srow, dist = scenario_summary(state)
        scenario_rows.append(srow)
        dominant_dist_frames.append(dist)
        spell_rows.append(spell_summary(state))
        vwap_bins_frames.append(vwap_proximity_bins(state, args.nbins))
        diagnostics_rows.extend(scenario_diagnostics(state))

        pivot_df, pivot_diag = run_pivot_switchability(
            state=state,
            sample_events=args.sample_events,
            rng=rng,
            event_path=event_path,
            write_event_level=args.write_event_level,
            event_header_state=event_header_state,
        )
        pivot_frames.append(pivot_df)
        diagnostics_rows.extend(pivot_diag)

        pass_df, sanity_df, pass_diag = run_price_displacement(state)
        pass_frames.append(pass_df)
        sanity_frames.append(sanity_df)
        diagnostics_rows.extend(pass_diag)

    scenario_df = pd.DataFrame(scenario_rows)
    dominant_df = pd.concat(dominant_dist_frames, ignore_index=True) if dominant_dist_frames else pd.DataFrame()
    spell_df = pd.DataFrame(spell_rows)
    vwap_bins_df = pd.concat(vwap_bins_frames, ignore_index=True) if vwap_bins_frames else pd.DataFrame()
    pivot_df = pd.concat(pivot_frames, ignore_index=True) if pivot_frames else pd.DataFrame()
    pass_df = pd.concat(pass_frames, ignore_index=True) if pass_frames else pd.DataFrame()
    sanity_df = pd.concat(sanity_frames, ignore_index=True) if sanity_frames else pd.DataFrame()

    main_contrast_df, main_diag = make_main_contrast(scenario_df, pivot_df, pass_df)
    diagnostics_rows.extend(main_diag)
    diagnostics_df = pd.DataFrame(diagnostics_rows)
    diagnostics_pass = not diagnostics_df["status"].eq("FAIL").any()

    dataframe_to_csv(scenario_df, tables_dir / "scenario_summary.csv")
    dataframe_to_csv(dominant_df, tables_dir / "dominant_distribution.csv")
    dataframe_to_csv(spell_df, tables_dir / "spell_summary.csv")
    dataframe_to_csv(vwap_bins_df, tables_dir / "vwap_proximity_bins.csv")
    dataframe_to_csv(pivot_df, tables_dir / "lwmp_pivot_switchability_summary.csv")
    dataframe_to_csv(pass_df, tables_dir / "settlement_pass_through_summary.csv")
    dataframe_to_csv(main_contrast_df, tables_dir / "main_contrast_summary.csv")
    dataframe_to_csv(sanity_df, diagnostics_dir / "vwap_kappa_sanity_checks.csv")
    dataframe_to_csv(meta, diagnostics_dir / "input_file_metadata.csv")
    dataframe_to_csv(diagnostics_df, diagnostics_dir / "diagnostics.csv")

    readme_df = build_readme(args, meta, run_ts, script_path)
    tables = {
        "scenario_summary": scenario_df,
        "dominant_distribution": dominant_df,
        "spell_summary": spell_df,
        "vwap_proximity_bins": vwap_bins_df,
        "lwmp_pivot_switchability": pivot_df,
        "settlement_pass_through": pass_df,
        "main_contrast_summary": main_contrast_df,
        "diagnostics": diagnostics_df,
    }
    out_xlsx = tables_dir / "leave_one_exchange_out_validation.xlsx"
    write_excel(out_xlsx, tables, readme_df)

    runinfo = [
        f"run_timestamp_utc={run_ts}",
        f"root={root}",
        f"input_dir={input_dir}",
        f"out_dir={out_dir}",
        f"script_path={script_path}",
        f"min_venues={args.min_venues}",
        f"sample_events_per_scenario={args.sample_events}",
        f"seed={args.seed}",
        f"nbins={args.nbins}",
        f"write_event_level={args.write_event_level}",
        f"diagnostics_pass={diagnostics_pass}",
        f"excel_path={out_xlsx}",
    ]
    (runinfo_dir / "leave_one_exchange_out_runinfo.txt").write_text("\n".join(runinfo), encoding="utf-8")

    print("\n[DONE]")
    print(f"Excel file: {out_xlsx}")
    print("\nmain_contrast_summary:")
    print(main_contrast_df.to_string(index=False))
    print(f"\nDiagnostics pass: {diagnostics_pass}")


if __name__ == "__main__":
    main()

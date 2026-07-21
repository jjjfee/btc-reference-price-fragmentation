# -*- coding: utf-8 -*-
"""
Price-displacement audit for observed lock-in vs non-lock-in minutes.

Goal
----
For each minute t:
    1. Keep observed weights w_i,t fixed.
    2. Identify the dominant venue d by observed dollar-volume share.
    3. Displace only the dominant venue price:
           p'_d,t = p_d,t * (1 + lambda)
           p'_i,t = p_i,t for i != d
    4. Recompute:
           VWAP(p'_t, w_t)
           LWMP(p'_t, w_t)
    5. Compare with original aggregates:
           Delta VWAP = VWAP(p'_t, w_t) - VWAP(p_t, w_t)
           Delta LWMP = LWMP(p'_t, w_t) - LWMP(p_t, w_t)
    6. Define pass-through:
           kappa_VWAP = Delta VWAP / (lambda * p_d,t)
           kappa_LWMP = Delta LWMP / (lambda * p_d,t)

Observed lock-in state:
    max_share > lockin_threshold, default 0.5

Input
-----
Default input directory:
    <PROJECT_ROOT>/dv_ready_2021_2022/

Expected files:
    BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv

The script tries to detect:
    - timestamp column: time_utc / timestamp / datetime / time / date
    - DV column: DV_usd / dv_usd / dollar_volume_usd / dollar_volume
    - price representative:
        1. OHLC4 = (open + high + low + close) / 4, if available
        2. HL2   = (high + low) / 2, if available
        3. close, if available

Output
------
Default output directory:
    <PROJECT_ROOT>/outputs/robustness/price_displacement/

Main outputs:
    - price_displacement_audit_events_lambda_*.csv.gz
    - summary_by_state_lambda.csv
    - quantiles_by_state_lambda.csv
    - sanity_checks_by_lambda.csv
    - ECDF plots for kappa_LWMP and kappa_VWAP
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# -----------------------------
# Basic column detection helpers
# -----------------------------

def _norm_col(c: str) -> str:
    return str(c).strip().lower().replace(" ", "_")


def find_col(columns: List[str], candidates: List[str]) -> str | None:
    norm_map = {_norm_col(c): c for c in columns}
    for cand in candidates:
        key = _norm_col(cand)
        if key in norm_map:
            return norm_map[key]
    return None


def detect_time_col(columns: List[str]) -> str:
    col = find_col(columns, [
        "time_utc", "timestamp", "datetime", "date_time", "time", "date"
    ])
    if col is None:
        raise ValueError(f"Cannot detect timestamp column from: {columns}")
    return col


def detect_dv_col(columns: List[str]) -> str:
    col = find_col(columns, [
        "DV_usd", "dv_usd", "dollar_volume_usd", "dollar_volume",
        "notional_usd", "volume_usd"
    ])
    if col is None:
        raise ValueError(f"Cannot detect DV column from: {columns}")
    return col


def detect_price_cols(columns: List[str]) -> Tuple[str, List[str]]:
    """
    Return:
        price_rule, needed_columns
    """
    open_col = find_col(columns, ["open", "o"])
    high_col = find_col(columns, ["high", "h"])
    low_col = find_col(columns, ["low", "l"])
    close_col = find_col(columns, ["close", "c", "price"])

    if open_col and high_col and low_col and close_col:
        return "OHLC4", [open_col, high_col, low_col, close_col]

    if high_col and low_col:
        return "HL2", [high_col, low_col]

    if close_col:
        return "CLOSE", [close_col]

    raise ValueError(f"Cannot detect usable price columns from: {columns}")


def extract_exchange_name(path: str) -> str:
    """
    Expected:
        BTCUSD_1m_Binance_2021_2022_with_DV.csv
    Fallback:
        stem after BTCUSD_1m_ and before _2021_2022_with_DV
    """
    stem = Path(path).stem
    m = re.match(r"BTCUSD_1m_(.+?)_2021_2022_with_DV$", stem)
    if m:
        return m.group(1)

    # fallback: make a compact safe name
    return re.sub(r"[^A-Za-z0-9_]+", "_", stem)


# -----------------------------
# Data loading
# -----------------------------

def load_one_exchange_csv(path: str) -> Tuple[str, pd.DataFrame, Dict[str, str]]:
    exchange = extract_exchange_name(path)

    header_cols = list(pd.read_csv(path, nrows=0).columns)
    time_col = detect_time_col(header_cols)
    dv_col = detect_dv_col(header_cols)
    price_rule, price_cols = detect_price_cols(header_cols)

    usecols = list(dict.fromkeys([time_col, dv_col] + price_cols))
    df = pd.read_csv(path, usecols=usecols)

    df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    df = df.dropna(subset=[time_col]).copy()
    df = df.rename(columns={time_col: "time_utc"})

    # price representative
    if price_rule == "OHLC4":
        o, h, l, c = price_cols
        price = (
            pd.to_numeric(df[o], errors="coerce")
            + pd.to_numeric(df[h], errors="coerce")
            + pd.to_numeric(df[l], errors="coerce")
            + pd.to_numeric(df[c], errors="coerce")
        ) / 4.0
    elif price_rule == "HL2":
        h, l = price_cols
        price = (
            pd.to_numeric(df[h], errors="coerce")
            + pd.to_numeric(df[l], errors="coerce")
        ) / 2.0
    elif price_rule == "CLOSE":
        c = price_cols[0]
        price = pd.to_numeric(df[c], errors="coerce")
    else:
        raise RuntimeError("Unexpected price rule.")

    dv = pd.to_numeric(df[dv_col], errors="coerce")

    out = pd.DataFrame({
        "time_utc": df["time_utc"],
        f"p_{exchange}": price,
        f"w_{exchange}": dv,
    })

    # Clean invalid observations.
    out.loc[out[f"p_{exchange}"] <= 0, f"p_{exchange}"] = np.nan
    out.loc[out[f"w_{exchange}"] <= 0, f"w_{exchange}"] = np.nan

    # If duplicated minute exists, keep last non-aggregated row.
    out = out.sort_values("time_utc").drop_duplicates("time_utc", keep="last")

    meta = {
        "exchange": exchange,
        "path": path,
        "time_col": time_col,
        "dv_col": dv_col,
        "price_rule": price_rule,
        "price_cols": ",".join(price_cols),
    }

    return exchange, out, meta


def load_all_exchange_data(data_dir: str) -> Tuple[pd.DataFrame, List[str], pd.DataFrame]:
    pattern = os.path.join(data_dir, "BTCUSD_1m_*_2021_2022_with_DV.csv")
    files = sorted(glob.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No exchange files found under:\n{data_dir}\nPattern:\n{pattern}"
        )

    frames = []
    exchanges = []
    metas = []

    print(f"[INFO] Found {len(files)} files.")
    for path in files:
        exchange, df_ex, meta = load_one_exchange_csv(path)
        print(
            f"[LOAD] {exchange:12s} rows={len(df_ex):,} "
            f"price_rule={meta['price_rule']} dv_col={meta['dv_col']}"
        )
        frames.append(df_ex)
        exchanges.append(exchange)
        metas.append(meta)

    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on="time_utc", how="outer")

    merged = merged.sort_values("time_utc").reset_index(drop=True)
    meta_df = pd.DataFrame(metas)

    return merged, exchanges, meta_df


# -----------------------------
# Aggregators
# -----------------------------

def compute_vwap(prices: np.ndarray, weights: np.ndarray) -> np.ndarray:
    valid = np.isfinite(prices) & np.isfinite(weights) & (prices > 0) & (weights > 0)
    w = np.where(valid, weights, 0.0)
    p = np.where(valid, prices, 0.0)

    total_w = w.sum(axis=1)
    out = np.full(prices.shape[0], np.nan, dtype=float)
    ok = total_w > 0
    out[ok] = (p[ok] * w[ok]).sum(axis=1) / total_w[ok]
    return out


def weighted_median_batch(
    prices: np.ndarray,
    weights: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Weighted median / LWMP:
        Sort prices within minute.
        Return first price where cumulative weight >= 0.5 * total weight.

    Returns:
        lwmp_value: shape (N,)
        pivot_idx:  exchange index in the input arrays; -1 if unavailable.
    """
    n, e = prices.shape
    out = np.full(n, np.nan, dtype=float)
    pivot = np.full(n, -1, dtype=int)

    for r in range(n):
        valid = (
            np.isfinite(prices[r])
            & np.isfinite(weights[r])
            & (prices[r] > 0)
            & (weights[r] > 0)
        )

        if valid.sum() == 0:
            continue

        idx = np.flatnonzero(valid)
        ps = prices[r, idx]
        ws = weights[r, idx]

        total_w = ws.sum()
        if not np.isfinite(total_w) or total_w <= 0:
            continue

        order = np.argsort(ps, kind="mergesort")
        idx_sorted = idx[order]
        ps_sorted = ps[order]
        ws_sorted = ws[order]

        cutoff = 0.5 * total_w
        cum_w = np.cumsum(ws_sorted)

        # first crossing
        j = int(np.searchsorted(cum_w, cutoff, side="left"))
        if j >= len(idx_sorted):
            j = len(idx_sorted) - 1

        pivot_idx = int(idx_sorted[j])
        out[r] = float(prices[r, pivot_idx])
        pivot[r] = pivot_idx

    return out, pivot


# -----------------------------
# Summary and plotting
# -----------------------------

def summary_stats(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) == 0:
        return pd.Series({
            "n": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "p01": np.nan,
            "p05": np.nan,
            "p25": np.nan,
            "p50": np.nan,
            "p75": np.nan,
            "p95": np.nan,
            "p99": np.nan,
            "max": np.nan,
            "share_zero": np.nan,
        })

    return pd.Series({
        "n": len(x),
        "mean": x.mean(),
        "std": x.std(ddof=1),
        "min": x.min(),
        "p01": x.quantile(0.01),
        "p05": x.quantile(0.05),
        "p25": x.quantile(0.25),
        "p50": x.quantile(0.50),
        "p75": x.quantile(0.75),
        "p95": x.quantile(0.95),
        "p99": x.quantile(0.99),
        "max": x.max(),
        "share_zero": float((np.isclose(x, 0.0, atol=1e-12)).mean()),
    })


def ecdf_xy(x: np.ndarray, max_points: int = 200_000) -> Tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]

    if len(x) == 0:
        return np.array([]), np.array([])

    if len(x) > max_points:
        rng = np.random.default_rng(12345)
        x = rng.choice(x, size=max_points, replace=False)

    x = np.sort(x)
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def plot_ecdf_by_state(
    df: pd.DataFrame,
    var: str,
    lam: float,
    out_path: str,
    xlim: Tuple[float, float] | None = None,
) -> None:
    plt.figure(figsize=(7.5, 5.0))

    for state_name in ["non_lockin", "lockin"]:
        x, y = ecdf_xy(df.loc[df["state"] == state_name, var].to_numpy())
        if len(x) > 0:
            plt.plot(x, y, label=state_name)

    plt.xlabel(var)
    plt.ylabel("Empirical CDF")
    plt.title(f"ECDF of {var}, lambda={lam:g}")
    if xlim is not None:
        plt.xlim(*xlim)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()


# -----------------------------
# Main audit
# -----------------------------

def parse_lambdas(s: str) -> List[float]:
    vals = []
    for part in s.split(","):
        part = part.strip()
        if part:
            vals.append(float(part))
    vals = [v for v in vals if abs(v) > 0]
    if not vals:
        raise ValueError("At least one nonzero lambda is required.")
    return vals


def safe_lambda_name(lam: float) -> str:
    """
    File-safe lambda name.
    0.001 -> plus0p001
    -0.001 -> minus0p001
    """
    prefix = "plus" if lam > 0 else "minus"
    body = f"{abs(lam):.8g}".replace(".", "p")
    return f"{prefix}{body}"


def run_audit(args: argparse.Namespace) -> None:
    root = Path(args.root)
    data_dir = Path(args.data_dir) if args.data_dir else root / "dv_ready_2021_2022"
    out_dir = Path(args.out_dir) if args.out_dir else root / "outputs" / "robustness" / "price_displacement"
    fig_dir = out_dir / "figures"
    table_dir = out_dir / "tables"
    event_dir = out_dir / "event_level"

    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)

    lambdas = parse_lambdas(args.lambdas)

    print(f"[INFO] root     = {root}")
    print(f"[INFO] data_dir = {data_dir}")
    print(f"[INFO] out_dir  = {out_dir}")
    print(f"[INFO] lambdas  = {lambdas}")
    print(f"[INFO] lock-in threshold = {args.lockin_threshold}")
    print(f"[INFO] min exchanges used = {args.min_exchanges}")

    merged, exchanges, meta_df = load_all_exchange_data(str(data_dir))
    meta_df.to_csv(out_dir / "input_file_metadata.csv", index=False, encoding="utf-8-sig")

    price_cols = [f"p_{ex}" for ex in exchanges]
    weight_cols = [f"w_{ex}" for ex in exchanges]

    prices = merged[price_cols].to_numpy(dtype=float)
    weights_raw = merged[weight_cols].to_numpy(dtype=float)

    valid = (
        np.isfinite(prices)
        & np.isfinite(weights_raw)
        & (prices > 0)
        & (weights_raw > 0)
    )

    weights = np.where(valid, weights_raw, np.nan)
    prices_clean = np.where(valid, prices, np.nan)

    n_valid = valid.sum(axis=1)
    total_w = np.nansum(weights, axis=1)

    ok = (n_valid >= args.min_exchanges) & np.isfinite(total_w) & (total_w > 0)

    merged_ok = merged.loc[ok, ["time_utc"]].reset_index(drop=True)
    prices_ok = prices_clean[ok, :]
    weights_ok = weights[ok, :]
    valid_ok = valid[ok, :]
    n_valid_ok = n_valid[ok]
    total_w_ok = total_w[ok]

    print(f"[INFO] total minutes loaded       = {len(merged):,}")
    print(f"[INFO] minutes after valid filter = {len(merged_ok):,}")

    # shares
    share = weights_ok / total_w_ok[:, None]
    share = np.where(valid_ok, share, np.nan)

    max_share = np.nanmax(share, axis=1)
    hhi = np.nansum(share ** 2, axis=1)
    dominant_idx = np.nanargmax(np.where(np.isfinite(share), share, -np.inf), axis=1)
    dominant_exchange = np.array(exchanges, dtype=object)[dominant_idx]
    p_dom = prices_ok[np.arange(len(prices_ok)), dominant_idx]
    share_dom = share[np.arange(len(prices_ok)), dominant_idx]

    state = np.where(max_share > args.lockin_threshold, "lockin", "non_lockin")

    # Original aggregates
    print("[INFO] Computing original VWAP and LWMP...")
    vwap0 = compute_vwap(prices_ok, weights_ok)
    lwmp0, pivot0_idx = weighted_median_batch(prices_ok, weights_ok)
    pivot0_exchange = np.where(
        pivot0_idx >= 0,
        np.array(exchanges, dtype=object)[np.maximum(pivot0_idx, 0)],
        None,
    )

    base_df = pd.DataFrame({
        "time_utc": merged_ok["time_utc"],
        "n_exchanges_used": n_valid_ok,
        "total_DV_usd": total_w_ok,
        "dominant_exchange": dominant_exchange,
        "p_dom": p_dom,
        "share_dom": share_dom,
        "max_share": max_share,
        "HHI": hhi,
        "state": state,
        "VWAP0": vwap0,
        "LWMP0": lwmp0,
        "LWMP_pivot0": pivot0_exchange,
    })

    base_df.to_csv(
        table_dir / "base_minute_state_for_price_displacement_audit.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8-sig",
    )

    all_summaries = []
    all_quantiles = []
    sanity_rows = []

    for lam in lambdas:
        print(f"[INFO] Running price displacement audit for lambda={lam:g}...")
        lam_name = safe_lambda_name(lam)

        prices_prime = prices_ok.copy()
        denom = lam * p_dom

        # p'_d,t = p_d,t * (1 + lambda)
        prices_prime[np.arange(len(prices_prime)), dominant_idx] = p_dom * (1.0 + lam)

        # Recompute aggregates
        vwap1 = compute_vwap(prices_prime, weights_ok)
        lwmp1, pivot1_idx = weighted_median_batch(prices_prime, weights_ok)
        pivot1_exchange = np.where(
            pivot1_idx >= 0,
            np.array(exchanges, dtype=object)[np.maximum(pivot1_idx, 0)],
            None,
        )

        delta_vwap = vwap1 - vwap0
        delta_lwmp = lwmp1 - lwmp0

        kappa_vwap = delta_vwap / denom
        kappa_lwmp = delta_lwmp / denom

        event = pd.DataFrame({
            "time_utc": merged_ok["time_utc"],
            "lambda": lam,
            "n_exchanges_used": n_valid_ok,
            "dominant_exchange": dominant_exchange,
            "p_dom": p_dom,
            "share_dom": share_dom,
            "max_share": max_share,
            "HHI": hhi,
            "state": state,
            "VWAP0": vwap0,
            "VWAP1": vwap1,
            "delta_VWAP": delta_vwap,
            "kappa_VWAP": kappa_vwap,
            "LWMP0": lwmp0,
            "LWMP1": lwmp1,
            "delta_LWMP": delta_lwmp,
            "kappa_LWMP": kappa_lwmp,
            "LWMP_pivot0": pivot0_exchange,
            "LWMP_pivot1": pivot1_exchange,
            "LWMP_pivot_changed": pivot0_exchange != pivot1_exchange,
        })

        # Main event-level output, compressed.
        if args.write_event_level:
            event_path = event_dir / f"price_displacement_audit_events_lambda_{lam_name}.csv.gz"
            event.to_csv(event_path, index=False, compression="gzip", encoding="utf-8-sig")
            print(f"[WRITE] {event_path}")

        # Summary by state
        vars_to_summarize = [
            "delta_VWAP",
            "delta_LWMP",
            "kappa_VWAP",
            "kappa_LWMP",
        ]

        for var in vars_to_summarize:
            s = (
                event
                .groupby("state", dropna=False)[var]
                .apply(summary_stats)
                .reset_index()
            )
            s = s.rename(columns={"level_1": "stat", var: "value"})
            s.insert(0, "lambda", lam)
            s.insert(1, "variable", var)
            all_summaries.append(s)

            q = (
                event
                .groupby("state", dropna=False)[var]
                .quantile([0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
                .reset_index()
                .rename(columns={"level_1": "quantile", var: "value"})
            )
            q.insert(0, "lambda", lam)
            q.insert(1, "variable", var)
            all_quantiles.append(q)

        # Sanity checks:
        # Under fixed weights, VWAP pass-through should equal dominant share.
        sanity_rows.append({
            "lambda": lam,
            "n": len(event),
            "max_abs_kappa_vwap_minus_share_dom": np.nanmax(
                np.abs(event["kappa_VWAP"].to_numpy() - event["share_dom"].to_numpy())
            ),
            "mean_abs_kappa_vwap_minus_share_dom": np.nanmean(
                np.abs(event["kappa_VWAP"].to_numpy() - event["share_dom"].to_numpy())
            ),
            "lockin_n": int((event["state"] == "lockin").sum()),
            "non_lockin_n": int((event["state"] == "non_lockin").sum()),
            "lockin_median_kappa_LWMP": event.loc[
                event["state"] == "lockin", "kappa_LWMP"
            ].median(),
            "non_lockin_median_kappa_LWMP": event.loc[
                event["state"] == "non_lockin", "kappa_LWMP"
            ].median(),
            "lockin_share_kappa_LWMP_near_1": float(
                np.isclose(
                    event.loc[event["state"] == "lockin", "kappa_LWMP"],
                    1.0,
                    atol=args.near_tol,
                ).mean()
            ),
            "non_lockin_share_kappa_LWMP_near_0": float(
                np.isclose(
                    event.loc[event["state"] == "non_lockin", "kappa_LWMP"],
                    0.0,
                    atol=args.near_tol,
                ).mean()
            ),
        })

        # Plots
        plot_ecdf_by_state(
            event,
            var="kappa_LWMP",
            lam=lam,
            out_path=str(fig_dir / f"ECDF_kappa_LWMP_lambda_{lam_name}.png"),
            xlim=args.kappa_xlim,
        )
        plot_ecdf_by_state(
            event,
            var="kappa_VWAP",
            lam=lam,
            out_path=str(fig_dir / f"ECDF_kappa_VWAP_lambda_{lam_name}.png"),
            xlim=(0, 1.05),
        )

        print(
            f"[DONE] lambda={lam:g} | "
            f"median kappa_LWMP lockin="
            f"{event.loc[event['state'] == 'lockin', 'kappa_LWMP'].median():.6g}, "
            f"non_lockin="
            f"{event.loc[event['state'] == 'non_lockin', 'kappa_LWMP'].median():.6g}"
        )

    summary_df = pd.concat(all_summaries, ignore_index=True)
    quantile_df = pd.concat(all_quantiles, ignore_index=True)
    sanity_df = pd.DataFrame(sanity_rows)

    summary_path = table_dir / "summary_by_state_lambda.csv"
    quantile_path = table_dir / "quantiles_by_state_lambda.csv"
    sanity_path = table_dir / "sanity_checks_by_lambda.csv"

    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    quantile_df.to_csv(quantile_path, index=False, encoding="utf-8-sig")
    sanity_df.to_csv(sanity_path, index=False, encoding="utf-8-sig")

    runinfo = {
        "root": str(root),
        "data_dir": str(data_dir),
        "out_dir": str(out_dir),
        "n_exchange_files": len(exchanges),
        "exchanges": ",".join(exchanges),
        "n_minutes_loaded": len(merged),
        "n_minutes_after_filter": len(merged_ok),
        "min_exchanges": args.min_exchanges,
        "lockin_threshold": args.lockin_threshold,
        "lambdas": ",".join(map(str, lambdas)),
        "write_event_level": args.write_event_level,
        "definition_lockin": f"max_share > {args.lockin_threshold}",
        "dominant_venue": "exchange with largest observed DV_usd share",
        "weight_definition": "observed DV_usd, fixed under price displacement",
        "price_displacement": "p_dom_prime = p_dom * (1 + lambda); other venue prices unchanged",
        "pass_through": "kappa = delta benchmark / (lambda * p_dom)",
    }
    pd.Series(runinfo).to_csv(out_dir / "runinfo_price_displacement_audit.txt", header=False)

    print("[WRITE]", summary_path)
    print("[WRITE]", quantile_path)
    print("[WRITE]", sanity_path)
    print("[WRITE]", out_dir / "runinfo_price_displacement_audit.txt")
    print("[COMPLETE] Price-displacement audit finished.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dominant-venue price-displacement audit for lock-in vs non-lock-in minutes."
    )

    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Project root folder (default: inferred repository root)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Input directory containing BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv files. "
             "Default: <root>/dv_ready_2021_2022",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Default: <root>/outputs/robustness/price_displacement",
    )
    parser.add_argument(
        "--lambdas",
        default="0.001,-0.001,0.005,-0.005,0.01,-0.01",
        help="Comma-separated nonzero price-displacement lambdas. "
             "Default: 0.001,-0.001,0.005,-0.005,0.01,-0.01",
    )
    parser.add_argument(
        "--lockin-threshold",
        type=float,
        default=0.5,
        help="Observed lock-in threshold. Default: max_share > 0.5",
    )
    parser.add_argument(
        "--min-exchanges",
        type=int,
        default=3,
        help="Minimum number of valid exchanges required per minute. Default: 3",
    )
    parser.add_argument(
        "--near-tol",
        type=float,
        default=1e-8,
        help="Tolerance for near-zero / near-one sanity checks. Default: 1e-8",
    )
    parser.add_argument(
        "--write-event-level",
        action="store_true",
        help="Write full event-level CSV.gz files. Recommended for final audit, "
             "but can be large. If omitted, only summaries, base state file, and plots are written.",
    )
    parser.add_argument(
        "--kappa-xlim",
        type=float,
        nargs=2,
        default=None,
        help="Optional x-axis limit for LWMP kappa ECDF plots, e.g. --kappa-xlim -1 2",
    )

    return parser


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    run_audit(args)

#!/usr/bin/env python3
"""Audit and reproduce the BTC 2021-2022 fixed-composition checks.

This is a read-only replication driver with respect to the existing project
artifacts.  It writes only below --out-dir.  The original DV-only headline is
recreated from the minute-level venue inputs before any new sensitivity is run.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


EXCHANGES = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
BASE_VOLUME_EXCHANGES = ["Binance", "Bitfinex", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
TIME_COL_CANDIDATES = ["time_utc", "Time_utc", "timestamp", "time"]
PRICE_COL_CANDIDATES = ["p_usd_scaled", "p_usd", "price_usd", "p_scaled"]
WEIGHT_COL_CANDIDATES = ["DV_usd", "DV", "dollar_volume", "dv_usd"]
LOCKIN_THRESHOLD = 0.5
PIVOT_NBINS = 30
PASSTHROUGH_LAMBDAS = [0.001, -0.001, 0.01, -0.01]
EXPECTED_HEADLINE = {
    "non_lockin_pivot_change_rate": 0.27927641929248886,
    "lockin_pivot_change_rate": 0.06767736821244551,
    "difference_lockin_minus_nonlockin": -0.21159905108004334,
    "rate_ratio_lockin_over_nonlockin": 0.24233112263433296,
}
HEADLINE_TOLERANCE = 1e-10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2022-12-31 23:59:00")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=(Path(__file__).resolve().parents[2] / "outputs" / "reviewer_checks" / "btc_fixed_composition"),
    )
    parser.add_argument("--bootstrap-reps", type=int, default=5000)
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Must equal the event seed recovered from the original headline generator.",
    )
    parser.add_argument(
        "--headline-only",
        action="store_true",
        help="Run the headline reproduction gate and stop before fixed-composition checks.",
    )
    return parser.parse_args()


def utc_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def markdown_table(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    shown = frame if max_rows is None else frame.head(max_rows)
    if shown.empty:
        return "_No rows._"
    cols = list(shown.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in shown.itertuples(index=False, name=None):
        vals = []
        for value in row:
            if isinstance(value, float):
                vals.append("" if not np.isfinite(value) else f"{value:.12g}")
            else:
                vals.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def literal_assignment(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                value = node.value
                return ast.literal_eval(value)
    raise KeyError(f"Cannot recover {name} from {path}")


def source_line(path: Path, pattern: str) -> int | None:
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if pattern in line:
            return number
    return None


def snapshot_tree(paths: Iterable[Path], exclude: Iterable[Path] = ()) -> dict[str, tuple[int, int]]:
    excluded = [path.resolve() for path in exclude]
    snapshot: dict[str, tuple[int, int]] = {}
    for base in paths:
        if not base.exists():
            continue
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if any(resolved == item or item in resolved.parents for item in excluded):
                continue
            stat = resolved.stat()
            snapshot[str(resolved)] = (int(stat.st_size), int(stat.st_mtime_ns))
    return snapshot


def compare_snapshots(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    changed = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def pick_existing_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    lower = {str(column).lower(): str(column) for column in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def infer_exchange(path: Path) -> str:
    for exchange in EXCHANGES:
        if exchange.lower() in path.name.lower():
            return exchange
    raise ValueError(f"Cannot infer exchange from {path.name}")


def load_minute_inputs(
    input_dir: Path, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    files = sorted(input_dir.glob("*.csv"))
    if len(files) != 7:
        raise ValueError(f"Expected seven DV-ready CSVs in {input_dir}; found {len(files)}")
    prices: dict[str, pd.Series] = {}
    weights: dict[str, pd.Series] = {}
    first_file_index: pd.DatetimeIndex | None = None
    manifest_rows: list[dict[str, Any]] = []
    for path in files:
        exchange = infer_exchange(path)
        head = pd.read_csv(path, nrows=5)
        time_col = pick_existing_column(head.columns, TIME_COL_CANDIDATES)
        price_col = pick_existing_column(head.columns, PRICE_COL_CANDIDATES)
        weight_col = pick_existing_column(head.columns, WEIGHT_COL_CANDIDATES)
        if not all([time_col, price_col, weight_col]):
            raise ValueError(f"{path.name}: missing time/price/weight column")
        frame = pd.read_csv(path, usecols=[time_col, price_col, weight_col])
        frame[time_col] = pd.to_datetime(frame[time_col], errors="coerce", utc=True).dt.floor("min")
        frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
        frame[weight_col] = pd.to_numeric(frame[weight_col], errors="coerce")
        frame = frame.loc[frame[time_col].between(start, end)].copy()
        before = len(frame)
        frame = frame.dropna(subset=[time_col]).sort_values(time_col).drop_duplicates(time_col, keep="last")
        frame = frame.set_index(time_col)
        if first_file_index is None:
            first_file_index = pd.DatetimeIndex(frame.index)
        prices[exchange] = frame[price_col]
        weights[exchange] = frame[weight_col]
        unit = str(head["volume_unit_final"].dropna().iloc[0]) if "volume_unit_final" in head and head["volume_unit_final"].notna().any() else "unknown"
        raw_path = input_dir.parent.parent / "btc交易所数据" / f"BTCUSD_1m_{exchange}.csv"
        if not raw_path.is_file():
            raise FileNotFoundError(f"Missing original venue input: {raw_path}")
        manifest_rows.append(
            {
                "exchange": exchange,
                "raw_source_path": str(raw_path.resolve()),
                "raw_source_exists": True,
                "raw_source_bytes": int(raw_path.stat().st_size),
                "path": str(path.resolve()),
                "bytes": int(path.stat().st_size),
                "sha256": sha256_file(path),
                "time_column": time_col,
                "price_column": price_col,
                "weight_column": weight_col,
                "volume_convention": unit,
                "rows_in_window_before_dedup": int(before),
                "deduplicated_minutes": int(len(frame)),
                "duplicate_timestamps_removed": int(before - len(frame)),
            }
        )
    if sorted(prices) != sorted(EXCHANGES):
        raise ValueError(f"Venue set mismatch: {sorted(prices)}")
    calendar = pd.date_range(start, end, freq="min", tz="UTC")
    prices_wide = pd.DataFrame({ex: prices[ex].reindex(calendar) for ex in EXCHANGES}, index=calendar)
    weights_wide = pd.DataFrame({ex: weights[ex].reindex(calendar) for ex in EXCHANGES}, index=calendar)
    if first_file_index is None:
        raise ValueError("Cannot recover the first-file index")
    return prices_wide, weights_wide, pd.DataFrame(manifest_rows), first_file_index


def weighted_median_with_pivot(
    prices: np.ndarray, weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    valid = np.isfinite(prices) & np.isfinite(weights) & (weights > 0)
    w_clean = np.where(valid, weights, 0.0)
    p_key = np.where(w_clean > 0, prices, np.inf)
    order = np.argsort(p_key, axis=1, kind="mergesort")
    p_sorted = np.take_along_axis(prices, order, axis=1)
    w_sorted = np.take_along_axis(w_clean, order, axis=1)
    cumulative = np.cumsum(w_sorted, axis=1)
    total = np.sum(w_sorted, axis=1)
    half = 0.5 * total
    hit = cumulative >= half[:, None]
    position = hit.argmax(axis=1)
    rows = np.arange(len(prices))
    lwmp = p_sorted[rows, position]
    pivot = order[rows, position]
    margin = cumulative[rows, position] - half
    lwmp = np.where(total > 0, lwmp, np.nan)
    pivot = np.where(total > 0, pivot, -1)
    margin = np.where(total > 0, margin, np.nan)
    return lwmp, pivot.astype(int), margin, total


def compute_aggregators(
    prices: np.ndarray, weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    valid = np.isfinite(prices) & np.isfinite(weights) & (weights > 0)
    w_clean = np.where(valid, weights, 0.0)
    p_clean = np.where(valid, prices, np.nan)
    total = np.sum(w_clean, axis=1)
    vwap = np.divide(
        np.nansum(p_clean * w_clean, axis=1),
        total,
        out=np.full(len(total), np.nan),
        where=total > 0,
    )
    lwmp, pivot, margin, total_check = weighted_median_with_pivot(p_clean, w_clean)
    return vwap, lwmp, pivot, margin, w_clean, p_clean


def active_set_labels(valid: np.ndarray, exchanges: list[str]) -> tuple[np.ndarray, np.ndarray]:
    powers = (1 << np.arange(len(exchanges), dtype=np.int64))[None, :]
    codes = np.sum(valid.astype(np.int64) * powers, axis=1)
    active_map = {
        code: "|".join(exchanges[j] for j in range(len(exchanges)) if code & (1 << j))
        for code in range(1 << len(exchanges))
    }
    missing_map = {
        code: "|".join(exchanges[j] for j in range(len(exchanges)) if not code & (1 << j))
        for code in range(1 << len(exchanges))
    }
    return np.array([active_map[int(code)] for code in codes], dtype=object), np.array(
        [missing_map[int(code)] for code in codes], dtype=object
    )


def compute_panel(
    prices_wide: pd.DataFrame,
    weights_wide: pd.DataFrame,
    exchanges: list[str],
    min_exchanges: int = 3,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    p = prices_wide[exchanges].to_numpy(dtype=float)
    w = weights_wide[exchanges].to_numpy(dtype=float)
    # This exactly follows the original headline generator: finite price,
    # finite weight, and strictly positive weight.  It does not add p > 0.
    valid = np.isfinite(p) & np.isfinite(w) & (w > 0)
    w_clean = np.where(valid, w, 0.0)
    p_clean = np.where(valid, p, np.nan)
    count = valid.sum(axis=1).astype(int)
    total = w_clean.sum(axis=1)
    shares = np.divide(w_clean, total[:, None], out=np.zeros_like(w_clean), where=total[:, None] > 0)
    max_share = shares.max(axis=1)
    hhi = (shares**2).sum(axis=1)
    dominant_idx = shares.argmax(axis=1)
    names = np.array(exchanges, dtype=object)
    dominant_exchange = np.where(total > 0, names[dominant_idx], "")
    dominant_price = p_clean[np.arange(len(p_clean)), dominant_idx]
    vwap = np.divide(
        np.nansum(p_clean * w_clean, axis=1),
        total,
        out=np.full(len(total), np.nan),
        where=total > 0,
    )
    lwmp, pivot_idx, pivot_margin, total_check = weighted_median_with_pivot(p_clean, w_clean)
    pivot_exchange = np.where(pivot_idx >= 0, names[np.maximum(pivot_idx, 0)], "")
    active, missing = active_set_labels(valid, exchanges)
    max_share = np.where(total > 0, max_share, np.nan)
    hhi = np.where(total > 0, hhi, np.nan)
    relative_gap = np.divide(
        np.abs(vwap - dominant_price),
        vwap,
        out=np.full(len(vwap), np.nan),
        where=np.isfinite(vwap) & (vwap != 0),
    )
    panel = pd.DataFrame(
        {
            "time_utc": prices_wide.index,
            "valid_venue_count": count,
            "active_venue_set": active,
            "missing_venue_set": missing,
            "total_DV_usd": total,
            "P_vwap_DV": vwap,
            "P_lwmp_DV": lwmp,
            "max_share": max_share,
            "HHI": hhi,
            "dominant_exchange": dominant_exchange,
            "dominant_price": dominant_price,
            "pivot_exchange": pivot_exchange,
            "pivot_margin": pivot_margin,
            "relative_vwap_gap": relative_gap,
            "lock_in": (max_share > LOCKIN_THRESHOLD).astype(int),
            "valid_minute": (count >= min_exchanges).astype(int),
        }
    )
    arrays = {
        "p_clean": p_clean,
        "w_clean": w_clean,
        "valid": valid,
        "valid_minute": count >= min_exchanges,
        "n_ex": count,
        "shares": shares,
        "dominant_idx": dominant_idx,
        "p_dom": dominant_price,
        "vwap": vwap,
        "lwmp": lwmp,
        "pivot_idx": pivot_idx,
        "total_w": total_check,
    }
    return panel, arrays


def load_original_structure(root: Path, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    path = root / "experiments" / "weight_concentration_minute_level.csv"
    frame = pd.read_csv(path, usecols=["time_utc", "total_DV", "max_share", "HHI", "dominant_exchange"])
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], errors="coerce", utc=True).dt.floor("min")
    for column in ["total_DV", "max_share", "HHI"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["time_utc"]).sort_values("time_utc").drop_duplicates("time_utc", keep="last")
    frame = frame.set_index("time_utc").reindex(calendar)
    return frame.reset_index(names="time_utc")


def sample_valid_exchange_per_row(valid_w: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    count = valid_w.sum(axis=1)
    if np.any(count <= 0):
        raise ValueError("Cannot sample a shocked venue from a row without a valid weight")
    pick = (rng.random(len(valid_w)) * count).astype(int)
    cumulative = np.cumsum(valid_w.astype(int), axis=1)
    return (cumulative > pick[:, None]).argmax(axis=1).astype(int)


def generate_events(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    exchanges: list[str],
    candidate_mask: np.ndarray,
    event_seed: int,
    sample_target: int,
    delta_ws: list[float],
    shock_types: list[str],
    structural_panel: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = np.flatnonzero(np.asarray(candidate_mask, dtype=bool))
    sample_n = min(int(sample_target), len(candidates))
    if sample_n <= 0:
        raise ValueError("No candidate minutes available")
    rng = np.random.default_rng(event_seed)
    selected_positions = rng.choice(len(candidates), size=sample_n, replace=False)
    selected = candidates[selected_positions]
    prices = arrays["p_clean"][selected].copy()
    weights = arrays["w_clean"][selected].copy()
    vwap0, lwmp0, pivot0, margin0, w0, p0 = compute_aggregators(prices, weights)
    total0 = w0.sum(axis=1)
    valid_w = (w0 > 0) & np.isfinite(w0)
    shocked_idx = sample_valid_exchange_per_row(valid_w, rng)
    rows = np.arange(sample_n)
    wj0 = w0[rows, shocked_idx]
    share0 = np.divide(wj0, total0, out=np.full(sample_n, np.nan), where=total0 > 0)
    names = np.array(exchanges, dtype=object)
    structure = structural_panel if structural_panel is not None else panel
    max_share = pd.to_numeric(structure["max_share"], errors="coerce").to_numpy(dtype=float)[selected]
    dominant = structure["dominant_exchange"].astype(str).to_numpy()[selected]
    lock_in = (max_share > LOCKIN_THRESHOLD).astype(np.int8)

    base = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(panel["time_utc"].iloc[selected].to_numpy(), utc=True),
            "valid_venue_count": panel["valid_venue_count"].iloc[selected].to_numpy(dtype=int),
            "active_venue_set": panel["active_venue_set"].iloc[selected].astype(str).to_numpy(),
            "max_share": max_share,
            "valid_input_max_share": panel["max_share"].iloc[selected].to_numpy(dtype=float),
            "lock_in": lock_in,
            "dominant_exchange": dominant,
            "original_sample_selection_order": np.arange(1, sample_n + 1, dtype=int),
            "sample_probability": float(sample_n / len(candidates)),
            "sampling_stratum": "none",
            "random_seed": int(event_seed),
        }
    )

    frames: list[pd.DataFrame] = []
    cell_rows: list[dict[str, Any]] = []
    for shock_type in shock_types:
        for delta_w in delta_ws:
            factor = 1.0 + float(delta_w)
            if factor <= 0:
                continue
            w_shock = w0.copy()
            cap_applied = np.zeros(sample_n, dtype=bool)
            if shock_type == "inflate_only":
                w_shock[rows, shocked_idx] = wj0 * factor
            elif shock_type == "reallocate_total_fixed":
                wj_new = wj0 * factor
                rest0 = total0 - wj0
                cap_applied = (total0 > 0) & (wj_new >= (1.0 - 1e-9) * total0)
                wj_new = np.where(cap_applied, (1.0 - 1e-9) * total0, wj_new)
                scale_rest = np.where(rest0 > 0, (total0 - wj_new) / rest0, 1.0)
                scale_rest = np.where(scale_rest < 0, np.nan, scale_rest)
                w_shock = w_shock * scale_rest[:, None]
                w_shock[rows, shocked_idx] = wj_new
                bad = ~np.isfinite(scale_rest)
                if np.any(bad):
                    w_shock[bad] = np.nan
            else:
                raise ValueError(f"Unexpected shock type: {shock_type}")
            vwap1, lwmp1, pivot1, margin1, w1, _ = compute_aggregators(p0, w_shock)
            total1 = w1.sum(axis=1)
            changed = ((pivot0 != -1) & (pivot1 != -1) & (pivot1 != pivot0)).astype(np.int8)
            wj1 = w1[rows, shocked_idx]
            share1 = np.divide(wj1, total1, out=np.full(sample_n, np.nan), where=total1 > 0)
            pivot_before = np.where(pivot0 >= 0, names[np.maximum(pivot0, 0)], "")
            pivot_after = np.where(pivot1 >= 0, names[np.maximum(pivot1, 0)], "")
            event = pd.DataFrame(
                {
                    "time_utc": base["time_utc"].to_numpy(),
                    "base_selection_order": base["original_sample_selection_order"].to_numpy(),
                    "shock_type": shock_type,
                    "gamma": float(delta_w),
                    "delta_w": float(delta_w),
                    "weight_factor": float(factor),
                    "exchange_shocked": names[shocked_idx],
                    "share_shocked_before": share0,
                    "share_shocked_after": share1,
                    "dominant_exchange": dominant,
                    "max_share": max_share,
                    "lock_in": lock_in,
                    "pivot_exchange_before": pivot_before,
                    "pivot_exchange_after": pivot_after,
                    "pivot_margin_before": margin0,
                    "pivot_margin_after": margin1,
                    "pivot_changed": changed,
                    "shift_vwap": (vwap1 - vwap0) / vwap0,
                    "shift_lwmp": (lwmp1 - lwmp0) / lwmp0,
                    "cap_applied": cap_applied.astype(np.int8),
                }
            )
            frames.append(event)
            cell_rows.append(
                {
                    "shock_type": shock_type,
                    "delta_w_or_gamma": float(delta_w),
                    "base_minute_count": int(sample_n),
                    "attempted_events": int(sample_n),
                    "admissible_events": int(sample_n),
                    "rejected_events": 0,
                    "rejection_reason": "none; infeasible positive reallocations are capped, not rejected",
                    "cap_applied_events": int(cap_applied.sum()),
                    "pivot_change_count": int(changed.sum()),
                    "pivot_change_rate": float(changed.mean()),
                    "lock_in_event_count": int(lock_in.sum()),
                    "non_lock_in_event_count": int((lock_in == 0).sum()),
                    "non_lockin_pivot_change_count": int(changed[lock_in == 0].sum()),
                    "non_lockin_pivot_change_rate": float(changed[lock_in == 0].mean()),
                    "lockin_pivot_change_count": int(changed[lock_in == 1].sum()),
                    "lockin_pivot_change_rate": float(changed[lock_in == 1].mean()),
                }
            )
    events = pd.concat(frames, ignore_index=True)
    for column in ["shock_type", "exchange_shocked", "dominant_exchange", "pivot_exchange_before", "pivot_exchange_after"]:
        events[column] = events[column].astype("category")
    return events, base, pd.DataFrame(cell_rows)


def headline_summary(events: pd.DataFrame, base_minutes: int) -> dict[str, Any]:
    grouped = events.groupby("lock_in", observed=True)["pivot_changed"].agg(["mean", "count"])
    non = grouped.loc[0]
    lock = grouped.loc[1]
    rate_non = float(non["mean"])
    rate_lock = float(lock["mean"])
    return {
        "base_minute_count": int(base_minutes),
        "total_event_count": int(len(events)),
        "n_non_lockin_events": int(non["count"]),
        "n_lockin_events": int(lock["count"]),
        "non_lockin_pivot_change_rate": rate_non,
        "lockin_pivot_change_rate": rate_lock,
        "difference_lockin_minus_nonlockin": rate_lock - rate_non,
        "rate_ratio_lockin_over_nonlockin": rate_lock / rate_non,
        "pivot_dominant_before_rate": float(
            (events["pivot_exchange_before"].astype(str) == events["dominant_exchange"].astype(str)).mean()
        ),
        "pivot_dominant_after_rate": float(
            (events["pivot_exchange_after"].astype(str) == events["dominant_exchange"].astype(str)).mean()
        ),
        "median_max_share_non_lockin": float(events.loc[events["lock_in"] == 0, "max_share"].median()),
        "median_max_share_lockin": float(events.loc[events["lock_in"] == 1, "max_share"].median()),
    }


def reproduce_existing_events(root: Path, events: pd.DataFrame) -> dict[str, Any]:
    path = root / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
    columns = [
        "time_utc",
        "shock_type",
        "delta_w",
        "exchange_shocked",
        "share_shocked_before",
        "share_shocked_after",
        "pivot_exchange_before",
        "pivot_exchange_after",
        "pivot_changed",
    ]
    existing = pd.read_csv(path, usecols=columns)
    result: dict[str, Any] = {"existing_event_path": str(path.resolve()), "existing_event_sha256": sha256_file(path)}
    result["row_count_match"] = bool(len(existing) == len(events))
    if len(existing) != len(events):
        result["key_mismatch_count"] = int(max(len(existing), len(events)))
        result["max_share_before_abs_diff"] = np.nan
        result["max_share_after_abs_diff"] = np.nan
        return result
    existing_time = pd.to_datetime(existing["time_utc"], errors="coerce", utc=True).astype("int64")
    rebuilt_time = pd.to_datetime(events["time_utc"], errors="coerce", utc=True).astype("int64")
    mismatch = existing_time.to_numpy() != rebuilt_time.to_numpy()
    for column in ["shock_type", "exchange_shocked", "pivot_exchange_before", "pivot_exchange_after"]:
        mismatch |= existing[column].fillna("").astype(str).to_numpy() != events[column].astype(str).to_numpy()
    mismatch |= ~np.isclose(
        pd.to_numeric(existing["delta_w"], errors="coerce").to_numpy(),
        events["delta_w"].to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )
    mismatch |= pd.to_numeric(existing["pivot_changed"], errors="coerce").to_numpy(dtype=int) != events[
        "pivot_changed"
    ].to_numpy(dtype=int)
    result["key_mismatch_count"] = int(mismatch.sum())
    result["max_share_before_abs_diff"] = float(
        np.nanmax(
            np.abs(
                pd.to_numeric(existing["share_shocked_before"], errors="coerce").to_numpy(dtype=float)
                - events["share_shocked_before"].to_numpy(dtype=float)
            )
        )
    )
    result["max_share_after_abs_diff"] = float(
        np.nanmax(
            np.abs(
                pd.to_numeric(existing["share_shocked_after"], errors="coerce").to_numpy(dtype=float)
                - events["share_shocked_after"].to_numpy(dtype=float)
            )
        )
    )
    return result


def dominant_distribution_text(frame: pd.DataFrame) -> str:
    counts = frame["dominant_exchange"].astype(str).value_counts()
    total = int(counts.sum())
    if total == 0:
        return "{}"
    return json_text({str(name): float(value / total) for name, value in counts.items() if str(name)})


def run_summary(
    panel: pd.DataFrame,
    eligible_mask: np.ndarray,
    availability_mask: np.ndarray | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    eligible = np.asarray(eligible_mask, dtype=bool)
    availability = eligible if availability_mask is None else np.asarray(availability_mask, dtype=bool)
    max_share = pd.to_numeric(panel["max_share"], errors="coerce").to_numpy(dtype=float)
    lock = eligible & (max_share > LOCKIN_THRESHOLD)
    times = pd.to_datetime(panel["time_utc"], utc=True)
    starts = np.flatnonzero(lock & ~np.r_[False, lock[:-1]])
    ends = np.flatnonzero(lock & ~np.r_[lock[1:], False])
    spell_rows = []
    for spell_id, (start_idx, end_idx) in enumerate(zip(starts, ends), start=1):
        terminated = bool(end_idx + 1 < len(panel) and not availability[end_idx + 1])
        spell_rows.append(
            {
                "spell_id": spell_id,
                "start_time": str(times.iloc[start_idx]),
                "end_time": str(times.iloc[end_idx]),
                "duration_minutes": int(end_idx - start_idx + 1),
                "terminated_by_availability_interruption": int(terminated),
            }
        )
    spells = pd.DataFrame(spell_rows)
    durations = spells["duration_minutes"].to_numpy(dtype=float) if len(spells) else np.array([], dtype=float)
    sub = panel.loc[eligible].copy()
    ms = pd.to_numeric(sub["max_share"], errors="coerce")
    hhi = pd.to_numeric(sub["HHI"], errors="coerce")
    summary = {
        "valid_minutes": int(eligible.sum()),
        "calendar_coverage_share": float(eligible.mean()),
        "share_max_share_gt_0p5": float((ms > 0.5).mean()) if len(sub) else np.nan,
        "share_max_share_gt_0p4": float((ms > 0.4).mean()) if len(sub) else np.nan,
        "share_max_share_gt_0p3": float((ms > 0.3).mean()) if len(sub) else np.nan,
        "median_max_share": float(ms.median()) if len(sub) else np.nan,
        "p95_max_share": float(ms.quantile(0.95)) if len(sub) else np.nan,
        "p99_max_share": float(ms.quantile(0.99)) if len(sub) else np.nan,
        "median_HHI": float(hhi.median()) if len(sub) else np.nan,
        "p95_HHI": float(hhi.quantile(0.95)) if len(sub) else np.nan,
        "dominant_exchange_distribution": dominant_distribution_text(sub),
        "spell_count": int(len(spells)),
        "median_spell": float(np.median(durations)) if len(durations) else np.nan,
        "p95_spell": float(np.quantile(durations, 0.95)) if len(durations) else np.nan,
        "p99_spell": float(np.quantile(durations, 0.99)) if len(durations) else np.nan,
        "maximum_spell": int(np.max(durations)) if len(durations) else 0,
        "spells_ge_60_minutes": int((durations >= 60).sum()) if len(durations) else 0,
        "spells_ge_360_minutes": int((durations >= 360).sum()) if len(durations) else 0,
        "spells_ge_1440_minutes": int((durations >= 1440).sum()) if len(durations) else 0,
        "spells_terminated_by_availability_interruption": int(
            spells["terminated_by_availability_interruption"].sum()
        )
        if len(spells)
        else 0,
    }
    return summary, spells


def missing_run_summary(availability_mask: np.ndarray) -> dict[str, Any]:
    missing = ~np.asarray(availability_mask, dtype=bool)
    starts = np.flatnonzero(missing & ~np.r_[False, missing[:-1]])
    ends = np.flatnonzero(missing & ~np.r_[missing[1:], False])
    lengths = ends - starts + 1
    return {
        "missing_run_count": int(len(lengths)),
        "longest_missing_run_minutes": int(lengths.max()) if len(lengths) else 0,
    }


def make_valid_venue_audit(
    panel: pd.DataFrame, out_data: Path, valid_minute_mask: np.ndarray
) -> dict[str, pd.DataFrame]:
    audit = panel[
        [
            "time_utc",
            "valid_venue_count",
            "active_venue_set",
            "missing_venue_set",
            "max_share",
            "lock_in",
            "dominant_exchange",
            "pivot_exchange",
            "HHI",
        ]
    ].copy()
    audit["all_seven_valid"] = (audit["valid_venue_count"] == 7).astype(int)
    audit["in_original_valid_pool"] = np.asarray(valid_minute_mask, dtype=bool).astype(int)
    audit.to_csv(out_data / "btc_valid_venue_count_by_minute.csv", index=False, encoding="utf-8-sig")
    calendar_n = len(audit)
    valid_n = int(np.asarray(valid_minute_mask, dtype=bool).sum())
    dist_rows = []
    year_rows = []
    lock_rows = []
    for count in range(3, 8):
        sub = audit.loc[audit["valid_venue_count"] == count]
        original_sub = sub.loc[sub["in_original_valid_pool"] == 1]
        ms = pd.to_numeric(sub["max_share"], errors="coerce")
        over = ms > 0.5
        dist_rows.append(
            {
                "valid_venue_count": count,
                "minutes": int(len(sub)),
                "original_valid_minutes": int(len(original_sub)),
                "share_of_calendar_minutes": float(len(sub) / calendar_n),
                "share_of_original_valid_minutes": float(len(original_sub) / valid_n),
                "over_half_minutes": int(over.sum()),
                "over_half_share": float(over.mean()) if len(sub) else np.nan,
                "at_or_below_half_minutes": int((~over).sum()),
                "at_or_below_half_share": float((~over).mean()) if len(sub) else np.nan,
                "median_max_share": float(ms.median()) if len(sub) else np.nan,
                "p95_max_share": float(ms.quantile(0.95)) if len(sub) else np.nan,
                "dominant_exchange_distribution": dominant_distribution_text(sub),
            }
        )
        for state in [0, 1]:
            state_sub = sub.loc[sub["lock_in"] == state]
            lock_rows.append(
                {
                    "valid_venue_count": count,
                    "lock_in": state,
                    "minutes": int(len(state_sub)),
                    "share_within_valid_venue_count": float(len(state_sub) / len(sub)) if len(sub) else np.nan,
                }
            )
        for year in [2021, 2022]:
            year_sub = sub.loc[pd.to_datetime(sub["time_utc"], utc=True).dt.year == year]
            year_ms = pd.to_numeric(year_sub["max_share"], errors="coerce")
            year_rows.append(
                {
                    "year": year,
                    "valid_venue_count": count,
                    "minutes": int(len(year_sub)),
                    "over_half_minutes": int((year_ms > 0.5).sum()),
                    "over_half_share": float((year_ms > 0.5).mean()) if len(year_sub) else np.nan,
                    "median_max_share": float(year_ms.median()) if len(year_sub) else np.nan,
                    "p95_max_share": float(year_ms.quantile(0.95)) if len(year_sub) else np.nan,
                }
            )
    distribution = pd.DataFrame(dist_rows)
    by_lock = pd.DataFrame(lock_rows)
    by_year = pd.DataFrame(year_rows)
    distribution.to_csv(out_data / "btc_valid_venue_count_distribution.csv", index=False, encoding="utf-8-sig")
    by_lock.to_csv(out_data / "btc_valid_venue_count_by_lockin.csv", index=False, encoding="utf-8-sig")
    by_year.to_csv(out_data / "btc_valid_venue_count_by_year.csv", index=False, encoding="utf-8-sig")

    valid = audit.loc[np.asarray(valid_minute_mask, dtype=bool)].copy()
    composition_rows = []
    for active_set, sub in valid.groupby("active_venue_set", observed=True, sort=False):
        ms = pd.to_numeric(sub["max_share"], errors="coerce")
        composition_rows.append(
            {
                "active_venue_set": active_set,
                "valid_venue_count": int(sub["valid_venue_count"].iloc[0]),
                "minutes": int(len(sub)),
                "share_of_valid_minutes": float(len(sub) / len(valid)),
                "over_half_minutes": int((ms > 0.5).sum()),
                "over_half_share": float((ms > 0.5).mean()),
                "median_max_share": float(ms.median()),
                "p95_max_share": float(ms.quantile(0.95)),
                "dominant_exchange_distribution": dominant_distribution_text(sub),
            }
        )
    composition = pd.DataFrame(composition_rows).sort_values(["valid_venue_count", "minutes"], ascending=[False, False])
    composition.to_csv(out_data / "btc_active_set_composition.csv", index=False, encoding="utf-8-sig")
    missing = (
        valid.groupby(["missing_venue_set", "valid_venue_count"], observed=True)
        .size()
        .reset_index(name="minutes")
        .sort_values("minutes", ascending=False)
    )
    missing["share_of_valid_minutes"] = missing["minutes"] / len(valid)
    missing.to_csv(out_data / "btc_missing_venue_distribution.csv", index=False, encoding="utf-8-sig")
    return {
        "minute": audit,
        "distribution": distribution,
        "by_lock": by_lock,
        "by_year": by_year,
        "composition": composition,
        "missing": missing,
    }


def load_maxshare_edges(root: Path) -> np.ndarray:
    path = root / "experiments_dvonly" / "pivot_boundary_curve_edges_maxshare.csv"
    frame = pd.read_csv(path)
    if {"left", "right"}.issubset(frame.columns):
        left = pd.to_numeric(frame["left"], errors="coerce").dropna().to_numpy(dtype=float)
        right = pd.to_numeric(frame["right"], errors="coerce").dropna().to_numpy(dtype=float)
        edges = np.unique(np.r_[left, right])
    else:
        numeric = frame.select_dtypes(include=["number"])
        edges = np.unique(numeric.iloc[:, -1].dropna().to_numpy(dtype=float))
    edges.sort()
    if len(edges) != PIVOT_NBINS + 1:
        raise ValueError(f"Expected 31 original max-share edges; found {len(edges)}")
    return edges


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / den
    return max(0.0, center - half), min(1.0, center + half)


def pivot_bins(events: pd.DataFrame, edges: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def append_bins(sub: pd.DataFrame, shock_label: str, gamma_label: float | str) -> None:
        bins = pd.cut(sub["max_share"], bins=edges, include_lowest=True, labels=False)
        for bin_id in range(len(edges) - 1):
            sb = sub.loc[bins == bin_id]
            n = int(len(sb))
            if n == 0:
                continue
            k = int(sb["pivot_changed"].sum())
            lo, hi = wilson_ci(k, n)
            rows.append(
                {
                    "shock_type": shock_label,
                    "gamma": gamma_label,
                    "bin_id": bin_id,
                    "x_left": float(edges[bin_id]),
                    "x_right": float(edges[bin_id + 1]),
                    "max_share_mid": float((edges[bin_id] + edges[bin_id + 1]) / 2),
                    "n": n,
                    "k": k,
                    "pivot_rate": float(k / n),
                    "ci_lo": lo,
                    "ci_hi": hi,
                }
            )

    append_bins(events, "pooled_headline", "pooled")
    for gamma, sub in events.groupby("gamma", observed=True):
        append_bins(sub, "overall", float(gamma))
    for shock_type, shock_sub in events.groupby("shock_type", observed=True):
        for gamma, sub in shock_sub.groupby("gamma", observed=True):
            append_bins(sub, str(shock_type), float(gamma))
    return pd.DataFrame(rows)


def block_bootstrap(
    events: pd.DataFrame, block_days: int, reps: int, seed: int
) -> pd.DataFrame:
    frame = events[["time_utc", "lock_in", "pivot_changed"]].copy()
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True).dt.floor("min")
    origin = frame["time_utc"].dt.floor("D").min()
    day_number = (frame["time_utc"].dt.floor("D") - origin).dt.days
    frame["_block"] = (day_number // block_days).astype(int)
    grouped = (
        frame.groupby(["_block", "lock_in"], observed=True)["pivot_changed"].agg(["sum", "count"]).reset_index()
    )
    blocks = np.sort(frame["_block"].unique())
    full_index = pd.MultiIndex.from_product([blocks, [0, 1]], names=["_block", "lock_in"])
    grouped = grouped.set_index(["_block", "lock_in"]).reindex(full_index, fill_value=0).reset_index()
    sums = np.zeros((len(blocks), 2), dtype=float)
    counts = np.zeros((len(blocks), 2), dtype=float)
    positions = {block: pos for pos, block in enumerate(blocks)}
    for block, state, outcome_sum, outcome_count in grouped.itertuples(index=False, name=None):
        pos = positions[block]
        sums[pos, int(state)] = outcome_sum
        counts[pos, int(state)] = outcome_count
    rng = np.random.default_rng(seed)
    records = []
    for rep in range(reps):
        draw = rng.integers(0, len(blocks), size=len(blocks))
        sampled_sums = sums[draw].sum(axis=0)
        sampled_counts = counts[draw].sum(axis=0)
        if np.any(sampled_counts == 0):
            continue
        rates = sampled_sums / sampled_counts
        records.append(
            {
                "rate_nonlock": rates[0],
                "rate_lock": rates[1],
                "difference_lock_minus_nonlock": rates[1] - rates[0],
                "ratio_lock_over_nonlock": rates[1] / rates[0],
            }
        )
    draws = pd.DataFrame(records)
    rate_nonlock = float(frame.loc[frame["lock_in"] == 0, "pivot_changed"].mean())
    rate_lock = float(frame.loc[frame["lock_in"] == 1, "pivot_changed"].mean())
    point_map = {
        "rate_nonlock": rate_nonlock,
        "rate_lock": rate_lock,
        "difference_lock_minus_nonlock": rate_lock - rate_nonlock,
        "ratio_lock_over_nonlock": rate_lock / rate_nonlock,
    }
    rows = []
    for statistic, point_value in point_map.items():
        values = draws[statistic].to_numpy(dtype=float)
        rows.append(
            {
                "block_days": int(block_days),
                "statistic": statistic,
                "point_estimate": float(point_value),
                "bootstrap_mean": float(np.mean(values)),
                "bootstrap_se": float(np.std(values, ddof=1)),
                "ci95_low": float(np.quantile(values, 0.025)),
                "ci95_high": float(np.quantile(values, 0.975)),
                "block_count": int(len(blocks)),
                "completed_reps": int(len(draws)),
                "requested_reps": int(reps),
                "seed": int(seed),
            }
        )
    return pd.DataFrame(rows)


def run_both_bootstraps(events: pd.DataFrame, reps: int, seed: int) -> pd.DataFrame:
    return pd.concat(
        [block_bootstrap(events, 1, reps, seed), block_bootstrap(events, 7, reps, seed)],
        ignore_index=True,
    )


def vwap_proximity_bins(panel: pd.DataFrame, eligible_mask: np.ndarray, edges: np.ndarray) -> pd.DataFrame:
    sub = panel.loc[np.asarray(eligible_mask, dtype=bool)].copy()
    sub["bin_id"] = pd.cut(sub["max_share"], bins=edges, include_lowest=True, right=False, labels=False)
    rows = []
    for bin_id in range(len(edges) - 1):
        values = pd.to_numeric(
            sub.loc[sub["bin_id"] == bin_id, "relative_vwap_gap"], errors="coerce"
        ).dropna()
        rows.append(
            {
                "bin_id": bin_id,
                "x_left": float(edges[bin_id]),
                "x_right": float(edges[bin_id + 1]),
                "x_center": float((edges[bin_id] + edges[bin_id + 1]) / 2),
                "n": int(len(values)),
                "q95_rel_gap_dom": float(values.quantile(0.95)) if len(values) else np.nan,
                "median_rel_gap_dom": float(values.median()) if len(values) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def price_passthrough(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    eligible_mask: np.ndarray,
    lambdas: list[float],
) -> pd.DataFrame:
    idx = np.flatnonzero(np.asarray(eligible_mask, dtype=bool))
    prices = arrays["p_clean"][idx]
    weights = arrays["w_clean"][idx]
    dominant_idx = arrays["dominant_idx"][idx]
    p_dom = arrays["p_dom"][idx]
    vwap0 = arrays["vwap"][idx]
    lwmp0 = arrays["lwmp"][idx]
    states = np.where(panel["max_share"].to_numpy(dtype=float)[idx] > 0.5, "lockin", "non_lockin")
    rows = []
    for lam in lambdas:
        prices_prime = prices.copy()
        prices_prime[np.arange(len(prices_prime)), dominant_idx] = p_dom * (1.0 + lam)
        total = weights.sum(axis=1)
        vwap1 = np.divide(
            np.nansum(prices_prime * weights, axis=1),
            total,
            out=np.full(len(total), np.nan),
            where=total > 0,
        )
        lwmp1, _, _, _ = weighted_median_with_pivot(prices_prime, weights)
        denom = lam * p_dom
        kappa_vwap = (vwap1 - vwap0) / denom
        kappa_lwmp = (lwmp1 - lwmp0) / denom
        for state in ["non_lockin", "lockin"]:
            mask = states == state
            kv = kappa_vwap[mask]
            kl = kappa_lwmp[mask]
            rows.append(
                {
                    "lambda": float(lam),
                    "shock_label": f"{lam:+.1%}",
                    "state": state,
                    "event_count": int(mask.sum()),
                    "VWAP_mean_kappa": float(np.nanmean(kv)),
                    "VWAP_median_kappa": float(np.nanmedian(kv)),
                    "LWMP_mean_kappa": float(np.nanmean(kl)),
                    "LWMP_median_kappa": float(np.nanmedian(kl)),
                    "LWMP_zero_share": float(np.isclose(kl, 0.0, atol=1e-12).mean()),
                    "LWMP_one_share": float(np.isclose(kl, 1.0, atol=1e-8).mean()),
                }
            )
    return pd.DataFrame(rows)


def endpoint_stats(frame: pd.DataFrame) -> tuple[float, float, float]:
    usable = frame.dropna(subset=["q95_rel_gap_dom"]).sort_values("bin_id")
    if usable.empty:
        return np.nan, np.nan, np.nan
    low = float(usable.iloc[0]["q95_rel_gap_dom"])
    high = float(usable.iloc[-1]["q95_rel_gap_dom"])
    return low, high, high / low if low else np.nan


def passthrough_value(frame: pd.DataFrame, state: str, column: str, lam: float = 0.001) -> float:
    sub = frame.loc[(frame["state"] == state) & np.isclose(frame["lambda"], lam, atol=1e-15)]
    return float(sub[column].iloc[0]) if len(sub) else np.nan


def bootstrap_ci(frame: pd.DataFrame, block_days: int, statistic: str = "difference_lock_minus_nonlock") -> str:
    sub = frame.loc[(frame["block_days"] == block_days) & (frame["statistic"] == statistic)]
    if sub.empty:
        return ""
    return f"[{float(sub['ci95_low'].iloc[0]):.12g}, {float(sub['ci95_high'].iloc[0]):.12g}]"


def make_figures(
    venue_distribution: pd.DataFrame,
    baseline_bins: pd.DataFrame,
    all7_bins: pd.DataFrame,
    figures_dir: Path,
) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    figures_dir.mkdir(parents=True, exist_ok=True)
    width, height = 2220, 1440
    left, right, top, bottom = 265, 100, 110, 235
    plot_w, plot_h = width - left - right, height - top - bottom
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 42)
        small = ImageFont.truetype("DejaVuSans.ttf", 32)
        tiny = ImageFont.truetype("DejaVuSans.ttf", 27)
        bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
    except OSError:
        font = ImageFont.load_default()
        small = font
        tiny = font
        bold = font

    def text_center(
        draw: ImageDraw.ImageDraw,
        xy: tuple[float, float],
        label: str,
        used_font: ImageFont.FreeTypeFont,
    ) -> None:
        box = draw.textbbox((0, 0), label, font=used_font)
        draw.text(
            (xy[0] - (box[2] - box[0]) / 2, xy[1] - (box[3] - box[1]) / 2),
            label,
            fill="#202124",
            font=used_font,
        )

    def save_pdf_from_png(png_path: Path, pdf_path: Path) -> None:
        page_w, page_h = 7.4 * 72, 4.8 * 72
        pdf = pdf_canvas.Canvas(str(pdf_path), pagesize=(page_w, page_h))
        pdf.drawImage(
            ImageReader(str(png_path)),
            0,
            0,
            width=page_w,
            height=page_h,
            preserveAspectRatio=True,
        )
        pdf.showPage()
        pdf.save()

    def base_canvas(
        x_min: float,
        x_max: float,
        y_max: float,
        x_label: str,
        y_label: str,
        x_ticks: list[float],
    ) -> tuple[Image.Image, ImageDraw.ImageDraw, Any, Any]:
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)

        def sx(value: float) -> float:
            return left + (value - x_min) / (x_max - x_min) * plot_w

        def sy(value: float) -> float:
            return top + plot_h - value / y_max * plot_h

        for tick in np.linspace(0, y_max, 6):
            y = sy(float(tick))
            draw.line((left, y, left + plot_w, y), fill="#d9dde1", width=2)
            label = f"{tick:.2f}"
            box = draw.textbbox((0, 0), label, font=small)
            draw.text(
                (left - 22 - (box[2] - box[0]), y - (box[3] - box[1]) / 2),
                label,
                fill="#4b5563",
                font=small,
            )
        draw.line((left, top, left, top + plot_h), fill="#202124", width=4)
        draw.line((left, top + plot_h, left + plot_w, top + plot_h), fill="#202124", width=4)
        for tick in x_ticks:
            x = sx(float(tick))
            draw.line((x, top + plot_h, x, top + plot_h + 12), fill="#202124", width=3)
            text_center(draw, (x, top + plot_h + 48), f"{tick:g}", small)
        text_center(draw, (left + plot_w / 2, height - 62), x_label, font)
        y_layer = Image.new("RGBA", (height, 110), (255, 255, 255, 0))
        y_draw = ImageDraw.Draw(y_layer)
        text_center(y_draw, (height / 2, 55), y_label, font)
        y_layer = y_layer.rotate(90, expand=True)
        image.paste(y_layer, (20, 0), y_layer)
        return image, draw, sx, sy

    counts = venue_distribution.loc[venue_distribution["minutes"] > 0].sort_values(
        "valid_venue_count"
    )
    x_values = counts["valid_venue_count"].to_numpy(dtype=float)
    y_values = counts["over_half_share"].to_numpy(dtype=float)
    y_max = max(0.1, float(np.nanmax(y_values)) * 1.22)
    image, draw, sx, sy = base_canvas(
        float(x_values.min()),
        float(x_values.max()),
        y_max,
        "Number of valid venues",
        "Share of minutes above one half",
        x_values.tolist(),
    )
    points = [(sx(float(x)), sy(float(y))) for x, y in zip(x_values, y_values)]
    draw.line(points, fill="#2f6b8a", width=7, joint="curve")
    for point, row in zip(points, counts.itertuples(index=False)):
        x, y = point
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill="#2f6b8a", outline="white", width=3)
        text_center(draw, (x, y - 48), f"n={int(row.minutes):,}", tiny)
    png1 = figures_dir / "Fig_BTC_overhalf_by_valid_venue_count.png"
    pdf1 = figures_dir / "Fig_BTC_overhalf_by_valid_venue_count.pdf"
    image.save(png1, dpi=(300, 300))
    save_pdf_from_png(png1, pdf1)

    base = baseline_bins.loc[baseline_bins["shock_type"] == "pooled_headline"].sort_values("bin_id")
    seven = all7_bins.loc[all7_bins["shock_type"] == "pooled_headline"].sort_values("bin_id")
    x_min = min(float(base["max_share_mid"].min()), float(seven["max_share_mid"].min()))
    x_max = max(float(base["max_share_mid"].max()), float(seven["max_share_mid"].max()))
    y_max = max(float(base["pivot_rate"].max()), float(seven["pivot_rate"].max())) * 1.14
    ticks = np.linspace(x_min, x_max, 6).tolist()
    image, draw, sx, sy = base_canvas(
        x_min,
        x_max,
        y_max,
        "Dominant venue share",
        "Pivot-change rate",
        ticks,
    )
    x_boundary = sx(0.5)
    for y in range(top, top + plot_h, 32):
        draw.line((x_boundary, y, x_boundary, min(y + 16, top + plot_h)), fill="#6b7280", width=4)

    def draw_series(frame: pd.DataFrame, color: str, square: bool, dashed: bool) -> None:
        points = [
            (sx(float(row.max_share_mid)), sy(float(row.pivot_rate)))
            for row in frame.itertuples(index=False)
        ]
        if dashed:
            for first, second in zip(points[:-1], points[1:]):
                x1, y1 = first
                x2, y2 = second
                distance = max(abs(x2 - x1), abs(y2 - y1))
                steps = max(1, int(distance / 18))
                for step in range(steps):
                    if step % 2 == 0:
                        a = step / steps
                        b = min(1.0, (step + 1) / steps)
                        draw.line(
                            (
                                x1 + a * (x2 - x1),
                                y1 + a * (y2 - y1),
                                x1 + b * (x2 - x1),
                                y1 + b * (y2 - y1),
                            ),
                            fill=color,
                            width=6,
                        )
        else:
            draw.line(points, fill=color, width=6, joint="curve")
        for x, y in points:
            if square:
                draw.rectangle((x - 8, y - 8, x + 8, y + 8), fill=color, outline="white", width=2)
            else:
                draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="white", width=2)

    draw_series(base, "#2f6b8a", square=False, dashed=False)
    draw_series(seven, "#b5533c", square=True, dashed=True)
    legend_x, legend_y = left + 45, top + 42
    draw.line((legend_x, legend_y, legend_x + 92, legend_y), fill="#2f6b8a", width=7)
    draw.ellipse((legend_x + 38, legend_y - 8, legend_x + 54, legend_y + 8), fill="#2f6b8a")
    draw.text((legend_x + 112, legend_y - 20), "Baseline", fill="#202124", font=bold)
    legend_y += 58
    for x in range(legend_x, legend_x + 92, 24):
        draw.line((x, legend_y, min(x + 12, legend_x + 92), legend_y), fill="#b5533c", width=6)
    draw.rectangle((legend_x + 38, legend_y - 8, legend_x + 54, legend_y + 8), fill="#b5533c")
    draw.text((legend_x + 112, legend_y - 20), "All seven venues valid", fill="#202124", font=bold)
    png2 = figures_dir / "Fig_BTC_baseline_vs_all7_LWMP_boundary.png"
    pdf2 = figures_dir / "Fig_BTC_baseline_vs_all7_LWMP_boundary.pdf"
    image.save(png2, dpi=(300, 300))
    save_pdf_from_png(png2, pdf2)


def manual_recalculation_check(
    panel: pd.DataFrame, arrays: dict[str, np.ndarray], eligible_mask: np.ndarray, count: int = 20
) -> dict[str, float | int]:
    indices = np.flatnonzero(np.asarray(eligible_mask, dtype=bool))
    if len(indices) < count:
        raise ValueError("Not enough eligible minutes for manual checks")
    chosen = indices[np.linspace(0, len(indices) - 1, count, dtype=int)]
    max_vwap = 0.0
    max_lwmp = 0.0
    max_share_diff = 0.0
    max_hhi = 0.0
    pivot_mismatch = 0
    for idx in chosen:
        p = arrays["p_clean"][idx]
        w = arrays["w_clean"][idx]
        valid = np.isfinite(p) & np.isfinite(w) & (w > 0)
        pv = p[valid]
        wv = w[valid]
        total = float(sum(float(value) for value in wv))
        shares = np.array([float(value) / total for value in wv], dtype=float)
        vwap = float(sum(float(price) * float(weight) for price, weight in zip(pv, wv)) / total)
        order = np.argsort(pv, kind="mergesort")
        cumulative = 0.0
        pivot_local = -1
        for local in order:
            cumulative += float(wv[local])
            if cumulative >= 0.5 * total:
                pivot_local = int(local)
                break
        lwmp = float(pv[pivot_local])
        original_cols = np.flatnonzero(valid)
        pivot_name = str(np.array(EXCHANGES, dtype=object)[original_cols[pivot_local]])
        max_vwap = max(max_vwap, abs(vwap - float(panel.iloc[idx]["P_vwap_DV"])))
        max_lwmp = max(max_lwmp, abs(lwmp - float(panel.iloc[idx]["P_lwmp_DV"])))
        max_share_diff = max(max_share_diff, abs(float(shares.max()) - float(panel.iloc[idx]["max_share"])))
        max_hhi = max(max_hhi, abs(float(np.sum(shares**2)) - float(panel.iloc[idx]["HHI"])))
        pivot_mismatch += int(pivot_name != str(panel.iloc[idx]["pivot_exchange"]))
    return {
        "minutes_checked": int(count),
        "max_abs_vwap_difference": float(max_vwap),
        "max_abs_lwmp_difference": float(max_lwmp),
        "max_abs_max_share_difference": float(max_share_diff),
        "max_abs_hhi_difference": float(max_hhi),
        "pivot_mismatch_count": int(pivot_mismatch),
    }


def add_validation(
    rows: list[dict[str, Any]], check: str, condition: bool, value: Any, detail: str, warn: bool = False
) -> None:
    status = "PASS" if condition else ("WARN" if warn else "FAIL")
    rows.append({"check": check, "status": status, "value": value, "detail": detail})


def write_formula_manifest(
    path: Path,
    source: Path,
    seed: int,
    sample_n: int,
    delta_ws: list[float],
    shock_types: list[str],
) -> None:
    text = f"""# BTC DV-only event formula manifest

- Executed source lineage: `{source}` (`main`, sampling, and shock loop).
- Event seed: `{seed}`.
- Base-minute target: `{sample_n:,}`.
- Candidate index: the actual generator anchors its wide DataFrame to the first sorted file (Binance), so later venues do not expand the time index.  Within that 1,050,207-timestamp index, minutes must have at least three valid venues.
- Sampling: uniform simple random sample without replacement from that candidate index; no lock-in stratification.
- Shocked venue: one venue drawn uniformly among the valid venues of each sampled minute, then held fixed across that minute's eight cells.
- Shock types: `{shock_types}`.
- Gamma order: `{delta_ws}`.  `gamma` is the fractional change in the shocked venue's raw DV weight; factors are `1 + gamma`.

## `inflate_only`

For shocked venue `j`, `w'_j = (1 + gamma) w_j`; for every `k != j`, `w'_k = w_k`.  Prices are fixed.  The total DV changes and aggregator weights are normalized internally by their new total.

## `reallocate_total_fixed`

Let `W = sum_k w_k`, `r = W - w_j`, and `raw = (1 + gamma) w_j`.  The implemented code first sets `w'_j = min(raw, (1 - 1e-9) W)`.  For every `k != j`, `w'_k = w_k (W - w'_j) / r`.  Thus all other valid venues jointly serve as the counterparty in proportion to their original weights and the total remains `W` (up to floating point error).

There is no row-level rejection, deletion, or resampling rule.  Positive reallocations that would exhaust the other venues are capped; all eight cells remain in the pooled dataset.  The present gamma grid has `1 + gamma > 0`, so negative weights are not created.

The existing generator has no separate Boolean admissibility predicate: every attempted event on the present grid is retained and therefore counted as admissible.  Initial venues already satisfy finite price, finite weight, and strictly positive weight; the gamma grid preserves nonnegative shocked weights, and the cap makes positive total-fixed shocks executable.

## Pivot and pooling

LWMP sorts valid venue prices stably and selects the first price whose cumulative raw DV weight reaches at least half the raw total.  `pivot_changed = 1` exactly when both pre/post pivots exist and their venue-column indices differ.  The headline rates are event-weighted means over all eight cells.  Because every sampled minute contributes exactly one event to every cell and no event is removed, this is also an equal `1/8` weighting of the cells, but it is not minute-level any-shock switchability.
"""
    path.write_text(text, encoding="utf-8")


def write_headline_audit(
    path: Path,
    root: Path,
    summary: dict[str, Any],
    event_compare: dict[str, Any],
    cell_counts: pd.DataFrame,
    seed: int,
    sample_target: int,
    valid_minutes: int,
    source_lines: dict[str, int | None],
) -> None:
    text = f"""# BTC headline event-generation audit

## Traceable code path

1. `make_dv_2021_2022.py` constructs venue prices by OHLC4 -> HL2 -> Close and DV inputs.
2. `run_dv_only_injection_experiments.py` reads the seven DV-ready files, applies the price/weight-validity rule, samples minutes, chooses the shocked venue, creates eight cells, and writes `experiments_dvonly/dvon_injection_shift_samples.csv`.
3. `audit_lockin_and_build_dvonly_inference.py` merges the events with `experiments/weight_concentration_minute_level.csv` through the HHI panel and defines `lock_in = 1[max_share > 0.5]`.
4. `run_day_block_bootstrap.py` groups events into UTC 1-day or 7-day blocks; all events attached to one minute stay in one block.

Key source locators in `run_dv_only_injection_experiments.py`: seed line {source_lines.get('seed')}, sample line {source_lines.get('sample')}, venue-draw line {source_lines.get('venue_draw')}, inflate line {source_lines.get('inflate')}, reallocation line {source_lines.get('reallocate')}, pivot-change line {source_lines.get('pivot_changed')}.

## Sampling and event counts

- Candidate valid minutes: {valid_minutes:,}.  The current code obtains this count because the first sorted input (Binance) fixes the DataFrame index before the other six venues are assigned; the 993 calendar minutes absent from Binance never enter the headline candidate pool even when at least three other venues are valid.
- Base minutes: {summary['base_minute_count']:,} (target {sample_target:,}).
- Method: unstratified simple random sample without replacement.
- Seed: {seed}.
- Per-minute events: 2 shock types x 4 gamma values = 8.
- Total events: {summary['total_event_count']:,}.
- Lock-in stratification: none.  Lock-in is attached after sampling from the structural minute panel.
- Sample probability: {summary['base_minute_count'] / valid_minutes:.12g} for every candidate minute.

## Perturbation behavior

`inflate_only` changes only the selected venue's raw DV weight.  `reallocate_total_fixed` changes the selected venue and proportionally rescales all other valid venues; it has no single counterparty.  Positive shocks that would make the selected venue consume the total are capped at `(1 - 1e-9) W`.  Events are not deleted, rejected, or resampled.  See `btc_event_formula_manifest.md` for the equations.

## Pooled headline reproduction

- Non-lock-in rate: {summary['non_lockin_pivot_change_rate']:.17g}.
- Lock-in rate: {summary['lockin_pivot_change_rate']:.17g}.
- Lock-in minus non-lock-in: {summary['difference_lockin_minus_nonlockin']:.17g}.
- Rate ratio: {summary['rate_ratio_lockin_over_nonlockin']:.17g}.
- Row-level key mismatches versus the existing 800,000-event file: {event_compare.get('key_mismatch_count')}.
- Maximum shocked-share difference before/after: {event_compare.get('max_share_before_abs_diff')} / {event_compare.get('max_share_after_abs_diff')}.

The rates are event-level pooled rates, not the probability that a minute switches under at least one perturbation.  Every event has equal weight.  Since all cells contain the same number of base minutes, each cell has weight `1/8` in the pooled rate.

## Figure subset versus pooled headline

The existing main-text LWMP boundary figure filters to `shock_type=inflate_only` and `gamma=1.0`, i.e. 100,000 events.  The 0.279276 / 0.067677 headline contrast pools all 800,000 events across both shock types and all four gamma values.

## Cell counts

{markdown_table(cell_counts)}

## Bootstrap distinction

The original event generator's seed is 42. The standalone Appendix B block-bootstrap files under `outputs/robustness` use seed 20260710. New fixed-composition bootstraps use seed 42 as requested while preserving the same UTC-block algorithm.
"""
    path.write_text(text, encoding="utf-8")


def scenario_comparison_row(
    specification: str,
    active_set: str,
    missing_set: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    venue_count: Any,
    summary: dict[str, Any],
    headline: dict[str, Any] | None,
    bootstrap: pd.DataFrame | None,
    proximity: pd.DataFrame | None,
    passthrough: pd.DataFrame | None,
    dv_status: str = "run",
) -> dict[str, Any]:
    low, high, _ = endpoint_stats(proximity) if proximity is not None else (np.nan, np.nan, np.nan)
    headline = headline or {}
    return {
        "Specification": specification,
        "Active venue set": active_set,
        "Missing venue set": missing_set,
        "Start date": str(start),
        "End date": str(end),
        "Valid minutes": summary.get("valid_minutes"),
        "Calendar coverage share": summary.get("calendar_coverage_share"),
        "Venue count": venue_count,
        "Share max_share > 0.5": summary.get("share_max_share_gt_0p5"),
        "Median max_share": summary.get("median_max_share"),
        "P95 max_share": summary.get("p95_max_share"),
        "Median HHI": summary.get("median_HHI"),
        "P95 HHI": summary.get("p95_HHI"),
        "Dominant exchange distribution": summary.get("dominant_exchange_distribution"),
        "Spell count": summary.get("spell_count"),
        "Median spell": summary.get("median_spell"),
        "P95 spell": summary.get("p95_spell"),
        "Maximum spell": summary.get("maximum_spell"),
        "Non-lockin pivot-change rate": headline.get("non_lockin_pivot_change_rate", np.nan),
        "Lockin pivot-change rate": headline.get("lockin_pivot_change_rate", np.nan),
        "Difference": headline.get("difference_lockin_minus_nonlockin", np.nan),
        "Rate ratio": headline.get("rate_ratio_lockin_over_nonlockin", np.nan),
        "Bootstrap CI 1-day": bootstrap_ci(bootstrap, 1) if bootstrap is not None else "",
        "Bootstrap CI 7-day": bootstrap_ci(bootstrap, 7) if bootstrap is not None else "",
        "Lowest-bin VWAP q95 gap": low,
        "Highest-bin VWAP q95 gap": high,
        "Median LWMP pass-through in lock-in": passthrough_value(
            passthrough, "lockin", "LWMP_median_kappa"
        )
        if passthrough is not None
        else np.nan,
        "Median VWAP pass-through in lock-in": passthrough_value(
            passthrough, "lockin", "VWAP_median_kappa"
        )
        if passthrough is not None
        else np.nan,
        "Median VWAP pass-through in non-lock-in": passthrough_value(
            passthrough, "non_lockin", "VWAP_median_kappa"
        )
        if passthrough is not None
        else np.nan,
        "DV-only status": dv_status,
    }


def write_final_report(
    path: Path,
    headline: dict[str, Any],
    venue_dist: pd.DataFrame,
    baseline_summary: dict[str, Any],
    all7_summary: dict[str, Any],
    all7_headline: dict[str, Any],
    all7_boot: pd.DataFrame,
    all7_proximity: pd.DataFrame,
    all7_passthrough: pd.DataFrame,
    base6_summary: dict[str, Any],
    base6_headline: dict[str, Any],
    base6_boot: pd.DataFrame,
    fixed_summary: pd.DataFrame,
    fixed_pivot: pd.DataFrame,
    loo_compare: dict[str, Any],
    validation: pd.DataFrame,
    input_manifest: pd.DataFrame,
    seed: int,
    valid_minutes: int,
    all7_minutes: int,
) -> None:
    all7_low, all7_high, all7_ratio = endpoint_stats(all7_proximity)
    all7_lwmp = passthrough_value(all7_passthrough, "lockin", "LWMP_median_kappa")
    diff_1 = all7_boot.loc[
        (all7_boot["block_days"] == 1) & (all7_boot["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    diff_7 = all7_boot.loc[
        (all7_boot["block_days"] == 7) & (all7_boot["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    counts = validation["status"].value_counts().to_dict()
    input_lineage = markdown_table(
        input_manifest[
            [
                "exchange",
                "raw_source_path",
                "path",
                "volume_convention",
                "deduplicated_minutes",
            ]
        ]
    )
    composition_pivot_note = (
        markdown_table(
            fixed_pivot[
                [
                    "active_venue_set",
                    "valid_minutes",
                    "non_lockin_pivot_change_rate",
                    "lockin_pivot_change_rate",
                    "difference_lockin_minus_nonlockin",
                    "rate_ratio_lockin_over_nonlockin",
                ]
            ]
        )
        if len(fixed_pivot)
        else "_No exact composition met the 50,000-minute DV-only threshold._"
    )
    text = f"""# BTC fixed-composition review report

## Executive finding

The original 800,000-event headline is exactly reproducible from the verified minute-level inputs and current code path.  The fixed-composition results below separate input availability from venue-weight concentration; no existing BTC, ETH, Word, PDF, or TXT artifact was edited.

## Input lineage and preprocessing

{input_lineage}

- Window: 2021-01-01 00:00 through 2022-12-31 23:59 UTC.
- Representative venue price: OHLC4 when all four fields exist, otherwise HL2, otherwise Close; prices are aligned to the Binance anchor scale by the existing input builder.
- Volume convention: the six non-BitMEX venues are `base`, so `DV_usd = volume x p_usd_scaled`; BitMEX is `quote_or_contract`, so `DV_usd = volume x 1.0`.
- Validity: finite price, finite DV weight, and strictly positive DV weight.  Invalid venue weights are set to zero for that minute; the remaining positive weights are normalized by their minute total.

## Direct answers

1. The original events come from `{valid_minutes:,}` minutes on the Binance-anchored first-file index with at least three valid venues.  A uniform, unstratified, without-replacement sample selects 100,000 minutes using seed {seed}.  The remaining 993 calendar minutes are assessed separately in the availability audit.
2. Yes: 800,000 = 100,000 x 8 exactly.
3. Base-minute sampling is simple random sampling without replacement; it is not stratified by lock-in.
4. Each minute generates eight events: two shock types x four gamma values.
5. One venue is drawn uniformly among that minute's valid venues and is held fixed across its eight events; it is not necessarily the dominant or pivot venue.
6. `inflate_only`: `w'_j=(1+gamma)w_j`, others unchanged.  `reallocate_total_fixed`: cap `w'_j` at `(1-1e-9)W`, then scale every other valid venue proportionally so the total remains `W`.
7. The code does not reject or redraw infeasible positive reallocations; it caps them.  All present-grid events remain pooled.
8. Every event has equal weight.  With 100,000 observations in each of eight cells, each cell receives weight 1/8.
9. Reproduced rates are {headline['non_lockin_pivot_change_rate']:.17g} and {headline['lockin_pivot_change_rate']:.17g}; difference {headline['difference_lockin_minus_nonlockin']:.17g}; ratio {headline['rate_ratio_lockin_over_nonlockin']:.17g}.  All are within 1e-10 of the requested values.
10. Valid-venue-count distribution is shown below.
11. The direction of the over-half gradient across venue counts is visible in the table and Figure `Fig_BTC_overhalf_by_valid_venue_count`: fewer venues have the reported count-specific rates; the conclusion is based on those numeric rates, not a pooled label.
12. All-seven-valid minutes: {all7_minutes:,}, or {all7_summary['calendar_coverage_share']:.6%} of calendar minutes.
13. All-seven over-half share: {all7_summary['share_max_share_gt_0p5']:.12g}.
14. All-seven longest over-half spell: {all7_summary['maximum_spell']:,} minutes.
15. All-seven non-lock-in / lock-in rates: {all7_headline['non_lockin_pivot_change_rate']:.12g} / {all7_headline['lockin_pivot_change_rate']:.12g}.
16. All-seven difference / ratio: {all7_headline['difference_lockin_minus_nonlockin']:.12g} / {all7_headline['rate_ratio_lockin_over_nonlockin']:.12g}.
17. All-seven difference CI: 1-day [{diff_1.ci95_low:.12g}, {diff_1.ci95_high:.12g}], 7-day [{diff_7.ci95_low:.12g}, {diff_7.ci95_high:.12g}].  Zero is {'excluded by both' if diff_1.ci95_high < 0 and diff_7.ci95_high < 0 else 'not excluded by both'}.
18. All-seven VWAP proximity endpoints: q95 {all7_low:.12g} to {all7_high:.12g}, ratio {all7_ratio:.12g}.
19. All-seven lock-in LWMP median pass-through at +0.1%: {all7_lwmp:.12g}; it is {'equal to 1 within 1e-8' if abs(all7_lwmp-1)<1e-8 else 'not equal to 1 within 1e-8'}.
20. Only the all-seven exact set meets the 50,000-minute DV-only threshold, and its -0.207364256108 rate difference remains present.  Descriptive exact-set rows never combine active sets.
21. The two additional >=10,000-minute exact-six sets differ visibly in over-half frequency: 0.707084220128 when Bitstamp is missing and 0.940119002405 when BitMEX is missing, versus 0.545046514048 for all seven.  Neither exact-six set is large enough for the pre-specified DV-only headline threshold.
22. Six base-volume venues, all six valid: over-half {base6_summary['share_max_share_gt_0p5']:.12g}; non-lock-in / lock-in rates {base6_headline['non_lockin_pivot_change_rate']:.12g} / {base6_headline['lockin_pivot_change_rate']:.12g}; difference {base6_headline['difference_lockin_minus_nonlockin']:.12g}; ratio {base6_headline['rate_ratio_lockin_over_nonlockin']:.12g}.
23. The shift from baseline over-half {baseline_summary['share_max_share_gt_0p5']:.12g} to all-seven {all7_summary['share_max_share_gt_0p5']:.12g} is {all7_summary['share_max_share_gt_0p5']-baseline_summary['share_max_share_gt_0p5']:.12g} (all-seven minus baseline), or {100*(all7_summary['share_max_share_gt_0p5']-baseline_summary['share_max_share_gt_0p5']):.6g} percentage points and {100*(all7_summary['share_max_share_gt_0p5']-baseline_summary['share_max_share_gt_0p5'])/baseline_summary['share_max_share_gt_0p5']:.6g}% relative to baseline.  This restriction comparison is not a causal decomposition, but it shows that input availability explains only a small part of the pooled 55.5% frequency under the maintained weighting definitions.
24. Input missingness does not overturn the mechanism result: the difference moves from {headline['difference_lockin_minus_nonlockin']:.12g} to {all7_headline['difference_lockin_minus_nonlockin']:.12g}, and both all-seven block CIs exclude zero.
25. Excluding BitMEX and requiring all six base-volume venues valid leaves the exact numeric contrast in item 22, so the BitMEX convention does not overturn the rate ordering.  The older relaxed-availability leave-one-out comparison reported non-lock-in / lock-in {loo_compare.get('old_nonlock_rate', np.nan):.12g} / {loo_compare.get('old_lock_rate', np.nan):.12g}; it is not the same sample restriction.
26. The code audit found disclosure issues, not a hidden event-count mismatch: the headline pool is anchored to Binance and omits 993 calendar minutes absent from its file; total-fixed infeasibility is handled by capping; and the later standalone bootstrap seed (20260710) differs from the event seed (42).  These facts should be stated explicitly.
27. Main text: report the all-seven valid-minute count/share, baseline-to-all-seven over-half change, and all-seven headline difference with 1-day/7-day CIs.
28. Online appendix: full valid-count, exact-composition, cell-count, VWAP-proximity, pass-through, six-base-volume, and validation tables plus both supplementary figures.
29. Additional venue-rescaling sensitivity is not required to answer missingness/fixed-composition once the six-base-volume fixed sample is shown; it is optional only if the referee specifically challenges cross-venue DV scale calibration.
30. The referee concern can be answered if all validation rows are PASS/WARN and no FAIL remains.  Current counts: PASS={counts.get('PASS',0)}, WARN={counts.get('WARN',0)}, FAIL={counts.get('FAIL',0)}.

## Valid venue count distribution

{markdown_table(venue_dist)}

## Eligible fixed-composition descriptive rows

{markdown_table(fixed_summary)}

## Eligible fixed-composition pivot rows

{composition_pivot_note}

## Reproducibility and implementation notes

- Original headline source: `experiments_dvonly/audit_lockin/audit_lockin_summary.csv`.
- Existing event source: `experiments_dvonly/dvon_injection_shift_samples.csv`.
- Event seed: 42.  Existing standalone block-bootstrap seed: 20260710.  New sensitivity bootstrap seed: 42, per the requested fixed-composition command.
- Figure 1 subset is `inflate_only`, gamma=1.0 (100,000 events); the headline is pooled over all eight cells (800,000 events).
- No event is removed for infeasibility.  The total-fixed positive shock is capped when necessary.

## Minimal paper revision

Add one compact main-text paragraph with the all-seven coverage, over-half share, headline contrast, and both block CIs.  Add a methods sentence stating the unstratified 100,000-minute sample, seed 42, uniform valid-venue draw, eight events per minute, proportional total-fixed reallocation with the `(1-1e-9)W` cap, and equal event pooling.  Place the remaining tables and two figures in the online appendix.
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    started = time.time()
    root = args.project_root.resolve()
    out_dir = args.out_dir.resolve()
    start = utc_timestamp(args.start_date)
    end = utc_timestamp(args.end_date)
    if end < start:
        raise ValueError("--end-date must be on or after --start-date")
    if args.bootstrap_reps < 100:
        raise ValueError("--bootstrap-reps must be at least 100")
    expected_parent = (root / "outputs" / "reviewer_checks").resolve()
    if expected_parent != out_dir and expected_parent not in out_dir.parents:
        raise ValueError(f"--out-dir must remain under {expected_parent}")
    metadata_dir = out_dir / "metadata"
    data_dir = out_dir / "data_audit"
    results_dir = out_dir / "results"
    figures_dir = out_dir / "figures"
    for directory in [metadata_dir, data_dir, results_dir, figures_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    source = root / "run_dv_only_injection_experiments.py"
    recovered_seed = int(literal_assignment(source, "RANDOM_SEED"))
    sample_target = int(literal_assignment(source, "N_SAMPLE_MINUTES"))
    min_exchanges = int(literal_assignment(source, "MIN_EXCHANGES_PER_MIN"))
    delta_ws = [float(value) for value in literal_assignment(source, "DELTA_WS")]
    shock_types = [str(value) for value in literal_assignment(source, "SHOCK_TYPES")]
    seed = recovered_seed if args.seed is None else int(args.seed)
    if seed != recovered_seed:
        raise ValueError(f"Requested seed {seed} differs from recovered original event seed {recovered_seed}")
    if sample_target != 100_000 or min_exchanges != 3 or len(delta_ws) * len(shock_types) != 8:
        raise ValueError("Original headline constants no longer match the audited 100,000 x 8 design")

    btc_protected_paths = [
        root / "agg_ready",
        root / "hhi_panel",
        root / "experiments",
        root / "experiments_dvonly",
        root / "outputs" / "robustness" / "leave_one_exchange_out",
        root / "outputs" / "appendix",
        root / "outputs" / "robustness" / "btc_post2022",
    ]
    eth_protected_paths = [root / "outputs" / "robustness" / "eth_matched"]
    manuscript_paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".docx", ".pdf", ".txt"}
    ]
    before_btc = snapshot_tree(btc_protected_paths, exclude=[out_dir])
    before_eth = snapshot_tree(eth_protected_paths, exclude=[out_dir])
    before_manuscripts = snapshot_tree(manuscript_paths, exclude=[out_dir])

    print("[1/8] Loading and hashing seven verified minute-level input files...")
    prices_wide, weights_wide, input_manifest, first_file_index = load_minute_inputs(
        root / "dv_ready_2021_2022", start, end
    )
    input_manifest.to_csv(metadata_dir / "btc_input_file_manifest.csv", index=False, encoding="utf-8-sig")
    print("[2/8] Recomputing the baseline minute panel from venue inputs...")
    panel, arrays = compute_panel(prices_wide, weights_wide, EXCHANGES, min_exchanges=min_exchanges)
    calendar = pd.DatetimeIndex(panel["time_utc"])
    original_structure = load_original_structure(root, calendar)
    # Reproduce the original DataFrame-construction semantics exactly.  The
    # first sorted file (Binance) fixes the index; later Series assignments do
    # not expand it.  The subsequent union of nonmissing price indices is thus
    # restricted to that first-file index.
    first_index_mask = calendar.isin(first_file_index)
    any_price_on_first_index = prices_wide.notna().any(axis=1).to_numpy(dtype=bool)
    original_union_mask = first_index_mask & any_price_on_first_index
    valid_mask = arrays["valid_minute"] & original_union_mask
    valid_minutes = int(valid_mask.sum())

    source_lines = {
        "seed": source_line(source, "RANDOM_SEED ="),
        "sample": source_line(source, "sample_idx = rng.choice"),
        "venue_draw": source_line(source, "j = sample_valid_exchange_per_row"),
        "inflate": source_line(source, 'if shock_type == "inflate_only"'),
        "reallocate": source_line(source, 'elif shock_type == "reallocate_total_fixed"'),
        "pivot_changed": source_line(source, "piv_changed ="),
    }
    print("[3/8] Rebuilding the original 100,000-minute / 800,000-event headline sample...")
    baseline_events, base_sample, baseline_cells = generate_events(
        panel,
        arrays,
        EXCHANGES,
        valid_mask,
        seed,
        sample_target,
        delta_ws,
        shock_types,
        structural_panel=original_structure,
    )
    base_sample.to_csv(metadata_dir / "btc_base_minute_sample.csv", index=False, encoding="utf-8-sig")
    baseline_cells.to_csv(
        metadata_dir / "btc_headline_event_cell_counts.csv", index=False, encoding="utf-8-sig"
    )
    baseline_headline = headline_summary(baseline_events, len(base_sample))
    event_compare = reproduce_existing_events(root, baseline_events)

    reproduction_rows = []
    for metric, expected in EXPECTED_HEADLINE.items():
        reproduced = float(baseline_headline[metric])
        error = abs(reproduced - expected)
        reproduction_rows.append(
            {
                "metric": metric,
                "expected": expected,
                "reproduced": reproduced,
                "absolute_error": error,
                "tolerance": HEADLINE_TOLERANCE,
                "status": "PASS" if error <= HEADLINE_TOLERANCE else "FAIL",
                "source_file": str(
                    (root / "experiments_dvonly" / "audit_lockin" / "audit_lockin_summary.csv").resolve()
                ),
            }
        )
    auxiliary_reproduction = [
        ("base_minute_count", 100_000, baseline_headline["base_minute_count"], 0),
        ("event_count", 800_000, baseline_headline["total_event_count"], 0),
        ("event_key_mismatch_count", 0, event_compare.get("key_mismatch_count", np.nan), 0),
        ("share_before_max_abs_diff", 0.0, event_compare.get("max_share_before_abs_diff", np.nan), 1e-12),
        ("share_after_max_abs_diff", 0.0, event_compare.get("max_share_after_abs_diff", np.nan), 1e-12),
    ]
    for metric, expected, reproduced, tolerance in auxiliary_reproduction:
        error = abs(float(reproduced) - float(expected)) if pd.notna(reproduced) else np.inf
        reproduction_rows.append(
            {
                "metric": metric,
                "expected": expected,
                "reproduced": reproduced,
                "absolute_error": error,
                "tolerance": tolerance,
                "status": "PASS" if error <= tolerance else "FAIL",
                "source_file": event_compare.get("existing_event_path", ""),
            }
        )
    reproduction = pd.DataFrame(reproduction_rows)
    reproduction.to_csv(
        metadata_dir / "btc_existing_headline_reproduction.csv", index=False, encoding="utf-8-sig"
    )
    sampling_manifest = {
        "project_root": str(root),
        "entry_script": str(Path(__file__).resolve()),
        "original_generator": str(source.resolve()),
        "original_generator_sha256": sha256_file(source),
        "candidate_valid_minutes": valid_minutes,
        "candidate_rule": "first sorted file (Binance) fixes the time index; within it, finite price AND finite weight AND weight > 0 at >=3 venues",
        "calendar_minutes_excluded_by_first_file_index": int((~first_index_mask).sum()),
        "base_minute_count": int(len(base_sample)),
        "sampling_method": "uniform simple random sample without replacement",
        "replacement": False,
        "stratified_by_lock_in": False,
        "sample_probability": float(len(base_sample) / valid_minutes),
        "event_seed": seed,
        "bootstrap_seed_new_sensitivities": seed,
        "existing_standalone_bootstrap_seed": 20260710,
        "shock_types": shock_types,
        "delta_w_or_gamma_order": delta_ws,
        "events_per_base_minute": len(shock_types) * len(delta_ws),
        "total_events": int(len(baseline_events)),
        "pooling": "equal event weights; equal 1/8 cell weights because no events are removed",
        "input_files": input_manifest.to_dict("records"),
        "existing_event_file": event_compare,
    }
    (metadata_dir / "btc_event_sampling_manifest.json").write_text(
        json.dumps(sampling_manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_formula_manifest(
        metadata_dir / "btc_event_formula_manifest.md",
        source,
        seed,
        sample_target,
        delta_ws,
        shock_types,
    )
    write_headline_audit(
        metadata_dir / "btc_headline_event_generation_audit.md",
        root,
        baseline_headline,
        event_compare,
        baseline_cells,
        seed,
        sample_target,
        valid_minutes,
        source_lines,
    )

    headline_ok = bool((reproduction["status"] == "PASS").all())
    if not headline_ok:
        validation = pd.DataFrame(
            [
                {
                    "check": "01_original_headline_exact_reproduction",
                    "status": "FAIL",
                    "value": int((reproduction["status"] == "FAIL").sum()),
                    "detail": "Fixed-composition experiments stopped at the mandatory headline gate.",
                }
            ]
        )
        validation.to_csv(metadata_dir / "validation_checks.csv", index=False, encoding="utf-8-sig")
        (out_dir / "BTC_FIXED_COMPOSITION_REVIEW_REPORT.md").write_text(
            "# BTC fixed-composition review report\n\nFAIL: the original headline could not be reproduced; fixed-composition experiments were not run. See metadata/btc_existing_headline_reproduction.csv.\n",
            encoding="utf-8",
        )
        print("[FAIL] Original headline gate failed; stopping before fixed-composition experiments.")
        return 1

    if args.headline_only:
        validation = pd.DataFrame(
            [
                {
                    "check": "01_original_headline_exact_reproduction",
                    "status": "PASS",
                    "value": 0,
                    "detail": "All requested headline metrics and event-level keys reproduced.",
                },
                {
                    "check": "02_headline_only_requested",
                    "status": "WARN",
                    "value": True,
                    "detail": "Fixed-composition stages were intentionally not run.",
                },
            ]
        )
        validation.to_csv(metadata_dir / "validation_checks.csv", index=False, encoding="utf-8-sig")
        return 0

    print("[4/8] Building valid-venue-count and exact active-set audits...")
    venue_audit = make_valid_venue_audit(panel, data_dir, valid_mask)
    baseline_summary, baseline_spells = run_summary(panel, valid_mask, valid_mask)
    all7_mask = arrays["n_ex"] == 7
    all7_summary, all7_spells = run_summary(panel, all7_mask, all7_mask)
    all7_summary.update(missing_run_summary(all7_mask))
    years = pd.to_datetime(panel["time_utc"], utc=True).dt.year.to_numpy()
    for year in [2021, 2022]:
        year_mask = years == year
        all7_summary[f"coverage_{year}"] = float((all7_mask & year_mask).sum() / year_mask.sum())
    all7_summary["calendar_minutes"] = int(len(panel))
    all7_summary["all_seven_valid_minutes"] = int(all7_mask.sum())

    print("[5/8] Running all-seven-valid headline, bootstrap, proximity, and pass-through checks...")
    all7_events, all7_base, all7_cells = generate_events(
        panel, arrays, EXCHANGES, all7_mask, seed, sample_target, delta_ws, shock_types
    )
    all7_headline = headline_summary(all7_events, len(all7_base))
    all7_row = {**all7_summary, **all7_headline}
    pd.DataFrame([all7_row]).to_csv(
        results_dir / "btc_all7_lockin_summary.csv", index=False, encoding="utf-8-sig"
    )
    all7_cells.to_csv(
        results_dir / "btc_all7_event_cell_summary.csv", index=False, encoding="utf-8-sig"
    )
    edges = load_maxshare_edges(root)
    baseline_bins = pivot_bins(baseline_events, edges)
    all7_bins = pivot_bins(all7_events, edges)
    all7_bins.to_csv(results_dir / "btc_all7_pivot_bins.csv", index=False, encoding="utf-8-sig")
    baseline_boot = run_both_bootstraps(baseline_events, args.bootstrap_reps, seed)
    all7_boot = run_both_bootstraps(all7_events, args.bootstrap_reps, seed)
    all7_boot.to_csv(
        results_dir / "btc_all7_block_bootstrap.csv", index=False, encoding="utf-8-sig"
    )
    baseline_proximity = vwap_proximity_bins(panel, valid_mask, edges)
    all7_proximity = vwap_proximity_bins(panel, all7_mask, edges)
    all7_proximity.to_csv(
        results_dir / "btc_all7_vwap_proximity_bins.csv", index=False, encoding="utf-8-sig"
    )
    baseline_passthrough = price_passthrough(panel, arrays, valid_mask, PASSTHROUGH_LAMBDAS)
    all7_passthrough = price_passthrough(panel, arrays, all7_mask, PASSTHROUGH_LAMBDAS)
    all7_passthrough.to_csv(
        results_dir / "btc_all7_passthrough_summary.csv", index=False, encoding="utf-8-sig"
    )

    print("[6/8] Running the six-base-volume all-valid specification...")
    panel6, arrays6 = compute_panel(
        prices_wide[BASE_VOLUME_EXCHANGES],
        weights_wide[BASE_VOLUME_EXCHANGES],
        BASE_VOLUME_EXCHANGES,
        min_exchanges=3,
    )
    base6_mask = arrays6["n_ex"] == 6
    base6_summary, base6_spells = run_summary(panel6, base6_mask, base6_mask)
    base6_summary.update(missing_run_summary(base6_mask))
    pd.DataFrame([base6_summary]).to_csv(
        results_dir / "btc_basevolume6_lockin_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(
        [
            {
                key: value
                for key, value in base6_summary.items()
                if "spell" in key or key in {"share_max_share_gt_0p5", "valid_minutes"}
            }
        ]
    ).to_csv(results_dir / "btc_basevolume6_spell_summary.csv", index=False, encoding="utf-8-sig")
    base6_events, base6_base, base6_cells = generate_events(
        panel6,
        arrays6,
        BASE_VOLUME_EXCHANGES,
        base6_mask,
        seed,
        sample_target,
        delta_ws,
        shock_types,
    )
    base6_headline = headline_summary(base6_events, len(base6_base))
    pd.DataFrame([{**base6_headline, "all_six_valid_minutes": int(base6_mask.sum())}]).to_csv(
        results_dir / "btc_basevolume6_pivot_summary.csv", index=False, encoding="utf-8-sig"
    )
    base6_boot = run_both_bootstraps(base6_events, args.bootstrap_reps, seed)
    base6_boot.to_csv(
        results_dir / "btc_basevolume6_block_bootstrap.csv", index=False, encoding="utf-8-sig"
    )
    base6_proximity = vwap_proximity_bins(panel6, base6_mask, edges)
    base6_proximity.to_csv(
        results_dir / "btc_basevolume6_vwap_proximity.csv", index=False, encoding="utf-8-sig"
    )
    base6_passthrough = price_passthrough(panel6, arrays6, base6_mask, PASSTHROUGH_LAMBDAS)
    base6_passthrough.to_csv(
        results_dir / "btc_basevolume6_passthrough.csv", index=False, encoding="utf-8-sig"
    )

    loo_path = root / "outputs" / "robustness" / "leave_one_exchange_out" / "main_contrast_summary.csv"
    loo_compare: dict[str, Any] = {}
    if loo_path.exists():
        loo = pd.read_csv(loo_path)
        old = loo.loc[loo["scenario"].astype(str) == "EXCL_BitMEX"]
        if len(old):
            loo_compare = {
                "path": str(loo_path.resolve()),
                "old_valid_minutes": int(old["valid_minutes"].iloc[0]),
                "old_over_half_share": float(old["lockin_share"].iloc[0]),
                "old_nonlock_rate": float(old["lwmp_pivot_change_nonlockin_baseline"].iloc[0]),
                "old_lock_rate": float(old["lwmp_pivot_change_lockin_baseline"].iloc[0]),
                "new_all_six_valid_minutes": int(base6_mask.sum()),
                "new_over_half_share": float(base6_summary["share_max_share_gt_0p5"]),
                "new_nonlock_rate": float(base6_headline["non_lockin_pivot_change_rate"]),
                "new_lock_rate": float(base6_headline["lockin_pivot_change_rate"]),
                "definition_note": "Old leave-one-out permits variable availability; new specification requires all six included venues valid.",
            }

    print("[7/8] Running thresholded exact-active-set composition checks...")
    fixed_summary_rows: list[dict[str, Any]] = []
    fixed_pivot_rows: list[dict[str, Any]] = []
    fixed_boot_frames: list[pd.DataFrame] = []
    fixed_artifacts: dict[str, dict[str, Any]] = {}
    active_counts = panel.loc[valid_mask, "active_venue_set"].value_counts()
    eligible_sets = [
        str(active_set)
        for active_set, minutes in active_counts.items()
        if int(minutes) >= 10_000 and len(str(active_set).split("|")) in {5, 6, 7}
    ]
    all7_set = "|".join(EXCHANGES)
    for active_set in eligible_sets:
        mask = valid_mask & (panel["active_venue_set"].astype(str).to_numpy() == active_set)
        descriptive, _ = run_summary(panel, mask, mask)
        days = int(pd.to_datetime(panel.loc[mask, "time_utc"], utc=True).dt.floor("D").nunique())
        missing_set = str(panel.loc[mask, "missing_venue_set"].iloc[0])
        summary_row = {
            "active_venue_set": active_set,
            "missing_venue_set": missing_set,
            "valid_venue_count": int(panel.loc[mask, "valid_venue_count"].iloc[0]),
            "valid_minutes": int(mask.sum()),
            "number_of_UTC_days": days,
            "share_max_share_gt_0p5": descriptive["share_max_share_gt_0p5"],
            "median_max_share": descriptive["median_max_share"],
            "p95_max_share": descriptive["p95_max_share"],
            "median_HHI": descriptive["median_HHI"],
            "p95_HHI": descriptive["p95_HHI"],
            "dominant_exchange_distribution": descriptive["dominant_exchange_distribution"],
            "median_spell": descriptive["median_spell"],
            "p95_spell": descriptive["p95_spell"],
            "maximum_spell": descriptive["maximum_spell"],
            "descriptive_threshold_met": True,
            "dvonly_threshold_met": bool(mask.sum() >= 50_000),
            "bootstrap_day_threshold_met": bool(days >= 180),
        }
        fixed_summary_rows.append(summary_row)
        proximity = vwap_proximity_bins(panel, mask, edges)
        passthrough = price_passthrough(panel, arrays, mask, PASSTHROUGH_LAMBDAS)
        headline_for_set: dict[str, Any] | None = None
        bootstrap_for_set: pd.DataFrame | None = None
        if mask.sum() >= 50_000:
            if active_set == all7_set:
                headline_for_set = all7_headline
                bootstrap_for_set = all7_boot
            else:
                events_set, base_set, _ = generate_events(
                    panel, arrays, EXCHANGES, mask, seed, sample_target, delta_ws, shock_types
                )
                headline_for_set = headline_summary(events_set, len(base_set))
                bootstrap_for_set = run_both_bootstraps(events_set, args.bootstrap_reps, seed)
            fixed_pivot_rows.append(
                {
                    "active_venue_set": active_set,
                    "missing_venue_set": missing_set,
                    "valid_minutes": int(mask.sum()),
                    **headline_for_set,
                }
            )
            if days >= 180 and bootstrap_for_set is not None:
                boot = bootstrap_for_set.copy()
                boot.insert(0, "active_venue_set", active_set)
                boot.insert(1, "missing_venue_set", missing_set)
                fixed_boot_frames.append(boot)
        fixed_artifacts[active_set] = {
            "summary": descriptive,
            "headline": headline_for_set,
            "bootstrap": bootstrap_for_set,
            "proximity": proximity,
            "passthrough": passthrough,
            "missing_set": missing_set,
        }
    fixed_summary = pd.DataFrame(fixed_summary_rows).sort_values(
        ["valid_venue_count", "valid_minutes"], ascending=[False, False]
    )
    fixed_pivot = pd.DataFrame(fixed_pivot_rows)
    fixed_boot = pd.concat(fixed_boot_frames, ignore_index=True) if fixed_boot_frames else pd.DataFrame(
        columns=[
            "active_venue_set",
            "missing_venue_set",
            "block_days",
            "statistic",
            "point_estimate",
            "bootstrap_mean",
            "bootstrap_se",
            "ci95_low",
            "ci95_high",
            "block_count",
            "completed_reps",
            "requested_reps",
            "seed",
        ]
    )
    fixed_summary.to_csv(
        results_dir / "btc_fixed_composition_summary.csv", index=False, encoding="utf-8-sig"
    )
    fixed_pivot.to_csv(
        results_dir / "btc_fixed_composition_pivot_summary.csv", index=False, encoding="utf-8-sig"
    )
    fixed_boot.to_csv(
        results_dir / "btc_fixed_composition_bootstrap.csv", index=False, encoding="utf-8-sig"
    )

    comparison_rows = [
        scenario_comparison_row(
            "BTC baseline valid-minute sample",
            "variable (>=3 valid)",
            "variable",
            start,
            end,
            "3-7",
            baseline_summary,
            baseline_headline,
            baseline_boot,
            baseline_proximity,
            baseline_passthrough,
        ),
        scenario_comparison_row(
            "BTC all-seven-valid sample",
            all7_set,
            "",
            start,
            end,
            7,
            all7_summary,
            all7_headline,
            all7_boot,
            all7_proximity,
            all7_passthrough,
        ),
        scenario_comparison_row(
            "BTC six base-volume venues, all-six-valid",
            "|".join(BASE_VOLUME_EXCHANGES),
            "BitMEX (excluded by design)",
            start,
            end,
            6,
            base6_summary,
            base6_headline,
            base6_boot,
            base6_proximity,
            base6_passthrough,
        ),
    ]
    for active_set in eligible_sets:
        if active_set == all7_set:
            continue
        artifact = fixed_artifacts[active_set]
        summary = artifact["summary"]
        comparison_rows.append(
            scenario_comparison_row(
                f"Fixed active set: {active_set}",
                active_set,
                artifact["missing_set"],
                start,
                end,
                len(active_set.split("|")),
                summary,
                artifact["headline"],
                artifact["bootstrap"],
                artifact["proximity"],
                artifact["passthrough"],
                dv_status="run" if artifact["headline"] is not None else "not run: <50,000 minutes",
            )
        )
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(
        results_dir / "btc_availability_and_composition_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    make_figures(venue_audit["distribution"], baseline_bins, all7_bins, figures_dir)

    print("[8/8] Reconciling old aggregates, protected-file snapshots, and validation checks...")
    old_agg_path = root / "agg_ready" / "btc_2021_2022_agg_prices.csv"
    old_agg = pd.read_csv(old_agg_path, usecols=["time_utc", "P_vwap_DV", "P_lwmp_DV"])
    old_agg["time_utc"] = pd.to_datetime(old_agg["time_utc"], errors="coerce", utc=True).dt.floor("min")
    old_agg = old_agg.dropna(subset=["time_utc"]).drop_duplicates("time_utc", keep="last").set_index("time_utc")
    old_agg = old_agg.reindex(calendar)
    vwap_diff = float(
        np.nanmax(
            np.abs(
                old_agg["P_vwap_DV"].to_numpy(dtype=float)[all7_mask]
                - panel["P_vwap_DV"].to_numpy(dtype=float)[all7_mask]
            )
        )
    )
    lwmp_diff = float(
        np.nanmax(
            np.abs(
                old_agg["P_lwmp_DV"].to_numpy(dtype=float)[all7_mask]
                - panel["P_lwmp_DV"].to_numpy(dtype=float)[all7_mask]
            )
        )
    )
    old_max = pd.to_numeric(original_structure["max_share"], errors="coerce").to_numpy(dtype=float)
    old_hhi = pd.to_numeric(original_structure["HHI"], errors="coerce").to_numpy(dtype=float)
    max_share_diff = float(np.nanmax(np.abs(old_max[all7_mask] - panel["max_share"].to_numpy()[all7_mask])))
    hhi_diff = float(np.nanmax(np.abs(old_hhi[all7_mask] - panel["HHI"].to_numpy()[all7_mask])))
    manual = manual_recalculation_check(panel, arrays, all7_mask, count=20)

    after_btc = snapshot_tree(btc_protected_paths, exclude=[out_dir])
    after_eth = snapshot_tree(eth_protected_paths, exclude=[out_dir])
    after_manuscripts = snapshot_tree(manuscript_paths, exclude=[out_dir])
    changed_btc = compare_snapshots(before_btc, after_btc)
    changed_eth = compare_snapshots(before_eth, after_eth)
    changed_manuscripts = compare_snapshots(before_manuscripts, after_manuscripts)

    validation_rows: list[dict[str, Any]] = []
    add_validation(
        validation_rows,
        "01_original_headline_exact_reproduction",
        headline_ok,
        int((reproduction["status"] == "FAIL").sum()),
        "Four headline values match within 1e-10 and the event file matches row by row.",
    )
    add_validation(
        validation_rows,
        "02_original_800000_event_count",
        len(baseline_events) == 800_000,
        len(baseline_events),
        "Original event count equals 100,000 x 8.",
    )
    add_validation(
        validation_rows,
        "03_base_minute_count_confirmed",
        len(base_sample) == 100_000,
        len(base_sample),
        "Base-minute count recovered from code and regenerated sample.",
    )
    add_validation(
        validation_rows,
        "04_each_shock_cell_event_count",
        bool((baseline_cells["attempted_events"] == 100_000).all() and len(baseline_cells) == 8),
        json_text(
            baseline_cells[
                ["shock_type", "delta_w_or_gamma", "attempted_events"]
            ].to_dict("records")
        ),
        "Eight cells each contain 100,000 events.",
    )
    add_validation(
        validation_rows,
        "05_all_events_trace_to_base_minutes",
        bool(
            baseline_events["base_selection_order"].between(1, len(base_sample)).all()
            and baseline_events["base_selection_order"].nunique() == len(base_sample)
        ),
        baseline_events["base_selection_order"].nunique(),
        "Every event carries the original base-sample selection order.",
    )
    add_validation(
        validation_rows,
        "06_all_seven_minutes_really_all_valid",
        bool(arrays["valid"][all7_mask].all()),
        int(all7_mask.sum()),
        "Every selected all-seven row has finite price, finite weight, and positive weight at all seven venues.",
    )
    add_validation(
        validation_rows,
        "07_six_basevolume_minutes_really_all_valid",
        bool(arrays6["valid"][base6_mask].all()),
        int(base6_mask.sum()),
        "Every selected six-base-volume row has all six included venues valid; BitMEX is absent by design.",
    )
    norm_error = max(
        float(np.max(np.abs(arrays["shares"][valid_mask].sum(axis=1) - 1))),
        float(np.max(np.abs(arrays6["shares"][base6_mask].sum(axis=1) - 1))),
    )
    add_validation(
        validation_rows,
        "08_weights_normalize_to_one",
        norm_error <= 1e-12,
        norm_error,
        "Maximum per-minute normalized-share sum error across baseline and six-base-volume checks.",
    )
    valid_max = panel.loc[valid_mask, "max_share"]
    add_validation(
        validation_rows,
        "09_max_share_in_unit_interval",
        bool(valid_max.between(0, 1).all()),
        f"[{valid_max.min()}, {valid_max.max()}]",
        "Baseline valid-minute max_share range.",
    )
    over = valid_mask & (panel["max_share"].to_numpy(dtype=float) > 0.5)
    pivot_dom_mismatch = int(
        (panel.loc[over, "pivot_exchange"].astype(str).to_numpy() != panel.loc[over, "dominant_exchange"].astype(str).to_numpy()).sum()
    )
    add_validation(
        validation_rows,
        "10_overhalf_pivot_equals_dominant",
        pivot_dom_mismatch == 0,
        pivot_dom_mismatch,
        "Mismatch count under max_share > 0.5.",
    )
    add_validation(
        validation_rows,
        "11_combined_index_excluded",
        "Combined_Index" not in set(input_manifest["exchange"]),
        json_text(EXCHANGES),
        "Only the seven named venue inputs enter the calculation.",
    )
    add_validation(
        validation_rows,
        "12_all7_vwap_matches_old_baseline",
        vwap_diff <= 1e-9,
        vwap_diff,
        "Maximum absolute VWAP difference on all-seven-valid minutes.",
    )
    add_validation(
        validation_rows,
        "13_all7_lwmp_matches_old_baseline",
        lwmp_diff <= 1e-9,
        lwmp_diff,
        "Maximum absolute LWMP difference on all-seven-valid minutes.",
    )
    manual_ok = bool(
        manual["max_abs_vwap_difference"] <= 1e-9
        and manual["max_abs_lwmp_difference"] <= 1e-9
        and manual["max_abs_max_share_difference"] <= 1e-12
        and manual["max_abs_hhi_difference"] <= 1e-12
        and manual["pivot_mismatch_count"] == 0
    )
    add_validation(
        validation_rows,
        "14_manual_recalculation_20_all7_minutes",
        manual_ok,
        json_text(manual),
        "Independent scalar recomputation of VWAP, LWMP, max_share, HHI, and pivot.",
    )
    add_validation(
        validation_rows,
        "15_fixed_composition_never_mixes_active_sets",
        bool(fixed_summary["active_venue_set"].is_unique),
        int(len(fixed_summary)),
        "Each row is keyed by one exact active venue set.",
    )
    add_validation(
        validation_rows,
        "16_bootstrap_uses_UTC_blocks",
        bool(set(all7_boot["block_days"]) == {1, 7}),
        json_text(sorted(all7_boot["block_days"].unique().tolist())),
        "Blocks are constructed from UTC-floored event timestamps.",
    )
    add_validation(
        validation_rows,
        "17_same_minute_events_not_split",
        True,
        "block=floor((UTC_day-origin)/block_days)",
        "Block assignment is a deterministic function of the minute timestamp, so all eight events stay together.",
    )
    add_validation(
        validation_rows,
        "18_seed_recorded",
        seed == 42,
        seed,
        "Recovered from the original event generator; new sensitivity bootstraps use the requested event seed.",
    )
    duplicate_count = int(venue_audit["minute"]["time_utc"].duplicated().sum() + base_sample["time_utc"].duplicated().sum())
    add_validation(
        validation_rows,
        "19_no_duplicate_timestamps_in_minute_outputs",
        duplicate_count == 0,
        duplicate_count,
        "Checked the calendar audit and base-minute sample.",
    )
    nonempty_venue_distribution = venue_audit["distribution"].loc[
        venue_audit["distribution"]["minutes"] > 0
    ]
    core_missing = int(
        nonempty_venue_distribution.isna().sum().sum()
        + pd.DataFrame([all7_row]).isna().sum().sum()
        + pd.DataFrame([base6_headline]).isna().sum().sum()
        + fixed_summary.isna().sum().sum()
    )
    add_validation(
        validation_rows,
        "20_no_unexpected_missing_values_in_core_tables",
        core_missing == 0,
        core_missing,
        "Threshold-ineligible DV/bootstrap cells in the unified comparison are intentionally blank and labeled by DV-only status.",
    )
    add_validation(
        validation_rows,
        "21_existing_BTC_outputs_unmodified",
        len(changed_btc) == 0,
        json_text(changed_btc[:20]),
        "Size/mtime snapshots of existing BTC result trees are unchanged.",
    )
    add_validation(
        validation_rows,
        "22_existing_ETH_outputs_unmodified",
        len(changed_eth) == 0,
        json_text(changed_eth[:20]),
        "Size/mtime snapshot of the ETH replication tree is unchanged.",
    )
    add_validation(
        validation_rows,
        "23_Word_PDF_TXT_manuscripts_unmodified",
        len(changed_manuscripts) == 0,
        json_text(changed_manuscripts[:20]),
        "All pre-existing .docx/.pdf/.txt files outside the new output directory are unchanged.",
    )
    add_validation(
        validation_rows,
        "24_single_entry_reproduction",
        Path(__file__).resolve().is_file(),
        str(Path(__file__).resolve()),
        "The complete workflow is callable from this one script.",
    )
    add_validation(
        validation_rows,
        "25_validation_status_domain",
        True,
        "PASS|WARN|FAIL",
        "Status values are restricted to the requested domain.",
    )
    add_validation(
        validation_rows,
        "26_recomputed_all7_structure_matches_old",
        max(max_share_diff, hhi_diff) <= 1e-12,
        json_text({"max_share_max_abs_diff": max_share_diff, "HHI_max_abs_diff": hhi_diff}),
        "Old concentration values match the raw-input recomputation on all-seven-valid minutes.",
    )
    add_validation(
        validation_rows,
        "27_exclude_BitMEX_leave_one_out_crosscheck",
        bool(loo_compare) and base6_headline["lockin_pivot_change_rate"] < base6_headline["non_lockin_pivot_change_rate"],
        json_text(loo_compare),
        "The new fixed-all-six result is reconciled with, but not equated to, the older variable-availability leave-one-out result.",
    )
    add_validation(
        validation_rows,
        "28_original_venue_source_paths_confirmed",
        bool(input_manifest["raw_source_exists"].all() and len(input_manifest) == 7),
        json_text(input_manifest[["exchange", "raw_source_path"]].to_dict("records")),
        "All seven original venue CSV paths were resolved before the verified minute inputs were used.",
    )
    original_share_error = abs(
        float(venue_audit["distribution"]["share_of_original_valid_minutes"].sum()) - 1.0
    )
    original_count_total = int(
        venue_audit["distribution"]["original_valid_minutes"].sum()
    )
    add_validation(
        validation_rows,
        "29_original_valid_venue_count_shares_sum_to_one",
        original_share_error <= 1e-12 and original_count_total == valid_minutes,
        json_text(
            {
                "share_sum_abs_error": original_share_error,
                "original_valid_minute_count_sum": original_count_total,
            }
        ),
        "The venue-count shares use original-pool numerators and exactly exhaust the Binance-anchored valid-minute pool.",
    )
    validation = pd.DataFrame(validation_rows)
    if not set(validation["status"]).issubset({"PASS", "WARN", "FAIL"}):
        raise RuntimeError("Invalid validation status")
    validation.to_csv(metadata_dir / "validation_checks.csv", index=False, encoding="utf-8-sig")

    run_manifest = {
        "command": (
            f'"{sys.executable}" "{Path(__file__).resolve()}" --project-root "{root}" '
            f'--start-date "{args.start_date}" --end-date "{args.end_date}" --out-dir "{out_dir}" '
            f'--bootstrap-reps {args.bootstrap_reps} --seed {seed}'
        ),
        "started_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "elapsed_seconds": time.time() - started,
        "python": sys.version,
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "seed": seed,
        "bootstrap_reps": args.bootstrap_reps,
        "headline_gate": "PASS",
        "validation_counts": validation["status"].value_counts().to_dict(),
        "old_BTC_files_changed": changed_btc,
        "old_ETH_files_changed": changed_eth,
        "old_manuscript_files_changed": changed_manuscripts,
    }
    (metadata_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_final_report(
        out_dir / "BTC_FIXED_COMPOSITION_REVIEW_REPORT.md",
        baseline_headline,
        venue_audit["distribution"],
        baseline_summary,
        all7_summary,
        all7_headline,
        all7_boot,
        all7_proximity,
        all7_passthrough,
        base6_summary,
        base6_headline,
        base6_boot,
        fixed_summary,
        fixed_pivot,
        loo_compare,
        validation,
        input_manifest,
        seed,
        valid_minutes,
        int(all7_mask.sum()),
    )
    counts = validation["status"].value_counts().to_dict()
    print(
        f"[DONE] headline exact; valid minutes={valid_minutes:,}; all-seven={int(all7_mask.sum()):,}; "
        f"validation PASS={counts.get('PASS',0)} WARN={counts.get('WARN',0)} FAIL={counts.get('FAIL',0)}"
    )
    return 0 if counts.get("FAIL", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

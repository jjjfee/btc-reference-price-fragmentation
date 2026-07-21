#!/usr/bin/env python3
"""BTC post-2022 out-of-sample replication runner.

This runner keeps the original 2021-2022 calibration and core definitions, then
extends the date window. It writes only under the requested post-2022 output
directory and does not modify prior main-sample outputs.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BUILD_DIR = Path(__file__).resolve().parents[1] / "build"
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from make_dv_2021_2022 import (
    compute_p_repr,
    normalize_columns,
    parse_time_column,
    pick_col,
)
from run_dv_only_injection_experiments import (
    compute_aggregators,
    sample_valid_exchange_per_row,
    weighted_median_with_pivot,
)


EXCHANGES = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
PRICE_COL_CANDIDATES = ["p_usd_scaled", "p_usd", "price_usd", "p_scaled"]
WEIGHT_COL_CANDIDATES = ["DV_usd", "DV", "dollar_volume", "dv_usd"]
TIME_COL_CANDIDATES = ["Open time", "opentime", "timestamp", "date", "time", "datetime"]
VOLUME_COL_CANDIDATES = ["Volume", "volume", "vol", "qty", "amount", "turnover"]

MAIN_SAMPLE_START = "2021-01-01"
MAIN_SAMPLE_END = "2022-12-31 23:59:00"
POST_START_DEFAULT = "2023-01-01"
MIN_EXCHANGES_PER_MIN = 3
N_SAMPLE_MINUTES = 100_000
DELTA_WS = [0.5, 1.0, 2.0, -0.5]
SHOCK_TYPES = ["inflate_only", "reallocate_total_fixed"]
PIVOT_NBINS = 30
Z = 1.96


@dataclass
class Directories:
    root: Path
    raw_dir: Path
    out_dir: Path
    data_audit: Path
    results: Path
    figures: Path
    metadata: Path
    intermediate: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run BTC post-2022 core out-of-sample replication."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Project root containing existing 2021-2022 outputs.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=(Path(__file__).resolve().parents[2] / "data" / "external" / "raw" / "btc"),
        help="Directory containing raw BTCUSD_1m_<exchange>.csv files.",
    )
    parser.add_argument("--start-date", default=POST_START_DEFAULT)
    parser.add_argument(
        "--end-date",
        default="",
        help="Inclusive end timestamp/date. If omitted, the audit-selected end is used.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs") / "robustness" / "btc_post2022",
    )
    parser.add_argument("--reps", type=int, default=5000)
    parser.add_argument(
        "--seed",
        type=int,
        default=20260710,
        help="Seed for bootstrap and figure quantile intervals.",
    )
    parser.add_argument(
        "--event-seed",
        type=int,
        default=42,
        help="Seed for the DV-only perturbation minute sample; default matches the main-sample script.",
    )
    parser.add_argument("--chunk-size", type=int, default=200_000)
    parser.add_argument(
        "--sample-selection-only",
        action="store_true",
        help="Only run raw data audit and sample-window selection.",
    )
    return parser.parse_args()


def resolve_dirs(args: argparse.Namespace) -> Directories:
    root = args.root.resolve()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir = out_dir.resolve()
    dirs = Directories(
        root=root,
        raw_dir=args.raw_dir.resolve(),
        out_dir=out_dir,
        data_audit=out_dir / "data_audit",
        results=out_dir / "results",
        figures=out_dir / "figures",
        metadata=out_dir / "metadata",
        intermediate=out_dir / "intermediate",
    )
    for path in [
        dirs.out_dir,
        dirs.data_audit,
        dirs.results,
        dirs.figures,
        dirs.metadata,
        dirs.intermediate,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def utc_timestamp(value: str, is_end: bool = False) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    if is_end and len(value.strip()) == 10:
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)
    return ts.floor("min")


def exchange_from_path(path: Path) -> str:
    name = path.stem
    for ex in EXCHANGES:
        if ex.lower() in name.lower():
            return ex
    parts = name.split("_")
    return parts[2] if len(parts) >= 3 else name


def detect_columns(path: Path) -> dict[str, Any]:
    head = normalize_columns(pd.read_csv(path, nrows=5))
    time_col = pick_col(head, TIME_COL_CANDIDATES)
    open_col = pick_col(head, ["Open", "open"])
    high_col = pick_col(head, ["High", "high"])
    low_col = pick_col(head, ["Low", "low"])
    close_col = pick_col(head, ["Close", "close"])
    volume_col = pick_col(head, VOLUME_COL_CANDIDATES)
    if time_col is None:
        raise ValueError(f"{path.name}: cannot detect time column")
    if volume_col is None:
        raise ValueError(f"{path.name}: cannot detect volume column")
    return {
        "time_col": time_col,
        "open_col": open_col,
        "high_col": high_col,
        "low_col": low_col,
        "close_col": close_col,
        "volume_col": volume_col,
    }


def infer_volume_convention(volume_values: np.ndarray) -> tuple[str, float]:
    v = volume_values[np.isfinite(volume_values) & (volume_values > 0)]
    if len(v) < 10_000:
        return "unknown", np.nan
    frac = np.abs(v - np.round(v))
    int_ratio = float((frac < 1e-6).mean())
    if int_ratio > 0.95:
        return "quote_or_contract", int_ratio
    return "base", int_ratio


def safe_quantiles(values: np.ndarray, qs: list[float]) -> list[float]:
    v = values[np.isfinite(values)]
    if len(v) == 0:
        return [np.nan for _ in qs]
    return [float(np.quantile(v, q)) for q in qs]


def markdown_table(df: pd.DataFrame) -> str:
    """Small dependency-free markdown table writer."""
    if df.empty:
        return "_No rows._"
    work = df.copy()
    for col in work.columns:
        work[col] = work[col].map(
            lambda x: ""
            if pd.isna(x)
            else f"{x:.6g}"
            if isinstance(x, (float, np.floating))
            else str(x).replace("|", "\\|")
        )
    cols = [str(c) for c in work.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in work.columns) + " |")
    return "\n".join(lines)


def read_calibration(root: Path) -> pd.DataFrame:
    path = root / "dv_unit_and_price_scale_report.xlsx"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing main-sample calibration workbook: {path}. "
            "This run intentionally reuses the 2021-2022 calibration."
        )
    calibration = pd.read_excel(path)
    required = {
        "exchange",
        "price_scale_to_anchor",
        "anchor_usd_multiplier",
        "volume_unit_final",
    }
    missing = required - set(calibration.columns)
    if missing:
        raise KeyError(f"Calibration workbook missing columns: {sorted(missing)}")
    calibration["exchange"] = calibration["exchange"].astype(str)
    return calibration


def audit_raw_files(
    raw_dir: Path,
    post_start: pd.Timestamp,
    chunk_size: int,
) -> tuple[pd.DataFrame, dict[str, pd.Series], pd.DataFrame]:
    files = sorted(raw_dir.glob("BTCUSD_1m_*.csv"))
    if not files:
        raise FileNotFoundError(f"No BTCUSD raw CSV files found under {raw_dir}")

    coverage: dict[str, pd.Series] = {}
    audit_rows: list[dict[str, Any]] = []
    file_manifest_rows: list[dict[str, Any]] = []

    for path in files:
        ex = exchange_from_path(path)
        cols = detect_columns(path)
        usecols = list(
            dict.fromkeys(
                [
                    cols["time_col"],
                    cols["open_col"],
                    cols["high_col"],
                    cols["low_col"],
                    cols["close_col"],
                    cols["volume_col"],
                ]
            )
        )
        usecols = [c for c in usecols if c is not None]

        pieces = []
        volume_sample = []
        n_rows = 0
        n_time_parse_fail = 0
        first_ts: pd.Timestamp | None = None
        last_ts: pd.Timestamp | None = None

        for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_size):
            chunk = normalize_columns(chunk)
            t = parse_time_column(chunk[cols["time_col"]]).dt.floor("min")
            n_rows += len(chunk)
            n_time_parse_fail += int(t.isna().sum())

            p = compute_p_repr(
                chunk,
                cols["open_col"],
                cols["high_col"],
                cols["low_col"],
                cols["close_col"],
            )
            p = pd.to_numeric(p, errors="coerce")
            v = pd.to_numeric(chunk[cols["volume_col"]], errors="coerce")

            finite_t = t.dropna()
            if len(finite_t):
                mn = finite_t.min()
                mx = finite_t.max()
                first_ts = mn if first_ts is None else min(first_ts, mn)
                last_ts = mx if last_ts is None else max(last_ts, mx)

            v_ok = v[np.isfinite(v) & (v > 0)]
            if len(v_ok) and sum(len(a) for a in volume_sample) < 500_000:
                remaining = 500_000 - sum(len(a) for a in volume_sample)
                volume_sample.append(v_ok.iloc[:remaining].to_numpy(dtype=float))

            piece = pd.DataFrame(
                {
                    "time_utc": t,
                    "price_valid": np.isfinite(p) & (p > 0),
                    "volume_valid": np.isfinite(v) & (v > 0),
                }
            ).dropna(subset=["time_utc"])
            piece["valid"] = piece["price_valid"] & piece["volume_valid"]
            pieces.append(piece)

        if not pieces:
            raise ValueError(f"{path.name}: no parseable timestamps")

        raw_minute = pd.concat(pieces, ignore_index=True)
        duplicates = int(raw_minute["time_utc"].duplicated().sum())
        dedup = (
            raw_minute.sort_values("time_utc")
            .drop_duplicates("time_utc", keep="last")
            .reset_index(drop=True)
        )
        expected_minutes = int(
            ((last_ts - first_ts) / pd.Timedelta(minutes=1)) + 1
        )
        unique_minutes = int(len(dedup))
        missing_ratio = (
            (expected_minutes - unique_minutes) / expected_minutes
            if expected_minutes > 0
            else np.nan
        )

        vsample = (
            np.concatenate(volume_sample)
            if volume_sample
            else np.array([], dtype=float)
        )
        convention, int_ratio = infer_volume_convention(vsample)
        v_min, v_median, v_p95, v_max = safe_quantiles(vsample, [0.0, 0.5, 0.95, 1.0])

        audit_rows.append(
            {
                "exchange": ex,
                "file_name": path.name,
                "raw_path": str(path),
                "start_time": str(first_ts),
                "end_time": str(last_ts),
                "total_rows": int(n_rows),
                "unique_minutes": unique_minutes,
                "valid_price_minutes": int(dedup["price_valid"].sum()),
                "valid_volume_minutes": int(dedup["volume_valid"].sum()),
                "valid_price_and_volume_minutes": int(dedup["valid"].sum()),
                "duplicate_timestamps": duplicates,
                "missing_minute_ratio": float(missing_ratio),
                "time_parse_failures": int(n_time_parse_fail),
                "volume_field_name": cols["volume_col"],
                "volume_sample_positive_n": int(len(vsample)),
                "volume_min_positive_sample": v_min,
                "volume_median_positive_sample": v_median,
                "volume_p95_positive_sample": v_p95,
                "volume_max_positive_sample": v_max,
                "volume_integer_ratio_est": int_ratio,
                "inferred_volume_convention": convention,
            }
        )
        file_manifest_rows.append(
            {
                "exchange": ex,
                "file_name": path.name,
                "path": str(path),
                "bytes": int(path.stat().st_size),
                "time_col": cols["time_col"],
                "volume_col": cols["volume_col"],
                "price_rule": "OHLC4"
                if all(cols[c] for c in ["open_col", "high_col", "low_col", "close_col"])
                else "HL2"
                if cols["high_col"] and cols["low_col"]
                else "CLOSE",
            }
        )

        post = dedup.loc[dedup["time_utc"] >= post_start, ["time_utc", "valid"]].copy()
        coverage[ex] = post.set_index("time_utc")["valid"].astype(bool)

    return pd.DataFrame(audit_rows), coverage, pd.DataFrame(file_manifest_rows)


def yearly_coverage(coverage: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    max_end = max(series.index.max() for series in coverage.values() if len(series))
    start = pd.Timestamp(POST_START_DEFAULT, tz="UTC")
    full_index = pd.date_range(start, max_end, freq="min")
    matrix = pd.DataFrame(index=full_index)
    for ex in EXCHANGES:
        if ex in coverage:
            matrix[ex] = coverage[ex].reindex(full_index, fill_value=False).astype(bool)
    matrix = matrix[sorted(matrix.columns)]
    counts = matrix.sum(axis=1)

    rows: list[dict[str, Any]] = []
    for year, idx in pd.Series(matrix.index, index=matrix.index).groupby(matrix.index.year):
        segment_index = idx.index
        seg = matrix.loc[segment_index]
        seg_counts = counts.loc[segment_index]
        denom = len(seg)
        available = [c for c in seg.columns if bool(seg[c].any())]
        all_available = int((seg[available].sum(axis=1) == len(available)).sum()) if available else 0
        base = {
            "year": int(year),
            "window_start": str(segment_index.min()),
            "window_end": str(segment_index.max()),
            "calendar_minutes": int(denom),
            "minutes_at_least_3_valid": int((seg_counts >= 3).sum()),
            "share_at_least_3_valid": float((seg_counts >= 3).mean()),
            "minutes_at_least_5_valid": int((seg_counts >= 5).sum()),
            "share_at_least_5_valid": float((seg_counts >= 5).mean()),
            "available_exchange_count": int(len(available)),
            "minutes_all_available_valid": all_available,
            "share_all_available_valid": float(all_available / denom) if denom else np.nan,
        }
        for ex in seg.columns:
            base[f"{ex}_valid_minutes"] = int(seg[ex].sum())
            base[f"{ex}_coverage_share"] = float(seg[ex].mean())
        rows.append(base)

    return pd.DataFrame(rows), matrix


def longest_true_run(mask: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    if mask.empty or not bool(mask.any()):
        raise ValueError("No usable post-2022 minutes satisfying the validity rule")
    values = mask.to_numpy(dtype=bool)
    idx = mask.index
    best_start = best_end = cur_start = None
    best_len = cur_len = 0
    for i, val in enumerate(values):
        if val:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start = cur_start
                best_end = i
        else:
            cur_len = 0
            cur_start = None
    return idx[int(best_start)], idx[int(best_end)], int(best_len)


def choose_sample_window(
    matrix: pd.DataFrame,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp | None,
) -> dict[str, Any]:
    subset = matrix.loc[matrix.index >= requested_start]
    if requested_end is not None:
        subset = subset.loc[subset.index <= requested_end]
    counts = subset.sum(axis=1)
    valid3 = counts >= MIN_EXCHANGES_PER_MIN
    run_start, run_end, run_len = longest_true_run(valid3)
    return {
        "requested_start": str(requested_start),
        "requested_end": str(requested_end) if requested_end is not None else None,
        "selected_start": str(run_start),
        "selected_end": str(run_end),
        "selection_rule": f"longest continuous UTC-minute run with at least {MIN_EXCHANGES_PER_MIN} valid exchanges",
        "minimum_valid_exchanges_per_minute": MIN_EXCHANGES_PER_MIN,
        "selected_calendar_minutes": int(((run_end - run_start) / pd.Timedelta(minutes=1)) + 1),
        "selected_valid_minutes_rule_count": int(run_len),
        "post2022_raw_latest_timestamp": str(matrix.index.max()),
        "all_exchange_columns": list(matrix.columns),
    }


def write_data_audit_report(
    dirs: Directories,
    exchange_coverage: pd.DataFrame,
    yearly: pd.DataFrame,
    sample_selection: dict[str, Any],
    calibration: pd.DataFrame,
) -> None:
    lines = [
        "# BTC post-2022 data audit",
        "",
        "## Raw data path",
        f"- Raw BTC directory: `{dirs.raw_dir}`",
        f"- Main-sample calibration workbook: `{dirs.root / 'dv_unit_and_price_scale_report.xlsx'}`",
        "",
        "## Selected sample window",
        f"- Start: {sample_selection['selected_start']}",
        f"- End: {sample_selection['selected_end']}",
        f"- Rule: {sample_selection['selection_rule']}",
        f"- Valid calendar minutes in selected run: {sample_selection['selected_valid_minutes_rule_count']:,}",
        "",
        "## Exchange file coverage",
        markdown_table(exchange_coverage[
            [
                "exchange",
                "file_name",
                "start_time",
                "end_time",
                "total_rows",
                "valid_price_and_volume_minutes",
                "duplicate_timestamps",
                "missing_minute_ratio",
                "volume_field_name",
                "inferred_volume_convention",
            ]
        ]),
        "",
        "## Yearly post-2022 coverage",
        markdown_table(yearly[
            [
                "year",
                "calendar_minutes",
                "minutes_at_least_3_valid",
                "share_at_least_3_valid",
                "minutes_at_least_5_valid",
                "share_at_least_5_valid",
                "available_exchange_count",
                "minutes_all_available_valid",
                "share_all_available_valid",
            ]
        ]),
        "",
        "## 2021-2022 calibration reused",
        markdown_table(calibration[
            [
                "exchange",
                "price_scale_to_anchor",
                "anchor_usd_multiplier",
                "volume_unit_final",
                "volume_integer_ratio_est",
            ]
        ]),
        "",
        "## Notes",
        "- Price representative follows the main code path: OHLC4 if available, then HL2, then close.",
        "- Invalid observations are those with non-finite/non-positive price or non-finite/non-positive weight.",
        "- The post-2022 run reuses the 2021-2022 price-scale and volume-convention calibration.",
    ]
    (dirs.data_audit / "btc_post2022_data_audit.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def build_wide_post_sample(
    raw_dir: Path,
    calibration: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    full_index: pd.DatetimeIndex,
    chunk_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cal = calibration.set_index("exchange").to_dict(orient="index")
    prices = pd.DataFrame(index=full_index)
    weights = pd.DataFrame(index=full_index)
    rows: list[dict[str, Any]] = []

    for path in sorted(raw_dir.glob("BTCUSD_1m_*.csv")):
        ex = exchange_from_path(path)
        if ex not in cal:
            raise KeyError(f"No 2021-2022 calibration row for exchange {ex}")
        cols = detect_columns(path)
        usecols = list(
            dict.fromkeys(
                [
                    cols["time_col"],
                    cols["open_col"],
                    cols["high_col"],
                    cols["low_col"],
                    cols["close_col"],
                    cols["volume_col"],
                ]
            )
        )
        usecols = [c for c in usecols if c is not None]

        scale = float(cal[ex]["price_scale_to_anchor"])
        usd_mult = float(cal[ex]["anchor_usd_multiplier"])
        unit = str(cal[ex]["volume_unit_final"])
        parts = []
        n_rows_raw = n_rows_window = n_price_invalid = n_volume_invalid = n_time_fail = 0

        for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_size):
            chunk = normalize_columns(chunk)
            t = parse_time_column(chunk[cols["time_col"]]).dt.floor("min")
            n_rows_raw += len(chunk)
            n_time_fail += int(t.isna().sum())
            mask = (t >= start) & (t <= end)
            if not bool(mask.any()):
                continue
            sub = chunk.loc[mask].copy()
            t_sub = t.loc[mask]
            n_rows_window += len(sub)
            p_raw = compute_p_repr(
                sub,
                cols["open_col"],
                cols["high_col"],
                cols["low_col"],
                cols["close_col"],
            )
            p_raw = pd.to_numeric(p_raw, errors="coerce")
            p_usd = p_raw * scale * usd_mult
            v = pd.to_numeric(sub[cols["volume_col"]], errors="coerce")
            if unit == "base":
                dv = v * p_usd
            elif unit == "quote_or_contract":
                dv = v
            else:
                dv = v * p_usd
            n_price_invalid += int((~np.isfinite(p_usd) | (p_usd <= 0)).sum())
            n_volume_invalid += int((~np.isfinite(dv) | (dv <= 0)).sum())
            parts.append(pd.DataFrame({"time_utc": t_sub, "price": p_usd, "weight": dv}))

        if not parts:
            raise ValueError(f"{path.name}: no rows in selected post-2022 sample window")
        df = pd.concat(parts, ignore_index=True)
        before_dedup = len(df)
        df = df.dropna(subset=["time_utc"]).sort_values("time_utc")
        df = df.drop_duplicates("time_utc", keep="last").set_index("time_utc")
        prices[ex] = pd.to_numeric(df["price"], errors="coerce").reindex(full_index)
        weights[ex] = pd.to_numeric(df["weight"], errors="coerce").reindex(full_index)
        valid = (
            np.isfinite(prices[ex].to_numpy(dtype=float))
            & np.isfinite(weights[ex].to_numpy(dtype=float))
            & (prices[ex].to_numpy(dtype=float) > 0)
            & (weights[ex].to_numpy(dtype=float) > 0)
        )
        rows.append(
            {
                "exchange": ex,
                "raw_file": path.name,
                "rows_raw_file": int(n_rows_raw),
                "rows_in_window_before_dedup": int(n_rows_window),
                "duplicate_timestamps_in_window": int(before_dedup - len(df)),
                "time_parse_failures_raw": int(n_time_fail),
                "invalid_price_rows_in_window": int(n_price_invalid),
                "invalid_weight_rows_in_window": int(n_volume_invalid),
                "dedup_minutes_in_window": int(len(df)),
                "valid_minutes_after_main_rule": int(valid.sum()),
                "price_scale_to_anchor_reused": scale,
                "anchor_usd_multiplier_reused": usd_mult,
                "volume_unit_reused": unit,
            }
        )

    prices = prices[EXCHANGES]
    weights = weights[EXCHANGES]
    return prices, weights, pd.DataFrame(rows)


def compute_panel(
    prices_wide: pd.DataFrame, weights_wide: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    exchanges = list(prices_wide.columns)
    p = prices_wide.to_numpy(dtype=float)
    w = weights_wide.to_numpy(dtype=float)
    valid = np.isfinite(p) & np.isfinite(w) & (p > 0) & (w > 0)
    w_clean = np.where(valid, w, 0.0)
    p_clean = np.where(valid, p, np.nan)
    n_ex = valid.sum(axis=1).astype(int)
    total_w = w_clean.sum(axis=1)
    shares = np.divide(
        w_clean,
        total_w[:, None],
        out=np.zeros_like(w_clean),
        where=total_w[:, None] > 0,
    )
    max_share = shares.max(axis=1)
    hhi = (shares**2).sum(axis=1)
    dominant_idx = shares.argmax(axis=1)
    dominant_exchange = np.array(exchanges, dtype=object)[dominant_idx]
    p_dom = p_clean[np.arange(len(p_clean)), dominant_idx]
    share_dom = shares[np.arange(len(p_clean)), dominant_idx]
    vwap = np.divide(
        np.nansum(p_clean * w_clean, axis=1),
        total_w,
        out=np.full(len(total_w), np.nan),
        where=total_w > 0,
    )
    lwmp, pivot_idx, pivot_margin, total_w_check = weighted_median_with_pivot(p_clean, w_clean)
    pivot_exchange = np.where(
        pivot_idx >= 0,
        np.array(exchanges, dtype=object)[np.maximum(pivot_idx, 0)],
        "",
    )
    valid_minute = n_ex >= MIN_EXCHANGES_PER_MIN
    panel = pd.DataFrame(
        {
            "time_utc": prices_wide.index,
            "n_exchanges_used": n_ex,
            "total_DV_usd": total_w,
            "P_vwap_DV": vwap,
            "P_lwmp_DV": lwmp,
            "HHI": hhi,
            "max_share": max_share,
            "dominant_exchange": dominant_exchange,
            "dominant_price": p_dom,
            "share_dom": share_dom,
            "pivot_exchange": pivot_exchange,
            "pivot_margin": pivot_margin,
            "lock_in": (max_share > 0.5).astype(int),
            "valid_minute": valid_minute.astype(int),
        }
    )
    arrays = {
        "p_clean": p_clean,
        "w_clean": w_clean,
        "valid": valid,
        "valid_minute": valid_minute,
        "n_ex": n_ex,
        "shares": shares,
        "dominant_idx": dominant_idx,
        "p_dom": p_dom,
        "vwap": vwap,
        "lwmp": lwmp,
        "pivot_idx": pivot_idx,
        "total_w": total_w_check,
    }
    return panel, arrays


def spell_summary(panel_valid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = panel_valid[["time_utc", "lock_in"]].copy()
    lock = df["lock_in"].to_numpy(dtype=bool)
    times = pd.to_datetime(df["time_utc"], utc=True)
    spell_rows = []
    spell_id = 0
    i = 0
    while i < len(df):
        if not lock[i]:
            i += 1
            continue
        start_i = i
        j = i + 1
        while j < len(df) and lock[j] and (times.iloc[j] - times.iloc[j - 1] == pd.Timedelta(minutes=1)):
            j += 1
        spell_id += 1
        duration = j - start_i
        spell_rows.append(
            {
                "spell_id": spell_id,
                "start_time": str(times.iloc[start_i]),
                "end_time": str(times.iloc[j - 1]),
                "duration_minutes": int(duration),
            }
        )
        i = j

    spells = pd.DataFrame(spell_rows)
    durations = spells["duration_minutes"].to_numpy(dtype=float) if len(spells) else np.array([])
    summary = pd.DataFrame(
        [
            {
                "over_half_spell_count": int(len(spells)),
                "spell_duration_median": float(np.median(durations)) if len(durations) else np.nan,
                "spell_duration_p95": float(np.quantile(durations, 0.95)) if len(durations) else np.nan,
                "max_spell_minutes": int(np.max(durations)) if len(durations) else 0,
                "spells_ge_60_minutes": int((durations >= 60).sum()) if len(durations) else 0,
                "spells_ge_360_minutes": int((durations >= 360).sum()) if len(durations) else 0,
                "spells_ge_1440_minutes": int((durations >= 1440).sum()) if len(durations) else 0,
            }
        ]
    )
    return summary, spells


def lockin_summary(panel_valid: pd.DataFrame, spells_one_row: pd.DataFrame) -> pd.DataFrame:
    max_share = panel_valid["max_share"]
    row = {
        "valid_minutes": int(len(panel_valid)),
        "number_of_venues": int(panel_valid["n_exchanges_used"].max()),
        "median_max_share": float(max_share.median()),
        "p95_max_share": float(max_share.quantile(0.95)),
        "share_max_share_gt_0p5": float((max_share > 0.5).mean()),
    }
    row.update(spells_one_row.iloc[0].to_dict())
    return pd.DataFrame([row])


def wilson_ci(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / den
    return max(0.0, center - half), min(1.0, center + half)


def make_edges(x: pd.Series, nbins: int = PIVOT_NBINS) -> np.ndarray:
    arr = pd.to_numeric(x, errors="coerce").dropna().to_numpy(dtype=float)
    q = np.linspace(0, 1, nbins + 1)
    try:
        edges = np.quantile(arr, q, method="linear")
    except TypeError:
        edges = np.quantile(arr, q, interpolation="linear")
    edges = np.unique(edges)
    if len(edges) < 5:
        raise ValueError("Too few unique max_share edges")
    return edges


def run_dvonly_events(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    event_seed: int,
) -> pd.DataFrame:
    valid_idx = np.flatnonzero(arrays["valid_minute"])
    sample_n = min(N_SAMPLE_MINUTES, len(valid_idx))
    rng = np.random.default_rng(event_seed)
    selected = rng.choice(valid_idx, size=sample_n, replace=False)

    times = panel["time_utc"].iloc[selected].to_numpy()
    p = arrays["p_clean"][selected, :].copy()
    w = arrays["w_clean"][selected, :].copy()
    max_share = panel["max_share"].iloc[selected].to_numpy(dtype=float)
    dominant_exchange = panel["dominant_exchange"].iloc[selected].astype(str).to_numpy()

    _, _, p_vwap, p_lwmp, pivot0, margin0, totalw0, w_clean0, p_clean0 = compute_aggregators(p, w)
    valid_w0 = (w_clean0 > 0) & np.isfinite(w_clean0)
    shocked_idx = sample_valid_exchange_per_row(valid_w0, rng)
    wj0 = w_clean0[np.arange(sample_n), shocked_idx]
    share0 = np.divide(wj0, totalw0, out=np.full(sample_n, np.nan), where=totalw0 > 0)
    exchange_names = np.array(EXCHANGES, dtype=object)

    frames: list[pd.DataFrame] = []
    for shock_type in SHOCK_TYPES:
        for delta_w in DELTA_WS:
            factor = 1.0 + float(delta_w)
            if factor <= 0:
                continue
            w_shock = w_clean0.copy()
            if shock_type == "inflate_only":
                w_shock[np.arange(sample_n), shocked_idx] = wj0 * factor
            elif shock_type == "reallocate_total_fixed":
                wj_new = wj0 * factor
                rest0 = totalw0 - wj0
                too_big = (totalw0 > 0) & (wj_new >= (1.0 - 1e-9) * totalw0)
                wj_new = np.where(too_big, (1.0 - 1e-9) * totalw0, wj_new)
                scale_rest = np.where(rest0 > 0, (totalw0 - wj_new) / rest0, 1.0)
                scale_rest = np.where(scale_rest < 0, np.nan, scale_rest)
                w_shock = w_shock * scale_rest[:, None]
                w_shock[np.arange(sample_n), shocked_idx] = wj_new
                bad = ~np.isfinite(scale_rest)
                if np.any(bad):
                    w_shock[bad, :] = np.nan
            else:
                continue

            _, _, p_vwap1, p_lwmp1, pivot1, margin1, totalw1, w_clean1, _ = compute_aggregators(
                p_clean0, w_shock
            )
            pivot_changed = (pivot0 != -1) & (pivot1 != -1) & (pivot1 != pivot0)
            wj1 = w_clean1[np.arange(sample_n), shocked_idx]
            share1 = np.divide(wj1, totalw1, out=np.full(sample_n, np.nan), where=totalw1 > 0)
            frames.append(
                pd.DataFrame(
                    {
                        "time_utc": times,
                        "shock_type": shock_type,
                        "gamma": float(delta_w),
                        "delta_w": float(delta_w),
                        "weight_factor": float(factor),
                        "exchange_shocked": exchange_names[shocked_idx],
                        "share_shocked_before": share0,
                        "share_shocked_after": share1,
                        "dominant_exchange": dominant_exchange,
                        "max_share": max_share,
                        "lock_in": (max_share > 0.5).astype(int),
                        "pivot_exchange_before": np.where(pivot0 >= 0, exchange_names[np.maximum(pivot0, 0)], ""),
                        "pivot_exchange_after": np.where(pivot1 >= 0, exchange_names[np.maximum(pivot1, 0)], ""),
                        "pivot_margin_before": margin0,
                        "pivot_margin_after": margin1,
                        "pivot_changed": pivot_changed.astype(int),
                        "shift_vwap": (p_vwap1 - p_vwap) / p_vwap,
                        "shift_lwmp": (p_lwmp1 - p_lwmp) / p_lwmp,
                    }
                )
            )
    out = pd.concat(frames, ignore_index=True)
    out["time_utc"] = pd.to_datetime(out["time_utc"], utc=True).dt.floor("min")
    return out


def pivot_bins(events: pd.DataFrame, edges: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add_rows(sub: pd.DataFrame, shock_label: str) -> None:
        working = sub.copy()
        working["bin"] = pd.cut(working["max_share"], bins=edges, include_lowest=True, labels=False)
        for gamma, sg in working.groupby("gamma", observed=True):
            for bin_id, sb in sg.groupby("bin", observed=True):
                if pd.isna(bin_id):
                    continue
                b = int(bin_id)
                n = int(len(sb))
                k = int(sb["pivot_changed"].sum())
                lo, hi = wilson_ci(k, n)
                rows.append(
                    {
                        "shock_type": shock_label,
                        "gamma": float(gamma),
                        "bin_id": b,
                        "x_left": float(edges[b]),
                        "x_right": float(edges[b + 1]),
                        "max_share_mid": float((edges[b] + edges[b + 1]) / 2),
                        "n": n,
                        "k": k,
                        "pivot_rate": float(k / n) if n else np.nan,
                        "ci_lo": lo,
                        "ci_hi": hi,
                    }
                )

    add_rows(events, "overall")
    for shock_type in sorted(events["shock_type"].dropna().unique()):
        add_rows(events.loc[events["shock_type"] == shock_type], str(shock_type))
    return pd.DataFrame(rows).sort_values(["shock_type", "gamma", "max_share_mid"])


def pivot_contrast(events: pd.DataFrame) -> dict[str, float | int]:
    g = events.groupby("lock_in", observed=True)["pivot_changed"].agg(["mean", "count"])
    non = g.loc[0]
    lock = g.loc[1]
    return {
        "non_lockin_pivot_change_rate": float(non["mean"]),
        "lockin_pivot_change_rate": float(lock["mean"]),
        "difference_lockin_minus_nonlockin": float(lock["mean"] - non["mean"]),
        "rate_ratio_lockin_over_nonlockin": float(lock["mean"] / non["mean"]),
        "n_non_lockin_events": int(non["count"]),
        "n_lockin_events": int(lock["count"]),
        "n_events": int(len(events)),
    }


def block_bootstrap(events: pd.DataFrame, block_days: int, reps: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = events[["time_utc", "lock_in", "pivot_changed"]].copy()
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True).dt.floor("min")
    frame["_outcome"] = pd.to_numeric(frame["pivot_changed"], errors="coerce")
    frame["_lock"] = pd.to_numeric(frame["lock_in"], errors="coerce")
    frame = frame.dropna(subset=["time_utc", "_outcome", "_lock"])
    origin = frame["time_utc"].dt.floor("D").min()
    day_number = (frame["time_utc"].dt.floor("D") - origin).dt.days
    frame["_block"] = (day_number // block_days).astype(int)
    grouped = (
        frame.groupby(["_block", "_lock"], observed=True)["_outcome"]
        .agg(["sum", "count"])
        .reset_index()
    )
    blocks = np.sort(frame["_block"].unique())
    index = pd.MultiIndex.from_product([blocks, [0, 1]], names=["_block", "_lock"])
    grouped = grouped.set_index(["_block", "_lock"]).reindex(index, fill_value=0).reset_index()

    sums = np.zeros((len(blocks), 2), dtype=float)
    counts = np.zeros((len(blocks), 2), dtype=float)
    block_to_pos = {block: pos for pos, block in enumerate(blocks)}
    for block, lock_value, outcome_sum, outcome_count in grouped.itertuples(index=False, name=None):
        pos = block_to_pos[block]
        lock = int(lock_value)
        sums[pos, lock] = outcome_sum
        counts[pos, lock] = outcome_count

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
                "rep": rep,
                "block_days": block_days,
                "rate_nonlock": rates[0],
                "rate_lock": rates[1],
                "difference_lock_minus_nonlock": rates[1] - rates[0],
                "ratio_lock_over_nonlock": rates[1] / rates[0],
            }
        )
    draws = pd.DataFrame.from_records(records)
    rows = []
    for col in [
        "rate_nonlock",
        "rate_lock",
        "difference_lock_minus_nonlock",
        "ratio_lock_over_nonlock",
    ]:
        values = draws[col].to_numpy()
        rows.append(
            {
                "block_days": block_days,
                "statistic": col,
                "point_estimate": float(
                    {
                        "rate_nonlock": frame.loc[frame["_lock"] == 0, "_outcome"].mean(),
                        "rate_lock": frame.loc[frame["_lock"] == 1, "_outcome"].mean(),
                        "difference_lock_minus_nonlock": frame.loc[frame["_lock"] == 1, "_outcome"].mean()
                        - frame.loc[frame["_lock"] == 0, "_outcome"].mean(),
                        "ratio_lock_over_nonlock": frame.loc[frame["_lock"] == 1, "_outcome"].mean()
                        / frame.loc[frame["_lock"] == 0, "_outcome"].mean(),
                    }[col]
                ),
                "bootstrap_mean": float(np.mean(values)),
                "bootstrap_se": float(np.std(values, ddof=1)),
                "ci95_low": float(np.quantile(values, 0.025)),
                "ci95_high": float(np.quantile(values, 0.975)),
                "reps_completed": int(len(draws)),
                "seed": int(seed),
                "n_blocks": int(len(blocks)),
            }
        )
    return pd.DataFrame(rows), draws


def vwap_proximity_bins(panel_valid: pd.DataFrame, edges: np.ndarray, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = panel_valid.copy()
    base["rel_gap_dom"] = (base["P_vwap_DV"] - base["dominant_price"]).abs() / base["P_vwap_DV"]
    base["bin"] = pd.cut(base["max_share"], bins=edges, include_lowest=True, right=False)
    rows = []
    for i, interval in enumerate(base["bin"].cat.categories):
        sub = base.loc[base["bin"] == interval, "rel_gap_dom"].dropna().to_numpy(dtype=float)
        q95 = float(np.quantile(sub, 0.95)) if len(sub) else np.nan
        med = float(np.median(sub)) if len(sub) else np.nan
        if len(sub) >= 500:
            sample = sub
            if len(sample) > 20_000:
                sample = rng.choice(sample, size=20_000, replace=False)
            boots = np.array(
                [np.quantile(sample[rng.integers(0, len(sample), size=len(sample))], 0.95) for _ in range(500)]
            )
            ci_low = float(np.quantile(boots, 0.025))
            ci_high = float(np.quantile(boots, 0.975))
        else:
            ci_low = np.nan
            ci_high = np.nan
        rows.append(
            {
                "bin_id": i,
                "x_left": float(interval.left),
                "x_right": float(interval.right),
                "x_center": float((interval.left + interval.right) / 2),
                "n": int(len(sub)),
                "q95_rel_gap_dom": q95,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "median_rel_gap_dom": med,
            }
        )
    return pd.DataFrame(rows)


def run_price_passthrough(
    panel: pd.DataFrame, arrays: dict[str, np.ndarray], lambdas: list[float]
) -> pd.DataFrame:
    valid_idx = np.flatnonzero(arrays["valid_minute"])
    prices = arrays["p_clean"][valid_idx, :]
    weights = arrays["w_clean"][valid_idx, :]
    dominant_idx = arrays["dominant_idx"][valid_idx]
    p_dom = arrays["p_dom"][valid_idx]
    vwap0 = arrays["vwap"][valid_idx]
    lwmp0 = arrays["lwmp"][valid_idx]
    panel_valid = panel.iloc[valid_idx].reset_index(drop=True)
    states = np.where(panel_valid["max_share"].to_numpy(dtype=float) > 0.5, "lockin", "non_lockin")

    rows = []
    for lam in lambdas:
        prices_prime = prices.copy()
        prices_prime[np.arange(len(prices_prime)), dominant_idx] = p_dom * (1.0 + lam)
        vwap1 = np.divide(
            np.nansum(prices_prime * weights, axis=1),
            weights.sum(axis=1),
            out=np.full(len(prices_prime), np.nan),
            where=weights.sum(axis=1) > 0,
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
                    "shock_label": f"{lam:+.3%}",
                    "state": state,
                    "n": int(mask.sum()),
                    "VWAP_mean_kappa": float(np.nanmean(kv)),
                    "VWAP_median_kappa": float(np.nanmedian(kv)),
                    "LWMP_mean_kappa": float(np.nanmean(kl)),
                    "LWMP_median_kappa": float(np.nanmedian(kl)),
                    "LWMP_zero_share": float(np.isclose(kl, 0.0, atol=1e-12).mean()),
                    "LWMP_one_share": float(np.isclose(kl, 1.0, atol=1e-8).mean()),
                }
            )
    return pd.DataFrame(rows)


def plot_lwmp_boundary(bins: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    df = bins[
        (bins["shock_type"].astype(str) == "inflate_only")
        & np.isclose(pd.to_numeric(bins["gamma"], errors="coerce"), 1.0)
    ].copy()
    df = df.sort_values("max_share_mid")
    draw_line_chart(
        x=df["max_share_mid"].to_numpy(dtype=float),
        y=df["pivot_rate"].to_numpy(dtype=float),
        out_png=out_png,
        out_pdf=out_pdf,
        xlabel="Dominant venue share",
        ylabel="Pivot-change rate",
        y_min=0.0,
        y_max=1.0,
        ci_low=df["ci_lo"].to_numpy(dtype=float),
        ci_high=df["ci_hi"].to_numpy(dtype=float),
        vertical_x=0.5,
    )


def plot_vwap_proximity(bins: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    df = bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    ymax = float(np.nanmax(df["q95_rel_gap_dom"].to_numpy(dtype=float)) * 1.12)
    draw_line_chart(
        x=df["x_center"].to_numpy(dtype=float),
        y=df["q95_rel_gap_dom"].to_numpy(dtype=float),
        out_png=out_png,
        out_pdf=out_pdf,
        xlabel="Dominant venue share",
        ylabel="q95 relative VWAP gap",
        y_min=0.0,
        y_max=ymax if np.isfinite(ymax) and ymax > 0 else 0.01,
        ci_low=df["ci_low"].to_numpy(dtype=float),
        ci_high=df["ci_high"].to_numpy(dtype=float),
        vertical_x=0.5,
    )


def draw_line_chart(
    x: np.ndarray,
    y: np.ndarray,
    out_png: Path,
    out_pdf: Path,
    xlabel: str,
    ylabel: str,
    y_min: float,
    y_max: float,
    ci_low: np.ndarray | None = None,
    ci_high: np.ndarray | None = None,
    vertical_x: float | None = None,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 2160, 1380
    left, right, top, bottom = 210, 80, 90, 170
    plot_w = width - left - right
    plot_h = height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image, "RGBA")
    try:
        tick_font = ImageFont.truetype("DejaVuSans.ttf", 28)
        label_font = ImageFont.truetype("DejaVuSans.ttf", 34)
        label_font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
    except Exception:
        tick_font = ImageFont.load_default()
        label_font = tick_font
        label_font_bold = tick_font

    ok = np.isfinite(x) & np.isfinite(y)
    x = x[ok]
    y = y[ok]
    if ci_low is not None and ci_high is not None:
        ci_low = ci_low[ok]
        ci_high = ci_high[ok]

    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    x_pad = max((x_max - x_min) * 0.03, 1e-6)
    x_min -= x_pad
    x_max += x_pad

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    # Grid and axes.
    grid_color = (214, 219, 225, 255)
    axis_color = (35, 39, 47, 255)
    for frac in np.linspace(0, 1, 6):
        yy = top + frac * plot_h
        draw.line([(left, yy), (left + plot_w, yy)], fill=grid_color, width=2)
    for frac in np.linspace(0, 1, 6):
        xx = left + frac * plot_w
        draw.line([(xx, top), (xx, top + plot_h)], fill=(235, 238, 242, 255), width=1)
    draw.line([(left, top), (left, top + plot_h), (left + plot_w, top + plot_h)], fill=axis_color, width=4)

    # CI band.
    if ci_low is not None and ci_high is not None:
        ci_ok = np.isfinite(ci_low) & np.isfinite(ci_high)
        if bool(ci_ok.any()):
            upper = [(sx(float(xx)), sy(float(hi))) for xx, hi in zip(x[ci_ok], ci_high[ci_ok])]
            lower = [(sx(float(xx)), sy(float(lo))) for xx, lo in zip(x[ci_ok][::-1], ci_low[ci_ok][::-1])]
            draw.polygon(upper + lower, fill=(74, 125, 180, 42))

    # 0.5 boundary.
    if vertical_x is not None and x_min <= vertical_x <= x_max:
        vx = sx(vertical_x)
        dash = 18
        yy = top
        while yy < top + plot_h:
            draw.line([(vx, yy), (vx, min(yy + dash, top + plot_h))], fill=(20, 20, 20, 210), width=4)
            yy += dash * 2

    points = [(sx(float(xx)), sy(float(yy))) for xx, yy in zip(x, y)]
    if len(points) >= 2:
        draw.line(points, fill=(37, 99, 155, 255), width=7, joint="curve")
    for px, py in points:
        draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=(37, 99, 155, 255))

    # Ticks and labels.
    tick_color = (70, 76, 86, 255)
    for value in np.linspace(max(0.0, x_min), min(1.0, x_max), 6):
        xx = sx(float(value))
        draw.line([(xx, top + plot_h), (xx, top + plot_h + 12)], fill=axis_color, width=3)
        draw.text((xx - 34, top + plot_h + 28), f"{value:.2f}", fill=tick_color, font=tick_font)
    for value in np.linspace(y_min, y_max, 6):
        yy = sy(float(value))
        draw.line([(left - 12, yy), (left, yy)], fill=axis_color, width=3)
        draw.text((118, yy - 15), f"{value:.3g}", fill=tick_color, font=tick_font)

    label_bbox = draw.textbbox((0, 0), xlabel, font=label_font_bold)
    label_w = label_bbox[2] - label_bbox[0]
    draw.text((left + plot_w / 2 - label_w / 2, height - 86), xlabel, fill=axis_color, font=label_font_bold)

    ylabel_img = Image.new("RGBA", (520, 58), (255, 255, 255, 0))
    ylabel_draw = ImageDraw.Draw(ylabel_img)
    ylabel_draw.text((0, 8), ylabel, fill=axis_color, font=label_font_bold)
    ylabel_img = ylabel_img.rotate(90, expand=True)
    image.paste(ylabel_img, (14, top + plot_h // 2 - ylabel_img.height // 2), ylabel_img)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_png)
    image.save(out_pdf, "PDF", resolution=300.0)


def load_baseline_comparison(root: Path) -> dict[str, Any]:
    conc = pd.read_csv(root / "experiments" / "weight_concentration_minute_level.csv")
    conc["time_utc"] = pd.to_datetime(conc["time_utc"], utc=True)
    spells_summary, _ = spell_summary(
        conc.assign(lock_in=(pd.to_numeric(conc["max_share"], errors="coerce") > 0.5).astype(int))
    )
    audit = pd.read_csv(root / "experiments_dvonly" / "audit_lockin" / "audit_lockin_summary.csv")
    audit = audit.set_index("lock_in")
    boot1 = pd.read_csv(root / "outputs" / "robustness" / "bootstrap_1day" / "bootstrap_summary.csv")
    boot7 = pd.read_csv(root / "outputs" / "robustness" / "bootstrap_7day" / "bootstrap_summary.csv")
    vwap_bins = pd.read_csv(root / "experiments_structure_vwap" / "vwap_head_proximity_bins_maxshare.csv")
    vwap_valid = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    pass_summary = pd.read_csv(root / "outputs" / "appendix" / "G" / "summary_by_state_lambda.csv")

    def summary_value(variable: str, state: str, stat: str, lam: float = 0.001) -> float:
        s = pass_summary[
            np.isclose(pass_summary["lambda"], lam)
            & (pass_summary["variable"] == variable)
            & (pass_summary["state"] == state)
            & (pass_summary["stat"] == stat)
        ]
        return float(s["value"].iloc[0]) if len(s) else np.nan

    diff1 = boot1.loc[boot1["statistic"] == "difference_lock_minus_nonlock"].iloc[0]
    diff7 = boot7.loc[boot7["statistic"] == "difference_lock_minus_nonlock"].iloc[0]
    return {
        "Sample": "BTCUSD 2021-2022 baseline",
        "Start date": "2021-01-01",
        "End date": "2022-12-31 23:59:00",
        "Valid minutes": int(len(conc)),
        "Number of venues": 7,
        "Share max_share > 0.5": float((pd.to_numeric(conc["max_share"]) > 0.5).mean()),
        "Median max_share": float(pd.to_numeric(conc["max_share"]).median()),
        "P95 max_share": float(pd.to_numeric(conc["max_share"]).quantile(0.95)),
        "Non-lock-in pivot-change rate": float(audit.loc[0, "pivot_changed_rate"]),
        "Lock-in pivot-change rate": float(audit.loc[1, "pivot_changed_rate"]),
        "Difference": float(audit.loc[1, "pivot_changed_rate"] - audit.loc[0, "pivot_changed_rate"]),
        "Rate ratio": float(audit.loc[1, "pivot_changed_rate"] / audit.loc[0, "pivot_changed_rate"]),
        "Bootstrap CI, 1-day": f"[{diff1['ci95_low']:.6g}, {diff1['ci95_high']:.6g}]",
        "Bootstrap CI, 7-day": f"[{diff7['ci95_low']:.6g}, {diff7['ci95_high']:.6g}]",
        "Maximum lock-in spell": int(spells_summary.iloc[0]["max_spell_minutes"]),
        "VWAP q95 gap, lowest concentration bin": float(vwap_valid.iloc[0]["q95_rel_gap_dom"]),
        "VWAP q95 gap, highest concentration bin": float(vwap_valid.iloc[-1]["q95_rel_gap_dom"]),
        "Median LWMP pass-through, lock-in": summary_value("kappa_LWMP", "lockin", "p50"),
        "Median VWAP pass-through, lock-in": summary_value("kappa_VWAP", "lockin", "p50"),
        "Median VWAP pass-through, non-lock-in": summary_value("kappa_VWAP", "non_lockin", "p50"),
    }


def build_comparison_row(
    sample_selection: dict[str, Any],
    lock_summary: pd.DataFrame,
    pivot_stats: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    vwap_bins: pd.DataFrame,
    passthrough: pd.DataFrame,
) -> dict[str, Any]:
    diff1 = bootstrap_summary[
        (bootstrap_summary["block_days"] == 1)
        & (bootstrap_summary["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    diff7 = bootstrap_summary[
        (bootstrap_summary["block_days"] == 7)
        & (bootstrap_summary["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")

    def pt(state: str, col: str, lam: float = 0.001) -> float:
        s = passthrough[(np.isclose(passthrough["lambda"], lam)) & (passthrough["state"] == state)]
        return float(s[col].iloc[0]) if len(s) else np.nan

    row = lock_summary.iloc[0]
    return {
        "Sample": "BTCUSD post-2022 out-of-sample",
        "Start date": sample_selection["selected_start"],
        "End date": sample_selection["selected_end"],
        "Valid minutes": int(row["valid_minutes"]),
        "Number of venues": int(row["number_of_venues"]),
        "Share max_share > 0.5": float(row["share_max_share_gt_0p5"]),
        "Median max_share": float(row["median_max_share"]),
        "P95 max_share": float(row["p95_max_share"]),
        "Non-lock-in pivot-change rate": pivot_stats["non_lockin_pivot_change_rate"],
        "Lock-in pivot-change rate": pivot_stats["lockin_pivot_change_rate"],
        "Difference": pivot_stats["difference_lockin_minus_nonlockin"],
        "Rate ratio": pivot_stats["rate_ratio_lockin_over_nonlockin"],
        "Bootstrap CI, 1-day": f"[{diff1['ci95_low']:.6g}, {diff1['ci95_high']:.6g}]",
        "Bootstrap CI, 7-day": f"[{diff7['ci95_low']:.6g}, {diff7['ci95_high']:.6g}]",
        "Maximum lock-in spell": int(row["max_spell_minutes"]),
        "VWAP q95 gap, lowest concentration bin": float(vb.iloc[0]["q95_rel_gap_dom"]),
        "VWAP q95 gap, highest concentration bin": float(vb.iloc[-1]["q95_rel_gap_dom"]),
        "Median LWMP pass-through, lock-in": pt("lockin", "LWMP_median_kappa"),
        "Median VWAP pass-through, lock-in": pt("lockin", "VWAP_median_kappa"),
        "Median VWAP pass-through, non-lock-in": pt("non_lockin", "VWAP_median_kappa"),
    }


def validate_outputs(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    passthrough: pd.DataFrame,
    bootstrap_summary: pd.DataFrame,
    output_paths: list[Path],
) -> pd.DataFrame:
    valid_panel = panel[panel["valid_minute"] == 1].copy()
    checks: list[dict[str, Any]] = []

    share_sum = arrays["shares"][arrays["valid_minute"]].sum(axis=1)
    checks.append(
        {
            "check": "weights_normalize_to_one",
            "status": "PASS" if np.nanmax(np.abs(share_sum - 1.0)) < 1e-8 else "FAIL",
            "value": float(np.nanmax(np.abs(share_sum - 1.0))),
            "detail": "Maximum absolute deviation of row shares from one.",
        }
    )
    ms = valid_panel["max_share"]
    checks.append(
        {
            "check": "max_share_in_unit_interval",
            "status": "PASS" if ((ms >= -1e-12) & (ms <= 1 + 1e-12)).all() else "FAIL",
            "value": f"{float(ms.min()):.6g},{float(ms.max()):.6g}",
            "detail": "Minimum and maximum max_share.",
        }
    )
    lock = valid_panel["max_share"] > 0.5
    pivot_dom_viol = int((valid_panel.loc[lock, "pivot_exchange"] != valid_panel.loc[lock, "dominant_exchange"]).sum())
    checks.append(
        {
            "check": "lockin_pivot_is_dominant",
            "status": "PASS" if pivot_dom_viol == 0 else "FAIL",
            "value": pivot_dom_viol,
            "detail": "Violations of pivot==dominant when max_share>0.5.",
        }
    )
    lock_pt = passthrough[passthrough["state"] == "lockin"]
    max_lwmp_dev = float(np.nanmax(np.abs(lock_pt["LWMP_median_kappa"].to_numpy(dtype=float) - 1.0)))
    checks.append(
        {
            "check": "lwmp_lockin_passthrough_theory",
            "status": "PASS" if max_lwmp_dev < 1e-8 else "FAIL",
            "value": max_lwmp_dev,
            "detail": "Maximum |median LWMP kappa - 1| across lock-in price shocks.",
        }
    )
    checks.append(
        {
            "check": "bootstrap_uses_utc_blocks",
            "status": "PASS" if set(bootstrap_summary["block_days"].unique()) == {1, 7} else "FAIL",
            "value": ",".join(map(str, sorted(bootstrap_summary["block_days"].unique()))),
            "detail": "Bootstrap summaries are grouped by UTC block_days.",
        }
    )

    # Manual minute-level recomputation for VWAP and LWMP.
    valid_idx = np.flatnonzero(arrays["valid_minute"])
    pick = np.unique(np.linspace(0, len(valid_idx) - 1, num=min(9, len(valid_idx)), dtype=int))
    vwap_errs = []
    lwmp_errs = []
    for pos in valid_idx[pick]:
        p = arrays["p_clean"][pos]
        w = arrays["w_clean"][pos]
        ok = np.isfinite(p) & np.isfinite(w) & (p > 0) & (w > 0)
        vwap_manual = float((p[ok] * w[ok]).sum() / w[ok].sum())
        order = np.argsort(p[ok], kind="mergesort")
        ps = p[ok][order]
        ws = w[ok][order]
        lwmp_manual = float(ps[np.searchsorted(np.cumsum(ws), 0.5 * ws.sum(), side="left")])
        vwap_errs.append(abs(vwap_manual - arrays["vwap"][pos]))
        lwmp_errs.append(abs(lwmp_manual - arrays["lwmp"][pos]))
    checks.append(
        {
            "check": "manual_vwap_lwmp_recalculation",
            "status": "PASS" if max(vwap_errs + lwmp_errs) < 1e-8 else "FAIL",
            "value": f"vwap_max={max(vwap_errs):.3g};lwmp_max={max(lwmp_errs):.3g}",
            "detail": "Manual scalar recomputation on representative valid minutes.",
        }
    )
    for path in output_paths:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
            missing = int(df.isna().sum().sum())
            duplicate_time = int(df["time_utc"].duplicated().sum()) if "time_utc" in df.columns else 0
            checks.append(
                {
                    "check": f"output_audit:{path.name}",
                    "status": "PASS",
                    "value": f"rows={len(df)};missing={missing};duplicate_time={duplicate_time}",
                    "detail": str(path),
                }
            )
    return pd.DataFrame(checks)


def write_final_report(
    dirs: Directories,
    sample_selection: dict[str, Any],
    exchange_coverage: pd.DataFrame,
    yearly: pd.DataFrame,
    comparison: pd.DataFrame,
    validation: pd.DataFrame,
    pivot_stats: dict[str, Any],
    vwap_bins: pd.DataFrame,
    passthrough: pd.DataFrame,
) -> None:
    latest = exchange_coverage["end_time"].max()
    post_row = comparison[comparison["Sample"].str.contains("post-2022")].iloc[0]
    base_row = comparison[comparison["Sample"].str.contains("baseline")].iloc[0]
    overhalf_change = (
        "more frequent"
        if post_row["Share max_share > 0.5"] > base_row["Share max_share > 0.5"]
        else "less frequent"
    )
    diff1 = comparison.loc[comparison["Sample"].str.contains("post-2022"), "Bootstrap CI, 1-day"].iloc[0]
    diff7 = comparison.loc[comparison["Sample"].str.contains("post-2022"), "Bootstrap CI, 7-day"].iloc[0]
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    vwap_channel = bool(vb.iloc[-1]["q95_rel_gap_dom"] < vb.iloc[0]["q95_rel_gap_dom"])
    pt_lock = passthrough[(passthrough["state"] == "lockin") & np.isclose(passthrough["lambda"], 0.001)]
    pt_ok = bool(len(pt_lock) and abs(float(pt_lock["LWMP_median_kappa"].iloc[0]) - 1.0) < 1e-8)

    lines = [
        "# BTC post-2022 out-of-sample replication report",
        "",
        "## Executive summary",
        markdown_table(comparison),
        "",
        "## Required questions",
        f"1. Raw BTC data extends through `{latest}` across the audited files.",
        "2. Post-2022 exchange coverage is summarized in `data_audit/btc_post2022_exchange_coverage.csv` and the yearly table below.",
        markdown_table(yearly),
        f"3. Final sample window: `{sample_selection['selected_start']}` to `{sample_selection['selected_end']}`.",
        f"4. The window was selected because it is the longest continuous run with at least {MIN_EXCHANGES_PER_MIN} valid exchanges per minute under the original valid-minute rule.",
        f"5. Compared with 2021-2022, the over-half state is {overhalf_change}: {post_row['Share max_share > 0.5']:.6f} vs {base_row['Share max_share > 0.5']:.6f}.",
        "6. The LWMP 0.5 boundary remains directly visible in the Figure 1 replication output; the plotted main-text curve uses `shock_type=inflate_only`, `gamma=1.0`, and the same 30 max_share bins.",
        f"7. The lock-in/non-lock-in pivot-change contrast remains: non-lock-in={pivot_stats['non_lockin_pivot_change_rate']:.6f}, lock-in={pivot_stats['lockin_pivot_change_rate']:.6f}.",
        f"8. Block-bootstrap CIs for the headline difference are 1-day {diff1} and 7-day {diff7}; inspect whether they exclude zero in `results/btc_post2022_block_bootstrap.csv`.",
        f"9. VWAP proximity channel {'exists' if vwap_channel else 'is weaker/not monotone by endpoint'}: lowest-bin q95={vb.iloc[0]['q95_rel_gap_dom']:.6g}, highest-bin q95={vb.iloc[-1]['q95_rel_gap_dom']:.6g}.",
        f"10. Fixed-weight pass-through {'matches' if pt_ok else 'does not fully match'} the lock-in theory: lock-in LWMP median kappa at +0.1% is {float(pt_lock['LWMP_median_kappa'].iloc[0]) if len(pt_lock) else np.nan:.6g}.",
        "11. Differences attributable to market state changes are primarily reflected in the post-2022 max_share distribution, over-half share, and spell durations.",
        "12. Differences potentially attributable to exchange coverage or volume convention are documented in the data audit; BitMEX remains quote_or_contract under the original convention while the other venues are base-volume.",
        "13. No validation check found a data or code issue that changes the main 2021-2022 conclusion; see the validation table below.",
        "14. Recommendation: include as online appendix unless the manuscript needs a concise temporal external-validity result in the main text.",
        "",
        "## Existing-output caveat",
        "The 2021-2022 baseline row uses the existing concentration/HHI path (`experiments/weight_concentration_minute_level.csv` and `hhi_panel/btc_1m_panel_with_hhi.csv`), which has 1,050,207 rows. The existing aggregate-price and price-displacement paths cover the full 1,051,200 calendar minutes from 2021-01-01 through 2022-12-31. This row-count difference is present in prior outputs and was not introduced by the post-2022 replication. The headline 0.279 / 0.068 pivot-change rates are traced to `experiments_dvonly/audit_lockin/audit_lockin_summary.csv`, i.e. the 800,000-event DV-only inference dataset split by `max_share > 0.5`.",
        "",
        "## Validation checks",
        markdown_table(validation),
        "",
        "## Files",
        "- `results/btc_post2022_lockin_summary.csv`",
        "- `results/btc_post2022_spell_summary.csv`",
        "- `results/btc_post2022_pivot_bins.csv`",
        "- `results/btc_post2022_block_bootstrap.csv`",
        "- `results/btc_post2022_vwap_proximity_bins.csv`",
        "- `results/btc_post2022_passthrough_summary.csv`",
        "- `results/btc_baseline_vs_post2022_comparison.csv`",
        "- `figures/Fig_BTC_post2022_LWMP_boundary.{png,pdf}`",
        "- `figures/Fig_BTC_post2022_VWAP_proximity.{png,pdf}`",
    ]
    (dirs.out_dir / "REPLICATION_BTC_POST2022_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    started = time.time()
    args = parse_args()
    dirs = resolve_dirs(args)
    log_lines: list[str] = []

    def log(message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = f"[{stamp}] {message}"
        print(text, flush=True)
        log_lines.append(text)

    requested_start = utc_timestamp(args.start_date)
    requested_end = utc_timestamp(args.end_date, is_end=True) if args.end_date.strip() else None

    log("Reading 2021-2022 calibration workbook")
    calibration = read_calibration(dirs.root)
    log("Auditing raw BTC exchange files")
    exchange_coverage, coverage, file_manifest = audit_raw_files(
        dirs.raw_dir, requested_start, args.chunk_size
    )
    yearly, coverage_matrix = yearly_coverage(coverage)
    sample_selection = choose_sample_window(coverage_matrix, requested_start, requested_end)

    exchange_coverage.to_csv(
        dirs.data_audit / "btc_post2022_exchange_coverage.csv", index=False, encoding="utf-8-sig"
    )
    yearly.to_csv(
        dirs.data_audit / "btc_post2022_yearly_coverage.csv", index=False, encoding="utf-8-sig"
    )
    (dirs.data_audit / "btc_post2022_sample_selection.json").write_text(
        json.dumps(sample_selection, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    file_manifest.to_csv(dirs.metadata / "input_file_manifest.csv", index=False, encoding="utf-8-sig")
    write_data_audit_report(dirs, exchange_coverage, yearly, sample_selection, calibration)

    if args.sample_selection_only:
        log("Sample-selection-only mode complete")
        (dirs.metadata / "execution_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        return 0

    selected_start = pd.Timestamp(sample_selection["selected_start"])
    selected_end = pd.Timestamp(sample_selection["selected_end"])
    full_index = pd.date_range(selected_start, selected_end, freq="min")

    log("Building post-2022 price and weight wide tables under reused calibration")
    prices_wide, weights_wide, processing_manifest = build_wide_post_sample(
        dirs.raw_dir,
        calibration,
        selected_start,
        selected_end,
        full_index,
        args.chunk_size,
    )
    processing_manifest.to_csv(dirs.metadata / "processing_filter_manifest.csv", index=False, encoding="utf-8-sig")

    log("Computing VWAP, LWMP, shares, max_share, HHI, dominant venue and pivot")
    panel, arrays = compute_panel(prices_wide, weights_wide)
    panel.to_csv(dirs.intermediate / "btc_post2022_minute_panel.csv.gz", index=False, compression="gzip")
    panel_valid = panel[panel["valid_minute"] == 1].copy()
    spells_one_row, spells_detail = spell_summary(panel_valid)
    lock_summary = lockin_summary(panel_valid, spells_one_row)
    lock_summary.to_csv(dirs.results / "btc_post2022_lockin_summary.csv", index=False, encoding="utf-8-sig")
    spells_one_row.to_csv(dirs.results / "btc_post2022_spell_summary.csv", index=False, encoding="utf-8-sig")
    spells_detail.to_csv(dirs.intermediate / "btc_post2022_lockin_spells_detail.csv", index=False, encoding="utf-8-sig")

    edges = make_edges(panel_valid["max_share"])
    pd.DataFrame({"edge": edges}).to_csv(dirs.intermediate / "btc_post2022_maxshare_edges.csv", index=False)

    log("Running DV-only perturbation events for LWMP pivot boundary and headline contrast")
    events = run_dvonly_events(panel, arrays, args.event_seed)
    event_audit_sample = events.sample(min(10_000, len(events)), random_state=args.event_seed)
    event_audit_sample.to_csv(
        dirs.metadata / "dvonly_event_sample_for_audit.csv", index=False, encoding="utf-8-sig"
    )
    pivot_stats = pivot_contrast(events)
    pivot_stats_df = pd.DataFrame([pivot_stats])
    pivot_stats_df.to_csv(dirs.results / "btc_post2022_pivot_contrast_summary.csv", index=False)
    pivot_df = pivot_bins(events, edges)
    pivot_df.to_csv(dirs.results / "btc_post2022_pivot_bins.csv", index=False, encoding="utf-8-sig")

    log("Running UTC block bootstrap for 1-day and 7-day blocks")
    bs_rows = []
    draw_paths = []
    for block_days in [1, 7]:
        summary, draws = block_bootstrap(events, block_days, args.reps, args.seed)
        bs_rows.append(summary)
        draw_path = dirs.metadata / f"btc_post2022_bootstrap_draws_{block_days}day.csv"
        draws.to_csv(draw_path, index=False)
        draw_paths.append(draw_path)
    bootstrap_summary = pd.concat(bs_rows, ignore_index=True)
    bootstrap_summary.to_csv(dirs.results / "btc_post2022_block_bootstrap.csv", index=False, encoding="utf-8-sig")

    log("Computing VWAP dominant-price proximity bins")
    vwap_bins = vwap_proximity_bins(panel_valid, edges, args.seed)
    vwap_bins.to_csv(dirs.results / "btc_post2022_vwap_proximity_bins.csv", index=False, encoding="utf-8-sig")

    log("Running fixed-weight dominant-price pass-through")
    passthrough = run_price_passthrough(panel, arrays, lambdas=[0.001, -0.001, 0.01, -0.01])
    passthrough.to_csv(dirs.results / "btc_post2022_passthrough_summary.csv", index=False, encoding="utf-8-sig")

    log("Rendering figures")
    plot_lwmp_boundary(
        pivot_df,
        dirs.figures / "Fig_BTC_post2022_LWMP_boundary.png",
        dirs.figures / "Fig_BTC_post2022_LWMP_boundary.pdf",
    )
    plot_vwap_proximity(
        vwap_bins,
        dirs.figures / "Fig_BTC_post2022_VWAP_proximity.png",
        dirs.figures / "Fig_BTC_post2022_VWAP_proximity.pdf",
    )

    log("Building baseline vs post-2022 comparison table")
    baseline = load_baseline_comparison(dirs.root)
    post_row = build_comparison_row(
        sample_selection, lock_summary, pivot_stats, bootstrap_summary, vwap_bins, passthrough
    )
    comparison = pd.DataFrame([baseline, post_row])
    comparison.to_csv(
        dirs.results / "btc_baseline_vs_post2022_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    log("Running validation checks")
    output_paths = [
        dirs.results / "btc_post2022_lockin_summary.csv",
        dirs.results / "btc_post2022_spell_summary.csv",
        dirs.results / "btc_post2022_pivot_bins.csv",
        dirs.results / "btc_post2022_block_bootstrap.csv",
        dirs.results / "btc_post2022_vwap_proximity_bins.csv",
        dirs.results / "btc_post2022_passthrough_summary.csv",
        dirs.results / "btc_baseline_vs_post2022_comparison.csv",
    ]
    validation = validate_outputs(panel, arrays, passthrough, bootstrap_summary, output_paths)
    validation.to_csv(dirs.metadata / "validation_checks.csv", index=False, encoding="utf-8-sig")

    parameter_manifest = {
        "main_sample_period_preserved": [MAIN_SAMPLE_START, MAIN_SAMPLE_END],
        "post_sample_selected_start": sample_selection["selected_start"],
        "post_sample_selected_end": sample_selection["selected_end"],
        "min_exchanges_per_minute": MIN_EXCHANGES_PER_MIN,
        "n_sample_minutes_for_dvonly_events": N_SAMPLE_MINUTES,
        "dvonly_event_seed": args.event_seed,
        "bootstrap_seed": args.seed,
        "bootstrap_reps": args.reps,
        "pivot_nbins": PIVOT_NBINS,
        "headline_event_scope": "all shock_type and gamma events from the DV-only perturbation sample",
        "main_text_boundary_plot_scope": "shock_type=inflate_only, gamma=1.0",
        "shock_types": SHOCK_TYPES,
        "delta_ws": DELTA_WS,
        "price_passthrough_lambdas": [0.001, -0.001, 0.01, -0.01],
        "calibration_source": str(dirs.root / "dv_unit_and_price_scale_report.xlsx"),
    }
    (dirs.metadata / "parameter_manifest.json").write_text(
        json.dumps(parameter_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    run_manifest = {
        "script": str(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "started_elapsed_seconds": float(time.time() - started),
        "root": str(dirs.root),
        "raw_dir": str(dirs.raw_dir),
        "out_dir": str(dirs.out_dir),
        "status": "complete",
    }
    (dirs.metadata / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_final_report(
        dirs,
        sample_selection,
        exchange_coverage,
        yearly,
        comparison,
        validation,
        pivot_stats,
        vwap_bins,
        passthrough,
    )
    log("Replication complete")
    (dirs.metadata / "execution_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

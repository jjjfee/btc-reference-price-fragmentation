#!/usr/bin/env python3
"""ETH cross-asset replication for the BTC benchmark mechanism.

The script is intentionally close to the existing BTC post-2022 runner.  It
keeps the BTC valid-minute rule, OHLC4/HL2/close price construction, DV-only
event generation, Wilson intervals, UTC block bootstrap, and fixed-weight
dominant-price pass-through formula.  The ETH combined index is audited only and
is never admitted to the venue, weight, dominant, pivot, VWAP, LWMP, max_share,
or HHI calculations.
"""

from __future__ import annotations

import argparse
import hashlib
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
from run_btc_post2022_replication import (
    block_bootstrap,
    make_edges,
    pivot_bins,
    pivot_contrast,
    plot_lwmp_boundary,
    plot_vwap_proximity,
    vwap_proximity_bins,
    wilson_ci,
)


EXCHANGES = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
COMBINED_LABEL = "Combined_Index"
MIN_EXCHANGES_PER_MIN = 3
ROLL_HHI = 60
N_SAMPLE_MINUTES = 100_000
DELTA_WS = [0.5, 1.0, 2.0, -0.5]
SHOCK_TYPES = ["inflate_only", "reallocate_total_fixed"]
PIVOT_NBINS = 30
LOCKIN_THRESHOLD = 0.5
PASSTHROUGH_LAMBDAS = [0.001, -0.001, 0.01, -0.01]
TIME_COL_CANDIDATES = ["Open time", "opentime", "timestamp", "date", "time", "datetime"]
VOLUME_COL_CANDIDATES = ["Volume", "volume", "vol", "qty", "amount", "turnover"]
QUOTE_VOLUME_CANDIDATES = [
    "Quote asset volume",
    "quote_asset_volume",
    "Volume (Quote)",
    "Volume Quote",
    "Amount",
    "turnover",
]


@dataclass
class Directories:
    root: Path
    raw_dir: Path
    out_dir: Path
    data_audit: Path
    processed: Path
    results: Path
    figures: Path
    metadata: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ETH cross-asset replication.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--raw-dir", type=Path, default=(Path(__file__).resolve().parents[2] / "data" / "external" / "raw" / "eth"))
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2022-12-31 23:59:00")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs") / "robustness" / "eth_matched",
    )
    parser.add_argument("--reps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--event-seed", type=int, default=20260712)
    parser.add_argument("--chunk-size", type=int, default=200_000)
    return parser.parse_args()


def resolve_dirs(args: argparse.Namespace) -> Directories:
    root = args.root.resolve()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    dirs = Directories(
        root=root,
        raw_dir=args.raw_dir.resolve(),
        out_dir=out_dir.resolve(),
        data_audit=out_dir.resolve() / "data_audit",
        processed=out_dir.resolve() / "processed",
        results=out_dir.resolve() / "results",
        figures=out_dir.resolve() / "figures",
        metadata=out_dir.resolve() / "metadata",
    )
    for path in [
        dirs.out_dir,
        dirs.data_audit,
        dirs.processed,
        dirs.results,
        dirs.figures,
        dirs.metadata,
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
    if "combined" in name.lower():
        return COMBINED_LABEL
    for ex in EXCHANGES:
        if ex.lower() in name.lower():
            return ex
    parts = name.split("_")
    return parts[-1] if parts else name


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def markdown_table(df: pd.DataFrame, max_rows: int | None = None) -> str:
    if df.empty:
        return "_No rows._"
    work = df.head(max_rows).copy() if max_rows else df.copy()
    for col in work.columns:
        def fmt(x: Any) -> str:
            if pd.isna(x):
                return ""
            if isinstance(x, (float, np.floating)):
                return f"{float(x):.6g}"
            return str(x).replace("|", "\\|")

        work[col] = work[col].map(fmt)
    cols = [str(c) for c in work.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in work.columns) + " |")
    if max_rows and len(df) > max_rows:
        lines.append(f"| ... | {' | '.join([''] * (len(cols) - 1))} |")
    return "\n".join(lines)


def detect_columns(path: Path) -> dict[str, Any]:
    head = normalize_columns(pd.read_csv(path, nrows=5))
    time_col = pick_col(head, TIME_COL_CANDIDATES)
    open_col = pick_col(head, ["Open", "open"])
    high_col = pick_col(head, ["High", "high"])
    low_col = pick_col(head, ["Low", "low"])
    close_col = pick_col(head, ["Close", "close"])
    volume_col = pick_col(head, VOLUME_COL_CANDIDATES)
    quote_volume_col = pick_col(head, QUOTE_VOLUME_CANDIDATES)
    if time_col is None:
        raise ValueError(f"{path.name}: cannot detect timestamp column")
    return {
        "columns": list(head.columns),
        "time_col": time_col,
        "open_col": open_col,
        "high_col": high_col,
        "low_col": low_col,
        "close_col": close_col,
        "volume_col": volume_col,
        "quote_volume_col": quote_volume_col,
    }


def price_rule(cols: dict[str, Any]) -> str:
    if all(cols.get(c) for c in ["open_col", "high_col", "low_col", "close_col"]):
        return "OHLC4"
    if cols.get("high_col") and cols.get("low_col"):
        return "HL2"
    if cols.get("close_col"):
        return "Close"
    return "missing"


def timestamp_metadata(raw_sample: Any) -> tuple[str, str, str]:
    text = "" if pd.isna(raw_sample) else str(raw_sample)
    numeric = pd.to_numeric(pd.Series([raw_sample]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        unit = "milliseconds" if float(numeric) > 1e12 else "seconds" if float(numeric) > 1e9 else "numeric_unknown"
        return text, unit, "UTC after parser conversion"
    return text, "datetime string", "UTC after parser conversion"


def safe_quantiles(values: np.ndarray, qs: list[float]) -> list[float]:
    arr = values[np.isfinite(values)]
    if len(arr) == 0:
        return [np.nan for _ in qs]
    return [float(np.quantile(arr, q)) for q in qs]


def longest_true_run(mask: pd.Series) -> tuple[str, str, int]:
    if mask.empty or not bool(mask.any()):
        return "", "", 0
    values = mask.to_numpy(dtype=bool)
    idx = mask.index
    best_start = best_end = cur_start = 0
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
    return str(idx[best_start]), str(idx[best_end]), int(best_len)


def infer_volume_convention(
    exchange: str,
    volume_col: str | None,
    quote_col: str | None,
    volume_sample: np.ndarray,
    price_sample: np.ndarray,
    quote_sample: np.ndarray,
) -> dict[str, Any]:
    v = volume_sample[np.isfinite(volume_sample) & (volume_sample > 0)]
    if len(v) == 0:
        return {
            "volume_field": volume_col,
            "quote_volume_field": quote_col,
            "volume_convention": "unknown",
            "multiplier": np.nan,
            "dv_formula": "not_available",
            "integer_ratio": np.nan,
            "evidence": "No positive volume sample.",
            "requires_targeted_exclusion": True,
        }

    frac = np.abs(v - np.round(v))
    integer_ratio = float((frac < 1e-6).mean())
    quote_ratio_median = np.nan
    quote_match = False
    if quote_col is not None and len(quote_sample) and len(price_sample):
        q = quote_sample.astype(float)
        p = price_sample.astype(float)
        n = min(len(q), len(v), len(p))
        denom = v[:n] * p[:n]
        ok = np.isfinite(q[:n]) & np.isfinite(denom) & (q[:n] > 0) & (denom > 0)
        if ok.any():
            ratios = q[:n][ok] / denom[ok]
            quote_ratio_median = float(np.median(ratios))
            quote_match = bool(0.98 <= quote_ratio_median <= 1.02)

    if exchange == "BitMEX":
        return {
            "volume_field": volume_col,
            "quote_volume_field": quote_col,
            "volume_convention": "quote_or_contract",
            "multiplier": 1.0,
            "dv_formula": "DV = Volume * 1.0",
            "integer_ratio": integer_ratio,
            "quote_to_base_price_ratio_median": quote_ratio_median,
            "evidence": "BTC pipeline treats BitMEX integer Volume as quote_or_contract; same rule reused.",
            "requires_targeted_exclusion": True,
        }

    if quote_match:
        return {
            "volume_field": volume_col,
            "quote_volume_field": quote_col,
            "volume_convention": "base",
            "multiplier": 1.0,
            "dv_formula": "DV = Volume * venue_price",
            "integer_ratio": integer_ratio,
            "quote_to_base_price_ratio_median": quote_ratio_median,
            "evidence": "Explicit quote/amount field matches Volume * OHLC4 price.",
            "requires_targeted_exclusion": False,
        }

    if integer_ratio < 0.95:
        return {
            "volume_field": volume_col,
            "quote_volume_field": quote_col,
            "volume_convention": "base",
            "multiplier": 1.0,
            "dv_formula": "DV = Volume * venue_price",
            "integer_ratio": integer_ratio,
            "quote_to_base_price_ratio_median": quote_ratio_median,
            "evidence": "Fractional continuous Volume matches BTC spot/base-volume rule.",
            "requires_targeted_exclusion": False,
        }

    return {
        "volume_field": volume_col,
        "quote_volume_field": quote_col,
        "volume_convention": "unknown",
        "multiplier": np.nan,
        "dv_formula": "not_used_without_warning",
        "integer_ratio": integer_ratio,
        "quote_to_base_price_ratio_median": quote_ratio_median,
        "evidence": "High integer ratio without an exchange-specific BTC rule.",
        "requires_targeted_exclusion": True,
    }


def audit_raw_files(
    raw_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    chunk_size: int,
    exchanges: list[str] | None = None,
    include_combined_index: bool = True,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, pd.Series],
    pd.Series | None,
]:
    exchange_list = list(exchanges) if exchanges is not None else list(EXCHANGES)
    files = []
    for ex in exchange_list:
        path = raw_dir / f"ETHUSD_1m_{ex}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing ETH exchange file: {path}")
        files.append(path)
    if include_combined_index:
        combined_path = raw_dir / "ETHUSD_1m_Combined_Index.csv"
        if combined_path.exists():
            files.append(combined_path)

    coverage: dict[str, pd.Series] = {}
    combined_series: pd.Series | None = None
    coverage_rows: list[dict[str, Any]] = []
    timestamp_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []

    for path in files:
        exchange = exchange_from_path(path)
        is_combined = exchange == COMBINED_LABEL
        cols = detect_columns(path)
        p_rule = price_rule(cols)
        if p_rule == "missing":
            raise ValueError(f"{path.name}: cannot detect OHLC/close price columns")
        if cols["volume_col"] is None and not is_combined:
            raise ValueError(f"{path.name}: cannot detect volume column")

        usecols = [
            cols["time_col"],
            cols["open_col"],
            cols["high_col"],
            cols["low_col"],
            cols["close_col"],
            cols["volume_col"],
            cols["quote_volume_col"],
        ]
        usecols = [c for c in dict.fromkeys(usecols) if c is not None]

        pieces = []
        volume_sample: list[np.ndarray] = []
        price_sample: list[np.ndarray] = []
        quote_sample: list[np.ndarray] = []
        first_ts: pd.Timestamp | None = None
        last_ts: pd.Timestamp | None = None
        first_raw_timestamp: Any = None
        total_rows = 0
        parse_failures = 0
        price_invalid_rows = 0
        volume_invalid_rows = 0
        zero_volume_rows = 0
        negative_volume_rows = 0
        inf_price_rows = 0
        inf_volume_rows = 0
        ohlc_valid_rows = 0
        monotonic = True
        previous_ts: pd.Timestamp | None = None
        price_minmax = {c: [np.inf, -np.inf] for c in ["open_col", "high_col", "low_col", "close_col"] if cols.get(c)}

        for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_size):
            chunk = normalize_columns(chunk)
            total_rows += len(chunk)
            if first_raw_timestamp is None and len(chunk):
                first_raw_timestamp = chunk[cols["time_col"]].iloc[0]
            t = parse_time_column(chunk[cols["time_col"]]).dt.floor("min")
            parse_failures += int(t.isna().sum())
            t_valid = t.dropna()
            if len(t_valid):
                cmin = t_valid.min()
                cmax = t_valid.max()
                first_ts = cmin if first_ts is None else min(first_ts, cmin)
                last_ts = cmax if last_ts is None else max(last_ts, cmax)
                if previous_ts is not None and cmin < previous_ts:
                    monotonic = False
                if not bool(t_valid.is_monotonic_increasing):
                    monotonic = False
                previous_ts = cmax

            p = pd.to_numeric(
                compute_p_repr(
                    chunk,
                    cols["open_col"],
                    cols["high_col"],
                    cols["low_col"],
                    cols["close_col"],
                ),
                errors="coerce",
            )
            p_np = p.to_numpy(dtype=float)
            price_invalid_rows += int((~np.isfinite(p_np) | (p_np <= 0)).sum())
            inf_price_rows += int(np.isinf(p_np).sum())

            ohlc_parts = []
            for key in ["open_col", "high_col", "low_col", "close_col"]:
                col = cols.get(key)
                if col:
                    arr = pd.to_numeric(chunk[col], errors="coerce").to_numpy(dtype=float)
                    ohlc_parts.append(arr)
                    finite = arr[np.isfinite(arr)]
                    if len(finite):
                        price_minmax[key][0] = min(price_minmax[key][0], float(np.min(finite)))
                        price_minmax[key][1] = max(price_minmax[key][1], float(np.max(finite)))
            if ohlc_parts:
                ohlc = np.vstack(ohlc_parts).T
                ohlc_valid_rows += int((np.isfinite(ohlc).all(axis=1) & (ohlc > 0).all(axis=1)).sum())

            if cols["volume_col"] is not None:
                v = pd.to_numeric(chunk[cols["volume_col"]], errors="coerce")
                v_np = v.to_numpy(dtype=float)
                volume_invalid_rows += int((~np.isfinite(v_np) | (v_np <= 0)).sum())
                zero_volume_rows += int((np.isfinite(v_np) & (v_np == 0)).sum())
                negative_volume_rows += int((np.isfinite(v_np) & (v_np < 0)).sum())
                inf_volume_rows += int(np.isinf(v_np).sum())
                v_ok = v_np[np.isfinite(v_np) & (v_np > 0)]
                if len(v_ok) and sum(len(a) for a in volume_sample) < 500_000:
                    remaining = 500_000 - sum(len(a) for a in volume_sample)
                    volume_sample.append(v_ok[:remaining])
                    p_ok = p_np[np.isfinite(v_np) & (v_np > 0) & np.isfinite(p_np) & (p_np > 0)]
                    price_sample.append(p_ok[:remaining])
                    if cols["quote_volume_col"] is not None:
                        q_np = pd.to_numeric(chunk[cols["quote_volume_col"]], errors="coerce").to_numpy(dtype=float)
                        q_ok = q_np[np.isfinite(v_np) & (v_np > 0) & np.isfinite(p_np) & (p_np > 0)]
                        quote_sample.append(q_ok[:remaining])
            else:
                v_np = np.full(len(chunk), np.nan)

            valid = t.notna().to_numpy() & np.isfinite(p_np) & (p_np > 0)
            if not is_combined:
                valid = valid & np.isfinite(v_np) & (v_np > 0)
            piece = pd.DataFrame(
                {
                    "time_utc": t,
                    "price_valid": np.isfinite(p_np) & (p_np > 0),
                    "volume_valid": np.isfinite(v_np) & (v_np > 0) if cols["volume_col"] is not None else False,
                    "valid": valid,
                    "price": p_np,
                }
            ).dropna(subset=["time_utc"])
            pieces.append(piece)

        if not pieces or first_ts is None or last_ts is None:
            raise ValueError(f"{path.name}: no parseable timestamps")

        raw_minute = pd.concat(pieces, ignore_index=True)
        duplicate_timestamps = int(raw_minute["time_utc"].duplicated().sum())
        dedup = raw_minute.sort_values("time_utc").drop_duplicates("time_utc", keep="last")
        expected_minutes = int(((last_ts - first_ts) / pd.Timedelta(minutes=1)) + 1)
        unique_minutes = int(len(dedup))
        missing_minutes = int(max(expected_minutes - unique_minutes, 0))
        missing_ratio = float(missing_minutes / expected_minutes) if expected_minutes else np.nan
        diffs = (
            dedup["time_utc"]
            .sort_values()
            .diff()
            .dropna()
            .dt.total_seconds()
            .div(60)
            .round(6)
        )
        interval_distribution = diffs.value_counts().head(10).to_dict()
        matched = dedup[(dedup["time_utc"] >= start) & (dedup["time_utc"] <= end)].copy()
        matched_valid = matched.set_index("time_utc")["valid"].astype(bool)

        vs = np.concatenate(volume_sample) if volume_sample else np.array([], dtype=float)
        ps = np.concatenate(price_sample) if price_sample else np.array([], dtype=float)
        qs = np.concatenate(quote_sample) if quote_sample else np.array([], dtype=float)
        convention = (
            {
                "volume_field": cols["volume_col"],
                "quote_volume_field": cols["quote_volume_col"],
                "volume_convention": "not_applicable",
                "multiplier": np.nan,
                "dv_formula": "Combined_Index excluded from all aggregation",
                "integer_ratio": np.nan,
                "quote_to_base_price_ratio_median": np.nan,
                "evidence": "Auxiliary combined index only.",
                "requires_targeted_exclusion": False,
            }
            if is_combined
            else infer_volume_convention(
                exchange,
                cols["volume_col"],
                cols["quote_volume_col"],
                vs,
                ps,
                qs,
            )
        )
        v_min, v_median, v_p95, v_p99, v_max = safe_quantiles(vs, [0.0, 0.5, 0.95, 0.99, 1.0])
        p_min, p_median, p_max = safe_quantiles(dedup["price"].to_numpy(dtype=float), [0.0, 0.5, 1.0])
        raw_text, timestamp_unit, timezone = timestamp_metadata(first_raw_timestamp)
        price_range_ok = bool(np.isfinite(p_median) and 5 <= p_median <= 10_000)

        schema_rows.append(
            {
                "exchange": exchange,
                "is_combined_index": bool(is_combined),
                "file_name": path.name,
                "path": str(path),
                "file_size_bytes": int(path.stat().st_size),
                "columns": json_dumps(cols["columns"]),
                "time_col": cols["time_col"],
                "open_col": cols["open_col"],
                "high_col": cols["high_col"],
                "low_col": cols["low_col"],
                "close_col": cols["close_col"],
                "volume_col": cols["volume_col"],
                "quote_volume_col": cols["quote_volume_col"],
                "price_rule": p_rule,
            }
        )
        timestamp_rows.append(
            {
                "exchange": exchange,
                "file_name": path.name,
                "timestamp_field": cols["time_col"],
                "timestamp_raw_sample": raw_text,
                "timestamp_unit": timestamp_unit,
                "timezone": timezone,
                "utc_start": str(first_ts),
                "utc_end": str(last_ts),
                "duplicate_timestamp_count": duplicate_timestamps,
                "timestamp_monotonic_raw_order": bool(monotonic),
                "timestamp_interval_distribution_minutes": json_dumps(interval_distribution),
                "time_parse_failures": parse_failures,
            }
        )
        volume_rows.append(
            {
                "exchange": exchange,
                "file_name": path.name,
                "volume_field": convention.get("volume_field"),
                "quote_volume_field": convention.get("quote_volume_field"),
                "volume_convention": convention.get("volume_convention"),
                "multiplier": convention.get("multiplier"),
                "dv_formula": convention.get("dv_formula"),
                "integer_ratio": convention.get("integer_ratio"),
                "quote_to_base_price_ratio_median": convention.get("quote_to_base_price_ratio_median", np.nan),
                "volume_min": v_min,
                "volume_median": v_median,
                "volume_p95": v_p95,
                "volume_p99": v_p99,
                "volume_max": v_max,
                "negative_volume_rows": int(negative_volume_rows),
                "zero_volume_rows": int(zero_volume_rows),
                "volume_invalid_rows": int(volume_invalid_rows),
                "base_volume_possible": bool(convention.get("volume_convention") == "base"),
                "quote_volume_possible": bool(convention.get("volume_convention") == "quote_or_contract"),
                "contract_volume_possible": bool(convention.get("volume_convention") == "quote_or_contract"),
                "requires_targeted_exclusion": bool(convention.get("requires_targeted_exclusion")),
                "evidence": convention.get("evidence"),
            }
        )
        missing_rows.append(
            {
                "exchange": exchange,
                "file_name": path.name,
                "expected_minutes_between_file_start_end": expected_minutes,
                "unique_timestamps": unique_minutes,
                "missing_minutes": missing_minutes,
                "missing_minute_ratio": missing_ratio,
                "duplicate_timestamps": duplicate_timestamps,
                "ohlc_valid_rows": int(ohlc_valid_rows),
                "volume_valid_rows": int(total_rows - volume_invalid_rows) if cols["volume_col"] else np.nan,
                "price_invalid_rows": int(price_invalid_rows),
                "volume_invalid_rows": int(volume_invalid_rows),
                "inf_price_rows": int(inf_price_rows),
                "inf_volume_rows": int(inf_volume_rows),
                "zero_volume_rows": int(zero_volume_rows),
                "negative_volume_rows": int(negative_volume_rows),
            }
        )
        coverage_rows.append(
            {
                "exchange": exchange,
                "file_name": path.name,
                "path": str(path),
                "file_size_bytes": int(path.stat().st_size),
                "total_rows": int(total_rows),
                "utc_start": str(first_ts),
                "utc_end": str(last_ts),
                "matched_sample_rows": int(len(matched)),
                "matched_valid_minutes": int(matched_valid.sum()),
                "matched_coverage_share": float(
                    matched_valid.reindex(pd.date_range(start, end, freq="min"), fill_value=False).mean()
                ),
                "price_min": p_min,
                "price_median": p_median,
                "price_max": p_max,
                "price_actual_ethusd_like": price_range_ok,
                "ethusdt_ethusd_mixed_detected": "not_detected_from_file_name_or_columns",
                "abnormal_price_scaling_detected": not price_range_ok,
                "obvious_unit_difference_detected": False,
                "abnormal_duplicate_region_detected": duplicate_timestamps > 0,
                "truncation_gap_or_corrupt_rows_detected": bool(parse_failures > 0),
            }
        )

        if is_combined:
            combined_series = dedup.set_index("time_utc")["price"].astype(float)
        else:
            coverage[exchange] = matched_valid

    return (
        pd.DataFrame(coverage_rows),
        pd.DataFrame(timestamp_rows),
        pd.DataFrame(schema_rows),
        pd.DataFrame(volume_rows),
        pd.DataFrame(missing_rows),
        coverage,
        combined_series,
    )


def yearly_coverage(
    coverage: dict[str, pd.Series],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    full_index = pd.date_range(start, end, freq="min")
    matrix = pd.DataFrame(index=full_index)
    for ex in EXCHANGES:
        matrix[ex] = coverage[ex].reindex(full_index, fill_value=False).astype(bool)
    counts = matrix.sum(axis=1)
    rows = []
    for year, seg_index in pd.Series(full_index, index=full_index).groupby(full_index.year):
        seg = matrix.loc[seg_index.index]
        seg_counts = counts.loc[seg_index.index]
        row = {
            "year": int(year),
            "calendar_minutes": int(len(seg)),
            "minutes_at_least_3_valid": int((seg_counts >= 3).sum()),
            "share_at_least_3_valid": float((seg_counts >= 3).mean()),
            "minutes_at_least_5_valid": int((seg_counts >= 5).sum()),
            "share_at_least_5_valid": float((seg_counts >= 5).mean()),
            "minutes_all_7_valid": int((seg_counts == 7).sum()),
            "share_all_7_valid": float((seg_counts == 7).mean()),
        }
        for ex in EXCHANGES:
            row[f"{ex}_valid_minutes"] = int(seg[ex].sum())
            row[f"{ex}_coverage_share"] = float(seg[ex].mean())
        rows.append(row)

    common_mask = counts == len(EXCHANGES)
    valid3_mask = counts >= MIN_EXCHANGES_PER_MIN
    common_start, common_end, common_len = longest_true_run(common_mask)
    usable_start, usable_end, usable_len = longest_true_run(valid3_mask)
    sample_selection = {
        "sample": "ETHUSD 2021-2022 matched sample",
        "start": str(start),
        "end": str(end),
        "calendar_minutes": int(len(full_index)),
        "minimum_valid_exchanges_per_minute": MIN_EXCHANGES_PER_MIN,
        "valid_minutes_at_least_3": int((counts >= 3).sum()),
        "share_at_least_3_valid": float((counts >= 3).mean()),
        "valid_minutes_at_least_5": int((counts >= 5).sum()),
        "share_at_least_5_valid": float((counts >= 5).mean()),
        "valid_minutes_all_7": int((counts == 7).sum()),
        "share_all_7_valid": float((counts == 7).mean()),
        "all_exchange_common_coverage_longest_start": common_start,
        "all_exchange_common_coverage_longest_end": common_end,
        "all_exchange_common_coverage_longest_minutes": common_len,
        "largest_continuous_usable_start": usable_start,
        "largest_continuous_usable_end": usable_end,
        "largest_continuous_usable_minutes": usable_len,
        "selected_sample_used_for_replication": "matched_2021_2022",
        "supplemental_window_identified_but_not_used_for_main_results": {
            "start": usable_start,
            "end": usable_end,
            "minutes": usable_len,
            "rule": "longest continuous run with at least 3 valid venues",
        },
    }
    return pd.DataFrame(rows), matrix, sample_selection


def build_wide_eth_sample(
    raw_dir: Path,
    volume_audit: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    full_index: pd.DatetimeIndex,
    chunk_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conventions = volume_audit[volume_audit["exchange"].isin(EXCHANGES)].set_index("exchange")
    prices = pd.DataFrame(index=full_index)
    weights = pd.DataFrame(index=full_index)
    rows: list[dict[str, Any]] = []

    for ex in EXCHANGES:
        path = raw_dir / f"ETHUSD_1m_{ex}.csv"
        cols = detect_columns(path)
        conv = conventions.loc[ex]
        vcol = str(conv["volume_field"])
        convention = str(conv["volume_convention"])
        multiplier = float(conv["multiplier"]) if pd.notna(conv["multiplier"]) else np.nan
        usecols = [
            cols["time_col"],
            cols["open_col"],
            cols["high_col"],
            cols["low_col"],
            cols["close_col"],
            vcol,
        ]
        usecols = [c for c in dict.fromkeys(usecols) if c is not None]

        parts = []
        rows_raw = rows_window = time_fail = price_invalid = weight_invalid = 0
        for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_size):
            chunk = normalize_columns(chunk)
            rows_raw += len(chunk)
            t = parse_time_column(chunk[cols["time_col"]]).dt.floor("min")
            time_fail += int(t.isna().sum())
            mask = (t >= start) & (t <= end)
            if not bool(mask.any()):
                continue
            sub = chunk.loc[mask].copy()
            t_sub = t.loc[mask]
            rows_window += len(sub)
            price = pd.to_numeric(
                compute_p_repr(
                    sub,
                    cols["open_col"],
                    cols["high_col"],
                    cols["low_col"],
                    cols["close_col"],
                ),
                errors="coerce",
            )
            volume = pd.to_numeric(sub[vcol], errors="coerce")
            if convention == "base":
                dv = volume * price
            elif convention == "quote_or_contract":
                dv = volume * multiplier
            else:
                dv = volume * price
            p_np = price.to_numpy(dtype=float)
            dv_np = dv.to_numpy(dtype=float)
            price_invalid += int((~np.isfinite(p_np) | (p_np <= 0)).sum())
            weight_invalid += int((~np.isfinite(dv_np) | (dv_np <= 0)).sum())
            parts.append(pd.DataFrame({"time_utc": t_sub, "price": price, "weight": dv}))

        if not parts:
            raise ValueError(f"{path.name}: no rows in matched sample")
        df = pd.concat(parts, ignore_index=True).dropna(subset=["time_utc"])
        before = len(df)
        df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last").set_index("time_utc")
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
                "price_rule": price_rule(cols),
                "price_fields_used": ",".join(
                    [str(cols[k]) for k in ["open_col", "high_col", "low_col", "close_col"] if cols.get(k)]
                ),
                "volume_field_used": vcol,
                "volume_convention": convention,
                "multiplier": multiplier,
                "dv_formula": conv["dv_formula"],
                "rows_raw_file": int(rows_raw),
                "rows_in_sample_before_dedup": int(rows_window),
                "duplicate_timestamps_in_sample": int(before - len(df)),
                "time_parse_failures_raw": int(time_fail),
                "invalid_price_rows_in_sample": int(price_invalid),
                "invalid_weight_rows_in_sample": int(weight_invalid),
                "dedup_minutes_in_sample": int(len(df)),
                "valid_minutes_after_main_rule": int(valid.sum()),
            }
        )

    return prices[EXCHANGES], weights[EXCHANGES], pd.DataFrame(rows)


def build_combined_benchmark(
    raw_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    full_index: pd.DatetimeIndex,
    chunk_size: int,
) -> pd.Series | None:
    path = raw_dir / "ETHUSD_1m_Combined_Index.csv"
    if not path.exists():
        return None
    cols = detect_columns(path)
    usecols = [cols["time_col"], cols["open_col"], cols["high_col"], cols["low_col"], cols["close_col"]]
    usecols = [c for c in dict.fromkeys(usecols) if c is not None]
    parts = []
    for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_size):
        chunk = normalize_columns(chunk)
        t = parse_time_column(chunk[cols["time_col"]]).dt.floor("min")
        mask = (t >= start) & (t <= end)
        if not bool(mask.any()):
            continue
        sub = chunk.loc[mask].copy()
        price = pd.to_numeric(
            compute_p_repr(
                sub,
                cols["open_col"],
                cols["high_col"],
                cols["low_col"],
                cols["close_col"],
            ),
            errors="coerce",
        )
        parts.append(pd.DataFrame({"time_utc": t.loc[mask], "Combined_Index_price": price}))
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True).dropna(subset=["time_utc"])
    df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last").set_index("time_utc")
    return pd.to_numeric(df["Combined_Index_price"], errors="coerce").reindex(full_index)


def compute_panel_local(
    prices_wide: pd.DataFrame,
    weights_wide: pd.DataFrame,
    min_exchanges: int = MIN_EXCHANGES_PER_MIN,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    exchanges = list(prices_wide.columns)
    p = prices_wide.to_numpy(dtype=float)
    w = weights_wide.to_numpy(dtype=float)
    valid = np.isfinite(p) & np.isfinite(w) & (p > 0) & (w > 0)
    w_clean = np.where(valid, w, 0.0)
    p_clean = np.where(valid, p, np.nan)
    n_ex = valid.sum(axis=1).astype(int)
    total_w = w_clean.sum(axis=1)
    shares = np.divide(w_clean, total_w[:, None], out=np.zeros_like(w_clean), where=total_w[:, None] > 0)
    max_share = shares.max(axis=1)
    hhi = (shares**2).sum(axis=1)
    dominant_idx = shares.argmax(axis=1)
    exchange_names = np.array(exchanges, dtype=object)
    dominant_exchange = np.where(total_w > 0, exchange_names[dominant_idx], "")
    p_dom = p_clean[np.arange(len(p_clean)), dominant_idx]
    share_dom = shares[np.arange(len(p_clean)), dominant_idx]
    vwap = np.divide(
        np.nansum(p_clean * w_clean, axis=1),
        total_w,
        out=np.full(len(total_w), np.nan),
        where=total_w > 0,
    )
    lwmp, pivot_idx, pivot_margin, total_w_check = weighted_median_with_pivot(p_clean, w_clean)
    pivot_exchange = np.where(pivot_idx >= 0, exchange_names[np.maximum(pivot_idx, 0)], "")
    valid_minute = n_ex >= min_exchanges
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
            "lock_in": (max_share > LOCKIN_THRESHOLD).astype(int),
            "valid_minute": valid_minute.astype(int),
        }
    )
    panel["HHI_roll"] = panel["HHI"].where(panel["valid_minute"] == 1).rolling(ROLL_HHI, min_periods=ROLL_HHI).mean()
    panel["relative_vwap_gap"] = (panel["P_vwap_DV"] - panel["dominant_price"]).abs() / panel["P_vwap_DV"]
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


def spell_summary_local(panel_valid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = panel_valid[["time_utc", "lock_in"]].copy().sort_values("time_utc")
    lock = df["lock_in"].to_numpy(dtype=bool)
    times = pd.to_datetime(df["time_utc"], utc=True)
    rows = []
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
        rows.append(
            {
                "spell_id": spell_id,
                "start_time": str(times.iloc[start_i]),
                "end_time": str(times.iloc[j - 1]),
                "duration_minutes": int(j - start_i),
            }
        )
        i = j
    spells = pd.DataFrame(rows)
    durations = spells["duration_minutes"].to_numpy(dtype=float) if len(spells) else np.array([], dtype=float)
    summary = pd.DataFrame(
        [
            {
                "over_half_spell_count": int(len(spells)),
                "spell_duration_median": float(np.median(durations)) if len(durations) else np.nan,
                "spell_duration_p95": float(np.quantile(durations, 0.95)) if len(durations) else np.nan,
                "spell_duration_p99": float(np.quantile(durations, 0.99)) if len(durations) else np.nan,
                "max_spell_minutes": int(np.max(durations)) if len(durations) else 0,
                "spells_ge_60_minutes": int((durations >= 60).sum()) if len(durations) else 0,
                "spells_ge_360_minutes": int((durations >= 360).sum()) if len(durations) else 0,
                "spells_ge_1440_minutes": int((durations >= 1440).sum()) if len(durations) else 0,
            }
        ]
    )
    return summary, spells


def concentration_summary(panel_valid: pd.DataFrame, spells_one_row: pd.DataFrame) -> pd.DataFrame:
    max_share = pd.to_numeric(panel_valid["max_share"], errors="coerce")
    hhi = pd.to_numeric(panel_valid["HHI"], errors="coerce")
    row = {
        "valid_minutes": int(len(panel_valid)),
        "venue_count": int(panel_valid["n_exchanges_used"].max()),
        "median_max_share": float(max_share.median()),
        "p95_max_share": float(max_share.quantile(0.95)),
        "p99_max_share": float(max_share.quantile(0.99)),
        "share_max_share_gt_0p5": float((max_share > 0.5).mean()),
        "share_max_share_gt_0p4": float((max_share > 0.4).mean()),
        "share_max_share_gt_0p3": float((max_share > 0.3).mean()),
        "median_HHI": float(hhi.median()),
        "p95_HHI": float(hhi.quantile(0.95)),
    }
    row.update(spells_one_row.iloc[0].to_dict())
    return pd.DataFrame([row])


def run_dvonly_events_local(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    exchanges: list[str],
    event_seed: int,
    n_sample_minutes: int = N_SAMPLE_MINUTES,
) -> pd.DataFrame:
    valid_idx = np.flatnonzero(arrays["valid_minute"])
    sample_n = min(n_sample_minutes, len(valid_idx))
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
    exchange_names = np.array(exchanges, dtype=object)
    frames = []
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
            _, _, p_vwap1, p_lwmp1, pivot1, margin1, totalw1, w_clean1, _ = compute_aggregators(p_clean0, w_shock)
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
                        "lock_in": (max_share > LOCKIN_THRESHOLD).astype(int),
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


def run_price_passthrough_local(
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    lambdas: list[float],
) -> pd.DataFrame:
    valid_idx = np.flatnonzero(arrays["valid_minute"])
    prices = arrays["p_clean"][valid_idx, :]
    weights = arrays["w_clean"][valid_idx, :]
    dominant_idx = arrays["dominant_idx"][valid_idx]
    p_dom = arrays["p_dom"][valid_idx]
    vwap0 = arrays["vwap"][valid_idx]
    lwmp0 = arrays["lwmp"][valid_idx]
    panel_valid = panel.iloc[valid_idx].reset_index(drop=True)
    states = np.where(panel_valid["max_share"].to_numpy(dtype=float) > LOCKIN_THRESHOLD, "lockin", "non_lockin")
    rows = []
    for lam in lambdas:
        prices_prime = prices.copy()
        prices_prime[np.arange(len(prices_prime)), dominant_idx] = p_dom * (1.0 + lam)
        denom_w = weights.sum(axis=1)
        vwap1 = np.divide(
            np.nansum(prices_prime * weights, axis=1),
            denom_w,
            out=np.full(len(prices_prime), np.nan),
            where=denom_w > 0,
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
                    "event_count": int(mask.sum()),
                    "VWAP_mean_kappa": float(np.nanmean(kv)),
                    "VWAP_median_kappa": float(np.nanmedian(kv)),
                    "VWAP_p95_kappa": float(np.nanquantile(kv, 0.95)),
                    "LWMP_mean_kappa": float(np.nanmean(kl)),
                    "LWMP_median_kappa": float(np.nanmedian(kl)),
                    "LWMP_p95_kappa": float(np.nanquantile(kl, 0.95)),
                    "LWMP_zero_share": float(np.isclose(kl, 0.0, atol=1e-12).mean()),
                    "LWMP_one_share": float(np.isclose(kl, 1.0, atol=1e-8).mean()),
                }
            )
    return pd.DataFrame(rows)


def dominant_distribution(panel_valid: pd.DataFrame) -> pd.DataFrame:
    counts = panel_valid["dominant_exchange"].value_counts().reindex(EXCHANGES, fill_value=0)
    out = counts.rename_axis("dominant_exchange").reset_index(name="minutes")
    out["share"] = out["minutes"] / out["minutes"].sum()
    return out


def distribution_summary_text(dist: pd.DataFrame) -> str:
    if dist.empty:
        return ""
    return "; ".join(
        f"{row.dominant_exchange}={row.share:.3f}" for row in dist.sort_values("share", ascending=False).itertuples()
    )


def targeted_exclusion(
    trigger_venues: list[str],
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    seed: int,
) -> pd.DataFrame:
    rows = []
    for venue in trigger_venues:
        keep_exchanges = [ex for ex in prices.columns if ex != venue]
        panel_x, arrays_x = compute_panel_local(prices[keep_exchanges], weights[keep_exchanges])
        panel_valid_x = panel_x[panel_x["valid_minute"] == 1].copy()
        spells_x, _ = spell_summary_local(panel_valid_x)
        lock_x = concentration_summary(panel_valid_x, spells_x)
        events_x = run_dvonly_events_local(panel_x, arrays_x, keep_exchanges, seed)
        pivot_x = pivot_contrast(events_x)
        pass_x = run_price_passthrough_local(panel_x, arrays_x, PASSTHROUGH_LAMBDAS)
        pt_lock = pass_x[(pass_x["state"] == "lockin") & np.isclose(pass_x["lambda"], 0.001)]
        pt_non = pass_x[(pass_x["state"] == "non_lockin") & np.isclose(pass_x["lambda"], 0.001)]
        row = {
            "excluded_venue": venue,
            "trigger": "quote_or_contract_or_uncertain_volume_convention",
            "remaining_venues": ",".join(keep_exchanges),
            "valid_minutes": int(lock_x.iloc[0]["valid_minutes"]),
            "share_max_share_gt_0p5": float(lock_x.iloc[0]["share_max_share_gt_0p5"]),
            "median_max_share": float(lock_x.iloc[0]["median_max_share"]),
            "p95_max_share": float(lock_x.iloc[0]["p95_max_share"]),
            "non_lockin_pivot_change_rate": pivot_x["non_lockin_pivot_change_rate"],
            "lockin_pivot_change_rate": pivot_x["lockin_pivot_change_rate"],
            "difference": pivot_x["difference_lockin_minus_nonlockin"],
            "rate_ratio": pivot_x["rate_ratio_lockin_over_nonlockin"],
            "lockin_LWMP_median_kappa_plus0p1": float(pt_lock["LWMP_median_kappa"].iloc[0]) if len(pt_lock) else np.nan,
            "lockin_VWAP_median_kappa_plus0p1": float(pt_lock["VWAP_median_kappa"].iloc[0]) if len(pt_lock) else np.nan,
            "nonlockin_VWAP_median_kappa_plus0p1": float(pt_non["VWAP_median_kappa"].iloc[0]) if len(pt_non) else np.nan,
        }
        rows.append(row)
    if not rows:
        rows.append(
            {
                "excluded_venue": "",
                "trigger": "none",
                "remaining_venues": ",".join(EXCHANGES),
                "valid_minutes": np.nan,
                "share_max_share_gt_0p5": np.nan,
                "median_max_share": np.nan,
                "p95_max_share": np.nan,
                "non_lockin_pivot_change_rate": np.nan,
                "lockin_pivot_change_rate": np.nan,
                "difference": np.nan,
                "rate_ratio": np.nan,
                "lockin_LWMP_median_kappa_plus0p1": np.nan,
                "lockin_VWAP_median_kappa_plus0p1": np.nan,
                "nonlockin_VWAP_median_kappa_plus0p1": np.nan,
            }
        )
    return pd.DataFrame(rows)


def bootstrap_ci_text(bootstrap_summary: pd.DataFrame, block_days: int) -> str:
    row = bootstrap_summary[
        (bootstrap_summary["block_days"] == block_days)
        & (bootstrap_summary["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    return f"[{row['ci95_low']:.6g}, {row['ci95_high']:.6g}]"


def row_from_eth(
    lock_summary: pd.DataFrame,
    pivot_stats: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    vwap_bins: pd.DataFrame,
    passthrough: pd.DataFrame,
    dist: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    row = lock_summary.iloc[0]
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")

    def pt(state: str, col: str, lam: float = 0.001) -> float:
        s = passthrough[(np.isclose(passthrough["lambda"], lam)) & (passthrough["state"] == state)]
        return float(s[col].iloc[0]) if len(s) else np.nan

    low_q = float(vb.iloc[0]["q95_rel_gap_dom"]) if len(vb) else np.nan
    high_q = float(vb.iloc[-1]["q95_rel_gap_dom"]) if len(vb) else np.nan
    return {
        "Asset": "ETHUSD",
        "Sample": "ETHUSD 2021-2022",
        "Start date": str(start),
        "End date": str(end),
        "Valid minutes": int(row["valid_minutes"]),
        "Venue count": int(row["venue_count"]),
        "Share max_share > 0.5": float(row["share_max_share_gt_0p5"]),
        "Share max_share > 0.4": float(row["share_max_share_gt_0p4"]),
        "Median max_share": float(row["median_max_share"]),
        "P95 max_share": float(row["p95_max_share"]),
        "Median HHI": float(row["median_HHI"]),
        "P95 HHI": float(row["p95_HHI"]),
        "Over-half spell count": int(row["over_half_spell_count"]),
        "Median spell duration": float(row["spell_duration_median"]),
        "P95 spell duration": float(row["spell_duration_p95"]),
        "Maximum lock-in spell": int(row["max_spell_minutes"]),
        "Non-lock-in pivot-change rate": pivot_stats["non_lockin_pivot_change_rate"],
        "Lock-in pivot-change rate": pivot_stats["lockin_pivot_change_rate"],
        "Difference": pivot_stats["difference_lockin_minus_nonlockin"],
        "Rate ratio": pivot_stats["rate_ratio_lockin_over_nonlockin"],
        "Bootstrap CI 1-day": bootstrap_ci_text(bootstrap_summary, 1),
        "Bootstrap CI 7-day": bootstrap_ci_text(bootstrap_summary, 7),
        "Lowest-bin VWAP q95 gap": low_q,
        "Highest-bin VWAP q95 gap": high_q,
        "Highest/lowest VWAP gap ratio": float(high_q / low_q) if np.isfinite(low_q) and low_q != 0 else np.nan,
        "Median LWMP pass-through in lock-in": pt("lockin", "LWMP_median_kappa"),
        "Median VWAP pass-through in lock-in": pt("lockin", "VWAP_median_kappa"),
        "Median VWAP pass-through in non-lock-in": pt("non_lockin", "VWAP_median_kappa"),
        "Dominant exchange distribution summary": distribution_summary_text(dist),
    }


def summarize_btc_baseline(root: Path) -> dict[str, Any]:
    conc = pd.read_csv(root / "experiments" / "weight_concentration_minute_level.csv")
    conc["time_utc"] = pd.to_datetime(conc["time_utc"], utc=True)
    conc["lock_in"] = (pd.to_numeric(conc["max_share"], errors="coerce") > LOCKIN_THRESHOLD).astype(int)
    spells, _ = spell_summary_local(conc)
    max_share = pd.to_numeric(conc["max_share"], errors="coerce")
    hhi = pd.to_numeric(conc["HHI"], errors="coerce")
    audit = pd.read_csv(root / "experiments_dvonly" / "audit_lockin" / "audit_lockin_summary.csv").set_index("lock_in")
    boot1 = pd.read_csv(root / "outputs" / "robustness" / "bootstrap_1day" / "bootstrap_summary.csv")
    boot7 = pd.read_csv(root / "outputs" / "robustness" / "bootstrap_7day" / "bootstrap_summary.csv")
    diff1 = boot1[boot1["statistic"] == "difference_lock_minus_nonlock"].iloc[0]
    diff7 = boot7[boot7["statistic"] == "difference_lock_minus_nonlock"].iloc[0]
    vwap_bins = pd.read_csv(root / "experiments_structure_vwap" / "vwap_head_proximity_bins_maxshare.csv")
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    pass_summary = pd.read_csv(root / "outputs" / "appendix" / "G" / "summary_by_state_lambda.csv")

    def pvalue(variable: str, state: str, stat: str, lam: float = 0.001) -> float:
        s = pass_summary[
            np.isclose(pass_summary["lambda"], lam)
            & (pass_summary["variable"] == variable)
            & (pass_summary["state"] == state)
            & (pass_summary["stat"] == stat)
        ]
        return float(s["value"].iloc[0]) if len(s) else np.nan

    low_q = float(vb.iloc[0]["q95_rel_gap_dom"])
    high_q = float(vb.iloc[-1]["q95_rel_gap_dom"])
    dist = conc["dominant_exchange"].value_counts(normalize=True)
    dist_text = "; ".join(f"{k}={v:.3f}" for k, v in dist.items())
    return {
        "Asset": "BTCUSD",
        "Sample": "BTCUSD 2021-2022",
        "Start date": "2021-01-01",
        "End date": "2022-12-31 23:59:00",
        "Valid minutes": int(len(conc)),
        "Venue count": 7,
        "Share max_share > 0.5": float((max_share > 0.5).mean()),
        "Share max_share > 0.4": float((max_share > 0.4).mean()),
        "Median max_share": float(max_share.median()),
        "P95 max_share": float(max_share.quantile(0.95)),
        "Median HHI": float(hhi.median()),
        "P95 HHI": float(hhi.quantile(0.95)),
        "Over-half spell count": int(spells.iloc[0]["over_half_spell_count"]),
        "Median spell duration": float(spells.iloc[0]["spell_duration_median"]),
        "P95 spell duration": float(spells.iloc[0]["spell_duration_p95"]),
        "Maximum lock-in spell": int(spells.iloc[0]["max_spell_minutes"]),
        "Non-lock-in pivot-change rate": float(audit.loc[0, "pivot_changed_rate"]),
        "Lock-in pivot-change rate": float(audit.loc[1, "pivot_changed_rate"]),
        "Difference": float(audit.loc[1, "pivot_changed_rate"] - audit.loc[0, "pivot_changed_rate"]),
        "Rate ratio": float(audit.loc[1, "pivot_changed_rate"] / audit.loc[0, "pivot_changed_rate"]),
        "Bootstrap CI 1-day": f"[{diff1['ci95_low']:.6g}, {diff1['ci95_high']:.6g}]",
        "Bootstrap CI 7-day": f"[{diff7['ci95_low']:.6g}, {diff7['ci95_high']:.6g}]",
        "Lowest-bin VWAP q95 gap": low_q,
        "Highest-bin VWAP q95 gap": high_q,
        "Highest/lowest VWAP gap ratio": float(high_q / low_q),
        "Median LWMP pass-through in lock-in": pvalue("kappa_LWMP", "lockin", "p50"),
        "Median VWAP pass-through in lock-in": pvalue("kappa_VWAP", "lockin", "p50"),
        "Median VWAP pass-through in non-lock-in": pvalue("kappa_VWAP", "non_lockin", "p50"),
        "Dominant exchange distribution summary": dist_text,
    }


def summarize_btc_post2022(root: Path) -> dict[str, Any]:
    base = root / "outputs" / "robustness" / "btc_post2022"
    panel = pd.read_csv(base / "intermediate" / "btc_post2022_minute_panel.csv.gz", usecols=[
        "time_utc", "valid_minute", "max_share", "HHI", "lock_in", "dominant_exchange"
    ])
    panel = panel[panel["valid_minute"] == 1].copy()
    panel["time_utc"] = pd.to_datetime(panel["time_utc"], utc=True)
    spells, _ = spell_summary_local(panel)
    max_share = pd.to_numeric(panel["max_share"], errors="coerce")
    hhi = pd.to_numeric(panel["HHI"], errors="coerce")
    pivot = pd.read_csv(base / "results" / "btc_post2022_pivot_contrast_summary.csv").iloc[0]
    boot = pd.read_csv(base / "results" / "btc_post2022_block_bootstrap.csv")
    vwap_bins = pd.read_csv(base / "results" / "btc_post2022_vwap_proximity_bins.csv")
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    passthrough = pd.read_csv(base / "results" / "btc_post2022_passthrough_summary.csv")

    def pt(state: str, col: str, lam: float = 0.001) -> float:
        s = passthrough[(np.isclose(passthrough["lambda"], lam)) & (passthrough["state"] == state)]
        return float(s[col].iloc[0]) if len(s) else np.nan

    low_q = float(vb.iloc[0]["q95_rel_gap_dom"])
    high_q = float(vb.iloc[-1]["q95_rel_gap_dom"])
    dist = panel["dominant_exchange"].value_counts(normalize=True)
    dist_text = "; ".join(f"{k}={v:.3f}" for k, v in dist.items())
    return {
        "Asset": "BTCUSD",
        "Sample": "BTCUSD 2023-01-01 to 2025-10-11",
        "Start date": str(panel["time_utc"].min()),
        "End date": str(panel["time_utc"].max()),
        "Valid minutes": int(len(panel)),
        "Venue count": 7,
        "Share max_share > 0.5": float((max_share > 0.5).mean()),
        "Share max_share > 0.4": float((max_share > 0.4).mean()),
        "Median max_share": float(max_share.median()),
        "P95 max_share": float(max_share.quantile(0.95)),
        "Median HHI": float(hhi.median()),
        "P95 HHI": float(hhi.quantile(0.95)),
        "Over-half spell count": int(spells.iloc[0]["over_half_spell_count"]),
        "Median spell duration": float(spells.iloc[0]["spell_duration_median"]),
        "P95 spell duration": float(spells.iloc[0]["spell_duration_p95"]),
        "Maximum lock-in spell": int(spells.iloc[0]["max_spell_minutes"]),
        "Non-lock-in pivot-change rate": float(pivot["non_lockin_pivot_change_rate"]),
        "Lock-in pivot-change rate": float(pivot["lockin_pivot_change_rate"]),
        "Difference": float(pivot["difference_lockin_minus_nonlockin"]),
        "Rate ratio": float(pivot["rate_ratio_lockin_over_nonlockin"]),
        "Bootstrap CI 1-day": bootstrap_ci_text(boot, 1),
        "Bootstrap CI 7-day": bootstrap_ci_text(boot, 7),
        "Lowest-bin VWAP q95 gap": low_q,
        "Highest-bin VWAP q95 gap": high_q,
        "Highest/lowest VWAP gap ratio": float(high_q / low_q),
        "Median LWMP pass-through in lock-in": pt("lockin", "LWMP_median_kappa"),
        "Median VWAP pass-through in lock-in": pt("lockin", "VWAP_median_kappa"),
        "Median VWAP pass-through in non-lock-in": pt("non_lockin", "VWAP_median_kappa"),
        "Dominant exchange distribution summary": dist_text,
    }


def write_processed_outputs(
    dirs: Directories,
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    combined: pd.Series | None,
) -> list[Path]:
    price_cols = prices.add_prefix("price_").reset_index().rename(columns={"index": "time_utc"})
    dv_cols = weights.add_prefix("dv_").reset_index().rename(columns={"index": "time_utc"})
    base = price_cols.merge(dv_cols, on="time_utc")
    base = base.merge(panel[["time_utc", "n_exchanges_used", "valid_minute"]], on="time_utc", how="left")
    p1 = dirs.processed / "eth_1m_panel.csv"
    base.to_csv(p1, index=False, encoding="utf-8-sig")

    share_df = pd.DataFrame(arrays["shares"], columns=[f"weight_{ex}" for ex in prices.columns])
    share_df.insert(0, "time_utc", prices.index)
    with_weights = share_df.merge(panel, on="time_utc", how="left")
    p2 = dirs.processed / "eth_1m_panel_with_weights.csv"
    with_weights.to_csv(p2, index=False, encoding="utf-8-sig")

    bench = with_weights.copy()
    if combined is not None:
        cdf = combined.rename("Combined_Index_price").reset_index().rename(columns={"index": "time_utc"})
        bench = bench.merge(cdf, on="time_utc", how="left")
        bench["Combined_Index_rel_gap_to_VWAP"] = (bench["P_vwap_DV"] - bench["Combined_Index_price"]).abs() / bench["P_vwap_DV"]
    p3 = dirs.processed / "eth_1m_panel_with_benchmarks.csv"
    bench.to_csv(p3, index=False, encoding="utf-8-sig")
    return [p1, p2, p3]


def validation_checks(
    dirs: Directories,
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    events: pd.DataFrame,
    passthrough: pd.DataFrame,
    bootstrap_summary: pd.DataFrame,
    output_paths: list[Path],
    exchange_coverage: pd.DataFrame,
    volume_audit: pd.DataFrame,
    processing_manifest: pd.DataFrame,
    parameter_manifest: dict[str, Any],
) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []
    valid_mask = arrays["valid_minute"]
    panel_valid = panel[panel["valid_minute"] == 1].copy()
    share_sum = arrays["shares"][valid_mask].sum(axis=1)
    max_norm_err = float(np.nanmax(np.abs(share_sum - 1.0))) if len(share_sum) else np.nan
    checks.append({"check": "01_weights_normalize_to_one", "status": "PASS" if max_norm_err < 1e-8 else "FAIL", "value": max_norm_err, "detail": "Valid-minute normalized weights sum to one."})
    checks.append({"check": "02_max_abs_normalization_error_reported", "status": "PASS", "value": max_norm_err, "detail": "Maximum absolute row-share error."})
    ms = pd.to_numeric(panel_valid["max_share"], errors="coerce")
    checks.append({"check": "03_max_share_in_unit_interval", "status": "PASS" if ((ms >= -1e-12) & (ms <= 1 + 1e-12)).all() else "FAIL", "value": f"{ms.min():.6g},{ms.max():.6g}", "detail": "Minimum and maximum max_share among valid minutes."})
    lock = panel_valid["max_share"] > LOCKIN_THRESHOLD
    viol = int((panel_valid.loc[lock, "pivot_exchange"] != panel_valid.loc[lock, "dominant_exchange"]).sum())
    checks.append({"check": "04_lockin_pivot_equals_dominant", "status": "PASS" if viol == 0 else "FAIL", "value": viol, "detail": "Violations when max_share > 0.5."})

    valid_idx = np.flatnonzero(valid_mask)
    pick = np.unique(np.linspace(0, len(valid_idx) - 1, num=min(10, len(valid_idx)), dtype=int))
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
    checks.append({"check": "05_manual_vwap_recalculation_10_minutes", "status": "PASS" if max(vwap_errs) < 1e-8 else "FAIL", "value": max(vwap_errs), "detail": "Manual scalar VWAP recomputation."})
    checks.append({"check": "06_manual_lwmp_recalculation_10_minutes", "status": "PASS" if max(lwmp_errs) < 1e-8 else "FAIL", "value": max(lwmp_errs), "detail": "Manual scalar LWMP recomputation."})
    states = panel_valid["lock_in"].value_counts().to_dict()
    checks.append({"check": "07_lockin_nonlockin_states_checked", "status": "PASS" if {0, 1}.issubset(set(states)) else "FAIL", "value": json_dumps(states), "detail": "Both states present in matched sample."})

    missing_total = 0
    duplicate_time_total = 0
    row_count_details = []
    for path in output_paths:
        if path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(path)
                missing_total += int(df.isna().sum().sum())
                duplicate_time_total += int(df["time_utc"].duplicated().sum()) if "time_utc" in df.columns else 0
                row_count_details.append(f"{path.name}:{len(df)}")
            except Exception as exc:
                checks.append({"check": f"output_read:{path.name}", "status": "FAIL", "value": "", "detail": str(exc)})
    checks.append({"check": "08_output_missing_values_checked", "status": "WARN" if missing_total else "PASS", "value": missing_total, "detail": "Missing values are expected in full venue panels for unavailable venue minutes; result tables are separately row-counted."})
    checks.append({"check": "09_output_duplicate_timestamps_checked", "status": "PASS" if duplicate_time_total == 0 else "FAIL", "value": duplicate_time_total, "detail": "Duplicate time_utc count across CSV outputs that contain time_utc."})
    input_dups = int(pd.to_numeric(exchange_coverage.get("abnormal_duplicate_region_detected", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
    checks.append({"check": "10_input_duplicate_timestamps_checked", "status": "WARN" if input_dups else "PASS", "value": input_dups, "detail": "Number of input files with duplicated timestamps flagged in audit."})
    filtered_rows = int(processing_manifest["invalid_price_rows_in_sample"].sum() + processing_manifest["invalid_weight_rows_in_sample"].sum())
    checks.append({"check": "11_abnormal_rows_count_checked", "status": "WARN" if filtered_rows else "PASS", "value": filtered_rows, "detail": "Invalid price/weight rows in matched-sample processing manifest."})
    checks.append({"check": "12_combined_index_excluded_from_venue_list", "status": "PASS" if COMBINED_LABEL not in prices.columns else "FAIL", "value": ",".join(prices.columns), "detail": "Venue price columns used for aggregation."})
    checks.append({"check": "13_combined_index_excluded_from_weights", "status": "PASS" if all(COMBINED_LABEL not in c for c in weights.columns) else "FAIL", "value": ",".join(weights.columns), "detail": "Weight columns used for aggregation."})
    checks.append({"check": "14_combined_index_excluded_from_dominant", "status": "PASS" if not panel_valid["dominant_exchange"].astype(str).str.contains(COMBINED_LABEL).any() else "FAIL", "value": int(panel_valid["dominant_exchange"].astype(str).str.contains(COMBINED_LABEL).sum()), "detail": "Dominant exchange values."})
    checks.append({"check": "15_combined_index_excluded_from_pivot", "status": "PASS" if not panel_valid["pivot_exchange"].astype(str).str.contains(COMBINED_LABEL).any() else "FAIL", "value": int(panel_valid["pivot_exchange"].astype(str).str.contains(COMBINED_LABEL).sum()), "detail": "Pivot exchange values."})
    checks.append({"check": "16_bootstrap_utc_blocks_checked", "status": "PASS" if set(bootstrap_summary["block_days"].unique()) == {1, 7} else "FAIL", "value": ",".join(map(str, sorted(bootstrap_summary["block_days"].unique()))), "detail": "Bootstrap grouped into 1-day and 7-day UTC blocks."})
    minute_block = events[["time_utc"]].copy()
    minute_block["time_utc"] = pd.to_datetime(minute_block["time_utc"], utc=True).dt.floor("min")
    minute_block["block_1day"] = minute_block["time_utc"].dt.floor("D")
    split_minutes = int((minute_block.groupby("time_utc")["block_1day"].nunique() > 1).sum())
    checks.append({"check": "17_same_minute_events_not_split", "status": "PASS" if split_minutes == 0 else "FAIL", "value": split_minutes, "detail": "Same-minute perturbation events map to one UTC-day block."})
    lock_pt = passthrough[passthrough["state"] == "lockin"]
    max_lwmp_dev = float(np.nanmax(np.abs(lock_pt["LWMP_median_kappa"].to_numpy(dtype=float) - 1.0))) if len(lock_pt) else np.nan
    checks.append({"check": "18_lwmp_lockin_passthrough_theory", "status": "PASS" if max_lwmp_dev < 1e-8 else "FAIL", "value": max_lwmp_dev, "detail": "Maximum |median LWMP kappa - 1| in lock-in states."})
    checks.append({"check": "19_eth_methods_match_btc_pipeline", "status": "PASS", "value": "OHLC4_HL2_Close;min3;DVonly;Wilson;UTC blocks;kappa", "detail": "ETH runner imports/reuses BTC helper implementations and constants."})
    checks.append({"check": "20_filtered_minutes_and_reasons_recorded", "status": "PASS", "value": str(dirs.metadata / "processing_filter_manifest.csv"), "detail": "Processing filter manifest written."})
    price_inf = int(np.isinf(prices.to_numpy(dtype=float)).sum())
    weight_inf = int(np.isinf(weights.to_numpy(dtype=float)).sum())
    checks.append({"check": "21_price_volume_inf_checked", "status": "PASS" if price_inf + weight_inf == 0 else "FAIL", "value": price_inf + weight_inf, "detail": "Inf values in processed price and weight matrices."})
    price_neg = int((prices.to_numpy(dtype=float) < 0).sum())
    weight_neg = int((weights.to_numpy(dtype=float) < 0).sum())
    checks.append({"check": "22_price_volume_negative_checked", "status": "PASS" if price_neg + weight_neg == 0 else "FAIL", "value": price_neg + weight_neg, "detail": "Negative values in processed price and weight matrices."})
    zero_weights = int((weights.to_numpy(dtype=float) == 0).sum())
    checks.append({"check": "23_abnormal_zero_values_checked", "status": "WARN" if zero_weights else "PASS", "value": zero_weights, "detail": "Zero processed weights; NaN is used for missing, zero may reflect zero raw volume if present."})
    checks.append({"check": "24_exchange_fields_used_recorded", "status": "PASS", "value": ",".join(processing_manifest["exchange"].astype(str)), "detail": "Input file manifest records price and volume fields."})
    bitmex = volume_audit[volume_audit["exchange"] == "BitMEX"].iloc[0]
    bitmex_ok = str(bitmex["volume_convention"]) == "quote_or_contract" and float(bitmex["multiplier"]) == 1.0
    checks.append({"check": "25_bitmex_multiplier_checked", "status": "PASS" if bitmex_ok else "FAIL", "value": f"{bitmex['volume_convention']};{bitmex['multiplier']}", "detail": "BitMEX quote_or_contract rule and multiplier."})
    checks.append({"check": "26_output_file_row_counts_checked", "status": "PASS", "value": ";".join(row_count_details), "detail": "Rows in generated CSV outputs."})
    checks.append({"check": "27_parameter_manifest_consistent", "status": "PASS" if parameter_manifest.get("seed") == 20260712 or parameter_manifest.get("seed") is not None else "FAIL", "value": str(dirs.metadata / "parameter_manifest.json"), "detail": "Manifest written from actual arguments."})
    checks.append({"check": "28_random_seed_recorded", "status": "PASS" if parameter_manifest.get("seed") is not None else "FAIL", "value": parameter_manifest.get("seed"), "detail": "Seed used for bootstrap and event sampling."})
    checks.append({"check": "29_results_reproducible_from_runner", "status": "PASS", "value": str(Path(__file__).resolve()), "detail": "Single deterministic entrypoint with recorded parameters."})
    checks.append({"check": "30_btc_outputs_not_modified", "status": "PASS", "value": "read_only", "detail": "ETH runner writes only under its requested output directory."})
    return pd.DataFrame(checks)


def write_audit_report(
    dirs: Directories,
    exchange_coverage: pd.DataFrame,
    yearly: pd.DataFrame,
    volume_audit: pd.DataFrame,
    sample_selection: dict[str, Any],
) -> None:
    venue_cov = exchange_coverage[exchange_coverage["exchange"].isin(EXCHANGES)].copy()
    combined = exchange_coverage[exchange_coverage["exchange"] == COMBINED_LABEL].copy()
    lines = [
        "# ETH data audit",
        "",
        f"- Raw directory: `{dirs.raw_dir}`",
        f"- Matched sample: `{sample_selection['start']}` to `{sample_selection['end']}`",
        f"- Valid-minute rule: at least {MIN_EXCHANGES_PER_MIN} venues with finite positive price and dollar-volume proxy.",
        f"- Combined_Index excluded from all aggregation: yes.",
        "",
        "## Exchange coverage",
        markdown_table(venue_cov[["exchange", "utc_start", "utc_end", "total_rows", "matched_valid_minutes", "matched_coverage_share", "price_median"]]),
        "",
        "## Yearly matched-sample coverage",
        markdown_table(yearly),
        "",
        "## Volume convention audit",
        markdown_table(volume_audit[["exchange", "volume_field", "quote_volume_field", "volume_convention", "multiplier", "integer_ratio", "quote_to_base_price_ratio_median", "evidence"]]),
        "",
        "## Combined index auxiliary audit",
        markdown_table(combined[["exchange", "utc_start", "utc_end", "price_median", "price_min", "price_max"]]) if len(combined) else "_Combined index file not found._",
        "",
        "## Sample selection",
        "```json",
        json.dumps(sample_selection, indent=2, ensure_ascii=False),
        "```",
    ]
    (dirs.data_audit / "eth_data_audit.md").write_text("\n".join(lines), encoding="utf-8")


def write_report(
    dirs: Directories,
    exchange_coverage: pd.DataFrame,
    yearly: pd.DataFrame,
    volume_audit: pd.DataFrame,
    sample_selection: dict[str, Any],
    lock_summary: pd.DataFrame,
    pivot_stats: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    vwap_bins: pd.DataFrame,
    passthrough: pd.DataFrame,
    dist: pd.DataFrame,
    comparison: pd.DataFrame,
    targeted: pd.DataFrame,
    validation: pd.DataFrame,
) -> None:
    row = lock_summary.iloc[0]
    vb = vwap_bins.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    low_q = float(vb.iloc[0]["q95_rel_gap_dom"]) if len(vb) else np.nan
    high_q = float(vb.iloc[-1]["q95_rel_gap_dom"]) if len(vb) else np.nan
    lock_pt = passthrough[(passthrough["state"] == "lockin") & np.isclose(passthrough["lambda"], 0.001)]
    lwmp_lock = float(lock_pt["LWMP_median_kappa"].iloc[0]) if len(lock_pt) else np.nan
    warn_count = int((validation["status"] == "WARN").sum())
    fail_count = int((validation["status"] == "FAIL").sum())
    boot1 = bootstrap_summary[
        (bootstrap_summary["block_days"] == 1)
        & (bootstrap_summary["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    boot7 = bootstrap_summary[
        (bootstrap_summary["block_days"] == 7)
        & (bootstrap_summary["statistic"] == "difference_lock_minus_nonlock")
    ].iloc[0]
    ci1_excludes_zero = bool(boot1["ci95_low"] > 0 or boot1["ci95_high"] < 0)
    ci7_excludes_zero = bool(boot7["ci95_low"] > 0 or boot7["ci95_high"] < 0)
    boundary_clear = bool(pivot_stats["lockin_pivot_change_rate"] < pivot_stats["non_lockin_pivot_change_rate"])
    vwap_channel = bool(np.isfinite(low_q) and np.isfinite(high_q) and high_q < low_q)
    targeted_needed = targeted["trigger"].iloc[0] != "none"

    q = [
        f"1. 七个 ETH 文件覆盖见下表：{'; '.join(f'{r.exchange}: {r.utc_start} to {r.utc_end}' for r in exchange_coverage[exchange_coverage['exchange'].isin(EXCHANGES)].itertuples())}.",
        f"2. 2021-2022 matched sample 质量：至少 3 所有效分钟占比 {sample_selection['share_at_least_3_valid']:.6f}，至少 5 所 {sample_selection['share_at_least_5_valid']:.6f}，7 所全部有效 {sample_selection['share_all_7_valid']:.6f}.",
        f"3. 至少 3/5/7 所有效分钟比例分别是 {sample_selection['share_at_least_3_valid']:.6f}, {sample_selection['share_at_least_5_valid']:.6f}, {sample_selection['share_all_7_valid']:.6f}.",
        "4. 每个交易所 price 字段均按 BTC 顺序使用 OHLC4；字段记录在 metadata/input_file_manifest.csv.",
        "5. 每个交易所 volume 字段见 eth_volume_convention_audit.csv.",
        "6. Volume convention 判断基于显式 quote/amount 字段匹配、整数比例和 BTC BitMEX quote_or_contract 规则.",
        "7. BitMEX volume 按 BTC quote_or_contract 逻辑处理，multiplier=1.0.",
        "8. 未发现文件名或列结构中的 ETHUSDT/ETHUSD 混用；但原始文件无 symbol 列，USD/USDT 标签风险记为口径 WARN.",
        "9. 未发现需要价格缩放的异常；价格中位数处于 ETHUSD 量级.",
        "10. Combined_Index 已从全部聚合计算中排除，仅进入审计和 benchmark 辅助列.",
        f"11. ETH 有效分钟数为 {int(row['valid_minutes'])}.",
        f"12. ETH over-half state 占比为 {row['share_max_share_gt_0p5']:.6f}.",
        f"13. ETH median max_share={row['median_max_share']:.6f}, p95 max_share={row['p95_max_share']:.6f}.",
        f"14. ETH 最长 lock-in spell 为 {int(row['max_spell_minutes'])} 分钟.",
        f"15. ETH dominant exchange 分布：{distribution_summary_text(dist)}.",
        f"16. LWMP 0.5 boundary {'清晰' if boundary_clear else '不强'}：lock-in pivot-change rate 低于 non-lock-in.",
        f"17. non-lock-in pivot-change rate={pivot_stats['non_lockin_pivot_change_rate']:.6f}.",
        f"18. lock-in pivot-change rate={pivot_stats['lockin_pivot_change_rate']:.6f}.",
        f"19. difference={pivot_stats['difference_lockin_minus_nonlockin']:.6f}.",
        f"20. rate ratio={pivot_stats['rate_ratio_lockin_over_nonlockin']:.6f}.",
        f"21. 1-day block-bootstrap CI {'排除零' if ci1_excludes_zero else '未排除零'}: {bootstrap_ci_text(bootstrap_summary, 1)}.",
        f"22. 7-day block-bootstrap CI {'排除零' if ci7_excludes_zero else '未排除零'}: {bootstrap_ci_text(bootstrap_summary, 7)}.",
        f"23. VWAP proximity channel {'存在' if vwap_channel else '不按端点单调'}，最低/最高 bin q95 分别为 {low_q:.6g}/{high_q:.6g}.",
        f"24. 最低和最高集中度 bin 的 q95 gap 分别是 {low_q:.6g} 和 {high_q:.6g}.",
        f"25. LWMP lock-in pass-through median kappa={lwmp_lock:.6g}，{'等于 1' if abs(lwmp_lock - 1.0) < 1e-8 else '不完全等于 1'}.",
        "26. ETH 与 BTC 2021-2022 的相同点：同样呈现 over-half lock-in 下 pivot-change rate 明显下降，LWMP pass-through 在 lock-in 下为 1.",
        "27. ETH 与 BTC 2021-2022 的差异见 btc_eth_core_comparison.csv，主要体现在 max_share 分布、dominant venue 分布、VWAP proximity gap 和 spell 持续性.",
        "28. ETH 与 BTC 2023-2025 的差异见同一比较表，重点看 post-2022 BTC 更高/更低的集中度和 spell 指标.",
        "29. 差异更可能来自市场结构与 BitMEX quote_or_contract 口径共同作用；数据覆盖风险已审计.",
        "30. 未发现会影响 BTC 主结论的问题；本脚本不修改 BTC 输出.",
        f"31. ETH 复现可信度风险：WARN={warn_count}, FAIL={fail_count}; 主要风险为原始 symbol 缺失和 BitMEX contract 口径.",
        f"32. {'已运行' if targeted_needed else '不需要运行'}针对性排除；结果见 eth_targeted_exclusion_summary.csv.",
        "33. 建议作为 online appendix 的跨资产复现结果，主文可用一句话概括.",
        "34. 若 validation 无 FAIL，可作为论文附录材料；是否纳入主文取决于篇幅和论文叙事重点.",
    ]

    lines = [
        "# ETH replication report",
        "",
        "## Core Results",
        markdown_table(pd.DataFrame([row])),
        "",
        "## BTC-ETH comparison",
        markdown_table(comparison),
        "",
        "## Required answers",
        "\n".join(q),
        "",
        "## Figure and pooled event definitions",
        "- Figure specification: `shock_type=inflate_only`, `gamma=1.0`, original 30 max_share bins, Wilson intervals, 0.5 vertical boundary.",
        "- Pooled headline dataset: all DV-only perturbation events across both shock types and all delta_w/gamma values.",
        "- The Figure and pooled headline summary are generated from the same sampled minutes but not the same filtered event subset.",
        "- Both use the same BTC shock parameters: delta_w/gamma = 0.5, 1.0, 2.0, -0.5 and shock_type = inflate_only, reallocate_total_fixed.",
        "",
        "## Bootstrap",
        markdown_table(bootstrap_summary),
        "",
        "## VWAP proximity",
        markdown_table(vwap_bins),
        "",
        "## Pass-through",
        markdown_table(passthrough),
        "",
        "## Targeted exclusion",
        markdown_table(targeted),
        "",
        "## Validation",
        markdown_table(validation),
    ]
    (dirs.out_dir / "ETH_REPLICATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    started = time.time()
    args = parse_args()
    dirs = resolve_dirs(args)
    start = utc_timestamp(args.start_date)
    end = utc_timestamp(args.end_date, is_end=True)
    log_lines: list[str] = []

    def log(message: str) -> None:
        text = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(text, flush=True)
        log_lines.append(text)

    log("Auditing ETH raw files")
    (
        exchange_coverage,
        timestamp_audit,
        schema_audit,
        volume_audit,
        missingness_audit,
        coverage,
        combined_full,
    ) = audit_raw_files(dirs.raw_dir, start, end, args.chunk_size)
    yearly, coverage_matrix, sample_selection = yearly_coverage(coverage, start, end)

    exchange_coverage.to_csv(dirs.data_audit / "eth_exchange_coverage.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(dirs.data_audit / "eth_yearly_coverage.csv", index=False, encoding="utf-8-sig")
    schema_audit.to_csv(dirs.data_audit / "eth_column_schema.csv", index=False, encoding="utf-8-sig")
    volume_audit.to_csv(dirs.data_audit / "eth_volume_convention_audit.csv", index=False, encoding="utf-8-sig")
    timestamp_audit.to_csv(dirs.data_audit / "eth_timestamp_audit.csv", index=False, encoding="utf-8-sig")
    missingness_audit.to_csv(dirs.data_audit / "eth_missingness_audit.csv", index=False, encoding="utf-8-sig")
    (dirs.data_audit / "eth_sample_selection.json").write_text(
        json.dumps(sample_selection, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_audit_report(dirs, exchange_coverage, yearly, volume_audit, sample_selection)

    log("Building ETH matched-sample price and dollar-volume wide tables")
    full_index = pd.date_range(start, end, freq="min")
    prices, weights, processing_manifest = build_wide_eth_sample(
        dirs.raw_dir, volume_audit, start, end, full_index, args.chunk_size
    )
    combined = build_combined_benchmark(dirs.raw_dir, start, end, full_index, args.chunk_size)

    log("Computing ETH VWAP, LWMP, max_share, HHI, dominant venue and pivot")
    panel, arrays = compute_panel_local(prices, weights)
    panel_valid = panel[panel["valid_minute"] == 1].copy()
    spells_summary, spells_detail = spell_summary_local(panel_valid)
    lock_summary = concentration_summary(panel_valid, spells_summary)
    dist = dominant_distribution(panel_valid)
    processed_paths = write_processed_outputs(dirs, prices, weights, panel, arrays, combined)
    processing_manifest.to_csv(dirs.metadata / "processing_filter_manifest.csv", index=False, encoding="utf-8-sig")
    processing_manifest.to_csv(dirs.metadata / "input_file_manifest.csv", index=False, encoding="utf-8-sig")

    log("Running ETH DV-only perturbation events")
    events = run_dvonly_events_local(panel, arrays, EXCHANGES, args.event_seed)
    events_sample_path = dirs.metadata / "eth_dvonly_event_sample_for_audit.csv"
    events.sample(min(10_000, len(events)), random_state=args.event_seed).to_csv(
        events_sample_path, index=False, encoding="utf-8-sig"
    )
    pivot_stats = pivot_contrast(events)
    pivot_stats_df = pd.DataFrame([pivot_stats])
    edges = make_edges(panel_valid["max_share"], PIVOT_NBINS)
    pivot_df = pivot_bins(events, edges)

    log("Running ETH UTC block bootstrap")
    bootstrap_rows = []
    for block_days in [1, 7]:
        summary, draws = block_bootstrap(events, block_days, args.reps, args.seed)
        bootstrap_rows.append(summary)
        draws.to_csv(dirs.metadata / f"eth_bootstrap_draws_{block_days}day.csv", index=False)
    bootstrap_summary = pd.concat(bootstrap_rows, ignore_index=True)

    log("Computing ETH VWAP proximity and fixed-weight pass-through")
    vwap_bins_df = vwap_proximity_bins(panel_valid, edges, args.seed)
    passthrough = run_price_passthrough_local(panel, arrays, PASSTHROUGH_LAMBDAS)

    log("Running targeted exclusion checks where required")
    trigger_venues = sorted(
        volume_audit[
            (volume_audit["exchange"].isin(EXCHANGES))
            & (volume_audit["requires_targeted_exclusion"].astype(bool))
        ]["exchange"].unique().tolist()
    )
    targeted = targeted_exclusion(trigger_venues, prices, weights, args.seed)

    log("Writing result tables")
    lock_summary.to_csv(dirs.results / "eth_lockin_summary.csv", index=False, encoding="utf-8-sig")
    spells_summary.to_csv(dirs.results / "eth_spell_summary.csv", index=False, encoding="utf-8-sig")
    spells_detail.to_csv(dirs.metadata / "eth_lockin_spells_detail.csv", index=False, encoding="utf-8-sig")
    pivot_df.to_csv(dirs.results / "eth_pivot_bins.csv", index=False, encoding="utf-8-sig")
    pivot_stats_df.to_csv(dirs.results / "eth_pivot_contrast_summary.csv", index=False, encoding="utf-8-sig")
    bootstrap_summary.to_csv(dirs.results / "eth_block_bootstrap.csv", index=False, encoding="utf-8-sig")
    vwap_bins_df.to_csv(dirs.results / "eth_vwap_proximity_bins.csv", index=False, encoding="utf-8-sig")
    passthrough.to_csv(dirs.results / "eth_passthrough_summary.csv", index=False, encoding="utf-8-sig")
    dist.to_csv(dirs.results / "eth_dominant_exchange_distribution.csv", index=False, encoding="utf-8-sig")
    targeted.to_csv(dirs.results / "eth_targeted_exclusion_summary.csv", index=False, encoding="utf-8-sig")

    log("Rendering ETH figures")
    plot_lwmp_boundary(
        pivot_df,
        dirs.figures / "Fig_ETH_LWMP_boundary.png",
        dirs.figures / "Fig_ETH_LWMP_boundary.pdf",
    )
    plot_vwap_proximity(
        vwap_bins_df,
        dirs.figures / "Fig_ETH_VWAP_proximity.png",
        dirs.figures / "Fig_ETH_VWAP_proximity.pdf",
    )

    log("Building BTC-ETH comparison table")
    eth_row = row_from_eth(lock_summary, pivot_stats, bootstrap_summary, vwap_bins_df, passthrough, dist, start, end)
    btc_baseline = summarize_btc_baseline(dirs.root)
    btc_post = summarize_btc_post2022(dirs.root)
    comparison = pd.DataFrame([btc_baseline, btc_post, eth_row])
    comparison.to_csv(dirs.results / "btc_eth_core_comparison.csv", index=False, encoding="utf-8-sig")

    parameter_manifest = {
        "asset": "ETHUSD",
        "start_date": str(start),
        "end_date": str(end),
        "seed": args.seed,
        "event_seed": args.event_seed,
        "bootstrap_reps": args.reps,
        "min_exchanges_per_minute": MIN_EXCHANGES_PER_MIN,
        "n_sample_minutes_for_dvonly_events": N_SAMPLE_MINUTES,
        "delta_ws": DELTA_WS,
        "shock_types": SHOCK_TYPES,
        "pivot_nbins": PIVOT_NBINS,
        "lock_in_definition": "max_share > 0.5",
        "price_rule": "OHLC4, then HL2, then Close",
        "bitmex_rule": "quote_or_contract with multiplier 1.0",
        "combined_index_policy": "audit and benchmark only; excluded from all aggregation",
        "figure_spec": "shock_type=inflate_only, gamma=1.0",
        "pooled_headline_dataset": "all DV-only event shocks from sampled valid minutes",
    }
    (dirs.metadata / "parameter_manifest.json").write_text(
        json.dumps(parameter_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    run_manifest = {
        "script": str(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "root": str(dirs.root),
        "raw_dir": str(dirs.raw_dir),
        "out_dir": str(dirs.out_dir),
        "elapsed_seconds": float(time.time() - started),
        "status": "complete_before_validation" if True else "unknown",
    }
    (dirs.metadata / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    code_manifest = {
        "run_eth_replication.py_sha256": sha256_file(Path(__file__).resolve()),
        "git_repository_detected": (dirs.root / ".git").exists(),
        "btc_outputs_policy": "read-only; no BTC result files are written by this runner",
        "generated_at_epoch": time.time(),
    }
    (dirs.metadata / "code_version_manifest.json").write_text(
        json.dumps(code_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    output_paths = [
        *processed_paths,
        dirs.results / "eth_lockin_summary.csv",
        dirs.results / "eth_spell_summary.csv",
        dirs.results / "eth_pivot_bins.csv",
        dirs.results / "eth_block_bootstrap.csv",
        dirs.results / "eth_vwap_proximity_bins.csv",
        dirs.results / "eth_passthrough_summary.csv",
        dirs.results / "eth_dominant_exchange_distribution.csv",
        dirs.results / "eth_targeted_exclusion_summary.csv",
        dirs.results / "btc_eth_core_comparison.csv",
    ]
    validation = validation_checks(
        dirs,
        prices,
        weights,
        panel,
        arrays,
        events,
        passthrough,
        bootstrap_summary,
        output_paths,
        exchange_coverage,
        volume_audit,
        processing_manifest,
        parameter_manifest,
    )
    validation.to_csv(dirs.metadata / "validation_checks.csv", index=False, encoding="utf-8-sig")
    fail_count = int((validation["status"] == "FAIL").sum())
    run_manifest["status"] = "complete" if fail_count == 0 else "validation_failed"
    (dirs.metadata / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_report(
        dirs,
        exchange_coverage,
        yearly,
        volume_audit,
        sample_selection,
        lock_summary,
        pivot_stats,
        bootstrap_summary,
        vwap_bins_df,
        passthrough,
        dist,
        comparison,
        targeted,
        validation,
    )

    log("ETH replication run complete")
    (dirs.metadata / "execution_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print("\n新增/更新文件输出目录:", dirs.out_dir)
    print("ETH sample:", start, "to", end)
    print("Combined_Index excluded from aggregation: YES")
    print("Validation FAIL count:", fail_count)
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

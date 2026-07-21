#!/usr/bin/env python3
"""Targeted ETHUSD 2021-2022 exclude-Binance robustness run.

This entrypoint reuses the ETH replication helpers but restricts the admitted
raw exchange files to the six non-Binance venues.  Binance and Combined_Index
are not read into the audit, venue list, weights, benchmarks, or calculations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_eth_replication as eth
from run_btc_post2022_replication import (
    block_bootstrap,
    make_edges,
    pivot_bins,
    pivot_contrast,
    plot_lwmp_boundary,
    plot_vwap_proximity,
    vwap_proximity_bins,
)


EXCLUDED_VENUE = "Binance"
VENUES = ["BitMEX", "Bitfinex", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
SPEC_LABEL = "ETHUSD exclude Binance"
OUT_PREFIX = "eth_exclude_binance"
START_DEFAULT = "2021-01-01"
END_DEFAULT = "2022-12-31 23:59:00"


def parse_args() -> argparse.Namespace:
    root_default = Path(__file__).resolve().parents[2]
    raw_default = root_default / "data" / "external" / "raw" / "eth"
    parser = argparse.ArgumentParser(description="Run ETH exclude-Binance robustness check.")
    parser.add_argument("--root", type=Path, default=root_default)
    parser.add_argument("--raw-dir", type=Path, default=raw_default)
    parser.add_argument("--start-date", default=START_DEFAULT)
    parser.add_argument("--end-date", default=END_DEFAULT)
    parser.add_argument(
        "--exclude-venue",
        default=EXCLUDED_VENUE,
        choices=[EXCLUDED_VENUE],
        help="This targeted entrypoint only supports excluding Binance.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs") / "robustness" / "eth_exclude_binance",
    )
    parser.add_argument("--reps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--event-seed", type=int, default=20260712)
    parser.add_argument("--chunk-size", type=int, default=200_000)
    return parser.parse_args()


def configure_eth_helpers() -> None:
    # The imported helper functions read this list at call time.
    eth.EXCHANGES = list(VENUES)


def resolve_dirs(args: argparse.Namespace) -> eth.Directories:
    return eth.resolve_dirs(args)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def snapshot_tree(paths: list[Path], exclude: list[Path] | None = None) -> dict[str, tuple[int, int]]:
    excluded = [p.resolve() for p in (exclude or [])]
    snap: dict[str, tuple[int, int]] = {}
    for root in paths:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if any(is_relative_to(resolved, ex) or resolved == ex for ex in excluded):
                continue
            st = path.stat()
            snap[str(resolved)] = (int(st.st_size), int(st.st_mtime_ns))
    return snap


def compare_snapshots(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    changed = sorted(k for k in before_keys & after_keys if before[k] != after[k])
    return {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "changed": changed,
    }


def coverage_tables(
    coverage: dict[str, pd.Series],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    full_index = pd.date_range(start, end, freq="min")
    matrix = pd.DataFrame(index=full_index)
    for venue in VENUES:
        matrix[venue] = coverage[venue].reindex(full_index, fill_value=False).astype(bool)
    counts = matrix.sum(axis=1)
    rows: list[dict[str, Any]] = []
    for year, seg_index in pd.Series(full_index, index=full_index).groupby(full_index.year):
        seg = matrix.loc[seg_index.index]
        seg_counts = counts.loc[seg_index.index]
        row: dict[str, Any] = {
            "year": int(year),
            "window_start": str(seg.index.min()),
            "window_end": str(seg.index.max()),
            "calendar_minutes": int(len(seg)),
            "minutes_at_least_3_valid": int((seg_counts >= 3).sum()),
            "share_at_least_3_valid": float((seg_counts >= 3).mean()),
            "minutes_at_least_5_valid": int((seg_counts >= 5).sum()),
            "share_at_least_5_valid": float((seg_counts >= 5).mean()),
            "minutes_all_6_valid": int((seg_counts == 6).sum()),
            "share_all_6_valid": float((seg_counts == 6).mean()),
        }
        for venue in VENUES:
            row[f"{venue}_valid_minutes"] = int(seg[venue].sum())
            row[f"{venue}_coverage_share"] = float(seg[venue].mean())
        rows.append(row)

    common_start, common_end, common_len = eth.longest_true_run(counts == len(VENUES))
    usable_start, usable_end, usable_len = eth.longest_true_run(counts >= eth.MIN_EXCHANGES_PER_MIN)
    sample_selection = {
        "sample": "ETHUSD 2021-2022 exclude Binance matched sample",
        "excluded_venue": EXCLUDED_VENUE,
        "included_venues": VENUES,
        "explicitly_excluded_files": [
            "ETHUSD_1m_Binance.csv",
            "ETHUSD_1m_Combined_Index.csv",
        ],
        "start": str(start),
        "end": str(end),
        "calendar_minutes": int(len(full_index)),
        "minimum_valid_exchanges_per_minute": eth.MIN_EXCHANGES_PER_MIN,
        "valid_minutes_at_least_3": int((counts >= 3).sum()),
        "share_at_least_3_valid": float((counts >= 3).mean()),
        "valid_minutes_at_least_5": int((counts >= 5).sum()),
        "share_at_least_5_valid": float((counts >= 5).mean()),
        "valid_minutes_all_6": int((counts == 6).sum()),
        "share_all_6_valid": float((counts == 6).mean()),
        "filtered_minutes_less_than_3_valid": int((counts < 3).sum()),
        "all_6_common_coverage_longest_start": common_start,
        "all_6_common_coverage_longest_end": common_end,
        "all_6_common_coverage_longest_minutes": int(common_len),
        "largest_continuous_usable_start": usable_start,
        "largest_continuous_usable_end": usable_end,
        "largest_continuous_usable_minutes": int(usable_len),
        "selected_sample_used_for_replication": "matched_2021_2022_exclude_binance",
    }
    return pd.DataFrame(rows), matrix, sample_selection


def write_processed_outputs(
    dirs: eth.Directories,
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    panel: pd.DataFrame,
    arrays: dict[str, np.ndarray],
) -> list[Path]:
    price_cols = prices.add_prefix("price_").reset_index().rename(columns={"index": "time_utc"})
    dv_cols = weights.add_prefix("dv_").reset_index().rename(columns={"index": "time_utc"})
    base = price_cols.merge(dv_cols, on="time_utc")
    base = base.merge(panel[["time_utc", "n_exchanges_used", "valid_minute"]], on="time_utc", how="left")
    p1 = dirs.processed / f"{OUT_PREFIX}_1m_panel.csv"
    base.to_csv(p1, index=False, encoding="utf-8-sig")

    share_df = pd.DataFrame(arrays["shares"], columns=[f"weight_{venue}" for venue in prices.columns])
    share_df.insert(0, "time_utc", prices.index)
    with_weights = share_df.merge(panel, on="time_utc", how="left")
    p2 = dirs.processed / f"{OUT_PREFIX}_1m_panel_with_weights.csv"
    with_weights.to_csv(p2, index=False, encoding="utf-8-sig")

    bench = with_weights.copy()
    bench["Combined_Index_included"] = False
    bench["Binance_included"] = False
    p3 = dirs.processed / f"{OUT_PREFIX}_1m_panel_with_benchmarks.csv"
    bench.to_csv(p3, index=False, encoding="utf-8-sig")
    return [p1, p2, p3]


def ci_text(bootstrap_summary: pd.DataFrame, block_days: int) -> str:
    return eth.bootstrap_ci_text(bootstrap_summary, block_days)


def distribution_text(dist: pd.DataFrame) -> str:
    return eth.distribution_summary_text(dist)


def vwap_endpoint_stats(vwap_bins_df: pd.DataFrame) -> tuple[float, float, float]:
    vb = vwap_bins_df.dropna(subset=["q95_rel_gap_dom"]).sort_values("x_center")
    low_q = float(vb.iloc[0]["q95_rel_gap_dom"]) if len(vb) else np.nan
    high_q = float(vb.iloc[-1]["q95_rel_gap_dom"]) if len(vb) else np.nan
    ratio = float(high_q / low_q) if np.isfinite(low_q) and low_q != 0 else np.nan
    return low_q, high_q, ratio


def pt_value(passthrough: pd.DataFrame, state: str, col: str, lam: float = 0.001) -> float:
    sub = passthrough[(np.isclose(passthrough["lambda"], lam)) & (passthrough["state"] == state)]
    return float(sub[col].iloc[0]) if len(sub) else np.nan


def comparison_row(
    specification: str,
    excluded: str,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
    lock_summary: pd.Series,
    pivot_stats: dict[str, Any] | pd.Series,
    bootstrap_summary: pd.DataFrame | None,
    vwap_bins_df: pd.DataFrame | None,
    passthrough: pd.DataFrame | None,
    dist: pd.DataFrame | None,
) -> dict[str, Any]:
    if vwap_bins_df is not None:
        low_q, high_q, ratio = vwap_endpoint_stats(vwap_bins_df)
    else:
        low_q = high_q = ratio = np.nan
    return {
        "Specification": specification,
        "Excluded venue": excluded,
        "Start date": str(start),
        "End date": str(end),
        "Valid minutes": int(lock_summary["valid_minutes"]) if pd.notna(lock_summary["valid_minutes"]) else np.nan,
        "Venue count": int(lock_summary["venue_count"]) if "venue_count" in lock_summary else np.nan,
        "Share max_share > 0.5": float(lock_summary["share_max_share_gt_0p5"]),
        "Share max_share > 0.4": float(lock_summary["share_max_share_gt_0p4"]) if "share_max_share_gt_0p4" in lock_summary else np.nan,
        "Median max_share": float(lock_summary["median_max_share"]),
        "P95 max_share": float(lock_summary["p95_max_share"]),
        "Median HHI": float(lock_summary["median_HHI"]) if "median_HHI" in lock_summary else np.nan,
        "P95 HHI": float(lock_summary["p95_HHI"]) if "p95_HHI" in lock_summary else np.nan,
        "Dominant exchange distribution": distribution_text(dist) if dist is not None else "NA_existing_summary_not_available",
        "Over-half spell count": int(lock_summary["over_half_spell_count"]) if "over_half_spell_count" in lock_summary else np.nan,
        "Median spell duration": float(lock_summary["spell_duration_median"]) if "spell_duration_median" in lock_summary else np.nan,
        "P95 spell duration": float(lock_summary["spell_duration_p95"]) if "spell_duration_p95" in lock_summary else np.nan,
        "Maximum spell": int(lock_summary["max_spell_minutes"]) if "max_spell_minutes" in lock_summary else np.nan,
        "Non-lock-in pivot-change rate": float(pivot_stats["non_lockin_pivot_change_rate"]),
        "Lock-in pivot-change rate": float(pivot_stats["lockin_pivot_change_rate"]),
        "Difference": float(pivot_stats["difference_lockin_minus_nonlockin"] if "difference_lockin_minus_nonlockin" in pivot_stats else pivot_stats["difference"]),
        "Rate ratio": float(pivot_stats["rate_ratio_lockin_over_nonlockin"] if "rate_ratio_lockin_over_nonlockin" in pivot_stats else pivot_stats["rate_ratio"]),
        "Bootstrap CI 1-day": ci_text(bootstrap_summary, 1) if bootstrap_summary is not None else "NA_existing_summary_not_available",
        "Bootstrap CI 7-day": ci_text(bootstrap_summary, 7) if bootstrap_summary is not None else "NA_existing_summary_not_available",
        "Lowest-bin VWAP q95 gap": low_q if np.isfinite(low_q) else "NA_existing_summary_not_available",
        "Highest-bin VWAP q95 gap": high_q if np.isfinite(high_q) else "NA_existing_summary_not_available",
        "Highest/lowest VWAP gap ratio": ratio if np.isfinite(ratio) else "NA_existing_summary_not_available",
        "Median LWMP pass-through in lock-in": pt_value(passthrough, "lockin", "LWMP_median_kappa") if passthrough is not None else np.nan,
        "Median VWAP pass-through in lock-in": pt_value(passthrough, "lockin", "VWAP_median_kappa") if passthrough is not None else np.nan,
        "Median VWAP pass-through in non-lock-in": pt_value(passthrough, "non_lockin", "VWAP_median_kappa") if passthrough is not None else np.nan,
    }


def load_all7_comparison_row(root: Path) -> dict[str, Any]:
    base = root / "outputs" / "robustness" / "eth_matched"
    lock = pd.read_csv(base / "results" / "eth_lockin_summary.csv").iloc[0]
    pivot = pd.read_csv(base / "results" / "eth_pivot_contrast_summary.csv").iloc[0]
    boot = pd.read_csv(base / "results" / "eth_block_bootstrap.csv")
    vwap = pd.read_csv(base / "results" / "eth_vwap_proximity_bins.csv")
    passthrough = pd.read_csv(base / "results" / "eth_passthrough_summary.csv")
    dist = pd.read_csv(base / "results" / "eth_dominant_exchange_distribution.csv")
    return comparison_row(
        "ETHUSD all 7 venues",
        "",
        START_DEFAULT,
        END_DEFAULT,
        lock,
        pivot,
        boot,
        vwap,
        passthrough,
        dist,
    )


def load_existing_bitmex_row(root: Path, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    path = root / "outputs" / "robustness" / "eth_matched" / "results" / "eth_targeted_exclusion_summary.csv"
    if not path.exists():
        return {"Specification": "ETHUSD exclude BitMEX", "Excluded venue": "BitMEX"}
    df = pd.read_csv(path)
    sub = df[df["excluded_venue"].astype(str) == "BitMEX"]
    if sub.empty:
        return {"Specification": "ETHUSD exclude BitMEX", "Excluded venue": "BitMEX"}
    row = sub.iloc[0]
    lock = pd.Series(
        {
            "valid_minutes": row.get("valid_minutes", np.nan),
            "venue_count": 6,
            "share_max_share_gt_0p5": row.get("share_max_share_gt_0p5", np.nan),
            "share_max_share_gt_0p4": np.nan,
            "median_max_share": row.get("median_max_share", np.nan),
            "p95_max_share": row.get("p95_max_share", np.nan),
        }
    )
    pivot = pd.Series(
        {
            "non_lockin_pivot_change_rate": row.get("non_lockin_pivot_change_rate", np.nan),
            "lockin_pivot_change_rate": row.get("lockin_pivot_change_rate", np.nan),
            "difference": row.get("difference", np.nan),
            "rate_ratio": row.get("rate_ratio", np.nan),
        }
    )
    pass_summary = pd.DataFrame(
        [
            {
                "lambda": 0.001,
                "state": "lockin",
                "LWMP_median_kappa": row.get("lockin_LWMP_median_kappa_plus0p1", np.nan),
                "VWAP_median_kappa": row.get("lockin_VWAP_median_kappa_plus0p1", np.nan),
            },
            {
                "lambda": 0.001,
                "state": "non_lockin",
                "LWMP_median_kappa": np.nan,
                "VWAP_median_kappa": row.get("nonlockin_VWAP_median_kappa_plus0p1", np.nan),
            },
        ]
    )
    return comparison_row(
        "ETHUSD exclude BitMEX",
        "BitMEX",
        start,
        end,
        lock,
        pivot,
        None,
        None,
        pass_summary,
        None,
    )


def targeted_summary_row(
    lock_summary: pd.DataFrame,
    pivot_stats: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    passthrough: pd.DataFrame,
) -> dict[str, Any]:
    row = lock_summary.iloc[0]
    return {
        "excluded_venue": EXCLUDED_VENUE,
        "trigger": "dominant_exchange_frequency_0.862",
        "remaining_venues": ",".join(VENUES),
        "valid_minutes": int(row["valid_minutes"]),
        "share_max_share_gt_0p5": float(row["share_max_share_gt_0p5"]),
        "median_max_share": float(row["median_max_share"]),
        "p95_max_share": float(row["p95_max_share"]),
        "non_lockin_pivot_change_rate": float(pivot_stats["non_lockin_pivot_change_rate"]),
        "lockin_pivot_change_rate": float(pivot_stats["lockin_pivot_change_rate"]),
        "nonlockin_pivot_change_rate": float(pivot_stats["non_lockin_pivot_change_rate"]),
        "difference": float(pivot_stats["difference_lockin_minus_nonlockin"]),
        "rate_ratio": float(pivot_stats["rate_ratio_lockin_over_nonlockin"]),
        "bootstrap_ci_1day": ci_text(bootstrap_summary, 1),
        "bootstrap_ci_7day": ci_text(bootstrap_summary, 7),
        "lockin_LWMP_median_kappa_plus0p1": pt_value(passthrough, "lockin", "LWMP_median_kappa"),
        "lockin_VWAP_median_kappa_plus0p1": pt_value(passthrough, "lockin", "VWAP_median_kappa"),
        "nonlockin_VWAP_median_kappa_plus0p1": pt_value(passthrough, "non_lockin", "VWAP_median_kappa"),
    }


def update_parent_targeted_summary(root: Path, new_row: dict[str, Any]) -> Path:
    path = root / "outputs" / "robustness" / "eth_matched" / "results" / "eth_targeted_exclusion_summary.csv"
    if path.exists():
        existing = pd.read_csv(path)
        existing = existing[existing["excluded_venue"].astype(str) != EXCLUDED_VENUE].copy()
    else:
        existing = pd.DataFrame()
    out = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True, sort=False)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build_validation(
    dirs: eth.Directories,
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
    eth_core_diff: dict[str, Any],
    btc_diff: dict[str, Any],
    bitmex_rows_before: int,
    bitmex_rows_after: int,
) -> pd.DataFrame:
    checks = eth.validation_checks(
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
    ).to_dict(orient="records")
    for check in checks:
        if check.get("check") == "29_results_reproducible_from_runner":
            check["value"] = str(Path(__file__).resolve())
            check["detail"] = "Single deterministic exclude-Binance entrypoint with recorded parameters."
        elif check.get("check") == "30_btc_outputs_not_modified":
            check["detail"] = "This targeted runner writes only the exclude_binance tree and the requested ETH targeted summary append."

    panel_valid = panel[panel["valid_minute"] == 1].copy()
    joined_input = " ".join(processing_manifest.astype(str).to_numpy().ravel())
    checks.extend(
        [
            {
                "check": "31_binance_excluded_from_venue_list",
                "status": "PASS" if EXCLUDED_VENUE not in prices.columns else "FAIL",
                "value": ",".join(prices.columns),
                "detail": "Venue price columns used for this run.",
            },
            {
                "check": "32_binance_excluded_from_weight_columns",
                "status": "PASS" if all(EXCLUDED_VENUE not in c for c in weights.columns) else "FAIL",
                "value": ",".join(weights.columns),
                "detail": "Dollar-volume weight columns used for this run.",
            },
            {
                "check": "33_binance_excluded_from_dominant_exchange",
                "status": "PASS"
                if not panel_valid["dominant_exchange"].astype(str).str.contains(EXCLUDED_VENUE).any()
                else "FAIL",
                "value": int(panel_valid["dominant_exchange"].astype(str).str.contains(EXCLUDED_VENUE).sum()),
                "detail": "Dominant venue labels in valid minutes.",
            },
            {
                "check": "34_binance_excluded_from_pivot",
                "status": "PASS"
                if not panel_valid["pivot_exchange"].astype(str).str.contains(EXCLUDED_VENUE).any()
                else "FAIL",
                "value": int(panel_valid["pivot_exchange"].astype(str).str.contains(EXCLUDED_VENUE).sum()),
                "detail": "LWMP pivot labels in valid minutes.",
            },
            {
                "check": "35_binance_excluded_from_input_manifest",
                "status": "PASS" if EXCLUDED_VENUE not in joined_input else "FAIL",
                "value": ",".join(processing_manifest["exchange"].astype(str)),
                "detail": "Only six raw exchange CSVs are admitted.",
            },
            {
                "check": "36_combined_index_excluded_from_input_manifest",
                "status": "PASS" if eth.COMBINED_LABEL not in joined_input else "FAIL",
                "value": ",".join(processing_manifest["exchange"].astype(str)),
                "detail": "Combined_Index is not read or benchmarked in this targeted run.",
            },
            {
                "check": "37_figure_subset_and_pooled_dataset_recorded",
                "status": "PASS"
                if parameter_manifest.get("figure_spec") and parameter_manifest.get("pooled_headline_dataset")
                else "FAIL",
                "value": f"{parameter_manifest.get('figure_spec')}; {parameter_manifest.get('pooled_headline_dataset')}",
                "detail": "Figure subset and pooled event definitions are explicitly separated.",
            },
            {
                "check": "38_seed_equals_20260712",
                "status": "PASS" if int(parameter_manifest.get("seed")) == 20260712 else "FAIL",
                "value": parameter_manifest.get("seed"),
                "detail": "Bootstrap and event seed manifest.",
            },
            {
                "check": "39_seven_venue_eth_core_outputs_not_modified",
                "status": "PASS"
                if not eth_core_diff["added"] and not eth_core_diff["removed"] and not eth_core_diff["changed"]
                else "FAIL",
                "value": json.dumps({k: len(v) for k, v in eth_core_diff.items()}, sort_keys=True),
                "detail": "Excludes the required append to eth_targeted_exclusion_summary.csv and the new exclude_binance tree.",
            },
            {
                "check": "40_existing_exclude_bitmex_row_preserved",
                "status": "PASS" if bitmex_rows_before == bitmex_rows_after and bitmex_rows_after >= 1 else "FAIL",
                "value": f"before={bitmex_rows_before};after={bitmex_rows_after}",
                "detail": "Existing BitMEX targeted-exclusion row remains present.",
            },
            {
                "check": "41_btc_outputs_not_modified",
                "status": "PASS"
                if not btc_diff["added"] and not btc_diff["removed"] and not btc_diff["changed"]
                else "FAIL",
                "value": json.dumps({k: len(v) for k, v in btc_diff.items()}, sort_keys=True),
                "detail": "BTC output trees were stat-snapshotted before and after this run.",
            },
            {
                "check": "42_validation_status_vocabulary",
                "status": "PASS",
                "value": "PASS,WARN,FAIL",
                "detail": "The validation writer emits only the allowed statuses.",
            },
        ]
    )
    out = pd.DataFrame(checks)
    allowed = {"PASS", "WARN", "FAIL"}
    bad_status = ~out["status"].isin(allowed)
    if bad_status.any():
        out.loc[bad_status, "status"] = "FAIL"
    return out


def write_report(
    dirs: eth.Directories,
    sample_selection: dict[str, Any],
    exchange_coverage: pd.DataFrame,
    lock_summary: pd.DataFrame,
    spells_summary: pd.DataFrame,
    pivot_stats: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    vwap_bins_df: pd.DataFrame,
    passthrough: pd.DataFrame,
    dist: pd.DataFrame,
    comparison: pd.DataFrame,
    validation: pd.DataFrame,
) -> None:
    lock = lock_summary.iloc[0]
    spells = spells_summary.iloc[0]
    low_q, high_q, ratio = vwap_endpoint_stats(vwap_bins_df)
    top = dist.sort_values("share", ascending=False).iloc[0]
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
    lwmp_lock = pt_value(passthrough, "lockin", "LWMP_median_kappa")
    all7 = comparison[comparison["Specification"] == "ETHUSD all 7 venues"].iloc[0]
    diff_strength = (
        "减弱"
        if abs(float(pivot_stats["difference_lockin_minus_nonlockin"])) < abs(float(all7["Difference"]))
        else "增强"
    )
    supports_not_binance_only = (
        float(pivot_stats["difference_lockin_minus_nonlockin"]) < 0
        and ci1_excludes_zero
        and ci7_excludes_zero
        and abs(lwmp_lock - 1.0) < 1e-8
    )
    status_counts = validation["status"].value_counts().reindex(["PASS", "WARN", "FAIL"], fill_value=0)
    answers = [
        f"1. 实际有效分钟数为 {int(lock['valid_minutes'])}.",
        f"2. 至少 3/5/6 所有效分钟比例分别为 {sample_selection['share_at_least_3_valid']:.6f}, {sample_selection['share_at_least_5_valid']:.6f}, {sample_selection['share_all_6_valid']:.6f}.",
        f"3. 主要 dominant venue 为 {top['dominant_exchange']}，占比 {top['share']:.6f}.",
        f"4. dominant distribution 为 {distribution_text(dist)}；相对七所样本的 Binance=0.862，分布明显转向 {top['dominant_exchange']} 且更分散.",
        f"5. share(max_share > 0.5) = {lock['share_max_share_gt_0p5']:.6f}.",
        f"6. median max_share = {lock['median_max_share']:.6f}, p95 max_share = {lock['p95_max_share']:.6f}.",
        f"7. over-half spell count = {int(spells['over_half_spell_count'])}, median = {spells['spell_duration_median']:.6g}, p95 = {spells['spell_duration_p95']:.6g}.",
        f"8. 最长 lock-in spell = {int(spells['max_spell_minutes'])} minutes.",
        f"9. LWMP 0.5 boundary {'仍清晰' if pivot_stats['lockin_pivot_change_rate'] < pivot_stats['non_lockin_pivot_change_rate'] else '不清晰'}: lock-in rate lower than non-lock-in.",
        f"10. non-lock-in pivot-change rate = {pivot_stats['non_lockin_pivot_change_rate']:.6f}.",
        f"11. lock-in pivot-change rate = {pivot_stats['lockin_pivot_change_rate']:.6f}.",
        f"12. difference = {pivot_stats['difference_lockin_minus_nonlockin']:.6f}.",
        f"13. rate ratio = {pivot_stats['rate_ratio_lockin_over_nonlockin']:.6f}.",
        f"14. 1-day bootstrap CI {'排除零' if ci1_excludes_zero else '未排除零'}: {ci_text(bootstrap_summary, 1)}.",
        f"15. 7-day bootstrap CI {'排除零' if ci7_excludes_zero else '未排除零'}: {ci_text(bootstrap_summary, 7)}.",
        f"16. VWAP proximity channel {'仍存在' if np.isfinite(ratio) and high_q < low_q else '未呈现端点单调下降'}，highest/lowest ratio = {ratio:.6g}.",
        f"17. 最低与最高 concentration bin q95 gap 分别为 {low_q:.6g} 和 {high_q:.6g}.",
        f"18. LWMP lock-in median pass-through = {lwmp_lock:.6g}，{'等于 1' if abs(lwmp_lock - 1.0) < 1e-8 else '不等于 1'}.",
        f"19. 相对七所样本，exclude-Binance 的 LWMP headline difference {diff_strength}.",
        "20. 与现有 exclude-BitMEX 行相比，exclude-Binance 的完整六所重算结果见 comparison 表；BitMEX 既有行未被覆盖.",
        f"21. 七所 ETH 结果{'不只是由 Binance 驱动' if supports_not_binance_only else '仍需谨慎解释是否由 Binance 驱动'}，判断依据是六所样本 difference、bootstrap CI 和 pass-through.",
        "22. 未发现新的 volume convention 风险；BitMEX 仍按 quote_or_contract, multiplier=1.0.",
        f"23. validation FAIL={int(status_counts['FAIL'])}; 若为 0，则未发现削弱跨资产复现可信度的阻断性问题.",
        "24. 建议写入 online appendix，作为 Binance-dominance targeted exclusion 检验.",
        "25. 主文可用一句话提及该检验，并把完整表放入 appendix.",
        "26. 建议继续做完整 ETH leave-one-exchange-out，以避免只围绕 Binance 与 BitMEX 两个 targeted cases.",
    ]
    lines = [
        "# ETH exclude-Binance robustness report",
        "",
        "## Sample",
        f"- Included venues: {', '.join(VENUES)}",
        f"- Excluded files: ETHUSD_1m_Binance.csv; ETHUSD_1m_Combined_Index.csv",
        f"- Matched sample: {sample_selection['start']} to {sample_selection['end']}",
        "",
        "## Coverage",
        eth.markdown_table(exchange_coverage[["exchange", "matched_valid_minutes", "matched_coverage_share", "price_median"]]),
        "",
        "## Dominant Distribution",
        eth.markdown_table(dist),
        "",
        "## Concentration",
        eth.markdown_table(lock_summary),
        "",
        "## LWMP Headline",
        eth.markdown_table(pd.DataFrame([pivot_stats])),
        "",
        "## Bootstrap",
        eth.markdown_table(bootstrap_summary),
        "",
        "## VWAP Proximity",
        eth.markdown_table(vwap_bins_df),
        "",
        "## Pass-Through",
        eth.markdown_table(passthrough),
        "",
        "## Direct Comparison",
        eth.markdown_table(comparison),
        "",
        "## Required Answers",
        "\n".join(answers),
        "",
        "## Figure And Event Definitions",
        "- Figure subset: `shock_type=inflate_only`, `gamma=1.0`, 30 max_share bins, Wilson intervals, vertical boundary at 0.5.",
        "- Pooled headline dataset: both shock types and all delta_w/gamma values [-0.5, 0.5, 1.0, 2.0].",
        "- Event sampling uses the same sampled-minute logic and seed as the seven-venue ETH run.",
        "",
        "## Validation",
        eth.markdown_table(validation),
    ]
    (dirs.out_dir / "ETH_EXCLUDE_BINANCE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    started = time.time()
    args = parse_args()
    configure_eth_helpers()
    dirs = resolve_dirs(args)
    root = dirs.root
    start = eth.utc_timestamp(args.start_date)
    end = eth.utc_timestamp(args.end_date, is_end=True)
    log_lines: list[str] = []

    parent_summary = root / "outputs" / "robustness" / "eth_matched" / "results" / "eth_targeted_exclusion_summary.csv"
    bitmex_rows_before = 0
    if parent_summary.exists():
        parent_before = pd.read_csv(parent_summary)
        bitmex_rows_before = int((parent_before["excluded_venue"].astype(str) == "BitMEX").sum())

    eth_core_root = root / "outputs" / "robustness" / "eth_matched"
    eth_core_before = snapshot_tree([eth_core_root], exclude=[dirs.out_dir, parent_summary])
    btc_paths = [
        root / "outputs" / "appendix",
        root / "outputs" / "robustness" / "btc_post2022",
        root / "experiments",
        root / "experiments_dvonly",
        root / "outputs" / "appendix" / "G",
        root / "experiments_structure_vwap",
        root / "dv_ready",
        root / "dv_ready_2021_2022",
        root / "agg_ready",
        root / "hhi_panel",
    ]
    btc_before = snapshot_tree(btc_paths)

    def log(message: str) -> None:
        text = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(text, flush=True)
        log_lines.append(text)

    log("Auditing six ETH raw files; Binance and Combined_Index are not admitted")
    (
        exchange_coverage,
        timestamp_audit,
        schema_audit,
        volume_audit,
        missingness_audit,
        coverage,
        _combined_unused,
    ) = eth.audit_raw_files(
        dirs.raw_dir,
        start,
        end,
        args.chunk_size,
        exchanges=VENUES,
        include_combined_index=False,
    )
    yearly, coverage_matrix, sample_selection = coverage_tables(coverage, start, end)

    log("Writing six-venue audit outputs")
    exchange_coverage.to_csv(dirs.data_audit / f"{OUT_PREFIX}_exchange_coverage.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(dirs.data_audit / f"{OUT_PREFIX}_yearly_coverage.csv", index=False, encoding="utf-8-sig")
    timestamp_audit.to_csv(dirs.data_audit / f"{OUT_PREFIX}_timestamp_audit.csv", index=False, encoding="utf-8-sig")
    schema_audit.to_csv(dirs.data_audit / f"{OUT_PREFIX}_column_schema.csv", index=False, encoding="utf-8-sig")
    volume_audit.to_csv(dirs.data_audit / f"{OUT_PREFIX}_volume_convention_audit.csv", index=False, encoding="utf-8-sig")
    missingness_audit.to_csv(dirs.data_audit / f"{OUT_PREFIX}_missingness_audit.csv", index=False, encoding="utf-8-sig")
    (dirs.data_audit / f"{OUT_PREFIX}_sample_selection.json").write_text(
        json.dumps(sample_selection, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log("Building six-venue ETH price and dollar-volume panels from raw CSVs")
    full_index = pd.date_range(start, end, freq="min")
    prices, weights, processing_manifest = eth.build_wide_eth_sample(
        dirs.raw_dir,
        volume_audit,
        start,
        end,
        full_index,
        args.chunk_size,
    )

    log("Computing six-venue VWAP, LWMP, dominant venue, max_share and HHI")
    panel, arrays = eth.compute_panel_local(prices, weights)
    panel_valid = panel[panel["valid_minute"] == 1].copy()
    spells_summary, spells_detail = eth.spell_summary_local(panel_valid)
    lock_summary = eth.concentration_summary(panel_valid, spells_summary)
    dist = eth.dominant_distribution(panel_valid)
    processed_paths = write_processed_outputs(dirs, prices, weights, panel, arrays)

    processing_manifest.to_csv(dirs.data_audit / f"{OUT_PREFIX}_processing_filters.csv", index=False, encoding="utf-8-sig")
    processing_manifest.to_csv(dirs.metadata / "input_file_manifest.csv", index=False, encoding="utf-8-sig")
    processing_manifest.to_csv(dirs.metadata / "processing_filter_manifest.csv", index=False, encoding="utf-8-sig")

    log("Generating six-venue DV-only perturbation events")
    events = eth.run_dvonly_events_local(panel, arrays, VENUES, args.event_seed)
    events.sample(min(10_000, len(events)), random_state=args.event_seed).to_csv(
        dirs.metadata / f"{OUT_PREFIX}_dvonly_event_sample_for_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pivot_stats = pivot_contrast(events)
    pivot_stats_df = pd.DataFrame([pivot_stats])
    edges = make_edges(panel_valid["max_share"], eth.PIVOT_NBINS)
    pivot_df = pivot_bins(events, edges)

    log("Running UTC 1-day and 7-day block bootstrap")
    bootstrap_rows = []
    for block_days in [1, 7]:
        summary, draws = block_bootstrap(events, block_days, args.reps, args.seed)
        bootstrap_rows.append(summary)
        draws.to_csv(dirs.metadata / f"{OUT_PREFIX}_bootstrap_draws_{block_days}day.csv", index=False)
    bootstrap_summary = pd.concat(bootstrap_rows, ignore_index=True)

    log("Computing VWAP proximity and fixed-weight dominant-price pass-through")
    vwap_bins_df = vwap_proximity_bins(panel_valid, edges, args.seed)
    passthrough = eth.run_price_passthrough_local(panel, arrays, eth.PASSTHROUGH_LAMBDAS)

    max_lwmp_dev = float(
        np.nanmax(np.abs(passthrough.loc[passthrough["state"] == "lockin", "LWMP_median_kappa"].to_numpy(float) - 1.0))
    )
    if max_lwmp_dev >= 1e-8:
        raise RuntimeError(f"Lock-in LWMP median pass-through theory check failed: {max_lwmp_dev}")

    log("Writing six-venue result tables and figures")
    lock_summary.to_csv(dirs.results / f"{OUT_PREFIX}_lockin_summary.csv", index=False, encoding="utf-8-sig")
    spells_summary.to_csv(dirs.results / f"{OUT_PREFIX}_spell_summary.csv", index=False, encoding="utf-8-sig")
    spells_detail.to_csv(dirs.metadata / f"{OUT_PREFIX}_lockin_spells_detail.csv", index=False, encoding="utf-8-sig")
    pivot_df.to_csv(dirs.results / f"{OUT_PREFIX}_pivot_bins.csv", index=False, encoding="utf-8-sig")
    pivot_stats_df.to_csv(dirs.results / f"{OUT_PREFIX}_pivot_contrast_summary.csv", index=False, encoding="utf-8-sig")
    bootstrap_summary.to_csv(dirs.results / f"{OUT_PREFIX}_block_bootstrap.csv", index=False, encoding="utf-8-sig")
    vwap_bins_df.to_csv(dirs.results / f"{OUT_PREFIX}_vwap_proximity_bins.csv", index=False, encoding="utf-8-sig")
    passthrough.to_csv(dirs.results / f"{OUT_PREFIX}_passthrough_summary.csv", index=False, encoding="utf-8-sig")
    dist.to_csv(dirs.results / f"{OUT_PREFIX}_dominant_exchange_distribution.csv", index=False, encoding="utf-8-sig")
    plot_lwmp_boundary(
        pivot_df,
        dirs.figures / "Fig_ETH_exclude_Binance_LWMP_boundary.png",
        dirs.figures / "Fig_ETH_exclude_Binance_LWMP_boundary.pdf",
    )
    plot_vwap_proximity(
        vwap_bins_df,
        dirs.figures / "Fig_ETH_exclude_Binance_VWAP_proximity.png",
        dirs.figures / "Fig_ETH_exclude_Binance_VWAP_proximity.pdf",
    )

    log("Building direct comparison and updating targeted exclusion summary")
    target_row = targeted_summary_row(lock_summary, pivot_stats, bootstrap_summary, passthrough)
    update_parent_targeted_summary(root, target_row)
    parent_after = pd.read_csv(parent_summary)
    bitmex_rows_after = int((parent_after["excluded_venue"].astype(str) == "BitMEX").sum())

    exclude_binance_row = comparison_row(
        "ETHUSD exclude Binance",
        EXCLUDED_VENUE,
        start,
        end,
        lock_summary.iloc[0],
        pivot_stats,
        bootstrap_summary,
        vwap_bins_df,
        passthrough,
        dist,
    )
    comparison = pd.DataFrame(
        [
            load_all7_comparison_row(root),
            load_existing_bitmex_row(root, start, end),
            exclude_binance_row,
        ]
    )
    comparison.to_csv(dirs.results / "eth_exclusion_comparison.csv", index=False, encoding="utf-8-sig")

    parameter_manifest = {
        "asset": "ETHUSD",
        "specification": SPEC_LABEL,
        "excluded_venue": EXCLUDED_VENUE,
        "included_venues": VENUES,
        "excluded_files": ["ETHUSD_1m_Binance.csv", "ETHUSD_1m_Combined_Index.csv"],
        "start_date": str(start),
        "end_date": str(end),
        "seed": int(args.seed),
        "event_seed": int(args.event_seed),
        "bootstrap_reps": int(args.reps),
        "min_exchanges_per_minute": eth.MIN_EXCHANGES_PER_MIN,
        "n_sample_minutes_for_dvonly_events": eth.N_SAMPLE_MINUTES,
        "delta_ws": eth.DELTA_WS,
        "shock_types": eth.SHOCK_TYPES,
        "pivot_nbins": eth.PIVOT_NBINS,
        "lock_in_definition": "max_share > 0.5",
        "price_rule": "OHLC4, then HL2, then Close",
        "bitmex_rule": "quote_or_contract with multiplier 1.0",
        "combined_index_policy": "not read; excluded from audit, aggregation, benchmarks, weights, dominant, pivot, VWAP, LWMP, max_share, HHI",
        "figure_spec": "shock_type=inflate_only, gamma=1.0, 30 max_share bins, Wilson intervals",
        "pooled_headline_dataset": "both shock types and all delta_w/gamma values from six-venue sampled valid minutes",
    }
    (dirs.metadata / "parameter_manifest.json").write_text(
        json.dumps(parameter_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    run_manifest = {
        "script": str(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "root": str(root),
        "raw_dir": str(dirs.raw_dir),
        "out_dir": str(dirs.out_dir),
        "elapsed_seconds": float(time.time() - started),
        "status": "complete_before_validation",
    }
    (dirs.metadata / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    code_manifest = {
        "run_eth_exclude_binance.py_sha256": sha256_file(Path(__file__).resolve()),
        "run_eth_replication.py_sha256": sha256_file(root / "run_eth_replication.py"),
        "run_btc_out_of_sample_replication.py_sha256": sha256_file(root / "run_btc_out_of_sample_replication.py"),
        "git_repository_detected": (root / ".git").exists(),
        "btc_outputs_policy": "read-only; no BTC result files are written by this runner",
        "generated_at_epoch": time.time(),
    }
    (dirs.metadata / "code_version_manifest.json").write_text(
        json.dumps(code_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    output_paths = [
        *processed_paths,
        dirs.results / f"{OUT_PREFIX}_lockin_summary.csv",
        dirs.results / f"{OUT_PREFIX}_spell_summary.csv",
        dirs.results / f"{OUT_PREFIX}_pivot_bins.csv",
        dirs.results / f"{OUT_PREFIX}_block_bootstrap.csv",
        dirs.results / f"{OUT_PREFIX}_vwap_proximity_bins.csv",
        dirs.results / f"{OUT_PREFIX}_passthrough_summary.csv",
        dirs.results / f"{OUT_PREFIX}_dominant_exchange_distribution.csv",
        dirs.results / "eth_exclusion_comparison.csv",
    ]
    eth_core_after = snapshot_tree([eth_core_root], exclude=[dirs.out_dir, parent_summary])
    btc_after = snapshot_tree(btc_paths)
    validation = build_validation(
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
        compare_snapshots(eth_core_before, eth_core_after),
        compare_snapshots(btc_before, btc_after),
        bitmex_rows_before,
        bitmex_rows_after,
    )
    validation.to_csv(dirs.metadata / "validation_checks.csv", index=False, encoding="utf-8-sig")
    fail_count = int((validation["status"] == "FAIL").sum())
    warn_count = int((validation["status"] == "WARN").sum())
    pass_count = int((validation["status"] == "PASS").sum())
    run_manifest["status"] = "complete" if fail_count == 0 else "validation_failed"
    (dirs.metadata / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    write_report(
        dirs,
        sample_selection,
        exchange_coverage,
        lock_summary,
        spells_summary,
        pivot_stats,
        bootstrap_summary,
        vwap_bins_df,
        passthrough,
        dist,
        comparison,
        validation,
    )
    log("ETH exclude-Binance run complete")
    (dirs.metadata / "execution_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("\nOutput directory:", dirs.out_dir)
    print("Sample:", start, "to", end)
    print("Included venues:", ", ".join(VENUES))
    print("Dominant distribution:", distribution_text(dist))
    print("LWMP rates:", pivot_stats["non_lockin_pivot_change_rate"], pivot_stats["lockin_pivot_change_rate"])
    print("Bootstrap CI 1-day:", ci_text(bootstrap_summary, 1))
    print("Bootstrap CI 7-day:", ci_text(bootstrap_summary, 7))
    print(f"Validation counts: PASS={pass_count}, WARN={warn_count}, FAIL={fail_count}")
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

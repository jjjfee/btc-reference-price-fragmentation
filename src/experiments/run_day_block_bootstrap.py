#!/usr/bin/env python3
"""Dependence-robust inference for the LWMP pivot-change contrast.

The script resamples UTC time blocks and keeps every event within a selected block
together. This preserves serial dependence within blocks and dependence across
multiple perturbations attached to the same minute.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


TIMESTAMP_CANDIDATES = (
    "time_utc_dt",
    "time_utc",
    "timestamp",
    "datetime",
    "date_time",
)

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_RELATIVE_PATHS = (
    Path("experiments_dvonly") / "audit_lockin" / "dvonly_inference_dataset.csv",
    Path("experiments_dvonly") / "audit_lockin" / "dvonly_event_merged_for_audit.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UTC-day or multi-day block bootstrap for pivot-change rates."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=None,
        help="Optional CSV or Parquet event-level file; known project paths are used by default",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root (default: repository root inferred from this script)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory; defaults to the project's paper inference directory",
    )
    parser.add_argument("--timestamp-col", default=None)
    parser.add_argument("--outcome-col", default="pivot_changed")
    parser.add_argument("--lock-col", default="lock_in")
    parser.add_argument("--share-col", default="max_share")
    parser.add_argument("--shock-type", default=None)
    parser.add_argument("--delta-w", type=float, default=None)
    parser.add_argument("--block-days", type=int, default=1)
    parser.add_argument("--reps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260710)
    return parser.parse_args()


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.input is not None:
        input_path = args.input.expanduser()
        if not input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {input_path}")
    else:
        candidates = [args.root / relative for relative in DEFAULT_INPUT_RELATIVE_PATHS]
        input_path = next((path for path in candidates if path.is_file()), None)
        if input_path is None:
            checked = "\n  - ".join(str(path) for path in candidates)
            raise FileNotFoundError(
                "No default inference dataset was found. Checked:\n"
                f"  - {checked}\n"
                "Supply an explicit input path or override the project location with --root."
            )

    if args.out_dir is None:
        output_path = (
            args.root
            / "outputs"
            / "robustness"
            / f"bootstrap_{args.block_days}day"
        )
    else:
        output_path = args.out_dir.expanduser()
    return input_path, output_path


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError("Input must be .csv, .parquet, or .pq")


def resolve_timestamp_column(frame: pd.DataFrame, requested: str | None) -> str:
    if requested:
        if requested not in frame.columns:
            raise KeyError(f"Timestamp column not found: {requested}")
        return requested
    for name in TIMESTAMP_CANDIDATES:
        if name in frame.columns:
            return name
    raise KeyError(
        "No timestamp column found. Use --timestamp-col. "
        f"Tried: {', '.join(TIMESTAMP_CANDIDATES)}"
    )


def prepare_frame(frame: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    timestamp_col = resolve_timestamp_column(frame, args.timestamp_col)
    required = {timestamp_col, args.outcome_col}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    if args.shock_type is not None:
        if "shock_type" not in frame.columns:
            raise KeyError("--shock-type requires a shock_type column")
        frame = frame.loc[frame["shock_type"].astype(str) == args.shock_type].copy()

    if args.delta_w is not None:
        if "delta_w" not in frame.columns:
            raise KeyError("--delta-w requires a delta_w column")
        delta = pd.to_numeric(frame["delta_w"], errors="coerce")
        frame = frame.loc[np.isclose(delta, args.delta_w, rtol=0, atol=1e-12)].copy()

    frame["_time"] = pd.to_datetime(frame[timestamp_col], utc=True, errors="coerce")
    frame["_outcome"] = pd.to_numeric(frame[args.outcome_col], errors="coerce")

    if args.lock_col in frame.columns:
        frame["_lock"] = pd.to_numeric(frame[args.lock_col], errors="coerce")
    else:
        if args.share_col not in frame.columns:
            raise KeyError(
                f"Neither {args.lock_col!r} nor {args.share_col!r} is available to define lock-in"
            )
        share = pd.to_numeric(frame[args.share_col], errors="coerce")
        frame["_lock"] = (share > 0.5).astype(float)

    frame = frame.dropna(subset=["_time", "_outcome", "_lock"])
    frame = frame.loc[frame["_outcome"].isin([0, 1]) & frame["_lock"].isin([0, 1])].copy()
    if frame.empty:
        raise ValueError("No valid observations remain after filtering")

    origin = frame["_time"].dt.floor("D").min()
    day_number = (frame["_time"].dt.floor("D") - origin).dt.days
    frame["_block"] = (day_number // args.block_days).astype(int)
    return frame, timestamp_col


def block_totals(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        frame.groupby(["_block", "_lock"], observed=True)["_outcome"]
        .agg(["sum", "count"])
        .reset_index()
    )
    blocks = np.sort(frame["_block"].unique())
    index = pd.MultiIndex.from_product([blocks, [0.0, 1.0]], names=["_block", "_lock"])
    grouped = grouped.set_index(["_block", "_lock"]).reindex(index, fill_value=0).reset_index()
    return grouped


def point_estimates(frame: pd.DataFrame) -> dict[str, float | int]:
    result: dict[str, float | int] = {"n_events": int(len(frame))}
    rates = frame.groupby("_lock", observed=True)["_outcome"].agg(["mean", "count"])
    for lock in (0.0, 1.0):
        if lock not in rates.index:
            raise ValueError("Both lock-in states must be present")
        label = int(lock)
        result[f"rate_lock_{label}"] = float(rates.loc[lock, "mean"])
        result[f"n_lock_{label}"] = int(rates.loc[lock, "count"])
    result["difference_lock_minus_nonlock"] = (
        result["rate_lock_1"] - result["rate_lock_0"]
    )
    result["ratio_lock_over_nonlock"] = result["rate_lock_1"] / result["rate_lock_0"]
    result["n_blocks"] = int(frame["_block"].nunique())
    return result


def bootstrap(frame: pd.DataFrame, reps: int, seed: int) -> pd.DataFrame:
    totals = block_totals(frame)
    blocks = np.sort(totals["_block"].unique())
    n_blocks = len(blocks)

    sums = np.zeros((n_blocks, 2), dtype=float)
    counts = np.zeros((n_blocks, 2), dtype=float)
    block_to_pos = {block: pos for pos, block in enumerate(blocks)}
    for block, lock_value, outcome_sum, outcome_count in totals.itertuples(index=False, name=None):
        pos = block_to_pos[block]
        lock = int(lock_value)
        sums[pos, lock] = outcome_sum
        counts[pos, lock] = outcome_count

    rng = np.random.default_rng(seed)
    records = []
    for rep in range(reps):
        draw = rng.integers(0, n_blocks, size=n_blocks)
        sampled_sums = sums[draw].sum(axis=0)
        sampled_counts = counts[draw].sum(axis=0)
        if np.any(sampled_counts == 0):
            continue
        rates = sampled_sums / sampled_counts
        records.append(
            {
                "rep": rep,
                "rate_nonlock": rates[0],
                "rate_lock": rates[1],
                "difference_lock_minus_nonlock": rates[1] - rates[0],
                "ratio_lock_over_nonlock": rates[1] / rates[0],
            }
        )
    if not records:
        raise RuntimeError("All bootstrap draws were invalid")
    return pd.DataFrame.from_records(records)


def summarize_draws(draws: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in (
        "rate_nonlock",
        "rate_lock",
        "difference_lock_minus_nonlock",
        "ratio_lock_over_nonlock",
    ):
        values = draws[column].to_numpy()
        rows.append(
            {
                "statistic": column,
                "bootstrap_mean": float(np.mean(values)),
                "bootstrap_se": float(np.std(values, ddof=1)),
                "ci95_low": float(np.quantile(values, 0.025)),
                "ci95_high": float(np.quantile(values, 0.975)),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    if args.block_days < 1:
        raise ValueError("--block-days must be at least 1")
    if args.reps < 100:
        raise ValueError("--reps must be at least 100")

    args.input, args.out_dir = resolve_paths(args)

    frame = load_frame(args.input)
    frame, timestamp_col = prepare_frame(frame, args)
    point = point_estimates(frame)
    draws = bootstrap(frame, args.reps, args.seed)
    summary = summarize_draws(draws)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    draws.to_csv(args.out_dir / "bootstrap_draws.csv", index=False)
    summary.to_csv(args.out_dir / "bootstrap_summary.csv", index=False)

    run_info = {
        "input": str(args.input.resolve()),
        "timestamp_col": timestamp_col,
        "outcome_col": args.outcome_col,
        "lock_col": args.lock_col if args.lock_col in frame.columns else None,
        "share_col": args.share_col,
        "shock_type": args.shock_type,
        "delta_w": args.delta_w,
        "block_days": args.block_days,
        "reps_requested": args.reps,
        "reps_completed": int(len(draws)),
        "seed": args.seed,
        "point_estimates": point,
    }
    (args.out_dir / "run_info.json").write_text(
        json.dumps(run_info, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps(run_info, indent=2, ensure_ascii=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

# make_vwap_degradation_bins_maxshare.py
# ============================================================
# INPUTS:
#   1) experiments_dvonly/dvon_injection_shift_samples.csv
#   2) hhi_panel/btc_1m_panel_with_hhi.csv
#   (optional) experiments_dvonly/pivot_boundary_curve_edges_maxshare.csv  # reuse edges for mirror narrative
#
# OUTPUTS (written to experiments_dvonly/vwap_degradation/):
#   1) vwap_degradation_curve_bins_maxshare_delta1p0.csv
#   2) vwap_degradation_curve_edges_maxshare.csv
#   3) vwap_degradation_runinfo_maxshare_delta1p0.txt
#   4) Fig_vwap_degradation_q95abs_by_maxshare_delta1p0.png
# ============================================================

from __future__ import annotations

from pathlib import Path
import os
import sys
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# -----------------------------
# USER CONFIG
# -----------------------------
ROOT = Path(__file__).resolve().parents[2]

DVON_FILE = ROOT / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
PANEL_FILE = ROOT / "hhi_panel" / "btc_1m_panel_with_hhi.csv"

# If you want to strictly reuse your LWMP boundary edges, keep this on.
# If this file does not exist or cannot be parsed, the script will fall back to computing edges from panel.
EDGES_FILE_CANDIDATE = ROOT / "experiments_dvonly" / "pivot_boundary_curve_edges_maxshare.csv"

OUT_DIR = ROOT / "experiments_dvonly" / "vwap_degradation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Filters
DELTA_W_TARGET = 1.0
SHOCK_TYPE_KEEP = None  # e.g. "reallocate_total_fixed" or "inflate_only" or None for both

# Binning
NBINS = 30
MIN_N_PER_BIN = 200  # bins with too few obs -> CI unstable; mark as NaN
USE_EXISTING_EDGES_IF_POSSIBLE = True

# Y definition
USE_ABS_SHIFT = True
Q_LEVEL = 0.95  # p95 tail of |shift_vwap|

# Bootstrap CI for continuous quantile
BOOTSTRAP_B = 500
BOOTSTRAP_CI = (0.025, 0.975)
MAX_N_FOR_BOOTSTRAP = 20000  # speed cap per bin (subsample without replacement first)
RANDOM_SEED = 42

# Plot
FIG_NAME = "Fig_vwap_degradation_q95abs_by_maxshare_delta1p0.png"
DPI = 200


# -----------------------------
# Helpers
# -----------------------------
def _parse_time_utc(s: pd.Series) -> pd.Series:
    """Parse to UTC pandas Timestamp floored to minute."""
    # dvon time_utc is typically a string; panel time_utc_dt may be timestamp-like.
    t = pd.to_datetime(s, utc=True, errors="coerce")
    return t.dt.floor("min")


def _load_edges(edges_path: Path) -> np.ndarray:
    """
    Try to load edges from a CSV with unknown schema.
    Accepts common formats:
      - single column named 'edge' or similar
      - columns 'bin_left'/'bin_right' (we reconstruct unique sorted edges)
      - any numeric column (first numeric column)
    """
    df = pd.read_csv(edges_path)
    # Case 1: 'edge' column
    for col in ["edge", "edges", "bin_edge", "cut", "x_edge"]:
        if col in df.columns:
            arr = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy()
            arr = np.unique(arr)
            arr.sort()
            if len(arr) >= 3:
                return arr

    # Case 2: left/right columns
    left_cols = [c for c in df.columns if "left" in c.lower()]
    right_cols = [c for c in df.columns if "right" in c.lower()]
    if left_cols and right_cols:
        left = pd.to_numeric(df[left_cols[0]], errors="coerce").dropna().to_numpy()
        right = pd.to_numeric(df[right_cols[0]], errors="coerce").dropna().to_numpy()
        arr = np.unique(np.concatenate([left, right]))
        arr.sort()
        if len(arr) >= 3:
            return arr

    # Case 3: first numeric column
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if num_cols:
        arr = df[num_cols[0]].dropna().to_numpy()
        arr = np.unique(arr)
        arr.sort()
        if len(arr) >= 3:
            return arr

    raise ValueError(f"Cannot parse edges from: {edges_path}")


def _compute_edges_from_panel(panel_x: pd.Series, nbins: int) -> np.ndarray:
    """Compute quantile edges from panel distribution (not from event sample)."""
    x = pd.to_numeric(panel_x, errors="coerce").dropna().to_numpy()
    if x.size == 0:
        raise ValueError("Panel max_share is empty after cleaning.")
    qs = np.linspace(0.0, 1.0, nbins + 1)
    edges = np.quantile(x, qs)
    edges = np.unique(edges)
    edges.sort()
    if len(edges) < 3:
        raise ValueError("Computed edges are degenerate (too many duplicate quantiles).")
    return edges


def _bootstrap_quantile_ci(
    data: np.ndarray,
    q: float,
    b: int,
    ci: tuple[float, float],
    rng: np.random.Generator,
    max_n: int
) -> tuple[float, float, float]:
    """
    Returns (q_hat, ci_low, ci_high) using percentile bootstrap:
      - optionally subsample to max_n for speed
      - resample with replacement within the (sub)sample
    """
    data = data[np.isfinite(data)]
    n0 = data.size
    if n0 == 0:
        return (np.nan, np.nan, np.nan)

    if n0 > max_n:
        idx = rng.choice(n0, size=max_n, replace=False)
        data = data[idx]

    q_hat = float(np.quantile(data, q))
    n = data.size

    stats = np.empty(b, dtype=float)
    for i in range(b):
        samp_idx = rng.choice(n, size=n, replace=True)
        stats[i] = np.quantile(data[samp_idx], q)

    lo = float(np.quantile(stats, ci[0]))
    hi = float(np.quantile(stats, ci[1]))
    return (q_hat, lo, hi)


def _safe_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    t0 = time.time()
    rng = np.random.default_rng(RANDOM_SEED)

    # --- load dv-only events ---
    if not DVON_FILE.exists():
        print(f"[ERROR] Missing dvon file: {DVON_FILE}")
        return 1
    dvon = pd.read_csv(DVON_FILE)

    required_dvon = ["time_utc", "delta_w", "shift_vwap"]
    for c in required_dvon:
        if c not in dvon.columns:
            print(f"[ERROR] dvon file missing column: {c}")
            print(f"        columns={list(dvon.columns)}")
            return 1

    dvon["time_utc_dt"] = _parse_time_utc(dvon["time_utc"])
    dvon = dvon.dropna(subset=["time_utc_dt"])

    # filter delta_w
    dvon = dvon[pd.to_numeric(dvon["delta_w"], errors="coerce") == DELTA_W_TARGET].copy()

    # optional filter shock_type
    if SHOCK_TYPE_KEEP is not None:
        if "shock_type" not in dvon.columns:
            print("[ERROR] SHOCK_TYPE_KEEP is set but dvon has no 'shock_type' column.")
            return 1
        dvon = dvon[dvon["shock_type"] == SHOCK_TYPE_KEEP].copy()

    # clean shift_vwap
    dvon["shift_vwap"] = pd.to_numeric(dvon["shift_vwap"], errors="coerce")
    dvon = dvon.replace([np.inf, -np.inf], np.nan).dropna(subset=["shift_vwap"]).copy()

    if dvon.empty:
        print("[ERROR] No dvon rows left after filters (delta_w/shock_type/shift_vwap).")
        return 1

    # --- load panel ---
    if not PANEL_FILE.exists():
        print(f"[ERROR] Missing panel file: {PANEL_FILE}")
        return 1
    panel = pd.read_csv(PANEL_FILE)

    # time column in panel
    if "time_utc_dt" in panel.columns:
        panel["time_utc_dt"] = _parse_time_utc(panel["time_utc_dt"])
    elif "time_utc" in panel.columns:
        panel["time_utc_dt"] = _parse_time_utc(panel["time_utc"])
    else:
        print("[ERROR] panel file missing time column (need 'time_utc_dt' or 'time_utc').")
        print(f"        columns={list(panel.columns)}")
        return 1

    if "max_share" not in panel.columns:
        print("[ERROR] panel file missing 'max_share'.")
        print(f"        columns={list(panel.columns)}")
        return 1

    panel["max_share"] = pd.to_numeric(panel["max_share"], errors="coerce")
    panel = panel.dropna(subset=["time_utc_dt", "max_share"]).copy()

    # --- merge on minute UTC ---
    merged = dvon.merge(panel[["time_utc_dt", "max_share"]], on="time_utc_dt", how="left")
    before = len(dvon)
    after = merged["max_share"].notna().sum()
    merge_rate = after / max(before, 1)

    merged = merged.dropna(subset=["max_share"]).copy()
    merged = merged[(merged["max_share"] >= 0) & (merged["max_share"] <= 1)].copy()

    if merged.empty:
        print("[ERROR] No rows after merging dvon with panel on time_utc_dt.")
        return 1

    # --- define y ---
    if USE_ABS_SHIFT:
        merged["y"] = merged["shift_vwap"].abs()
    else:
        merged["y"] = merged["shift_vwap"]

    # --- edges ---
    edges_used = None
    edges_source = None
    if USE_EXISTING_EDGES_IF_POSSIBLE and EDGES_FILE_CANDIDATE.exists():
        try:
            edges_used = _load_edges(EDGES_FILE_CANDIDATE)
            edges_source = f"existing:{EDGES_FILE_CANDIDATE.name}"
        except Exception as e:
            edges_used = None
            edges_source = f"failed_existing:{e}"

    if edges_used is None:
        edges_used = _compute_edges_from_panel(panel["max_share"], NBINS)
        edges_source = "computed_from_panel_quantiles"

    # ensure edges cover data range
    # if not, extend slightly
    minx, maxx = float(merged["max_share"].min()), float(merged["max_share"].max())
    if minx < edges_used[0]:
        edges_used[0] = minx
    if maxx > edges_used[-1]:
        edges_used[-1] = maxx

    # --- binning ---
    merged["bin"] = pd.cut(
        merged["max_share"],
        bins=edges_used,
        include_lowest=True,
        right=False
    )

    # prepare bin table
    bins = []
    for i, interval in enumerate(merged["bin"].cat.categories):
        g = merged[merged["bin"] == interval]
        n = len(g)
        x_left = float(interval.left)
        x_right = float(interval.right)
        x_center = 0.5 * (x_left + x_right)

        if n < MIN_N_PER_BIN:
            bins.append({
                "bin_id": i,
                "x_left": x_left,
                "x_right": x_right,
                "x_center": x_center,
                "n": n,
                "y_q": np.nan,
                "ci_low": np.nan,
                "ci_high": np.nan,
                "y_median": float(np.nanmedian(g["y"])) if n > 0 else np.nan
            })
            continue

        arr = g["y"].to_numpy(dtype=float)
        q_hat, lo, hi = _bootstrap_quantile_ci(
            data=arr,
            q=Q_LEVEL,
            b=BOOTSTRAP_B,
            ci=BOOTSTRAP_CI,
            rng=rng,
            max_n=MAX_N_FOR_BOOTSTRAP
        )

        bins.append({
            "bin_id": i,
            "x_left": x_left,
            "x_right": x_right,
            "x_center": x_center,
            "n": n,
            "y_q": q_hat,
            "ci_low": lo,
            "ci_high": hi,
            "y_median": float(np.median(arr))
        })

    bins_df = pd.DataFrame(bins)

    # --- write outputs ---
    edges_out = OUT_DIR / "vwap_degradation_curve_edges_maxshare.csv"
    bins_out = OUT_DIR / "vwap_degradation_curve_bins_maxshare_delta1p0.csv"
    runinfo_out = OUT_DIR / "vwap_degradation_runinfo_maxshare_delta1p0.txt"
    fig_out = OUT_DIR / FIG_NAME

    # edges CSV (simple, single column)
    _safe_write_csv(pd.DataFrame({"edge": edges_used}), edges_out)
    _safe_write_csv(bins_df, bins_out)

    # runinfo txt
    with open(runinfo_out, "w", encoding="utf-8") as f:
        f.write("VWAP continuous degradation (DV-only)\n")
        f.write(f"ROOT={ROOT}\n")
        f.write(f"DVON_FILE={DVON_FILE}\n")
        f.write(f"PANEL_FILE={PANEL_FILE}\n")
        f.write(f"EDGES_SOURCE={edges_source}\n")
        f.write(f"DELTA_W_TARGET={DELTA_W_TARGET}\n")
        f.write(f"SHOCK_TYPE_KEEP={SHOCK_TYPE_KEEP}\n")
        f.write(f"USE_ABS_SHIFT={USE_ABS_SHIFT}\n")
        f.write(f"Q_LEVEL={Q_LEVEL}\n")
        f.write(f"NBINS={NBINS}\n")
        f.write(f"MIN_N_PER_BIN={MIN_N_PER_BIN}\n")
        f.write(f"BOOTSTRAP_B={BOOTSTRAP_B}\n")
        f.write(f"BOOTSTRAP_CI={BOOTSTRAP_CI}\n")
        f.write(f"MAX_N_FOR_BOOTSTRAP={MAX_N_FOR_BOOTSTRAP}\n")
        f.write(f"DVON_ROWS_AFTER_FILTER={len(dvon)}\n")
        f.write(f"MERGED_ROWS={len(merged)}\n")
        f.write(f"MERGE_RATE(max_share notna)={merge_rate:.6f}\n")
        f.write(f"RANDOM_SEED={RANDOM_SEED}\n")
        f.write(f"Elapsed_sec={time.time()-t0:.2f}\n")

    # --- plot ---
    plot_df = bins_df.dropna(subset=["y_q", "ci_low", "ci_high"]).copy()
    if plot_df.empty:
        print("[WARN] No bins with valid y_q and CI (check MIN_N_PER_BIN or data size).")
    else:
        plt.figure()
        plt.plot(plot_df["x_center"], plot_df["y_q"])
        plt.fill_between(plot_df["x_center"], plot_df["ci_low"], plot_df["ci_high"], alpha=0.25)
        plt.xlabel("max_share (binned)")
        plt.ylabel(f"q{int(Q_LEVEL*100)}(|shift_vwap|)")
        title = f"VWAP tail exposure vs concentration (delta_w={DELTA_W_TARGET})"
        if SHOCK_TYPE_KEEP is not None:
            title += f", shock_type={SHOCK_TYPE_KEEP}"
        plt.title(title)
        plt.tight_layout()
        plt.savefig(fig_out, dpi=DPI)
        plt.close()

    print("[OK] Done.")
    print(f"  bins:   {bins_out}")
    print(f"  edges:  {edges_out}")
    print(f"  runinfo:{runinfo_out}")
    print(f"  figure: {fig_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

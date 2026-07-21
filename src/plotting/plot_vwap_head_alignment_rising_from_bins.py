# plot_vwap_head_alignment_rising_from_bins.py
# ============================================================
# PURPOSE
#   Convert the existing "descending gap" plot into an exact
#   "rising alignment" mirror plot.
#
# MATHEMATICAL MAPPING
#   gap_t        = |P_vwap_DV - p_dom| / P_vwap_DV
#   alignment_t  = 1 - gap_t
#
#   Previous plot used:
#       q95(gap)
#
#   Exact rising mirror should use:
#       1 - q95(gap) = q05(alignment)
#
#   Therefore:
#       alignment_floor      = 1 - q95_rel_gap_dom
#       alignment_ci_low     = 1 - old_ci_high
#       alignment_ci_high    = 1 - old_ci_low
#
# INPUT
#   <PROJECT_ROOT>\experiments_structure_vwap\vwap_head_proximity_bins_maxshare.csv
#
# OUTPUTS
#   <PROJECT_ROOT>\experiments_structure_vwap\
#       - vwap_head_alignment_bins_maxshare.csv
#       - vwap_head_alignment_runinfo_maxshare.txt
#       - Fig_vwap_head_alignment_floor_by_maxshare.png
#
# INTERPRETATION
#   Higher values mean stronger alignment of VWAP with the dominant venue.
#   This is the exact upward mirror of the previous q95(relative gap) plot.
# ============================================================

from __future__ import annotations

from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick


# -----------------------------
# USER CONFIG
# -----------------------------
ROOT = Path(__file__).resolve().parents[2]
IN_DIR = ROOT / "experiments_structure_vwap"

BINS_IN = IN_DIR / "vwap_head_proximity_bins_maxshare.csv"

OUT_BINS = IN_DIR / "vwap_head_alignment_bins_maxshare.csv"
OUT_RUNINFO = IN_DIR / "vwap_head_alignment_runinfo_maxshare.txt"
OUT_FIG = IN_DIR / "Fig_vwap_head_alignment_floor_by_maxshare.png"

DPI = 200


def main() -> int:
    t0 = time.time()

    if not BINS_IN.exists():
        print(f"[ERROR] Missing input file: {BINS_IN}")
        return 1

    df = pd.read_csv(BINS_IN)

    required_cols = [
        "x_center",
        "x_left",
        "x_right",
        "n",
        "q95_rel_gap_dom",
        "ci_low",
        "ci_high",
        "median_rel_gap_dom",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[ERROR] Missing columns in input bins file: {missing}")
        print(f"Available columns: {list(df.columns)}")
        return 1

    # numeric cleanup
    num_cols = ["x_center", "x_left", "x_right", "n",
                "q95_rel_gap_dom", "ci_low", "ci_high", "median_rel_gap_dom"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # --------------------------------------------------------
    # Exact upward mirror:
    # old: q95(gap)
    # new: 1 - q95(gap) = q05(alignment)
    # --------------------------------------------------------
    df["q05_alignment"] = 1.0 - df["q95_rel_gap_dom"]
    df["alignment_ci_low"] = 1.0 - df["ci_high"]
    df["alignment_ci_high"] = 1.0 - df["ci_low"]

    # optional: median alignment (not exact mirror, but useful reference)
    df["median_alignment"] = 1.0 - df["median_rel_gap_dom"]

    # percent scale for readability
    df["q05_alignment_pct"] = df["q05_alignment"] * 100.0
    df["alignment_ci_low_pct"] = df["alignment_ci_low"] * 100.0
    df["alignment_ci_high_pct"] = df["alignment_ci_high"] * 100.0
    df["median_alignment_pct"] = df["median_alignment"] * 100.0

    # keep output tidy
    out_cols = [
        "x_left", "x_right", "x_center", "n",
        "q95_rel_gap_dom", "ci_low", "ci_high", "median_rel_gap_dom",
        "q05_alignment", "alignment_ci_low", "alignment_ci_high", "median_alignment",
        "q05_alignment_pct", "alignment_ci_low_pct", "alignment_ci_high_pct", "median_alignment_pct"
    ]
    out_df = df[out_cols].copy()
    out_df.to_csv(OUT_BINS, index=False, encoding="utf-8-sig")

    # runinfo
    with open(OUT_RUNINFO, "w", encoding="utf-8") as f:
        f.write("VWAP head alignment (rising mirror from existing bins)\n")
        f.write(f"INPUT_BINS={BINS_IN}\n")
        f.write("Transformation:\n")
        f.write("  gap_t = |P_vwap_DV - p_dom| / P_vwap_DV\n")
        f.write("  alignment_t = 1 - gap_t\n")
        f.write("  q05_alignment = 1 - q95_rel_gap_dom\n")
        f.write("  alignment_ci_low = 1 - old_ci_high\n")
        f.write("  alignment_ci_high = 1 - old_ci_low\n")
        f.write("Scale shown in figure: percent\n")
        f.write(f"N_ROWS={len(out_df)}\n")
        f.write(f"Elapsed_sec={time.time()-t0:.2f}\n")

    # plot
    plot_df = out_df.dropna(subset=["x_center", "q05_alignment_pct", "alignment_ci_low_pct", "alignment_ci_high_pct"]).copy()

    if plot_df.empty:
        print("[ERROR] No valid rows to plot after transformation.")
        return 1

    plt.figure()
    plt.plot(plot_df["x_center"], plot_df["q05_alignment_pct"])
    plt.fill_between(
        plot_df["x_center"],
        plot_df["alignment_ci_low_pct"],
        plot_df["alignment_ci_high_pct"],
        alpha=0.25
    )

    plt.xlabel("max_share (binned)")
    plt.ylabel("q05( dominant-venue alignment )  [%]")
    plt.title("VWAP alignment with dominant venue vs concentration")

    # show as normal percentage numbers, e.g. 99.88%
    ax = plt.gca()
    ax.yaxis.set_major_formatter(mtick.FormatStrFormatter("%.2f"))

    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=DPI)
    plt.close()

    print("[OK] Done.")
    print(f"  bins   : {OUT_BINS}")
    print(f"  runinfo: {OUT_RUNINFO}")
    print(f"  figure : {OUT_FIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

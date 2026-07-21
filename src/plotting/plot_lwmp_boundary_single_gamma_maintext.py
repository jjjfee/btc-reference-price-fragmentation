# plot_lwmp_boundary_single_gamma_maintext.py
# ============================================================
# PURPOSE
#   Plot a clean main-text LWMP boundary figure using ONLY ONE gamma.
#
# INPUT
#   Preferred existing bins CSV (auto-detect one of these):
#     1) <PROJECT_ROOT>\experiments_dvonly\pivot_boundary_curve_bins_maxshare.csv
#     2) <PROJECT_ROOT>\experiments_dvonly\pivot_boundary_curve_bins_maxshare_mid.csv
#     3) any CSV under experiments_dvonly whose name contains:
#        "pivot_boundary_curve_bins" and ".csv"
#
# EXPECTED CONTENT
#   Your current file format is compatible with:
#     shock_type, gamma, max_share_mid, n, k, pivot_rate, ci_lo, ci_hi
#
# OUTPUT
#   <PROJECT_ROOT>\experiments_dvonly\maintext_figs\
#     - Fig_LWMP_boundary_single_gamma1_inflate_only.png
#     - lwmp_boundary_single_gamma1_inflate_only_used_data.csv
#     - lwmp_boundary_single_gamma1_inflate_only_runinfo.txt
# ============================================================

from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import time


# -----------------------------
# USER CONFIG
# -----------------------------
ROOT = Path(__file__).resolve().parents[2]
BINS_DIR = ROOT / "experiments_dvonly"

OUT_DIR = ROOT / "experiments_dvonly" / "maintext_figs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Main-text choice
TARGET_SHOCK_TYPE = "inflate_only"
TARGET_GAMMA = 1.0

# Figure text
TITLE = "Pivot boundary curve | shock_type=inflate_only | gamma=1"
X_LABEL = "max_share_mid"
Y_LABEL = "Pivot switch rate (pivot_changed)"

# Candidate input files
CANDIDATE_FILES = [
    BINS_DIR / "pivot_boundary_curve_bins_maxshare.csv",
    BINS_DIR / "pivot_boundary_curve_bins_maxshare_mid.csv",
]

# Plot export
FIG_OUT = OUT_DIR / "Fig_LWMP_boundary_single_gamma1_inflate_only.png"
DATA_OUT = OUT_DIR / "lwmp_boundary_single_gamma1_inflate_only_used_data.csv"
RUNINFO_OUT = OUT_DIR / "lwmp_boundary_single_gamma1_inflate_only_runinfo.txt"
DPI = 220


# -----------------------------
# Helpers
# -----------------------------
def find_bins_file() -> Path:
    """Find an existing bins CSV."""
    for f in CANDIDATE_FILES:
        if f.exists():
            return f

    all_csv = sorted(BINS_DIR.glob("**/*pivot_boundary_curve_bins*.csv"))
    if all_csv:
        return all_csv[0]

    raise FileNotFoundError("No pivot boundary bins CSV found under experiments_dvonly.")


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in columns:
            return c
    return None


def infer_columns(df: pd.DataFrame) -> dict:
    cols = list(df.columns)

    # x columns
    x_col = first_existing(cols, [
        "max_share_mid",
        "max_share",
        "x_center",
        "x_mid",
        "bin_mid",
        "mid",
    ])

    # y columns
    y_col = first_existing(cols, [
        "pivot_rate",
        "pivot_changed_rate",
        "pivot_switch_rate",
        "rate",
        "p_hat",
        "prob",
        "mean",
        "y",
    ])

    # CI columns
    ci_low_col = first_existing(cols, [
        "ci_lo",
        "ci_low",
        "lower",
        "lb",
        "wilson_low",
        "lwr",
    ])
    ci_high_col = first_existing(cols, [
        "ci_hi",
        "ci_high",
        "upper",
        "ub",
        "wilson_high",
        "upr",
    ])

    # filter columns
    shock_col = first_existing(cols, [
        "shock_type",
        "shock",
        "shock_name",
    ])
    gamma_col = first_existing(cols, [
        "gamma",
        "delta_w",
        "delta",
    ])

    # optional count columns
    n_col = first_existing(cols, [
        "n",
        "count",
        "obs",
        "n_obs",
    ])

    k_col = first_existing(cols, [
        "k",
        "successes",
        "n_success",
    ])

    return {
        "x_col": x_col,
        "y_col": y_col,
        "ci_low_col": ci_low_col,
        "ci_high_col": ci_high_col,
        "shock_col": shock_col,
        "gamma_col": gamma_col,
        "n_col": n_col,
        "k_col": k_col,
    }


def clean_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c is not None and c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    t0 = time.time()

    bins_file = find_bins_file()
    df = pd.read_csv(bins_file)

    info = infer_columns(df)

    if info["x_col"] is None:
        raise ValueError(f"Cannot infer x column from columns: {list(df.columns)}")
    if info["y_col"] is None:
        raise ValueError(f"Cannot infer y column from columns: {list(df.columns)}")

    df = clean_numeric(
        df,
        [
            info["x_col"],
            info["y_col"],
            info["ci_low_col"],
            info["ci_high_col"],
            info["gamma_col"],
            info["n_col"],
            info["k_col"],
        ],
    )

    # filter shock_type
    if info["shock_col"] is not None:
        df = df[df[info["shock_col"]].astype(str) == TARGET_SHOCK_TYPE].copy()

    # filter gamma
    if info["gamma_col"] is not None:
        df = df[np.isclose(df[info["gamma_col"]], TARGET_GAMMA, atol=1e-12)].copy()

    if df.empty:
        raise ValueError(
            "No rows left after filtering. Check shock_type/gamma or input file."
        )

    # keep only useful columns
    keep_cols = [info["x_col"], info["y_col"]]
    if info["ci_low_col"] is not None:
        keep_cols.append(info["ci_low_col"])
    if info["ci_high_col"] is not None:
        keep_cols.append(info["ci_high_col"])
    if info["n_col"] is not None:
        keep_cols.append(info["n_col"])
    if info["k_col"] is not None:
        keep_cols.append(info["k_col"])

    plot_df = df[keep_cols].copy()
    plot_df = plot_df.dropna(subset=[info["x_col"], info["y_col"]]).copy()
    plot_df = plot_df.sort_values(info["x_col"]).copy()

    if plot_df.empty:
        raise ValueError("No valid rows to plot after cleaning.")

    # save used data
    rename_map = {
        info["x_col"]: "x",
        info["y_col"]: "y",
    }
    if info["ci_low_col"] is not None:
        rename_map[info["ci_low_col"]] = "ci_low"
    if info["ci_high_col"] is not None:
        rename_map[info["ci_high_col"]] = "ci_high"
    if info["n_col"] is not None:
        rename_map[info["n_col"]] = "n"
    if info["k_col"] is not None:
        rename_map[info["k_col"]] = "k"

    save_df = plot_df.rename(columns=rename_map)
    save_df.to_csv(DATA_OUT, index=False, encoding="utf-8-sig")

    # plot
    plt.figure(figsize=(9, 6))
    plt.plot(plot_df[info["x_col"]], plot_df[info["y_col"]], marker="o", linewidth=2)

    if info["ci_low_col"] is not None and info["ci_high_col"] is not None:
        ci_ok = plot_df[[info["ci_low_col"], info["ci_high_col"]]].notna().all(axis=1)
        if ci_ok.any():
            plt.fill_between(
                plot_df.loc[ci_ok, info["x_col"]],
                plot_df.loc[ci_ok, info["ci_low_col"]],
                plot_df.loc[ci_ok, info["ci_high_col"]],
                alpha=0.22
            )

    # 在 max_share = 0.5 处加竖虚线
    plt.axvline(x=0.5, linestyle="--", linewidth=1.5, alpha=0.8)

    plt.xlabel(X_LABEL)
    plt.ylabel(Y_LABEL)
    plt.title(TITLE)
    plt.ylim(0, 1)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=DPI)
    plt.close()



    # runinfo
    with open(RUNINFO_OUT, "w", encoding="utf-8") as f:
        f.write("LWMP single-gamma main-text boundary figure\n")
        f.write(f"INPUT_FILE={bins_file}\n")
        f.write(f"TARGET_SHOCK_TYPE={TARGET_SHOCK_TYPE}\n")
        f.write(f"TARGET_GAMMA={TARGET_GAMMA}\n")
        f.write(f"x_col={info['x_col']}\n")
        f.write(f"y_col={info['y_col']}\n")
        f.write(f"ci_low_col={info['ci_low_col']}\n")
        f.write(f"ci_high_col={info['ci_high_col']}\n")
        f.write(f"shock_col={info['shock_col']}\n")
        f.write(f"gamma_col={info['gamma_col']}\n")
        f.write(f"n_col={info['n_col']}\n")
        f.write(f"k_col={info['k_col']}\n")
        f.write(f"N_ROWS_PLOTTED={len(plot_df)}\n")
        f.write(f"Elapsed_sec={time.time()-t0:.2f}\n")

    print("[OK] Done.")
    print(f"Input : {bins_file}")
    print(f"Figure: {FIG_OUT}")
    print(f"Data  : {DATA_OUT}")
    print(f"Log   : {RUNINFO_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

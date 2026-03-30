# plot_vwap_head_proximity_vs_maxshare.py
# ============================================================
# PURPOSE
#   Test the structural hypothesis:
#   "As concentration rises, VWAP converges toward the dominant venue price."
#
# INPUTS
#   1) D:\cilck here\2代目\hhi_panel\btc_1m_panel_with_hhi.csv
#      Required columns:
#         - time_utc_dt  (or time_utc)
#         - max_share
#         - dominant_exchange
#
#   2) D:\cilck here\2代目\agg_ready\btc_2021_2022_agg_prices.csv
#      Required columns:
#         - time_utc
#         - P_vwap_DV
#
#   3) D:\cilck here\2代目\dv_ready_2021_2022\BTCUSD_1m_<EX>_2021_2022_with_DV.csv
#      Required columns in each file:
#         - time_utc
#         - p_usd_scaled
#
# OPTIONAL INPUT
#   4) D:\cilck here\2代目\experiments_dvonly\pivot_boundary_curve_edges_maxshare.csv
#      If present, reuse these edges so the x-axis is perfectly mirrored with LWMP boundary plots.
#
# OUTPUTS
#   Written to:
#     D:\cilck here\2代目\experiments_structure_vwap\
#
#   Files:
#     - vwap_head_proximity_bins_maxshare.csv
#     - vwap_head_proximity_edges_maxshare.csv
#     - vwap_head_proximity_runinfo_maxshare.txt
#     - Fig_vwap_head_proximity_q95_by_maxshare.png
#
# INTERPRETATION
#   y_t = |P_vwap_DV - p_dom| / P_vwap_DV
#   If VWAP structurally "collapses toward" the dominant venue as concentration rises,
#   then q95(y_t | max_share bin) should DECREASE with max_share.
# ============================================================

from __future__ import annotations

from pathlib import Path
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# -----------------------------
# USER CONFIG
# -----------------------------
ROOT = Path(r"D:\cilck here\2代目")

PANEL_FILE = ROOT / "hhi_panel" / "btc_1m_panel_with_hhi.csv"
AGG_FILE   = ROOT / "agg_ready" / "btc_2021_2022_agg_prices.csv"
DV_DIR     = ROOT / "dv_ready_2021_2022"

# Optional: reuse LWMP boundary edges for perfect x-axis mirroring
EDGES_FILE_CANDIDATE = ROOT / "experiments_dvonly" / "pivot_boundary_curve_edges_maxshare.csv"

EXCHANGES = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]

OUT_DIR = ROOT / "experiments_structure_vwap"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NBINS = 30
MIN_N_PER_BIN = 500

Q_LEVEL = 0.95
BOOTSTRAP_B = 500
BOOTSTRAP_CI = (0.025, 0.975)
MAX_N_FOR_BOOTSTRAP = 20000
RANDOM_SEED = 42

USE_EXISTING_EDGES_IF_POSSIBLE = True

FIG_NAME = "Fig_vwap_head_proximity_q95_by_maxshare.png"
DPI = 200


# -----------------------------
# Helpers
# -----------------------------
def parse_min_utc(s: pd.Series) -> pd.Series:
    """Parse datetime-like values to UTC minute."""
    t = pd.to_datetime(s, utc=True, errors="coerce")
    return t.dt.floor("min")


def load_edges(edges_path: Path) -> np.ndarray:
    """
    Robustly load precomputed edges from a CSV with unknown schema.
    Accepts:
      - single numeric column
      - column named edge/edges/bin_edge
      - left/right columns
    """
    df = pd.read_csv(edges_path)

    # named edge-like columns
    for col in ["edge", "edges", "bin_edge", "cut", "x_edge"]:
        if col in df.columns:
            arr = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy()
            arr = np.unique(arr)
            arr.sort()
            if len(arr) >= 3:
                return arr

    # left/right columns
    left_cols = [c for c in df.columns if "left" in c.lower()]
    right_cols = [c for c in df.columns if "right" in c.lower()]
    if left_cols and right_cols:
        left = pd.to_numeric(df[left_cols[0]], errors="coerce").dropna().to_numpy()
        right = pd.to_numeric(df[right_cols[0]], errors="coerce").dropna().to_numpy()
        arr = np.unique(np.concatenate([left, right]))
        arr.sort()
        if len(arr) >= 3:
            return arr

    # fallback: first numeric column
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if num_cols:
        arr = df[num_cols[0]].dropna().to_numpy()
        arr = np.unique(arr)
        arr.sort()
        if len(arr) >= 3:
            return arr

    raise ValueError(f"Cannot parse edges from {edges_path}")


def compute_edges_from_panel(panel_x: pd.Series, nbins: int) -> np.ndarray:
    """Quantile edges from the full panel distribution."""
    x = pd.to_numeric(panel_x, errors="coerce").dropna().to_numpy()
    if x.size == 0:
        raise ValueError("panel x is empty after cleaning")
    qs = np.linspace(0.0, 1.0, nbins + 1)
    edges = np.quantile(x, qs)
    edges = np.unique(edges)
    edges.sort()
    if len(edges) < 3:
        raise ValueError("Degenerate edges: too many duplicate quantiles")
    return edges


def bootstrap_quantile_ci(
    data: np.ndarray,
    q: float,
    b: int,
    ci: tuple[float, float],
    rng: np.random.Generator,
    max_n: int
) -> tuple[float, float, float]:
    """
    Percentile bootstrap CI for a sample quantile.
    Returns (q_hat, ci_low, ci_high).
    """
    data = data[np.isfinite(data)]
    if data.size == 0:
        return (np.nan, np.nan, np.nan)

    if data.size > max_n:
        idx = rng.choice(data.size, size=max_n, replace=False)
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


def safe_to_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    t0 = time.time()
    rng = np.random.default_rng(RANDOM_SEED)

    # ---- load panel ----
    if not PANEL_FILE.exists():
        print(f"[ERROR] Missing panel file: {PANEL_FILE}")
        return 1

    panel = pd.read_csv(PANEL_FILE)

    if "time_utc_dt" in panel.columns:
        panel["time_utc_dt"] = parse_min_utc(panel["time_utc_dt"])
    elif "time_utc" in panel.columns:
        panel["time_utc_dt"] = parse_min_utc(panel["time_utc"])
    else:
        print("[ERROR] panel missing time column: need 'time_utc_dt' or 'time_utc'")
        return 1

    required_panel = ["max_share", "dominant_exchange"]
    for c in required_panel:
        if c not in panel.columns:
            print(f"[ERROR] panel missing column: {c}")
            print(f"columns={list(panel.columns)}")
            return 1

    panel = safe_to_numeric(panel, ["max_share"])
    panel = panel.dropna(subset=["time_utc_dt", "max_share", "dominant_exchange"]).copy()
    panel = panel[(panel["max_share"] >= 0) & (panel["max_share"] <= 1)].copy()

    # ---- load agg ----
    if not AGG_FILE.exists():
        print(f"[ERROR] Missing agg file: {AGG_FILE}")
        return 1

    agg = pd.read_csv(AGG_FILE)

    if "time_utc" not in agg.columns:
        print("[ERROR] agg missing 'time_utc'")
        return 1
    if "P_vwap_DV" not in agg.columns:
        print("[ERROR] agg missing 'P_vwap_DV'")
        print(f"columns={list(agg.columns)}")
        return 1

    agg["time_utc_dt"] = parse_min_utc(agg["time_utc"])
    agg = safe_to_numeric(agg, ["P_vwap_DV"])
    agg = agg.dropna(subset=["time_utc_dt", "P_vwap_DV"]).copy()
    agg = agg[agg["P_vwap_DV"] > 0].copy()

    # ---- merge base panel + agg ----
    base = panel.merge(
        agg[["time_utc_dt", "P_vwap_DV"]],
        on="time_utc_dt",
        how="inner"
    )

    if base.empty:
        print("[ERROR] Empty base after merging panel and agg")
        return 1

    # ---- recover dominant venue price p_dom minute by minute ----
    base["p_dom"] = np.nan

    for ex in EXCHANGES:
        f = DV_DIR / f"BTCUSD_1m_{ex}_2021_2022_with_DV.csv"
        if not f.exists():
            print(f"[WARN] Missing DV-ready file: {f}")
            continue

        mask = (base["dominant_exchange"] == ex) & (base["p_dom"].isna())
        if mask.sum() == 0:
            continue

        print(f"[INFO] Filling dominant price for {ex} ... rows={int(mask.sum())}")

        dv = pd.read_csv(f, usecols=["time_utc", "p_usd_scaled"])
        dv["time_utc_dt"] = parse_min_utc(dv["time_utc"])
        dv = safe_to_numeric(dv, ["p_usd_scaled"])
        dv = dv.dropna(subset=["time_utc_dt", "p_usd_scaled"]).copy()
        dv = dv[dv["p_usd_scaled"] > 0].copy()

        tmp = base.loc[mask, ["time_utc_dt"]].merge(
            dv[["time_utc_dt", "p_usd_scaled"]],
            on="time_utc_dt",
            how="left"
        )

        base.loc[mask, "p_dom"] = tmp["p_usd_scaled"].to_numpy()

    base = base.dropna(subset=["p_dom"]).copy()
    base = base[base["p_dom"] > 0].copy()

    if base.empty:
        print("[ERROR] No rows left after filling dominant venue price")
        return 1

    # ---- define structural head-proximity metric ----
    # Relative distance between VWAP and the dominant venue price
    base["rel_gap_dom"] = (base["P_vwap_DV"] - base["p_dom"]).abs() / base["P_vwap_DV"]

    # ---- edges ----
    edges_used = None
    edges_source = None

    if USE_EXISTING_EDGES_IF_POSSIBLE and EDGES_FILE_CANDIDATE.exists():
        try:
            edges_used = load_edges(EDGES_FILE_CANDIDATE)
            edges_source = f"existing:{EDGES_FILE_CANDIDATE.name}"
        except Exception as e:
            edges_used = None
            edges_source = f"failed_existing:{e}"

    if edges_used is None:
        edges_used = compute_edges_from_panel(panel["max_share"], NBINS)
        edges_source = "computed_from_panel_quantiles"

    # make sure edges cover actual event range
    minx = float(base["max_share"].min())
    maxx = float(base["max_share"].max())
    if minx < edges_used[0]:
        edges_used[0] = minx
    if maxx > edges_used[-1]:
        edges_used[-1] = maxx

    # ---- binning ----
    base["bin"] = pd.cut(
        base["max_share"],
        bins=edges_used,
        include_lowest=True,
        right=False
    )

    rows = []
    for i, interval in enumerate(base["bin"].cat.categories):
        g = base[base["bin"] == interval]
        n = len(g)

        x_left = float(interval.left)
        x_right = float(interval.right)
        x_center = 0.5 * (x_left + x_right)

        if n < MIN_N_PER_BIN:
            rows.append({
                "bin_id": i,
                "x_left": x_left,
                "x_right": x_right,
                "x_center": x_center,
                "n": n,
                "q95_rel_gap_dom": np.nan,
                "ci_low": np.nan,
                "ci_high": np.nan,
                "median_rel_gap_dom": float(np.nanmedian(g["rel_gap_dom"])) if n > 0 else np.nan
            })
            continue

        arr = g["rel_gap_dom"].to_numpy(dtype=float)
        q_hat, lo, hi = bootstrap_quantile_ci(
            data=arr,
            q=Q_LEVEL,
            b=BOOTSTRAP_B,
            ci=BOOTSTRAP_CI,
            rng=rng,
            max_n=MAX_N_FOR_BOOTSTRAP
        )

        rows.append({
            "bin_id": i,
            "x_left": x_left,
            "x_right": x_right,
            "x_center": x_center,
            "n": n,
            "q95_rel_gap_dom": q_hat,
            "ci_low": lo,
            "ci_high": hi,
            "median_rel_gap_dom": float(np.median(arr))
        })

    bins_df = pd.DataFrame(rows)

    # ---- write outputs ----
    bins_out = OUT_DIR / "vwap_head_proximity_bins_maxshare.csv"
    edges_out = OUT_DIR / "vwap_head_proximity_edges_maxshare.csv"
    runinfo_out = OUT_DIR / "vwap_head_proximity_runinfo_maxshare.txt"
    fig_out = OUT_DIR / FIG_NAME

    bins_df.to_csv(bins_out, index=False, encoding="utf-8-sig")
    pd.DataFrame({"edge": edges_used}).to_csv(edges_out, index=False, encoding="utf-8-sig")

    with open(runinfo_out, "w", encoding="utf-8") as f:
        f.write("VWAP head proximity vs concentration\n")
        f.write(f"ROOT={ROOT}\n")
        f.write(f"PANEL_FILE={PANEL_FILE}\n")
        f.write(f"AGG_FILE={AGG_FILE}\n")
        f.write(f"DV_DIR={DV_DIR}\n")
        f.write(f"EXCHANGES={EXCHANGES}\n")
        f.write(f"EDGES_SOURCE={edges_source}\n")
        f.write(f"NBINS={NBINS}\n")
        f.write(f"MIN_N_PER_BIN={MIN_N_PER_BIN}\n")
        f.write(f"Q_LEVEL={Q_LEVEL}\n")
        f.write(f"BOOTSTRAP_B={BOOTSTRAP_B}\n")
        f.write(f"BOOTSTRAP_CI={BOOTSTRAP_CI}\n")
        f.write(f"MAX_N_FOR_BOOTSTRAP={MAX_N_FOR_BOOTSTRAP}\n")
        f.write(f"RANDOM_SEED={RANDOM_SEED}\n")
        f.write(f"N_FINAL={len(base)}\n")
        f.write(f"Elapsed_sec={time.time()-t0:.2f}\n")

    # ---- plot ----
    plot_df = bins_df.dropna(subset=["q95_rel_gap_dom", "ci_low", "ci_high"]).copy()

    if plot_df.empty:
        print("[WARN] No valid bins to plot. Check MIN_N_PER_BIN or data coverage.")
    else:
        plt.figure()
        plt.plot(plot_df["x_center"], plot_df["q95_rel_gap_dom"], label="q95 rel gap")
        plt.fill_between(
            plot_df["x_center"],
            plot_df["ci_low"],
            plot_df["ci_high"],
            alpha=0.25
        )
        plt.xlabel("max_share (binned)")
        plt.ylabel("q95( |P_vwap_DV - p_dom| / P_vwap_DV )")
        plt.title("VWAP proximity to dominant venue vs concentration")
        plt.tight_layout()
        plt.savefig(fig_out, dpi=DPI)
        plt.close()

    print("[OK] Done.")
    print(f"  bins   : {bins_out}")
    print(f"  edges  : {edges_out}")
    print(f"  runinfo: {runinfo_out}")
    print(f"  figure : {fig_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

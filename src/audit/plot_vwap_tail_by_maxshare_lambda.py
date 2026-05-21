# plot_vwap_tail_by_maxshare_lambda.py
# ------------------------------------------------------------
# Goal:
#   Plot VWAP tail response vs structural concentration (max_share),
#   using effective injection intensity lambda for normalization.
#
# Inputs:
#   experiments_dvonly/dvon_injection_shift_samples.csv
#   hhi_panel/btc_1m_panel_with_hhi.csv
#
# Outputs (default):
#   experiments_dvonly/Fig_VWAP_p90_p95_p99_absShift_over_lambda_by_maxshare_quintile.png
#   experiments_dvonly/Fig_VWAP_p90_p95_p99_absShift_by_maxshare_quintile.png
#   experiments_dvonly/Table_VWAP_tail_over_lambda_by_maxshare_quintile.csv
# ------------------------------------------------------------

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = Path(r"D:\cilck here\2代目")

EVENT = BASE / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
PANEL = BASE / "hhi_panel" / "btc_1m_panel_with_hhi.csv"

OUT_FIG_NORM = BASE / "experiments_dvonly" / "Fig_VWAP_p90_p95_p99_absShift_over_lambda_by_maxshare_quintile.png"
OUT_FIG_RAW  = BASE / "experiments_dvonly" / "Fig_VWAP_p90_p95_p99_absShift_by_maxshare_quintile.png"
OUT_TABLE    = BASE / "experiments_dvonly" / "Table_VWAP_tail_over_lambda_by_maxshare_quintile.csv"

# ----- config -----
QUANTILES = [0.90, 0.95, 0.99]
N_BINS = 5                 # quintiles; set 10 for deciles etc.
MIN_PER_BIN = 500          # avoid tiny bins
EPS_LAMBDA = 1e-12         # avoid division blow-ups

def coerce_utc_minute(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True).dt.floor("min")

def pick_panel_time_col(pn: pd.DataFrame) -> str:
    if "time_utc_dt" in pn.columns:
        return "time_utc_dt"
    if "time_utc" in pn.columns:
        return "time_utc"
    raise ValueError("PANEL missing time column (time_utc_dt or time_utc).")

def compute_lambda_row(row) -> float:
    """
    Effective injection intensity:
      inflate_only: lambda = |delta| * s_before / (1 + delta*s_before)
      reallocate_total_fixed: lambda = |s_after - s_before|
    """
    st = str(row.get("shock_type", ""))
    s0 = row.get("share_shocked_before", np.nan)
    s1 = row.get("share_shocked_after", np.nan)
    d  = row.get("delta_w", np.nan)

    if not np.isfinite(s0) or s0 <= 0:
        return np.nan

    if st == "inflate_only":
        if not np.isfinite(d):
            return np.nan
        denom = 1.0 + d * s0
        if denom <= 0:
            return np.nan
        return (abs(d) * s0) / denom

    if st == "reallocate_total_fixed":
        if not np.isfinite(s1):
            return np.nan
        return abs(s1 - s0)

    # fallback (if you ever add new shock types):
    if np.isfinite(s1):
        return abs(s1 - s0)
    return np.nan

def bin_by_quantiles(x: pd.Series, n_bins: int) -> pd.Series:
    # qcut can fail if too many ties; use rank-based fallback
    try:
        return pd.qcut(x, n_bins, labels=False, duplicates="drop")
    except Exception:
        r = x.rank(method="average", pct=True)
        return pd.qcut(r, n_bins, labels=False, duplicates="drop")

def main():
    if not EVENT.exists():
        raise FileNotFoundError(f"Missing EVENT: {EVENT}")
    if not PANEL.exists():
        raise FileNotFoundError(f"Missing PANEL: {PANEL}")

    ev = pd.read_csv(EVENT)
    pn = pd.read_csv(PANEL)

    # ---- parse times ----
    if "time_utc" not in ev.columns:
        raise ValueError("EVENT missing time_utc")
    ev["time_utc"] = coerce_utc_minute(ev["time_utc"])

    tcol = pick_panel_time_col(pn)
    pn["time_utc"] = coerce_utc_minute(pn[tcol])

    # ---- core cols ----
    need_ev = ["shock_type", "delta_w", "share_shocked_before", "share_shocked_after", "shift_vwap"]
    miss = [c for c in need_ev if c not in ev.columns]
    if miss:
        raise ValueError(f"EVENT missing columns: {miss}")

    if "max_share" not in pn.columns:
        raise ValueError("PANEL missing max_share")

    # ---- numeric ----
    ev["delta_w"] = pd.to_numeric(ev["delta_w"], errors="coerce")
    ev["share_shocked_before"] = pd.to_numeric(ev["share_shocked_before"], errors="coerce")
    ev["share_shocked_after"]  = pd.to_numeric(ev["share_shocked_after"], errors="coerce")
    ev["shift_vwap"] = pd.to_numeric(ev["shift_vwap"], errors="coerce")  # NOTE: your script stores relative shift

    pn["max_share"] = pd.to_numeric(pn["max_share"], errors="coerce")

    # ---- merge max_share into events ----
    df = ev.merge(pn[["time_utc", "max_share"]], on="time_utc", how="inner")
    df = df.dropna(subset=["time_utc", "max_share", "shift_vwap", "share_shocked_before", "shock_type"]).copy()

    # ---- lambda & metrics ----
    df["lambda_eff"] = df.apply(compute_lambda_row, axis=1)
    df.loc[df["lambda_eff"] <= EPS_LAMBDA, "lambda_eff"] = np.nan

    df["abs_shift_vwap"] = df["shift_vwap"].abs()
    df["abs_shift_over_lambda"] = df["abs_shift_vwap"] / df["lambda_eff"]

    # drop bad rows
    df2 = df.dropna(subset=["abs_shift_over_lambda"]).copy()
    if len(df2) < 1000:
        print("[WARN] Too few rows after lambda normalization. Check lambda_eff distribution.")
    print(f"[INFO] merged rows={len(df):,}, usable (lambda>0)={len(df2):,}")

    # ---- bin by max_share quantiles ----
    df2["bin"] = bin_by_quantiles(df2["max_share"], N_BINS)
    df2 = df2.dropna(subset=["bin"]).copy()
    df2["bin"] = df2["bin"].astype(int)

    # summarize
    rows = []
    for b, sb in df2.groupby("bin"):
        n = len(sb)
        if n < MIN_PER_BIN:
            continue
        x_mid = float(sb["max_share"].median())
        lam_mid = float(sb["lambda_eff"].median())

        out = {"bin": int(b), "n": int(n), "max_share_mid": x_mid, "lambda_median": lam_mid}
        for q in QUANTILES:
            out[f"q{int(q*100)}_absShift_over_lambda"] = float(sb["abs_shift_over_lambda"].quantile(q))
            out[f"q{int(q*100)}_absShift"] = float(sb["abs_shift_vwap"].quantile(q))
        rows.append(out)

    tab = pd.DataFrame(rows).sort_values("max_share_mid")
    tab.to_csv(OUT_TABLE, index=False, encoding="utf-8-sig")
    print("saved table:", OUT_TABLE, "shape=", tab.shape)

    # ---- plot normalized ----
    fig, ax = plt.subplots(figsize=(9, 5))
    for q in QUANTILES:
        ax.plot(
            tab["max_share_mid"].to_numpy(),
            tab[f"q{int(q*100)}_absShift_over_lambda"].to_numpy(),
            marker="o",
            linewidth=1.5,
            markersize=3.5,
            label=f"p{int(q*100)}(|shift_vwap|/lambda)"
        )
    ax.set_xlabel("max_share (dominant DV share)")
    ax.set_ylabel("|shift_vwap| / lambda_eff")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(OUT_FIG_NORM, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("saved fig:", OUT_FIG_NORM)

    # ---- plot raw ----
    fig, ax = plt.subplots(figsize=(9, 5))
    for q in QUANTILES:
        ax.plot(
            tab["max_share_mid"].to_numpy(),
            tab[f"q{int(q*100)}_absShift"].to_numpy(),
            marker="o",
            linewidth=1.5,
            markersize=3.5,
            label=f"p{int(q*100)}(|shift_vwap|)"
        )
    ax.set_xlabel("max_share (dominant DV share)")
    ax.set_ylabel("|shift_vwap|   (relative shift)")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(OUT_FIG_RAW, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("saved fig:", OUT_FIG_RAW)

if __name__ == "__main__":
    main()

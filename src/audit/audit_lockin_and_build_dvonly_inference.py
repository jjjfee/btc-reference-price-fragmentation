from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# =========================
# Paths (edit if needed)
# =========================
BASE = Path(__file__).resolve().parents[2]

EVENT = BASE / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
PANEL = BASE / "hhi_panel" / "btc_1m_panel_with_hhi.csv"

# Optional fallback if PANEL misses total_DV / dominant_exchange / max_share
CONC  = BASE / "experiments" / "weight_concentration_minute_level.csv"

OUTDIR = BASE / "experiments_dvonly" / "audit_lockin"
OUTDIR.mkdir(parents=True, exist_ok=True)

OUT_MERGED = OUTDIR / "dvonly_event_merged_for_audit.csv"
OUT_SUMMARY_LOCKIN = OUTDIR / "audit_lockin_summary.csv"
OUT_SUMMARY_BINS   = OUTDIR / "audit_lockin_bins.csv"
OUT_INFERENCE_DATA = OUTDIR / "dvonly_inference_dataset.csv"

FIG_DOM_RATE = OUTDIR / "Fig_lockin_pivot_is_dominant_rate_by_maxshare.png"
FIG_GAP_HIST = OUTDIR / "Fig_lockin_margin_gap_hist.png"
FIG_GAP_SCAT = OUTDIR / "Fig_lockin_margin_gap_vs_maxshare.png"


# =========================
# Config
# =========================
Z = 1.96
NBINS = 30
MIN_N_PER_BIN = 200  # set 0 to disable

LOCKIN_THRESHOLD = 0.5  # max_share > 0.5 defines lock-in regime


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score CI for binomial proportion."""
    n = float(n)
    if n <= 0:
        return (np.nan, np.nan)
    p = float(k) / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / den
    half = (z * np.sqrt(max(p * (1.0 - p) / n + z * z / (4.0 * n * n), 0.0))) / den
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return lo, hi


def pick_time_col(df: pd.DataFrame) -> str:
    """Pick a time column from common candidates."""
    for c in ["time_utc", "time_utc_dt", "timestamp", "datetime", "time"]:
        if c in df.columns:
            return c
    raise ValueError("Cannot find a time column (expected time_utc or time_utc_dt etc.)")


def coerce_utc_minute(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True).dt.floor("min")


def first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return pd.read_csv(path)


def make_quantile_edges(x: np.ndarray, nbins: int) -> np.ndarray:
    q = np.linspace(0, 1, nbins + 1)
    try:
        edges = np.quantile(x, q, method="linear")
    except TypeError:
        edges = np.quantile(x, q, interpolation="linear")
    edges = np.unique(edges)
    if len(edges) < 5:
        raise RuntimeError("Too few unique quantile edges; check distribution.")
    return edges


def main():
    # -------------------------
    # Load event
    # -------------------------
    ev = safe_read_csv(EVENT)

    if "time_utc" not in ev.columns:
        raise ValueError("EVENT must contain time_utc")

    ev["time_utc"] = coerce_utc_minute(ev["time_utc"])
    ev = ev.dropna(subset=["time_utc"]).copy()

    gamma_col = "gamma" if "gamma" in ev.columns else ("delta_w" if "delta_w" in ev.columns else None)
    if gamma_col is None:
        raise ValueError("EVENT missing gamma/delta_w")

    ev["gamma"] = pd.to_numeric(ev[gamma_col], errors="coerce")
    ev["pivot_changed"] = pd.to_numeric(ev["pivot_changed"], errors="coerce").fillna(0).astype(int).clip(0, 1)

    # Optional fields used in audits
    for c in ["pivot_exchange_before", "pivot_exchange_after"]:
        if c not in ev.columns:
            raise ValueError(f"EVENT missing required column: {c}")

    # margins (needed for inequality audit)
    if "pivot_margin_before" not in ev.columns:
        raise ValueError("EVENT missing pivot_margin_before (needed for lock-in margin audit)")

    if "shock_type" not in ev.columns:
        raise ValueError("EVENT missing shock_type")

    # -------------------------
    # Load panel
    # -------------------------
    pn = safe_read_csv(PANEL)
    tcol_pn = pick_time_col(pn)
    pn["time_utc"] = coerce_utc_minute(pn[tcol_pn])

    # Try to get required structural columns from panel
    max_share_col = first_existing(pn, ["max_share"])
    hhi_roll_col  = first_existing(pn, ["HHI_roll", "hhi_roll"])
    hhi_col       = first_existing(pn, ["HHI", "hhi"])

    total_dv_col  = first_existing(pn, ["total_DV", "total_dv", "total_DV_usd", "total_dv_usd"])
    dom_col       = first_existing(pn, ["dominant_exchange", "dominant", "dominant_exch"])

    # -------------------------
    # Fallback to concentration minute file if needed
    # -------------------------
    conc = None
    if (max_share_col is None) or (total_dv_col is None) or (dom_col is None):
        if CONC.exists():
            conc = safe_read_csv(CONC)
            if "time_utc" not in conc.columns:
                raise ValueError("CONC file must contain time_utc")
            conc["time_utc"] = coerce_utc_minute(conc["time_utc"])

    # Build panel-like slim df
    keep = ["time_utc"]
    if max_share_col is not None:
        pn["max_share"] = pd.to_numeric(pn[max_share_col], errors="coerce")
        keep += ["max_share"]
    if hhi_roll_col is not None:
        pn["HHI_roll"] = pd.to_numeric(pn[hhi_roll_col], errors="coerce")
        keep += ["HHI_roll"]
    if hhi_col is not None:
        pn["HHI"] = pd.to_numeric(pn[hhi_col], errors="coerce")
        keep += ["HHI"]
    if total_dv_col is not None:
        pn["total_DV"] = pd.to_numeric(pn[total_dv_col], errors="coerce")
        keep += ["total_DV"]
    if dom_col is not None:
        pn["dominant_exchange"] = pn[dom_col].astype(str)
        keep += ["dominant_exchange"]

    pn_slim = pn[keep].dropna(subset=["time_utc"]).copy()

    # Fill from conc if still missing
    if conc is not None:
        conc_keep = ["time_utc"]
        if "max_share" in conc.columns:
            conc["max_share"] = pd.to_numeric(conc["max_share"], errors="coerce")
            conc_keep += ["max_share"]
        if "total_DV" in conc.columns:
            conc["total_DV"] = pd.to_numeric(conc["total_DV"], errors="coerce")
            conc_keep += ["total_DV"]
        if "dominant_exchange" in conc.columns:
            conc["dominant_exchange"] = conc["dominant_exchange"].astype(str)
            conc_keep += ["dominant_exchange"]
        if "HHI" in conc.columns:
            conc["HHI"] = pd.to_numeric(conc["HHI"], errors="coerce")
            conc_keep += ["HHI"]

        conc_slim = conc[conc_keep].copy()
        pn_slim = pn_slim.merge(conc_slim, on="time_utc", how="left", suffixes=("", "_conc"))

        # If panel missing, fill from conc columns
        if "max_share" not in pn_slim.columns and "max_share_conc" in pn_slim.columns:
            pn_slim["max_share"] = pn_slim["max_share_conc"]
        if "total_DV" not in pn_slim.columns and "total_DV_conc" in pn_slim.columns:
            pn_slim["total_DV"] = pn_slim["total_DV_conc"]
        if "dominant_exchange" not in pn_slim.columns and "dominant_exchange_conc" in pn_slim.columns:
            pn_slim["dominant_exchange"] = pn_slim["dominant_exchange_conc"]
        if "HHI" not in pn_slim.columns and "HHI_conc" in pn_slim.columns:
            pn_slim["HHI"] = pn_slim["HHI_conc"]

    # Final sanity for required columns
    required_panel = ["max_share", "total_DV", "dominant_exchange"]
    missing = [c for c in required_panel if c not in pn_slim.columns]
    if missing:
        raise ValueError(
            f"Missing required structural cols after panel+conc merge: {missing}. "
            f"Panel cols={list(pn.columns)[:40]} | Conc exists={CONC.exists()}"
        )

    pn_slim["max_share"] = pd.to_numeric(pn_slim["max_share"], errors="coerce")
    pn_slim["total_DV"] = pd.to_numeric(pn_slim["total_DV"], errors="coerce")
    pn_slim["dominant_exchange"] = pn_slim["dominant_exchange"].astype(str)

    # -------------------------
    # Merge event with structural panel
    # -------------------------
    df = ev.merge(pn_slim, on="time_utc", how="inner")
    df = df.dropna(subset=["gamma", "max_share", "total_DV", "dominant_exchange"]).copy()

    # -------------------------
    # Build lock-in / dominance / margin-gap audits
    # -------------------------
    df["lock_in"] = (df["max_share"] > LOCKIN_THRESHOLD).astype(int)

    df["pivot_is_dominant_before"] = (df["pivot_exchange_before"].astype(str) == df["dominant_exchange"]).astype(int)
    df["pivot_is_dominant_after"]  = (df["pivot_exchange_after"].astype(str)  == df["dominant_exchange"]).astype(int)

    # normalized margin gap for the inequality:
    # gap = (pivot_margin_before / total_DV) - (max_share - 0.5)
    df["pivot_margin_before"] = pd.to_numeric(df["pivot_margin_before"], errors="coerce")
    df["gap_norm"] = (df["pivot_margin_before"] / df["total_DV"]) - (df["max_share"] - LOCKIN_THRESHOLD)

    # basic derived fields for CI-methods migration
    df["date_utc"] = df["time_utc"].dt.date.astype(str)
    if "shift_lwmp" in df.columns:
        df["shift_lwmp"] = pd.to_numeric(df["shift_lwmp"], errors="coerce")
        df["abs_shift_lwmp"] = df["shift_lwmp"].abs()

    # Save merged (optional; can be large)
    df.to_csv(OUT_MERGED, index=False, encoding="utf-8-sig")
    print("saved merged:", OUT_MERGED, "shape=", df.shape)

    # -------------------------
    # Audit summary 1: lock_in vs dominance/pivot_changed
    # -------------------------
    g = df.groupby("lock_in", dropna=False)
    summary = g.agg(
        n=("pivot_changed", "size"),
        pivot_changed_rate=("pivot_changed", "mean"),
        pivot_is_dominant_before_rate=("pivot_is_dominant_before", "mean"),
        pivot_is_dominant_after_rate=("pivot_is_dominant_after", "mean"),
        max_share_median=("max_share", "median"),
    ).reset_index()

    # Add Wilson CI for pivot_changed_rate by lock_in
    rows = []
    for _, r in summary.iterrows():
        n = int(r["n"])
        k = int(round(r["pivot_changed_rate"] * n))
        lo, hi = wilson_ci(k, n, z=Z)
        rows.append((lo, hi))
    summary["pivot_changed_ci_lo"] = [x[0] for x in rows]
    summary["pivot_changed_ci_hi"] = [x[1] for x in rows]

    summary.to_csv(OUT_SUMMARY_LOCKIN, index=False, encoding="utf-8-sig")
    print("saved summary:", OUT_SUMMARY_LOCKIN)

    # -------------------------
    # Audit summary 2: bin-by-bin dominance (for plotting & inspection)
    # edges from FULL panel minutes (minute-weighted, not event-weighted)
    # -------------------------
    edges = make_quantile_edges(pn_slim["max_share"].dropna().to_numpy(), NBINS)
    df["bin"] = pd.cut(df["max_share"], bins=edges, include_lowest=True, labels=False)

    bin_rows = []
    for b, sb in df.groupby("bin"):
        if pd.isna(b):
            continue
        b = int(b)
        n = len(sb)
        if MIN_N_PER_BIN and n < MIN_N_PER_BIN:
            continue

        # pivot_is_dominant_before
        k_dom = int(sb["pivot_is_dominant_before"].sum())
        p_dom = k_dom / n
        lo_dom, hi_dom = wilson_ci(k_dom, n, z=Z)

        # pivot_changed
        k_pc = int(sb["pivot_changed"].sum())
        p_pc = k_pc / n
        lo_pc, hi_pc = wilson_ci(k_pc, n, z=Z)

        mid = float((edges[b] + edges[b + 1]) / 2.0)

        bin_rows.append(dict(
            bin_id=b,
            max_share_mid=mid,
            n=n,
            dom_rate=p_dom,
            dom_ci_lo=lo_dom,
            dom_ci_hi=hi_dom,
            pivot_changed_rate=p_pc,
            pc_ci_lo=lo_pc,
            pc_ci_hi=hi_pc,
            lockin_share=float((sb["lock_in"] == 1).mean()),
        ))

    bins = pd.DataFrame(bin_rows).sort_values("max_share_mid")
    bins.to_csv(OUT_SUMMARY_BINS, index=False, encoding="utf-8-sig")
    print("saved bins:", OUT_SUMMARY_BINS, "shape=", bins.shape)

    # -------------------------
    # Inequality audit: only in lock-in regime AND pivot equals dominant
    # -------------------------
    sub_lock = df[(df["lock_in"] == 1) & (df["pivot_is_dominant_before"] == 1)].copy()
    if len(sub_lock) > 0:
        gap = sub_lock["gap_norm"].to_numpy()
        stats = {
            "n_lockin_and_dominant": int(len(sub_lock)),
            "gap_min": float(np.nanmin(gap)),
            "gap_p01": float(np.nanquantile(gap, 0.01)),
            "gap_p05": float(np.nanquantile(gap, 0.05)),
            "gap_median": float(np.nanmedian(gap)),
            "gap_mean": float(np.nanmean(gap)),
            "share_gap_negative": float(np.mean(gap < -1e-12)),
        }
        print("Inequality gap_norm stats (lock_in & pivot dominant):")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    # -------------------------
    # Plot 1: Pr(pivot_before == dominant_exchange) vs max_share_mid (with Wilson band)
    # -------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(bins["max_share_mid"], bins["dom_rate"], marker="o", linewidth=1.5, markersize=3.5, label="Pr(pivot==dominant)")
    ax.fill_between(bins["max_share_mid"], bins["dom_ci_lo"], bins["dom_ci_hi"], alpha=0.18)
    ax.axvline(LOCKIN_THRESHOLD, linestyle="--", linewidth=1.2, label="max_share = 0.5")
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Dominant DV share (max_share)")
    ax.set_ylabel("Pr(pivot_exchange_before == dominant_exchange)")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(FIG_DOM_RATE, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("saved fig:", FIG_DOM_RATE)

    # -------------------------
    # Plot 2: Histogram of gap_norm in lock-in & pivot-dominant subset
    # -------------------------
    if len(sub_lock) > 0:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.hist(sub_lock["gap_norm"].dropna().to_numpy(), bins=60)
        ax.axvline(0.0, linestyle="--", linewidth=1.2)
        ax.set_xlabel("gap_norm = pivot_margin/total_DV - (max_share - 0.5)")
        ax.set_ylabel("Count")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(FIG_GAP_HIST, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print("saved fig:", FIG_GAP_HIST)

        # Plot 3: gap_norm vs max_share scatter (no subsampling; can be heavy)
        # If too heavy, sample down.
        sc = sub_lock[["max_share", "gap_norm"]].dropna()
        if len(sc) > 300000:
            sc = sc.sample(300000, random_state=42)
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.scatter(sc["max_share"].to_numpy(), sc["gap_norm"].to_numpy(), s=4)
        ax.axhline(0.0, linestyle="--", linewidth=1.2)
        ax.axvline(LOCKIN_THRESHOLD, linestyle="--", linewidth=1.2)
        ax.set_xlabel("max_share")
        ax.set_ylabel("gap_norm")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(FIG_GAP_SCAT, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print("saved fig:", FIG_GAP_SCAT)

    # -------------------------
    # DV-only inference dataset (for CI-methods migration)
    # -------------------------
    keep_cols = [
        "time_utc", "date_utc", "shock_type", "gamma",
        "max_share", "HHI_roll", "HHI",
        "dominant_exchange",
        "pivot_exchange_before", "pivot_exchange_after",
        "pivot_changed",
        "pivot_margin_before",
        "pivot_is_dominant_before",
        "total_DV",
    ]
    if "shift_lwmp" in df.columns:
        keep_cols += ["shift_lwmp", "abs_shift_lwmp"]

    keep_cols = [c for c in keep_cols if c in df.columns]
    df_inf = df[keep_cols].copy()
    df_inf.to_csv(OUT_INFERENCE_DATA, index=False, encoding="utf-8-sig")
    print("saved inference dataset:", OUT_INFERENCE_DATA, "shape=", df_inf.shape)


if __name__ == "__main__":
    main()

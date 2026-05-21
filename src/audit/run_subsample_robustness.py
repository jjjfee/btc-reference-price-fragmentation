# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import argparse
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# progress bar (optional)
try:
    from tqdm import tqdm
except Exception:
    def tqdm(x, **kwargs):
        return x

Z_DEFAULT = 1.96


def wilson_ci(k: int, n: int, z: float = Z_DEFAULT):
    n = float(n)
    if n <= 0:
        return (np.nan, np.nan)
    p = float(k) / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = (z * np.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0))) / den
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return lo, hi


def parse_time_utc(s: pd.Series) -> pd.Series:
    #统一：UTC + floor minute
    return pd.to_datetime(s, errors="coerce", utc=True).dt.floor("min")


def load_panel(panel_path: Path) -> pd.DataFrame:
    pn = pd.read_csv(panel_path)

    tcol = "time_utc_dt" if "time_utc_dt" in pn.columns else ("time_utc" if "time_utc" in pn.columns else None)
    if tcol is None:
        raise ValueError("[ERR] panel missing time column: need time_utc_dt or time_utc")

    pn["time_utc"] = parse_time_utc(pn[tcol])

    need_cols = ["time_utc", "max_share", "HHI_roll", "HHI", "dominant_exchange"]
    keep = [c for c in need_cols if c in pn.columns]
    pn = pn[keep].copy()

    # numeric cols
    for c in ["max_share", "HHI_roll", "HHI"]:
        if c in pn.columns:
            pn[c] = pd.to_numeric(pn[c], errors="coerce")

    if "dominant_exchange" in pn.columns:
        pn["dominant_exchange"] = pn["dominant_exchange"].astype(str)

    pn = pn.dropna(subset=["time_utc"]).drop_duplicates("time_utc", keep="last").sort_values("time_utc")
    pn = pn.set_index("time_utc", drop=True)
    return pn


def subsample_label(ts: pd.Series, scheme: str) -> pd.Series:
    # ts is datetime64[ns, UTC]
    if scheme == "year":
        return ts.dt.year.astype(str)
    if scheme == "halfyear":
        h = ((ts.dt.month - 1) // 6 + 1).astype(int)
        return ts.dt.year.astype(str) + "H" + h.astype(str)
    if scheme == "quarter":
        q = ts.dt.to_period("Q").astype(str)
        return q
    if scheme == "month":
        m = ts.dt.to_period("M").astype(str)
        return m
    raise ValueError(f"[ERR] unknown subsample scheme: {scheme}")


def plot_summary(df_sum: pd.DataFrame, outdir: Path, metric: str, scheme: str):
    """
    For each shock_type & lock_in, plot pivot_changed_rate over subsamples with one line per gamma.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    # ensure ordering of subsamples
    sub_order = sorted(df_sum["subsample"].unique().tolist())

    for shock_type in sorted(df_sum["shock_type"].unique()):
        for lock_in in sorted(df_sum["lock_in"].unique()):
            sub = df_sum[(df_sum["shock_type"] == shock_type) & (df_sum["lock_in"] == lock_in)].copy()
            if sub.empty:
                continue

            fig, ax = plt.subplots(figsize=(12, 4.8))

            for g in sorted(sub["gamma"].unique()):
                sg = sub[sub["gamma"] == g].copy()
                sg["subsample"] = pd.Categorical(sg["subsample"], categories=sub_order, ordered=True)
                sg = sg.sort_values("subsample")

                # draw line
                ax.plot(sg["subsample"].astype(str), sg["pivot_changed_rate"], marker="o", linewidth=1.2,
                        label=f"gamma={g:g}")

                # CI band as error bars
                y = sg["pivot_changed_rate"].to_numpy()
                ylo = sg["pivot_changed_ci_lo"].to_numpy()
                yhi = sg["pivot_changed_ci_hi"].to_numpy()
                err_lo = np.clip(y - ylo, 0, None)
                err_hi = np.clip(yhi - y, 0, None)
                ax.errorbar(sg["subsample"].astype(str), y, yerr=[err_lo, err_hi], fmt="none", capsize=2, linewidth=0.8)

            ax.set_ylim(0, 0.5)
            ax.set_ylabel("pivot changed rate")
            ax.set_xlabel("Subsample (year)")
            ax.grid(True, alpha=0.3)
            ax.legend(frameon=False, ncol=2, loc="upper right")

            title = f"Shock={shock_type}, lock-in={int(lock_in)}"
            ax.set_title(title)

            fig.tight_layout()
            out_png = outdir / f"Fig_subsample__metric_{metric}__scheme_{scheme}__shock_{shock_type}__lockin_{int(lock_in)}.png"
            fig.savefig(out_png, dpi=300, bbox_inches="tight")
            plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=r"D:\cilck here\2代目\experiments_dvonly\dvon_injection_shift_samples.csv")
    ap.add_argument("--panel", default=r"D:\cilck here\2代目\hhi_panel\btc_1m_panel_with_hhi.csv")
    ap.add_argument("--outdir", default=r"D:\cilck here\2代目\experiments_dvonly\subsample_robustness")
    ap.add_argument("--metric", default="max_share", choices=["max_share", "HHI_roll", "HHI"])
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--scheme", default="year", choices=["year", "halfyear", "quarter", "month"])
    ap.add_argument("--z", type=float, default=1.96)
    ap.add_argument("--chunksize", type=int, default=250_000)
    args = ap.parse_args()

    samples_path = Path(args.samples)
    panel_path = Path(args.panel)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not samples_path.exists():
        raise FileNotFoundError(f"[ERR] samples not found: {samples_path}")
    if not panel_path.exists():
        raise FileNotFoundError(f"[ERR] panel not found: {panel_path}")

    # 1) load panel (index = time_utc)
    print("[info] loading panel:", panel_path)
    pn = load_panel(panel_path)

    if args.metric not in pn.columns:
        raise ValueError(f"[ERR] panel missing metric column: {args.metric}. available={list(pn.columns)}")

    # 2) read samples in chunks, merge panel, compute subsample groups
    req = ["time_utc", "shock_type", "delta_w", "pivot_changed"]
    # your file has exactly these cols; keep minimal
    usecols = None  # read all (fast enough), or set to req + ...
    it = pd.read_csv(samples_path, chunksize=args.chunksize, usecols=usecols)

    all_parts = []
    for ch in tqdm(it, desc="load samples chunks"):
        if not all(c in ch.columns for c in req):
            missing = [c for c in req if c not in ch.columns]
            raise ValueError(f"[ERR] samples missing required columns: {missing}")

        ch["time_utc"] = parse_time_utc(ch["time_utc"])
        ch = ch.dropna(subset=["time_utc"]).copy()

        # gamma from delta_w
        ch["gamma"] = pd.to_numeric(ch["delta_w"], errors="coerce")
        ch["pivot_changed"] = pd.to_numeric(ch["pivot_changed"], errors="coerce").fillna(0).astype(int)

        # merge panel by time (left join)
        # panel indexed by time_utc
        ch = ch.join(pn[[args.metric] + ([c for c in ["dominant_exchange"] if c in pn.columns])], on="time_utc", how="left")

        # drop rows without metric (cannot define lock_in)
        ch = ch.dropna(subset=[args.metric, "gamma"]).copy()

        # lock_in definition
        ch["lock_in"] = (pd.to_numeric(ch[args.metric], errors="coerce") > args.threshold).astype(int)

        # subsample label
        ch["subsample"] = subsample_label(ch["time_utc"], args.scheme)

        # keep minimal for aggregation
        keep = ["shock_type", "gamma", "lock_in", "subsample", "pivot_changed", args.metric]
        all_parts.append(ch[keep])

    if not all_parts:
        raise RuntimeError("[ERR] no valid rows after merge+filter; check time alignment and metric availability")

    df = pd.concat(all_parts, ignore_index=True)

    # 3) aggregate: pivot_changed rate and Wilson CI per group
    gcols = ["shock_type", "gamma", "lock_in", "subsample"]
    agg = (
        df.groupby(gcols, as_index=False)
          .agg(n=("pivot_changed", "size"),
               k=("pivot_changed", "sum"),
               x_median=(args.metric, "median"))
    )
    agg["pivot_changed_rate"] = agg["k"] / agg["n"]
    ci = agg.apply(lambda r: wilson_ci(int(r["k"]), int(r["n"]), z=args.z), axis=1)
    agg["pivot_changed_ci_lo"] = [x[0] for x in ci]
    agg["pivot_changed_ci_hi"] = [x[1] for x in ci]
    agg["metric"] = args.metric
    agg["threshold"] = args.threshold

    # 4) save summary
    out_csv = outdir / f"subsample_robustness_summary__metric_{args.metric}__thr_{args.threshold}__scheme_{args.scheme}.csv"
    agg.sort_values(["shock_type", "gamma", "lock_in", "subsample"]).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("[saved]", out_csv, "shape=", agg.shape)

    # 5) plot
    figdir = outdir / "figs"
    plot_summary(agg, figdir, metric=args.metric, scheme=args.scheme)
    print("[done] figs saved to:", figdir)


if __name__ == "__main__":
    main()

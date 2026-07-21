from __future__ import annotations

from pathlib import Path
import argparse
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from tqdm import tqdm


def wilson_ci(k: int, n: int, z: float = 1.96):
    n = float(n)
    if n <= 0:
        return (np.nan, np.nan)
    p = float(k) / n
    den = 1.0 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = (z * np.sqrt(max(p*(1-p)/n + z*z/(4*n*n), 0.0))) / den
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return lo, hi


def pick_first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def parse_thresholds(s: str) -> list[float]:
    """
    Accept:
      - "0.45,0.5,0.55"
      - "linspace:0.45:0.60:9"  (min:max:num)
      - "arange:0.45:0.61:0.02" (start:stop:step) stop is inclusive-ish
    """
    s = s.strip()
    if s.startswith("linspace:"):
        _, a, b, n = s.split(":")
        return list(np.linspace(float(a), float(b), int(n)))
    if s.startswith("arange:"):
        _, a, b, step = s.split(":")
        a, b, step = float(a), float(b), float(step)
        xs = []
        x = a
        # include b with tolerance
        while x <= b + 1e-12:
            xs.append(float(np.round(x, 12)))
            x += step
        return xs
    # csv list
    return [float(x) for x in s.split(",") if x.strip()]


def summarize_for_threshold(
    df: pd.DataFrame,
    metric: str,
    thr: float,
    shock_col: str | None,
    gamma_col: str | None,
    pivot_changed_col: str,
    pivot_dom_col: str | None,
    z: float = 1.96,
):
    d = df.copy()
    d["lock_in"] = (pd.to_numeric(d[metric], errors="coerce") > thr).astype(int)

    group_cols = ["lock_in"]
    if shock_col:
        group_cols = [shock_col] + group_cols
    if gamma_col:
        group_cols = [gamma_col] + group_cols

    rows = []
    for keys, g in d.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_map = dict(zip(group_cols, keys))

        y = pd.to_numeric(g[pivot_changed_col], errors="coerce")
        y = y.dropna()
        n = int(len(y))
        k = int(y.sum()) if n > 0 else 0
        rate = (k / n) if n > 0 else np.nan
        lo, hi = wilson_ci(k, n, z=z) if n > 0 else (np.nan, np.nan)

        out = {
            "metric": metric,
            "threshold": thr,
            "n": n,
            "k": k,
            "pivot_changed_rate": rate,
            "pivot_changed_ci_lo": lo,
            "pivot_changed_ci_hi": hi,
            "x_median": float(np.nanmedian(pd.to_numeric(g[metric], errors="coerce"))),
        }
        out.update(key_map)

        if pivot_dom_col is not None:
            dom = pd.to_numeric(g[pivot_dom_col], errors="coerce").dropna()
            out["pivot_is_dominant_rate"] = float(dom.mean()) if len(dom) > 0 else np.nan

        # optional helpful columns if present
        for extra in ["HHI_roll", "HHI", "max_share", "pivot_margin_norm", "gap_norm"]:
            if extra in g.columns:
                out[f"{extra}_median"] = float(np.nanmedian(pd.to_numeric(g[extra], errors="coerce")))

        rows.append(out)

    return pd.DataFrame(rows)


def plot_rate_vs_threshold(summary: pd.DataFrame, out_png: Path, lock_in: int, shock_val: str, gamma_col: str | None):
    ss = summary.copy()
    ss = ss[ss["lock_in"] == lock_in]
    if "shock_type" in ss.columns:
        ss = ss[ss["shock_type"].astype(str) == str(shock_val)]

    if ss.empty:
        return

    fig, ax = plt.subplots(figsize=(10.5, 5.5))

    if gamma_col and (gamma_col in ss.columns):
        for g, sub in ss.groupby(gamma_col):
            sub = sub.sort_values("threshold")
            ax.plot(sub["threshold"], sub["pivot_changed_rate"], marker="o", label=f"{gamma_col}={g}")
            ax.fill_between(
                sub["threshold"],
                sub["pivot_changed_ci_lo"],
                sub["pivot_changed_ci_hi"],
                alpha=0.15,
            )
    else:
        sub = ss.sort_values("threshold")
        ax.plot(sub["threshold"], sub["pivot_changed_rate"], marker="o", label="pivot_changed_rate")
        ax.fill_between(sub["threshold"], sub["pivot_changed_ci_lo"], sub["pivot_changed_ci_hi"], alpha=0.15)

    metric = ss["metric"].iloc[0]
    ax.set_title("")
    ax.set_xlabel("Threshold")
    ax.set_ylabel("Pivot change rate")
    ax.set_ylim(0.0, 0.5)
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_share_lockin(df: pd.DataFrame, metric: str, thresholds: list[float], out_png: Path):
    x = pd.to_numeric(df[metric], errors="coerce")
    shares = []
    for thr in thresholds:
        shares.append(float(np.nanmean((x > thr).astype(float))))
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(thresholds, shares, marker="o")
    ax.set_title(f"Share(lock_in) vs threshold — metric={metric}")
    ax.set_xlabel("threshold")
    ax.set_ylabel("share(lock_in)")
    ax.set_ylim(-0.02, 1.02)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[2] / Path("experiments_dvonly/audit_lockin/dvonly_inference_dataset.csv")),
                    help="inference dataset or merged_for_audit csv")
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parents[2] / Path("experiments_dvonly/audit_lockin/threshold_robustness")))
    ap.add_argument("--metric", default="max_share", choices=["max_share", "HHI_roll", "HHI"])
    ap.add_argument("--thresholds", default="linspace:0.45:0.60:9",
                    help='e.g. "0.45,0.5,0.55" or "linspace:0.45:0.60:9" or "arange:0.45:0.61:0.02"')
    ap.add_argument("--z", type=float, default=1.96)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.data)

    # detect columns
    shock_col = pick_first_existing(df, ["shock_type"])
    gamma_col = pick_first_existing(df, ["gamma", "delta_w"])
    pivot_changed_col = pick_first_existing(df, ["pivot_changed"])
    if pivot_changed_col is None:
        raise ValueError("missing pivot_changed column in --data")

    pivot_dom_col = pick_first_existing(df, ["pivot_is_dominant", "pivot_is_dominant_before", "pivot_is_dominant_after"])

    # sanity
    if args.metric not in df.columns:
        raise ValueError(f"metric {args.metric} not in columns; available: {list(df.columns)[:30]} ...")

    thresholds = parse_thresholds(args.thresholds)

    all_summ = []
    for thr in tqdm(thresholds, desc="thresholds"):
        summ = summarize_for_threshold(
            df=df,
            metric=args.metric,
            thr=float(thr),
            shock_col=shock_col,
            gamma_col=gamma_col,
            pivot_changed_col=pivot_changed_col,
            pivot_dom_col=pivot_dom_col,
            z=args.z,
        )
        all_summ.append(summ)

    out = pd.concat(all_summ, ignore_index=True)
    out_csv = outdir / "threshold_robustness_summary.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("saved:", out_csv, "shape=", out.shape)

    # plot share(lock_in)
    share_png = outdir / f"Fig_share_lockin_vs_threshold__{args.metric}.png"
    plot_share_lockin(df, args.metric, thresholds, share_png)
    print("saved:", share_png)

    # determine shock values
    if shock_col and shock_col in df.columns:
        shock_vals = [str(x) for x in sorted(df[shock_col].dropna().unique())]
    else:
        shock_vals = ["overall"]

    # plot pivot_changed_rate vs threshold per shock_type
    for shock_val in shock_vals:
        for lock_in in [1, 0]:
            png = outdir / f"Fig_thr_robust__metric_{args.metric}__shock_{shock_val}__lockin_{lock_in}.png"
            plot_rate_vs_threshold(out, png, lock_in=lock_in, shock_val=shock_val, gamma_col=gamma_col)
            if png.exists():
                print("saved:", png)


if __name__ == "__main__":
    main()

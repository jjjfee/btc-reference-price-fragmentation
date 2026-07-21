from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless safe
import matplotlib.pyplot as plt


def infer_xcol(df: pd.DataFrame) -> str:
    """Infer x-axis mid column from common candidates."""
    candidates = [
        "max_share_mid",
        "hhi_roll_mid",
        "HHI_roll_mid",
        "HHI_mid",
        "hhi_mid",
        "x_mid",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(
        "Cannot infer x-axis column. Expected one of: "
        + ", ".join(candidates)
        + f". Found columns: {list(df.columns)[:30]}..."
    )


def plot_one(
    df: pd.DataFrame,
    xcol: str,
    shock_type: str,
    out_prefix: Path,
    title: str | None = None,
    xlabel: str | None = None,
    ylabel: str = "Pivot switch rate (pivot_changed)",
    ylim: tuple[float, float] = (0.0, 1.0),
    show_ci: bool = True,
):
    required = {"gamma", "pivot_rate", xcol}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Filter shock_type if column exists
    if "shock_type" in df.columns and shock_type != "ALL":
        df = df[df["shock_type"].astype(str) == shock_type].copy()
        if df.empty:
            raise ValueError(f"No rows after filtering shock_type={shock_type}")

    # Clean types
    df["gamma"] = pd.to_numeric(df["gamma"], errors="coerce")
    df[xcol] = pd.to_numeric(df[xcol], errors="coerce")
    df["pivot_rate"] = pd.to_numeric(df["pivot_rate"], errors="coerce")

    df = df.dropna(subset=["gamma", xcol, "pivot_rate"]).copy()

    # CI availability
    ci_ok = show_ci and ("ci_lo" in df.columns) and ("ci_hi" in df.columns)
    if ci_ok:
        df["ci_lo"] = pd.to_numeric(df["ci_lo"], errors="coerce")
        df["ci_hi"] = pd.to_numeric(df["ci_hi"], errors="coerce")

    # Sort for nice lines
    df = df.sort_values([ "gamma", xcol ])

    fig, ax = plt.subplots(figsize=(9, 5))

    for g, sub in df.groupby("gamma", sort=True):
        sub = sub.sort_values(xcol)
        x = sub[xcol].to_numpy()
        y = sub["pivot_rate"].to_numpy()

        # line
        ax.plot(x, y, marker="o", linewidth=1.5, markersize=3.5, label=f"gamma={g:g}")

        # CI band
        if ci_ok:
            lo = sub["ci_lo"].to_numpy()
            hi = sub["ci_hi"].to_numpy()
            ok = np.isfinite(lo) & np.isfinite(hi) & np.isfinite(x)
            if ok.any():
                ax.fill_between(x[ok], lo[ok], hi[ok], alpha=0.18)

    ax.set_ylim(*ylim)
    ax.set_xlabel(xlabel if xlabel else xcol)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)

    if title is None:
        st = shock_type
        if "shock_type" not in df.columns:
            st = "(no shock_type column)"
        title = f"Pivot boundary curve ({xcol}) | shock_type={st}"
    ax.set_title(title)

    # Legend outside (keeps plot clean)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)

    fig.tight_layout()

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    png = out_prefix.with_suffix(".png")
    pdf = out_prefix.with_suffix(".pdf")
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)

    return png, pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--bins",
        type=str,
        required=True,
        help="Path to pivot boundary bins CSV (e.g., pivot_boundary_curve_bins_maxshare.csv)",
    )
    ap.add_argument(
        "--outdir",
        type=str,
        default=str(Path(__file__).resolve().parents[2] / "outputs" / "main_text" / "figures"),
        help="Output directory for figures",
    )
    ap.add_argument(
        "--shock-type",
        type=str,
        default="inflate_only",
        help='shock_type to plot; use "ALL" to plot each shock_type separately (if column exists)',
    )
    ap.add_argument(
        "--xcol",
        type=str,
        default="",
        help="Optional: explicitly set x-axis column (e.g., max_share_mid or hhi_roll_mid)",
    )
    ap.add_argument("--no-ci", action="store_true", help="Disable CI band even if columns exist")
    ap.add_argument("--title", type=str, default="", help="Optional figure title")
    ap.add_argument("--xlabel", type=str, default="", help="Optional x-axis label")

    args = ap.parse_args()

    bins_path = Path(args.bins)
    if not bins_path.exists():
        raise FileNotFoundError(f"bins file not found: {bins_path}")

    df = pd.read_csv(bins_path)  # pandas.read_csv docs: supports Path-like
    xcol = args.xcol.strip() or infer_xcol(df)

    outdir = Path(args.outdir)
    stem = bins_path.stem

    show_ci = not args.no_ci
    title = args.title.strip() or None
    xlabel = args.xlabel.strip() or None

    # If shock_type column exists and user wants ALL, plot each separately
    if args.shock_type == "ALL" and "shock_type" in df.columns:
        shock_types = sorted(df["shock_type"].astype(str).dropna().unique().tolist())
        for st in shock_types + ["overall"] if "overall" in shock_types else shock_types:
            out_prefix = outdir / f"{stem}__shock_{st}__x_{xcol}"
            png, pdf = plot_one(
                df=df,
                xcol=xcol,
                shock_type=st,
                out_prefix=out_prefix,
                title=title,
                xlabel=xlabel,
                show_ci=show_ci,
            )
            print("saved:", png)
            print("saved:", pdf)
    else:
        st = args.shock_type
        out_prefix = outdir / f"{stem}__shock_{st}__x_{xcol}"
        png, pdf = plot_one(
            df=df,
            xcol=xcol,
            shock_type=st,
            out_prefix=out_prefix,
            title=title,
            xlabel=xlabel,
            show_ci=show_ci,
        )
        print("saved:", png)
        print("saved:", pdf)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", repr(e), file=sys.stderr)
        sys.exit(1)

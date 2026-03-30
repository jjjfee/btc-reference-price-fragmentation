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
    from tqdm import tqdm  # pip install tqdm
except Exception:
    def tqdm(x, **kwargs):
        return x


EXCH_ORDER_DEFAULT = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]


def weighted_median_with_pivot(p: np.ndarray, w: np.ndarray, exch: list[str]):
    """Return (lwmp_price, pivot_exchange, pivot_margin, total_w)."""
    m = np.isfinite(p) & np.isfinite(w) & (w > 0)
    if not np.any(m):
        return (np.nan, None, np.nan, 0.0)

    p2 = p[m]
    w2 = w[m]
    exch2 = [exch[i] for i in np.where(m)[0]]

    order = np.argsort(p2, kind="mergesort")
    p2 = p2[order]
    w2 = w2[order]
    exch2 = [exch2[i] for i in order]

    cw = np.cumsum(w2)
    tot = float(cw[-1])
    half = 0.5 * tot
    idx = int(np.searchsorted(cw, half, side="left"))
    pivot_margin = float(cw[idx] - half)  # >=0 by construction (up to num. error)
    return (float(p2[idx]), exch2[idx], pivot_margin, tot)


def load_panel(panel_path: Path):
    pn = pd.read_csv(panel_path)
    tcol = "time_utc_dt" if "time_utc_dt" in pn.columns else "time_utc"
    pn["time_utc"] = pd.to_datetime(pn[tcol], errors="coerce", utc=True).dt.floor("min")

    for c in ["max_share", "HHI_roll", "HHI"]:
        if c in pn.columns:
            pn[c] = pd.to_numeric(pn[c], errors="coerce")

    if "dominant_exchange" in pn.columns:
        pn["dominant_exchange"] = pn["dominant_exchange"].astype(str)

    pn = pn.dropna(subset=["time_utc", "max_share", "dominant_exchange"]).copy()
    pn = pn.sort_values("time_utc")
    return pn


def find_crossing_episodes(pn: pd.DataFrame, threshold: float, min_lockin_minutes: int, top_k: int):
    """
    Simple heuristic: find 'cross up' points (<=thr -> >thr) and keep those
    where the subsequent lock-in segment lasts at least min_lockin_minutes.
    Returns list of (t_cross, lock_end, dur_minutes, t_cross).
    """
    lock = (pn["max_share"] > threshold).astype(int)
    prev = lock.shift(1).fillna(0).astype(int)
    cross_up = (prev == 0) & (lock == 1)
    starts = pn.loc[cross_up, "time_utc"].to_list()

    episodes = []
    for st in starts:
        seg = pn[pn["time_utc"] >= st]
        end_rows = seg[(seg["max_share"] <= threshold)]
        if len(end_rows) > 0:
            ed = end_rows["time_utc"].iloc[0]
        else:
            ed = pn["time_utc"].iloc[-1] + pd.Timedelta(minutes=1)

        dur = int((ed - st) / pd.Timedelta(minutes=1))
        if dur >= min_lockin_minutes:
            episodes.append((st, ed, dur, st))

    episodes.sort(key=lambda x: x[2], reverse=True)
    return episodes[:top_k]


def find_clean_crossings(pn: pd.DataFrame,
                         threshold: float,
                         pre_below: int = 60,
                         post_above: int = 120,
                         top_k: int = 3):
    """
    Strict 'clean crossing':
      - there exists a rising edge at t_cross: max_share(t-1) <= thr and max_share(t) > thr
      - the previous pre_below minutes are all <= thr
      - the next post_above minutes are all > thr
    Returns list of (t_cross, lock_end, dur_minutes, t_cross).
    """
    pn = pn.sort_values("time_utc").reset_index(drop=True).copy()
    x = pn["max_share"].to_numpy(dtype=float)
    t = pn["time_utc"]

    above = (x > threshold)
    cross_idx = np.where((~above[:-1]) & (above[1:]))[0] + 1

    episodes = []
    n = len(pn)
    for i in cross_idx:
        i0 = i - pre_below
        j1 = i + post_above
        if i0 < 0 or j1 > n:
            continue

        if not np.all(x[i0:i] <= threshold):
            continue
        if not np.all(x[i:j1] > threshold):
            continue

        # lock segment end: first index after i where above becomes False
        end_i = None
        tail_false = np.where(~above[i:])[0]
        if len(tail_false) > 0:
            end_i = i + int(tail_false[0])
            ed = t.iloc[end_i]
        else:
            ed = t.iloc[-1] + pd.Timedelta(minutes=1)

        st = t.iloc[i]
        dur = int((ed - st) / pd.Timedelta(minutes=1))
        episodes.append((st, ed, dur, st))

    episodes.sort(key=lambda x: x[2], reverse=True)
    return episodes[:top_k]


def load_dv_slice(dv_dir: Path,
                  start: pd.Timestamp,
                  end: pd.Timestamp,
                  exch_order: list[str],
                  time_col="time_utc",
                  price_col="p_usd_scaled",
                  w_col="DV_usd"):
    """
    Load only [start,end] slice from each exchange dv_ready file using chunk scan.
    Return wide price/weight DataFrames indexed by time_utc with columns = exchanges.
    """
    files = list(dv_dir.glob("BTCUSD_1m_*_2021_2022_with_DV.csv"))
    if not files:
        raise FileNotFoundError(f"No dv_ready files in {dv_dir}")

    exch_to_file = {}
    for fp in files:
        name = fp.name
        parts = name.split("_")
        if len(parts) < 6:
            continue
        exch = parts[2]  # BTCUSD_1m_<Exchange>_...
        exch_to_file[exch] = fp

    price_wide = None
    weight_wide = None

    # outer progress (exchanges)
    for exch in tqdm(exch_order, desc="load dv slices (exchanges)", unit="exch"):
        if exch not in exch_to_file:
            continue
        fp = exch_to_file[exch]

        usecols = [time_col, price_col, w_col]
        chunks = pd.read_csv(fp, usecols=lambda c: c in usecols, chunksize=250_000)

        keep_parts = []
        for ch in tqdm(chunks, desc=f"scan {exch} chunks", unit="chunk", leave=False):
            ch = ch.rename(columns={time_col: "time_utc", price_col: "price", w_col: "w"})
            ch["time_utc"] = pd.to_datetime(ch["time_utc"], errors="coerce", utc=True).dt.floor("min")
            ch = ch.dropna(subset=["time_utc"])
            ch = ch[(ch["time_utc"] >= start) & (ch["time_utc"] <= end)]
            if len(ch) > 0:
                ch["price"] = pd.to_numeric(ch["price"], errors="coerce")
                ch["w"] = pd.to_numeric(ch["w"], errors="coerce")
                keep_parts.append(ch[["time_utc", "price", "w"]])

        if not keep_parts:
            continue

        d = pd.concat(keep_parts, ignore_index=True).drop_duplicates("time_utc", keep="last")
        d = d.set_index("time_utc").sort_index()

        pcol = f"p_{exch}"
        wcol2 = f"w_{exch}"
        d = d.rename(columns={"price": pcol, "w": wcol2})

        if price_wide is None:
            price_wide = d[[pcol]]
            weight_wide = d[[wcol2]]
        else:
            price_wide = price_wide.join(d[[pcol]], how="outer")
            weight_wide = weight_wide.join(d[[wcol2]], how="outer")

    if price_wide is None:
        raise RuntimeError("No exchange slices loaded (check dv_dir and exchange names).")

    return price_wide.sort_index(), weight_wide.sort_index()


def compute_baseline_pivot_series(price_wide: pd.DataFrame, weight_wide: pd.DataFrame, exch_order: list[str]):
    """
    For each minute in the union index, compute:
    - pivot_exchange (baseline)
    - pivot_margin_norm = pivot_margin / total_w
    - lwmp price and vwap price (baseline)
    """
    idx = price_wide.index.union(weight_wide.index).sort_values()
    price_wide = price_wide.reindex(idx)
    weight_wide = weight_wide.reindex(idx)

    cols_p = [f"p_{e}" for e in exch_order if f"p_{e}" in price_wide.columns]
    exch_from_p = [c.replace("p_", "") for c in cols_p]

    exch2, pcols2, wcols2 = [], [], []
    for e in exch_from_p:
        if f"w_{e}" in weight_wide.columns:
            exch2.append(e)
            pcols2.append(f"p_{e}")
            wcols2.append(f"w_{e}")

    P = price_wide[pcols2].to_numpy()
    W = weight_wide[wcols2].to_numpy()

    out = []
    for i in tqdm(range(len(idx)), total=len(idx), desc="compute pivots (minutes)", unit="min"):
        t = idx[i]
        p = P[i, :].astype(float)
        w = W[i, :].astype(float)

        m = np.isfinite(p) & np.isfinite(w) & (w > 0)
        if np.any(m):
            vwap = float(np.sum(p[m] * w[m]) / np.sum(w[m]))
        else:
            vwap = np.nan

        lwmp, piv_exch, piv_margin, totw = weighted_median_with_pivot(p, w, exch2)
        piv_margin_norm = (piv_margin / totw) if (totw > 0 and np.isfinite(piv_margin)) else np.nan

        out.append((t, vwap, lwmp, piv_exch, piv_margin_norm))

    res = pd.DataFrame(out, columns=["time_utc", "p_vwap", "p_lwmp", "pivot_exchange", "pivot_margin_norm"])
    res = res.set_index("time_utc")
    return res


def plot_episode(df: pd.DataFrame,
                 threshold: float,
                 title: str,
                 out_png: Path,
                 t_cross: pd.Timestamp | None = None):
    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)

    # (1) concentration
    axes[0].plot(df.index, df["max_share"], label="max_share")
    axes[0].axhline(threshold, linestyle="--", linewidth=1.2, label=f"{threshold:.2f} threshold")
    if "HHI_roll" in df.columns and df["HHI_roll"].notna().any():
        axes[0].plot(df.index, df["HHI_roll"], label="HHI_roll")
    axes[0].set_ylabel("Concentration")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(frameon=False, loc="best")

    # (2) lock-in & pivot==dominant
    axes[1].plot(df.index, df["lock_in"], label=f"lock_in (max_share>{threshold:.2f})")
    axes[1].plot(df.index, df["pivot_is_dominant"], label="pivot==dominant")
    axes[1].set_ylim(-0.05, 1.05)
    axes[1].set_ylabel("Indicators")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(frameon=False, loc="best")

    # (3) prices
    axes[2].plot(df.index, df["p_lwmp"], label="LWMP (baseline)")
    axes[2].plot(df.index, df["p_vwap"], label="VWAP (baseline)")
    axes[2].set_ylabel("Price (USD, scaled)")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(frameon=False, loc="best")

    # (4) mechanism: pivot_margin_norm vs max_share-threshold
    axes[3].plot(df.index, df["pivot_margin_norm"], label="pivot_margin_norm")
    axes[3].plot(df.index, df["max_share"] - threshold, label=f"max_share - {threshold:.2f}")
    axes[3].axhline(0.0, linestyle="--", linewidth=1.0)
    axes[3].set_ylabel("Slack / lower bound")
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(frameon=False, loc="best")

    # vertical line at crossing
    if t_cross is not None and pd.notna(t_cross):
        for ax in axes:
            ax.axvline(t_cross, linestyle="--", linewidth=1.0, alpha=0.7)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=r"D:\cilck here\2代目\hhi_panel\btc_1m_panel_with_hhi.csv")
    ap.add_argument("--dv-dir", default=r"D:\cilck here\2代目\dv_ready_2021_2022")
    ap.add_argument("--outdir", default=r"D:\cilck here\2代目\paper_outputs_frl\episodes_lockin")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--min-lockin-minutes", type=int, default=60)

    # plotting window around t_cross
    ap.add_argument("--pre-minutes", type=int, default=120)
    ap.add_argument("--post-minutes", type=int, default=240)

    # strict clean-crossing filter
    ap.add_argument("--no-clean-crossing", action="store_true",
                    help="disable strict clean-crossing filter; use simple lock-in episodes")
    ap.add_argument("--clean-pre-below", type=int, default=60,
                    help="require this many minutes <= threshold before crossing")
    ap.add_argument("--clean-post-above", type=int, default=120,
                    help="require this many minutes > threshold after crossing")

    ap.add_argument("--exchanges", nargs="*", default=EXCH_ORDER_DEFAULT)
    ap.add_argument("--start", default=None, help="optional episode start/cross time (UTC ISO)")
    ap.add_argument("--end", default=None, help="optional episode end time (UTC ISO)")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    pn = load_panel(Path(args.panel))

    # Decide episodes
    if args.start and args.end:
        t_cross = pd.to_datetime(args.start, utc=True)
        ed = pd.to_datetime(args.end, utc=True)
        episodes = [(t_cross, ed, int((ed - t_cross) / pd.Timedelta(minutes=1)), t_cross)]
        print("[info] using manual episode window.")
    else:
        episodes = []
        if not args.no_clean_crossing:
            episodes = find_clean_crossings(
                pn,
                threshold=args.threshold,
                pre_below=args.clean_pre_below,
                post_above=args.clean_post_above,
                top_k=args.top_k
            )
            if episodes:
                print(f"[info] using CLEAN crossings: {len(episodes)} episode(s).")
            else:
                print("[warn] no clean crossings found; fallback to simple lock-in episodes.")

        if not episodes:
            episodes = find_crossing_episodes(
                pn, threshold=args.threshold,
                min_lockin_minutes=args.min_lockin_minutes,
                top_k=args.top_k
            )
            if not episodes:
                raise RuntimeError("No episodes found. Try lowering thresholds/constraints.")
            print(f"[info] using SIMPLE episodes: {len(episodes)} episode(s).")

    # Process episodes
    for i, (st, ed, dur, t_cross) in enumerate(tqdm(episodes, desc="episodes", unit="ep"), start=1):
        # window around t_cross (NOT around st by definition)
        wst = t_cross - pd.Timedelta(minutes=args.pre_minutes)
        wed = t_cross + pd.Timedelta(minutes=args.post_minutes)

        wst = max(wst, pn["time_utc"].min())
        wed = min(wed, pn["time_utc"].max())

        # slice panel
        seg = pn[(pn["time_utc"] >= wst) & (pn["time_utc"] <= wed)].copy()
        seg = seg.set_index("time_utc").sort_index()
        seg["lock_in"] = (seg["max_share"] > args.threshold).astype(int)

        # load dv slice and compute baseline pivot/margins
        price_wide, weight_wide = load_dv_slice(Path(args.dv_dir), wst, wed, args.exchanges)
        piv = compute_baseline_pivot_series(price_wide, weight_wide, args.exchanges)

        # merge
        df = seg.join(piv, how="left")
        df["pivot_is_dominant"] = (
            df["pivot_exchange"].astype(str) == df["dominant_exchange"].astype(str)
        ).astype(int)

        # dominant label (mode)
        dominant = df["dominant_exchange"].dropna().mode()
        dominant = dominant.iloc[0] if len(dominant) else "NA"

        # save csv for audit
        csv_out = outdir / f"episode_{i:02d}_cross_{t_cross.strftime('%Y%m%d_%H%M')}_UTC.csv"
        df.reset_index().to_csv(csv_out, index=False, encoding="utf-8-sig")

        # plot
        title = f"Lock-in episode #{i} | cross={t_cross} UTC | dominant={dominant}"
        png_out = outdir / f"Fig_episode_{i:02d}_lockin_path.png"
        plot_episode(df, threshold=args.threshold, title=title, out_png=png_out, t_cross=t_cross)

        print("saved:", csv_out)
        print("saved:", png_out)


if __name__ == "__main__":
    main()

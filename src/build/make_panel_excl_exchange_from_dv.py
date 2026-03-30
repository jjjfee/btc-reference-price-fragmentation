from __future__ import annotations

from pathlib import Path
import argparse
import numpy as np
import pandas as pd

# Optional progress bars
try:
    from tqdm import tqdm
except Exception:
    tqdm = None


def _tqdm(iterable, **kwargs):
    if tqdm is None:
        return iterable
    return tqdm(iterable, **kwargs)


def parse_exchange_from_filename(fp: Path) -> str | None:
    """
    Expect: BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv
    """
    name = fp.name
    parts = name.split("_")
    if len(parts) < 6:
        return None
    # BTCUSD, 1m, Exchange, 2021, 2022, with, DV.csv  (sometimes 'with_DV.csv' as two parts)
    return parts[2]


def load_weight_series_csv(
    fp: Path,
    time_col: str,
    w_col: str,
    chunksize: int,
) -> pd.Series:
    """
    Load one exchange's DV weights into a Series indexed by minute time_utc (UTC tz-aware).
    Invalid/nonpositive weights are set to 0.
    """
    usecols = None  # safe with lambda
    parts = []

    reader = pd.read_csv(
        fp,
        usecols=lambda c: c in {time_col, w_col},
        chunksize=chunksize,
        low_memory=True,
    )

    chunk_iter = _tqdm(reader, desc=f"scan {fp.stem} chunks", unit="chunk")
    for ch in chunk_iter:
        if time_col not in ch.columns or w_col not in ch.columns:
            continue

        t = pd.to_datetime(ch[time_col], errors="coerce", utc=True).dt.floor("min")
        w = pd.to_numeric(ch[w_col], errors="coerce")

        tmp = pd.DataFrame({"time_utc": t, "w": w})
        tmp = tmp.dropna(subset=["time_utc"])
        # Clean weights: non-finite or <=0 -> 0
        tmp["w"] = pd.to_numeric(tmp["w"], errors="coerce")
        tmp.loc[~np.isfinite(tmp["w"].to_numpy()), "w"] = 0.0
        tmp.loc[tmp["w"] <= 0, "w"] = 0.0

        # Keep last record per minute within chunk
        tmp = tmp.drop_duplicates("time_utc", keep="last")
        parts.append(tmp)

    if not parts:
        raise RuntimeError(f"No data loaded from {fp}")

    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates("time_utc", keep="last").sort_values("time_utc")
    s = df.set_index("time_utc")["w"].astype("float64")
    return s


def roll_apply(x: pd.Series, window: int, how: str) -> pd.Series:
    r = x.rolling(window=window, min_periods=1)
    how = how.lower()
    if how == "mean":
        return r.mean()
    if how == "median":
        return r.median()
    if how == "sum":
        return r.sum()
    raise ValueError(f"Unknown roll method: {how} (use mean/median/sum)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dv-dir", required=True, help="dv_ready_2021_2022 directory")
    ap.add_argument("--panel-in", required=True, help="existing panel csv, e.g. btc_1m_panel_with_hhi.csv")
    ap.add_argument("--out", required=True, help="output panel csv path")

    ap.add_argument("--exclude", nargs="*", default=["Binance"], help="exchange(s) to exclude, default Binance")
    ap.add_argument("--time-col", default="time_utc", help="time column name in dv_ready csv")
    ap.add_argument("--w-col", default="DV_usd", help="weight column name in dv_ready csv")
    ap.add_argument("--chunksize", type=int, default=250_000)

    ap.add_argument("--roll-window", type=int, default=60, help="HHI_roll window in minutes (default 60)")
    ap.add_argument("--roll-method", default="mean", help="rolling method: mean/median/sum (default mean)")

    ap.add_argument("--asset-prefix", default="BTCUSD_1m_", help="file prefix filter (default BTCUSD_1m_)")
    ap.add_argument("--audit-out", default=None, help="optional audit csv output (dominant counts, etc.)")

    args = ap.parse_args()

    dv_dir = Path(args.dv_dir)
    panel_in = Path(args.panel_in)
    out = Path(args.out)

    exclude = set([str(x) for x in args.exclude])
    assert args.roll_window >= 1

    # ---- discover dv files
    files = sorted(dv_dir.glob(f"{args.asset_prefix}*_2021_2022_with_DV.csv"))
    if not files:
        raise FileNotFoundError(f"[ERR] no dv files found in {dv_dir} with pattern {args.asset_prefix}*_2021_2022_with_DV.csv")

    exch_to_file: dict[str, Path] = {}
    for fp in files:
        exch = parse_exchange_from_filename(fp)
        if exch:
            exch_to_file[exch] = fp

    keep_exchanges = [e for e in sorted(exch_to_file.keys()) if e not in exclude]
    if not keep_exchanges:
        raise RuntimeError(f"[ERR] after exclude={sorted(exclude)}, no exchanges left. found={sorted(exch_to_file.keys())}")

    print(f"[info] exclude={sorted(exclude)}")
    print(f"[info] using exchanges ({len(keep_exchanges)}): {keep_exchanges}")

    # ---- load DV weight series per exchange
    series = {}
    for e in _tqdm(keep_exchanges, desc="load dv weights (exchanges)", unit="exch"):
        fp = exch_to_file[e]
        s = load_weight_series_csv(fp, time_col=args.time_col, w_col=args.w_col, chunksize=args.chunksize)
        series[e] = s.rename(e)

    # ---- build wide weights
    W = pd.concat(series.values(), axis=1).sort_index()
    W = W.fillna(0.0)

    # total weight per minute
    total_w = W.sum(axis=1).astype("float64")
    valid = total_w > 0

    # shares (only where valid)
    denom = total_w.where(valid, np.nan)
    S = W.div(denom, axis=0)

    # metrics
    max_share = S.max(axis=1)
    # idxmax returns a label even if all NaN; guard with valid
    dominant = pd.Series(np.where(valid.to_numpy(), S.idxmax(axis=1).to_numpy(), None), index=S.index, dtype="object")

    hhi = (S ** 2).sum(axis=1)
    hhi_roll = roll_apply(hhi, window=args.roll_window, how=args.roll_method)

    # ---- column naming (use exactly what you asked if excluding Binance only)
    if exclude == {"Binance"}:
        suf = "_excl_binance"
    else:
        suf = "_excl_" + "_".join([x.lower() for x in sorted(exclude)])

    out_cols = pd.DataFrame(
        {
            f"max_share{suf}": max_share.astype("float64"),
            f"HHI{suf}": hhi.astype("float64"),
            f"HHI_roll{suf}": hhi_roll.astype("float64"),
            f"dominant_exchange{suf}": dominant.astype("object"),
        }
    )
    out_cols.index.name = "time_utc"

    # ---- merge into existing panel
    pn = pd.read_csv(panel_in)
    tcol = "time_utc_dt" if "time_utc_dt" in pn.columns else ("time_utc" if "time_utc" in pn.columns else None)
    if tcol is None:
        raise ValueError("[ERR] panel-in has no time_utc_dt or time_utc column")

    pn["time_utc"] = pd.to_datetime(pn[tcol], errors="coerce", utc=True).dt.floor("min")
    pn = pn.dropna(subset=["time_utc"]).copy()
    pn = pn.sort_values("time_utc")

    merged = pn.merge(out_cols.reset_index(), on="time_utc", how="left")

    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[saved] panel: {out} shape={merged.shape}")

    # ---- audit outputs (optional but recommended)
    audit_path = Path(args.audit_out) if args.audit_out else out.with_name(out.stem + "__audit.csv")

    aud = pd.DataFrame(
        {
            "minutes_total": [len(out_cols)],
            "minutes_valid": [int(valid.sum())],
            "share_max_share_gt_0p5": [float((max_share > 0.5).mean(skipna=True))],
            "max_share_median": [float(max_share.median(skipna=True))],
            "HHI_median": [float(hhi.median(skipna=True))],
            "HHI_roll_median": [float(hhi_roll.median(skipna=True))],
            "exclude": [",".join(sorted(exclude))],
            "roll_window": [args.roll_window],
            "roll_method": [args.roll_method],
        }
    )

    # dominant counts (top 10)
    dom_counts = dominant.value_counts(dropna=True).head(10).rename_axis("dominant_exchange").reset_index(name="count")
    dom_counts["share"] = dom_counts["count"] / max(1, int(valid.sum()))

    # write audit as two blocks (simple & readable)
    with open(audit_path, "w", encoding="utf-8-sig") as f:
        aud.to_csv(f, index=False)
        f.write("\n")
        dom_counts.to_csv(f, index=False)

    print(f"[saved] audit: {audit_path}")
    print("[done]")


if __name__ == "__main__":
    main()

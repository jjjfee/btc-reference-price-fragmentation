# run_exclude_exchange_dvonly.py
# ============================================================
# DV-only injection with excluded exchanges (e.g., exclude Binance)
# - Standalone (no dependency on run_dv_only_injection_experiments.py)
# - Chunked CSV loading + tqdm progress bars
# - Incremental CSV writing (append per scenario)
#
# Output:
#   <outdir>/dvon_injection_shift_samples__exclude_<...>.csv   (event-level, ~N*len(delta_w)*2 rows)
#   <outdir>/base_minute_metrics__exclude_<...>.csv           (minute-level, N rows)
#
# Usage example (Windows):
#   python "<PROJECT_ROOT>\experiments_dvonly\run_exclude_exchange_dvonly.py" ^
#     --dv-dir "<PROJECT_ROOT>\dv_ready_2021_2022" ^
#     --outdir "<PROJECT_ROOT>\experiments_dvonly\exclude_binance" ^
#     --exclude Binance ^
#     --n-sample-minutes 100000
# ============================================================

from __future__ import annotations

from pathlib import Path
import argparse
import re
import sys
import numpy as np
import pandas as pd

# tqdm optional
try:
    from tqdm import tqdm
except Exception:
    def tqdm(x, **kwargs):
        return x

EXCH_ORDER_DEFAULT = ["Binance","Bitfinex","BitMEX","Bitstamp","Coinbase","KuCoin","OKX"]


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


def parse_exchange_from_filename(name: str) -> str | None:
    # BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv
    m = re.match(r"BTCUSD_1m_(.+?)_2021_2022_with_DV\.csv$", name)
    if not m:
        return None
    return m.group(1)


def load_exchange_series(
    fp: Path,
    time_col: str,
    price_col: str,
    w_col: str,
    chunksize: int = 250_000
) -> tuple[pd.Series, pd.Series]:
    """
    Load one exchange DV-ready CSV into two Series indexed by time_utc (minute):
    - price: float
    - weight: float
    Keep last observation per minute (drop_duplicates keep last).
    """
    usecols = [time_col, price_col, w_col]
    parts = []

    it = pd.read_csv(fp, usecols=lambda c: c in usecols, chunksize=chunksize)
    for ch in tqdm(it, desc=f"scan {fp.stem}", unit="chunk"):
        ch = ch.rename(columns={time_col: "time_utc", price_col: "p", w_col: "w"})
        ch["time_utc"] = pd.to_datetime(ch["time_utc"], errors="coerce", utc=True).dt.floor("min")
        ch = ch.dropna(subset=["time_utc"])

        ch["p"] = pd.to_numeric(ch["p"], errors="coerce")
        ch["w"] = pd.to_numeric(ch["w"], errors="coerce")

        # NOTE: do NOT drop w<=0 here; keep for alignment; cleaning happens later
        parts.append(ch[["time_utc", "p", "w"]])

    if not parts:
        raise RuntimeError(f"empty read: {fp}")

    d = pd.concat(parts, ignore_index=True)
    d = d.dropna(subset=["time_utc"])
    d = d.drop_duplicates("time_utc", keep="last").sort_values("time_utc")
    d = d.set_index("time_utc")
    return d["p"], d["w"]


def clean_pw(P: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Cleaning consistent with your pipeline:
    invalid price/weight or w<=0 -> w=0, p=nan (excluded)
    """
    P2 = P.astype(float, copy=True)
    W2 = W.astype(float, copy=True)
    bad = (~np.isfinite(P2)) | (~np.isfinite(W2)) | (W2 <= 0)
    W2[bad] = 0.0
    P2[bad] = np.nan
    return P2, W2


def vwap(P: np.ndarray, W: np.ndarray) -> np.ndarray:
    num = np.nansum(P * W, axis=1)
    den = np.nansum(W, axis=1)
    out = np.full(P.shape[0], np.nan, dtype=float)
    m = den > 0
    out[m] = num[m] / den[m]
    return out


def mean_unweighted(P: np.ndarray) -> np.ndarray:
    return np.nanmean(P, axis=1)


def median_unweighted(P: np.ndarray) -> np.ndarray:
    return np.nanmedian(P, axis=1)


def lwmp_with_pivot(P: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized LWMP (weighted median) with pivot column and pivot margin.
    Returns:
      lwmp_price: (N,)
      pivot_col:  (N,) int in [0,M-1], or -1 if no valid
      pivot_margin: (N,) cw[idx] - 0.5*totw
      totw: (N,)
    """
    N, M = P.shape
    P2 = P.copy()
    W2 = W.copy()

    # invalid -> weight 0, price inf for sorting (weight 0 won't affect cumw)
    invalid = (~np.isfinite(P2)) | (~np.isfinite(W2)) | (W2 <= 0)
    W2[invalid] = 0.0
    Psort = P2.copy()
    Psort[invalid] = np.inf

    order = np.argsort(Psort, axis=1, kind="mergesort")
    Ps = np.take_along_axis(P2, order, axis=1)
    Ws = np.take_along_axis(W2, order, axis=1)

    cw = np.cumsum(Ws, axis=1)
    totw = cw[:, -1]
    half = 0.5 * totw

    ge = cw >= half[:, None]
    idx = ge.argmax(axis=1).astype(int)

    # handle totw==0 -> pivot invalid
    pivot_col = order[np.arange(N), idx]
    lwmp_price = Ps[np.arange(N), idx]
    pivot_margin = cw[np.arange(N), idx] - half

    bad = totw <= 0
    pivot_col = pivot_col.astype(int)
    pivot_col[bad] = -1
    lwmp_price[bad] = np.nan
    pivot_margin[bad] = np.nan

    return lwmp_price, pivot_col, pivot_margin, totw


def sample_uniform_valid_index(W_clean: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """
    For each row, pick one column uniformly among W_clean>0.
    Assumes each row has at least one valid column.
    """
    valid = (W_clean > 0).astype(float)
    s = valid.sum(axis=1, keepdims=True)
    prob = valid / s
    cdf = np.cumsum(prob, axis=1)
    u = rng.random(W_clean.shape[0])[:, None]
    j = (u <= cdf).argmax(axis=1).astype(int)
    return j


def compute_concentration_metrics(W_clean: np.ndarray, exch: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tot = W_clean.sum(axis=1)
    shares = np.zeros_like(W_clean, dtype=float)
    m = tot > 0
    shares[m] = W_clean[m] / tot[m, None]
    hhi = np.sum(shares * shares, axis=1)
    max_share = np.max(shares, axis=1)
    dom_idx = np.argmax(shares, axis=1).astype(int)
    dominant_exchange = np.array([exch[i] for i in dom_idx], dtype=object)
    return hhi, max_share, dominant_exchange


def rel_shift(new: np.ndarray, old: np.ndarray) -> np.ndarray:
    out = (new - old) / old
    out[~np.isfinite(out)] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dv-dir", required=True, help="dv_ready_2021_2022 directory")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--exchanges", nargs="*", default=EXCH_ORDER_DEFAULT)
    ap.add_argument("--exclude", nargs="*", default=["Binance"], help="exchange(s) to exclude entirely")
    ap.add_argument("--time-col", default="time_utc")
    ap.add_argument("--price-col", default="p_usd_scaled")
    ap.add_argument("--w-col", default="DV_usd")
    ap.add_argument("--chunksize", type=int, default=250_000)

    ap.add_argument("--random-seed", type=int, default=42)
    ap.add_argument("--min-exchanges-per-min", type=int, default=3)
    ap.add_argument("--n-sample-minutes", type=int, default=100_000)

    ap.add_argument("--delta-w", nargs="*", type=float, default=[-0.5, 0.5, 1.0, 2.0])
    ap.add_argument("--shock-types", nargs="*", default=["inflate_only", "reallocate_total_fixed"])
    ap.add_argument("--cap-eps", type=float, default=1e-9)

    ap.add_argument("--dry-run", action="store_true", help="small run for sanity check")
    args = ap.parse_args()

    dv_dir = Path(args.dv_dir)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.random_seed)

    # Discover files
    files = list(dv_dir.glob("BTCUSD_1m_*_2021_2022_with_DV.csv"))
    if not files:
        raise FileNotFoundError(f"[ERR] no dv_ready files found in: {dv_dir}")

    exch_to_file = {}
    for fp in files:
        exch = parse_exchange_from_filename(fp.name)
        if exch:
            exch_to_file[exch] = fp

    # Exchanges to use
    excl = set(args.exclude)
    exch_order = [e for e in args.exchanges if e not in excl]
    missing = [e for e in exch_order if e not in exch_to_file]
    if missing:
        raise FileNotFoundError(f"[ERR] missing dv_ready files for: {missing}")

    print(f"[info] using exchanges (excluded={sorted(excl)}): {exch_order}", flush=True)

    # Load all exchanges into Series
    p_series = {}
    w_series = {}

    for e in tqdm(exch_order, desc="load dv (exchanges)", unit="exch"):
        fp = exch_to_file[e]
        p, w = load_exchange_series(fp, args.time_col, args.price_col, args.w_col, chunksize=args.chunksize)
        # reduce memory a bit
        p_series[e] = p.astype("float64")
        w_series[e] = w.astype("float64")

    # Build union index
    idx = None
    for e in exch_order:
        idx = w_series[e].index if idx is None else idx.union(w_series[e].index)
    idx = idx.sort_values()

    # Build wide matrices
    P = np.full((len(idx), len(exch_order)), np.nan, dtype=float)
    W = np.full((len(idx), len(exch_order)), np.nan, dtype=float)

    for j, e in enumerate(exch_order):
        P[:, j] = p_series[e].reindex(idx).to_numpy()
        W[:, j] = w_series[e].reindex(idx).to_numpy()

    # Clean
    P_clean, W_clean = clean_pw(P, W)
    valid_ct = (W_clean > 0).sum(axis=1)
    ok = valid_ct >= args.min_exchanges_per_min
    ok_idx = np.flatnonzero(ok)

    if len(ok_idx) < args.n_sample_minutes:
        raise RuntimeError(f"[ERR] not enough eligible minutes after exclude={sorted(excl)}: "
                           f"eligible={len(ok_idx)} < n_sample_minutes={args.n_sample_minutes}")

    n_sample = 2_000 if args.dry_run else args.n_sample_minutes
    choose = rng.choice(ok_idx, size=n_sample, replace=False)
    choose.sort()
    print(f"[info] eligible minutes={len(ok_idx)}; sampled={len(choose)}", flush=True)

    P0 = P_clean[choose, :]
    W0 = W_clean[choose, :]

    # Baseline aggregators
    base_mean = mean_unweighted(P0)
    base_median = median_unweighted(P0)
    base_vwap = vwap(P0, W0)
    base_lwmp, base_pivcol, base_margin, base_totw = lwmp_with_pivot(P0, W0)

    base_margin_norm = np.where(base_totw > 0, base_margin / base_totw, np.nan)

    # Concentration metrics (on excluded-universe)
    base_hhi, base_max_share, base_dom = compute_concentration_metrics(W0, exch_order)
    base_lockin = (base_max_share > 0.5).astype(int)
    base_pivot_exch = np.array([exch_order[c] if c >= 0 else None for c in base_pivcol], dtype=object)
    base_pivot_is_dom = (base_pivot_exch == base_dom).astype(int)

    # Save minute-level base metrics for audit
    base_minute = pd.DataFrame({
        "time_utc": idx[choose].astype("datetime64[ns]").astype("datetime64[ns]"),
        "exclude": ",".join(sorted(excl)),
        "n_exchanges_used": (W0 > 0).sum(axis=1).astype(int),
        "total_DV": W0.sum(axis=1),
        "HHI_excl": base_hhi,
        "max_share_excl": base_max_share,
        "dominant_exchange_excl": base_dom,
        "lock_in_excl": base_lockin,
        "p_vwap_base": base_vwap,
        "p_lwmp_base": base_lwmp,
        "pivot_exchange_base": base_pivot_exch,
        "pivot_margin_norm_base": base_margin_norm,
        "pivot_is_dominant_base": base_pivot_is_dom,
    })
    base_minute_path = outdir / f"base_minute_metrics__exclude_{'_'.join(sorted(excl))}.csv"
    base_minute.to_csv(base_minute_path, index=False, encoding="utf-8-sig")
    print(f"[saved] {base_minute_path} shape={base_minute.shape}", flush=True)

    # Event-level output (incremental)
    out_csv = outdir / f"dvon_injection_shift_samples__exclude_{'_'.join(sorted(excl))}.csv"
    if out_csv.exists():
        out_csv.unlink()  # overwrite
    wrote_header = False

    deltas = args.delta_w
    shock_types = args.shock_types

    # Precompute shocked exchange index per row (uniform among valid) ONCE for comparability across scenarios
    j_shock = sample_uniform_valid_index(W0, rng)
    exch_shocked = np.array([exch_order[j] for j in j_shock], dtype=object)

    share_before = np.full(n_sample, np.nan, dtype=float)
    m_tot = base_totw > 0
    share_before[m_tot] = W0[m_tot, j_shock[m_tot]] / base_totw[m_tot]

    # Iterate scenarios and append results
    total_scen = len(shock_types) * len(deltas)
    scen_iter = tqdm([(st, dw) for st in shock_types for dw in deltas],
                     desc="run scenarios", unit="scen", total=total_scen)

    for shock_type, delta_w in scen_iter:
        factor = 1.0 + float(delta_w)
        if factor <= 0:
            print(f"[skip] delta_w={delta_w} -> factor<=0", flush=True)
            continue

        W1 = W0.copy()
        wj0 = W0[np.arange(n_sample), j_shock].copy()
        total0 = base_totw.copy()

        if shock_type == "inflate_only":
            W1[np.arange(n_sample), j_shock] = wj0 * factor

        elif shock_type == "reallocate_total_fixed":
            # target new wj, cap to keep rest positive
            wj_new = wj0 * factor
            cap = (1.0 - args.cap_eps) * total0
            too_big = (total0 > 0) & (wj_new >= cap)
            wj_new = np.where(too_big, cap, wj_new)

            rest0 = total0 - wj0
            # rest0 should be >0 due to min exchanges >=3, but keep guard
            scale_rest = np.ones_like(rest0)
            m = rest0 > 0
            scale_rest[m] = (total0[m] - wj_new[m]) / rest0[m]
            scale_rest[~np.isfinite(scale_rest)] = 1.0
            # apply scaling to all, then override shocked col
            W1 = W1 * scale_rest[:, None]
            W1[np.arange(n_sample), j_shock] = wj_new

            # final guard: negative -> 0
            W1[W1 < 0] = 0.0

        else:
            raise ValueError(f"unknown shock_type: {shock_type}")

        # After metrics
        P_mean_1 = base_mean  # unchanged by weights, but keep explicit
        P_median_1 = base_median
        P_vwap_1 = vwap(P0, W1)
        P_lwmp_1, pivcol_1, margin_1, totw_1 = lwmp_with_pivot(P0, W1)

        # shares
        share_after = np.full(n_sample, np.nan, dtype=float)
        m1 = totw_1 > 0
        share_after[m1] = W1[m1, j_shock[m1]] / totw_1[m1]

        # pivot exchange strings
        pivot_exch_after = np.array([exch_order[c] if c >= 0 else None for c in pivcol_1], dtype=object)

        pivot_changed = ((base_pivcol >= 0) & (pivcol_1 >= 0) & (pivcol_1 != base_pivcol)).astype(int)

        # relative shifts
        shift_mean = rel_shift(P_mean_1, base_mean)
        shift_median = rel_shift(P_median_1, base_median)
        shift_vwap = rel_shift(P_vwap_1, base_vwap)
        shift_lwmp = rel_shift(P_lwmp_1, base_lwmp)

        # build output block
        block = pd.DataFrame({
            "time_utc": idx[choose],
            "shock_type": shock_type,
            # keep both naming conventions
            "delta_w": float(delta_w),
            "gamma": float(delta_w),
            "weight_factor": float(factor),

            "exchange_shocked": exch_shocked,
            "share_shocked_before": share_before,
            "share_shocked_after": share_after,

            "pivot_exchange_before": base_pivot_exch,
            "pivot_exchange_after": pivot_exch_after,
            "pivot_margin_before": base_margin,
            "pivot_margin_after": margin_1,
            "pivot_changed": pivot_changed,

            "shift_mean": shift_mean,
            "shift_median": shift_median,
            "shift_vwap": shift_vwap,
            "shift_lwmp": shift_lwmp,

            # extra audit columns (excluded-universe baseline)
            "HHI_excl": base_hhi,
            "max_share_excl": base_max_share,
            "dominant_exchange_excl": base_dom,
            "lock_in_excl": base_lockin,
            "pivot_is_dominant_before_excl": base_pivot_is_dom,
        })

        block.to_csv(out_csv, mode="a", index=False, header=(not wrote_header), encoding="utf-8-sig")
        wrote_header = True

    print(f"[done] saved event-level: {out_csv}", flush=True)
    print("Tip: if you want a quick sanity run first, add --dry-run", flush=True)


if __name__ == "__main__":
    main()

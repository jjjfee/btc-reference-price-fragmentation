# run_dv_only_injection_experiments.py
# ============================================================
# DV-only injection (only change DV_usd weights, NOT prices)
# Focus: pivot_changed for LWMP, plus VWAP continuous degradation
#
# Inputs:
#   dv_ready_2021_2022\BTCUSD_1m_{EX}_2021_2022_with_DV.csv
# Outputs:
#   experiments_dvonly\dvon_injection_shift_samples.csv
#   experiments_dvonly\Table_dvonly_injection_summary.xlsx
# ============================================================

from pathlib import Path
import pandas as pd
import numpy as np

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "dv_ready_2021_2022"
OUT_DIR = ROOT / "experiments_dvonly"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_SAMPLES = OUT_DIR / "dvon_injection_shift_samples.csv"
OUT_TABLE   = OUT_DIR / "Table_dvonly_injection_summary.xlsx"

# ---------- Params ----------
RANDOM_SEED = 42
N_SAMPLE_MINUTES = 100_000
MIN_EXCHANGES_PER_MIN = 3

# DV shock magnitudes: w' = w*(1+delta_w)
DELTA_WS = [0.5, 1.0, 2.0, -0.5]  # factors: 1.5x, 2x, 3x, 0.5x
SHOCK_TYPES = ["inflate_only", "reallocate_total_fixed"]

# ---------- Column candidates ----------
TIME_COL_CANDIDATES   = ["time_utc", "Time_utc", "timestamp", "time"]
PRICE_COL_CANDIDATES  = ["p_usd_scaled", "p_usd", "price_usd", "p_scaled"]
WEIGHT_COL_CANDIDATES = ["DV_usd", "DV", "dollar_volume", "dv_usd"]

def pick_existing_column(cols, candidates):
    lower_map = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None

def infer_exchange_name(fp: Path) -> str:
    # Your filename style: BTCUSD_1m_Binance_2021_2022_with_DV.csv
    known = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
    nm = fp.stem
    for k in known:
        if k.lower() in nm.lower():
            return k
    parts = nm.split("_")
    return parts[2] if len(parts) >= 3 else nm

def load_exchange_wide():
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No csv files found in: {INPUT_DIR}")

    prices = pd.DataFrame()
    weights = pd.DataFrame()

    for fp in files:
        ex = infer_exchange_name(fp)
        head = pd.read_csv(fp, nrows=5)
        cols = list(head.columns)
        tcol = pick_existing_column(cols, TIME_COL_CANDIDATES)
        pcol = pick_existing_column(cols, PRICE_COL_CANDIDATES)
        wcol = pick_existing_column(cols, WEIGHT_COL_CANDIDATES)
        if tcol is None or pcol is None or wcol is None:
            raise ValueError(f"{fp.name} missing needed columns: time={tcol}, price={pcol}, weight={wcol}")

        df = pd.read_csv(fp, usecols=[tcol, pcol, wcol])
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce", utc=True)
        df[pcol] = pd.to_numeric(df[pcol], errors="coerce")
        df[wcol] = pd.to_numeric(df[wcol], errors="coerce")

        df = df.dropna(subset=[tcol]).sort_values(tcol).drop_duplicates(tcol, keep="last").set_index(tcol)
        prices[ex] = df[pcol]
        weights[ex] = df[wcol]

    # union index
    all_index = None
    for c in prices.columns:
        idx = prices[c].dropna().index
        all_index = idx if all_index is None else all_index.union(idx)

    prices = prices.reindex(all_index).sort_index()
    weights = weights.reindex(all_index).sort_index()

    return prices, weights

def weighted_median_with_pivot(p: np.ndarray, w: np.ndarray):
    """
    Row-wise weighted median + pivot (original column index) + pivot margin.
    Stable tie-breaking via mergesort.
    """
    N, K = p.shape
    valid = np.isfinite(p) & np.isfinite(w) & (w > 0)
    w2 = np.where(valid, w, 0.0)

    # invalid -> sort to the end
    p_key = np.where(w2 > 0, p, np.inf)

    order = np.argsort(p_key, axis=1, kind="mergesort")
    p_sorted = np.take_along_axis(p, order, axis=1)
    w_sorted = np.take_along_axis(w2, order, axis=1)

    cumw = np.cumsum(w_sorted, axis=1)
    totalw = np.sum(w_sorted, axis=1)
    half = 0.5 * totalw

    hit = (cumw >= half[:, None])
    idx = hit.argmax(axis=1)

    lwmp = p_sorted[np.arange(N), idx]
    pivot_col = order[np.arange(N), idx]
    margin = cumw[np.arange(N), idx] - half

    lwmp = np.where(totalw > 0, lwmp, np.nan)
    pivot_col = np.where(totalw > 0, pivot_col, -1)
    margin = np.where(totalw > 0, margin, np.nan)

    return lwmp, pivot_col.astype(int), margin, totalw

def compute_aggregators(p: np.ndarray, w: np.ndarray):
    valid = np.isfinite(p) & np.isfinite(w) & (w > 0)
    w_clean = np.where(valid, w, 0.0)
    p_clean = np.where(valid, p, np.nan)

    P_mean = np.nanmean(p_clean, axis=1)
    P_median = np.nanmedian(p_clean, axis=1)

    denom = np.sum(w_clean, axis=1)
    P_vwap = np.where(denom > 0, np.nansum(p_clean * w_clean, axis=1) / denom, np.nan)

    P_lwmp, pivot_col, pivot_margin, totalw = weighted_median_with_pivot(p_clean, w_clean)
    return P_mean, P_median, P_vwap, P_lwmp, pivot_col, pivot_margin, totalw, w_clean, p_clean

def sample_valid_exchange_per_row(valid_w: np.ndarray, rng: np.random.Generator):
    """
    valid_w: (N,K) bool where weight>0
    returns j: (N,) chosen column index, uniformly among valid columns each row
    """
    N, K = valid_w.shape
    cnt = valid_w.sum(axis=1)
    if np.any(cnt <= 0):
        # should not happen if we pre-filter minutes
        cnt = np.maximum(cnt, 1)
    pick = (rng.random(N) * cnt).astype(int)  # 0..cnt-1
    cum = np.cumsum(valid_w.astype(int), axis=1)
    j = (cum > pick[:, None]).argmax(axis=1)
    return j.astype(int)

def rel_shift(P_new, P_old):
    return (P_new - P_old) / P_old

def summarize_abs(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return (np.nan, np.nan, 0)
    ax = np.abs(x)
    return (float(np.median(ax)), float(np.quantile(ax, 0.95)), int(ax.size))

def main():
    print("[INFO] Loading wide tables from:", INPUT_DIR)
    prices_wide, weights_wide = load_exchange_wide()

    exchanges = list(prices_wide.columns)
    times = prices_wide.index

    p_all = prices_wide.to_numpy(dtype=float)
    w_all = weights_wide.to_numpy(dtype=float)

    # keep minutes with >= MIN_EXCHANGES_PER_MIN valid exchanges (weight>0 and finite)
    valid_any = np.isfinite(p_all) & np.isfinite(w_all) & (w_all > 0)
    n_ex = valid_any.sum(axis=1)

    keep = n_ex >= MIN_EXCHANGES_PER_MIN
    times = times[keep]
    p_all = p_all[keep, :]
    w_all = w_all[keep, :]

    print(f"[INFO] Minutes kept (>= {MIN_EXCHANGES_PER_MIN} exchanges): {len(times):,}")
    print(f"[INFO] Exchanges: {exchanges}")

    rng = np.random.default_rng(RANDOM_SEED)
    n = len(times)
    sample_n = min(N_SAMPLE_MINUTES, n)
    sample_idx = rng.choice(n, size=sample_n, replace=False)

    t = times[sample_idx]
    p = p_all[sample_idx, :].copy()
    w = w_all[sample_idx, :].copy()

    # baseline
    P_mean, P_median, P_vwap, P_lwmp, pivot0, margin0, totalw0, w_clean0, p_clean0 = compute_aggregators(p, w)

    # choose shocked exchange per row among valid weights
    valid_w0 = (w_clean0 > 0) & np.isfinite(w_clean0)
    j = sample_valid_exchange_per_row(valid_w0, rng)

    # shocked share before
    wj0 = w_clean0[np.arange(sample_n), j]
    share0 = np.where(totalw0 > 0, wj0 / totalw0, np.nan)

    rows = []
    for shock_type in SHOCK_TYPES:
        for delta_w in DELTA_WS:
            factor = 1.0 + float(delta_w)
            if factor <= 0:
                continue

            w_shock = w_clean0.copy()

            if shock_type == "inflate_only":
                w_shock[np.arange(sample_n), j] = wj0 * factor
            elif shock_type == "reallocate_total_fixed":
                # keep total weight per minute constant, adjust others proportionally
                wj_new = wj0 * factor
                rest0 = totalw0 - wj0
                # If rest0 is 0, can't reallocate; fall back to inflate_only behavior
                scale_rest = np.where(rest0 > 0, (totalw0 - wj_new) / rest0, 1.0)

                # avoid negative weights: cap wj_new at (1-eps)*totalw0
                eps = 1e-12
                too_big = (totalw0 > 0) & (wj_new >= (1.0 - 1e-9) * totalw0)
                wj_new = np.where(too_big, (1.0 - 1e-9) * totalw0, wj_new)
                scale_rest = np.where(rest0 > 0, (totalw0 - wj_new) / rest0, 1.0)
                scale_rest = np.where(scale_rest < 0, np.nan, scale_rest)

                # apply
                for k in range(w_shock.shape[1]):
                    wk = w_shock[:, k]
                    wk = np.where(k == 0, wk, wk)  # no-op (keep structure)
                    w_shock[:, k] = wk
                # scale all, then override j
                w_shock = w_shock * scale_rest[:, None]
                w_shock[np.arange(sample_n), j] = wj_new
                # any nan scale_rest -> nan row
                bad = ~np.isfinite(scale_rest)
                if np.any(bad):
                    w_shock[bad, :] = np.nan
            else:
                continue

            # compute with shocked weights
            Pm2, Pmed2, Pv2, Pl2, pivot1, margin1, totalw1, w_clean1, _ = compute_aggregators(p_clean0, w_shock)

            # relative shifts
            d_mean = rel_shift(Pm2, P_mean)
            d_median = rel_shift(Pmed2, P_median)
            d_vwap = rel_shift(Pv2, P_vwap)
            d_lwmp = rel_shift(Pl2, P_lwmp)

            # pivot changed
            piv_changed = (pivot0 != -1) & (pivot1 != -1) & (pivot1 != pivot0)
            piv_changed = piv_changed.astype(int)

            # shocked share after
            wj1 = w_clean1[np.arange(sample_n), j]
            share1 = np.where(totalw1 > 0, wj1 / totalw1, np.nan)

            for i in range(sample_n):
                rows.append(dict(
                    time_utc=str(t[i]),
                    shock_type=shock_type,
                    delta_w=float(delta_w),
                    weight_factor=float(factor),
                    exchange_shocked=exchanges[int(j[i])],

                    share_shocked_before=float(share0[i]) if np.isfinite(share0[i]) else np.nan,
                    share_shocked_after=float(share1[i]) if np.isfinite(share1[i]) else np.nan,

                    pivot_exchange_before=exchanges[int(pivot0[i])] if int(pivot0[i]) >= 0 else "",
                    pivot_exchange_after=exchanges[int(pivot1[i])] if int(pivot1[i]) >= 0 else "",
                    pivot_margin_before=float(margin0[i]) if np.isfinite(margin0[i]) else np.nan,
                    pivot_margin_after=float(margin1[i]) if np.isfinite(margin1[i]) else np.nan,
                    pivot_changed=int(piv_changed[i]),

                    shift_mean=float(d_mean[i]) if np.isfinite(d_mean[i]) else np.nan,
                    shift_median=float(d_median[i]) if np.isfinite(d_median[i]) else np.nan,
                    shift_vwap=float(d_vwap[i]) if np.isfinite(d_vwap[i]) else np.nan,
                    shift_lwmp=float(d_lwmp[i]) if np.isfinite(d_lwmp[i]) else np.nan,
                ))

            print(f"[OK] finished shock_type={shock_type}, delta_w={delta_w:+.2f}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_SAMPLES, index=False, encoding="utf-8-sig")
    print("✅ Saved samples:", OUT_SAMPLES)

    # -------- summary table (overall) --------
    sum_rows = []
    for (st, dw), g in df.groupby(["shock_type", "delta_w"], observed=True):
        medL, p95L, nL = summarize_abs(g["shift_lwmp"])
        medV, p95V, nV = summarize_abs(g["shift_vwap"])
        piv = pd.to_numeric(g["pivot_changed"], errors="coerce")
        piv_rate = float(np.nanmean(piv)) if len(piv) else np.nan

        # conditional shifts when pivot actually changes (useful for narrative)
        g_flip = g[pd.to_numeric(g["pivot_changed"], errors="coerce") == 1]
        medL_flip, p95L_flip, nL_flip = summarize_abs(g_flip["shift_lwmp"])

        sum_rows.append(dict(
            shock_type=st,
            delta_w=float(dw),
            weight_factor=float(1.0 + float(dw)),
            N=int(len(g)),
            pivot_changed_rate=float(piv_rate),

            lwmp_median_abs_shift=float(medL),
            lwmp_p95_abs_shift=float(p95L),
            vwap_median_abs_shift=float(medV),
            vwap_p95_abs_shift=float(p95V),

            lwmp_median_abs_shift_cond_on_flip=float(medL_flip),
            lwmp_p95_abs_shift_cond_on_flip=float(p95L_flip),
            N_flip=int(len(g_flip)),
        ))

    summary = pd.DataFrame(sum_rows).sort_values(["shock_type","delta_w"])
    with pd.ExcelWriter(OUT_TABLE, engine="openpyxl") as w:
        summary.to_excel(w, index=False, sheet_name="overall")
    print("✅ Saved summary:", OUT_TABLE)

if __name__ == "__main__":
    main()

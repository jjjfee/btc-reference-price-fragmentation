import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# ============================================================
# PATHS
# ============================================================
ROOT   = r"D:\cilck here\2代目"
PANEL  = os.path.join(ROOT, "hhi_panel", "btc_1m_panel_with_hhi.csv")
INJ    = os.path.join(ROOT, "experiments", "injection_shift_samples.csv")
OUTDIR = os.path.join(ROOT, "paper_outputs_frl")
os.makedirs(OUTDIR, exist_ok=True)

TARGET_DELTAS = [0.05, 0.10]
TOL = 1e-12

# 机制图里：小于这个 N 的格子会被“屏蔽不画”（但仍会标注 N=?）
MIN_N_TO_PLOT = 200

# ============================================================
# IO helpers (atomic write + handle PermissionError)
# ============================================================
def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def safe_to_csv(df: pd.DataFrame, outpath: str, **kwargs):
    """
    Atomic write for CSV. If target is locked (Excel/WPS open), write timestamped alt.
    Keeps the correct extension (.csv) so downstream tools are happy.
    """
    base, ext = os.path.splitext(outpath)
    if ext.lower() != ".csv":
        ext = ".csv"
        outpath = base + ext

    tmp = f"{base}__tmp_{_ts()}{ext}"
    try:
        df.to_csv(tmp, encoding="utf-8-sig", **kwargs)
        os.replace(tmp, outpath)
        print("Saved:", outpath)
        return outpath
    except PermissionError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        alt = f"{base}__{_ts()}{ext}"
        df.to_csv(alt, encoding="utf-8-sig", **kwargs)
        print(f"[WARN] Permission denied for {outpath} (file may be open). Wrote to:", alt)
        return alt

def safe_savefig(fig, outpath: str, **kwargs):
    """
    Atomic write for figures. IMPORTANT: temp file keeps same extension (.png/.pdf/...)
    so matplotlib can infer format.
    """
    base, ext = os.path.splitext(outpath)
    if ext == "":
        ext = ".png"
        outpath = base + ext

    tmp = f"{base}__tmp_{_ts()}{ext}"
    try:
        fig.savefig(tmp, **kwargs)
        os.replace(tmp, outpath)
        print("Saved:", outpath)
        return outpath
    except PermissionError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        alt = f"{base}__{_ts()}{ext}"
        fig.savefig(alt, **kwargs)
        print(f"[WARN] Permission denied for {outpath} (file may be open). Wrote to:", alt)
        return alt

# ============================================================
# Helpers
# ============================================================
def pick_time_col(df, min_rate=0.5):
    cols = list(df.columns)
    cand = []
    if len(cols) and str(cols[0]).lower().startswith("unnamed"):
        cand.append(cols[0])
    for c in cols:
        cl = str(c).lower()
        if any(k in cl for k in ["time", "date", "datetime", "timestamp", "ts", "open", "dt"]):
            cand.append(c)
    seen = set()
    cand = [c for c in cand if not (c in seen or seen.add(c))]

    best, best_rate = None, 0.0
    for c in cand:
        s = pd.to_datetime(df[c], errors="coerce", utc=True)
        rate = float(s.notna().mean())
        if rate > best_rate:
            best, best_rate = c, rate
    if best is None or best_rate < min_rate:
        return None, best_rate
    return best, best_rate

def wilson_ci(k, n, z=1.96):
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = (z*np.sqrt((p*(1-p)/n) + (z*z/(4*n*n)))) / den
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return lo, hi

def bootstrap_p95_ci(x, B=300, seed=123, maxn=200_000):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    if x.size > maxn:
        x = rng.choice(x, size=maxn, replace=False)

    p0 = float(np.quantile(x, 0.95))
    n = x.size
    idx = rng.integers(0, n, size=(B, n))
    boot = np.quantile(x[idx], 0.95, axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return (p0, float(lo), float(hi))

def make_qgroup(series, q=5):
    """
    Safe quantile grouping -> returns Int64 1..K (K<=q if duplicates drop).
    Avoids pandas qcut label-length mismatch issue.
    """
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    cat = pd.qcut(s, q, duplicates="drop")
    # codes: -1 for NaN
    codes = pd.Series(cat.cat.codes, index=s.index).astype("Int64")
    # shift to 1..K
    out = codes + 1
    out = out.where(out > 0, pd.NA)
    return out

def tercile_low_high_mask(s):
    s = pd.to_numeric(s, errors="coerce")
    q1 = float(np.nanquantile(s, 1/3))
    q2 = float(np.nanquantile(s, 2/3))
    low = s <= q1
    high = s >= q2
    return low, high, q1, q2

def yerr_from_ci(val, lo, hi):
    """
    Matplotlib bar yerr must be non-negative lengths.
    Also handles NaN safely.
    """
    val = np.asarray(val, dtype=float)
    lo  = np.asarray(lo,  dtype=float)
    hi  = np.asarray(hi,  dtype=float)

    good = np.isfinite(val) & np.isfinite(lo) & np.isfinite(hi)
    err_low  = np.zeros_like(val, dtype=float)
    err_high = np.zeros_like(val, dtype=float)

    err_low[good]  = np.clip(val[good] - lo[good], 0.0, None)
    err_high[good] = np.clip(hi[good] - val[good], 0.0, None)
    return np.vstack([err_low, err_high])

# ============================================================
# 1) PANEL: build concentration measures + quintiles
# ============================================================
panel_head = pd.read_csv(PANEL, nrows=5000, low_memory=False)
tcol, trate = pick_time_col(panel_head, min_rate=0.5)
if tcol is None:
    raise ValueError(f"[panel] 找不到可解析时间列（解析率={trate:.2f}）。请 print(panel_head.columns)")

panel = pd.read_csv(PANEL, low_memory=False)
panel.columns = [c.lower() for c in panel.columns]
tcol_l = str(tcol).lower()

need_panel = ["hhi", "max_share"]
for c in need_panel:
    if c not in panel.columns:
        raise ValueError(f"[panel] 缺少列 {c}。当前列名前30：{list(panel.columns)[:30]}")

panel["time_utc"] = pd.to_datetime(panel[tcol_l], errors="coerce", utc=True).dt.floor("min")

# Use hhi_roll if available, else hhi
hhi_base = panel["hhi_roll"] if "hhi_roll" in panel.columns else panel["hhi"]
panel["hhi_base"] = pd.to_numeric(hhi_base, errors="coerce").replace([np.inf, -np.inf], np.nan)
panel["max_share"] = pd.to_numeric(panel["max_share"], errors="coerce").replace([np.inf, -np.inf], np.nan)

# Derived concentration measures
panel["neff"] = 1.0 / panel["hhi_base"]
panel["top_hhi_share"] = (panel["max_share"]**2) / panel["hhi_base"]
panel["hhi_rest"] = panel["hhi_base"] - (panel["max_share"]**2)

# Normalized rest (optional)
den = (1.0 - panel["max_share"])**2
panel["hhi_rest_norm"] = panel["hhi_rest"] / den.replace(0, np.nan)

# Quantile groups: Q1=low, Q5=high
panel["q_hhi"]      = make_qgroup(panel["hhi_base"], q=5)
panel["q_maxshare"] = make_qgroup(panel["max_share"], q=5)
panel["q_tophhi"]   = make_qgroup(panel["top_hhi_share"], q=5)
panel["q_hhirest"]  = make_qgroup(panel["hhi_rest"], q=5)
panel["q_hhirestN"] = make_qgroup(panel["hhi_rest_norm"], q=5)
panel["q_neff"]     = make_qgroup(-panel["neff"], q=5)  # negate: Q5 = more concentrated

q_cols = ["q_hhi","q_maxshare","q_tophhi","q_hhirest","q_hhirestN","q_neff"]

panel = panel[
    ["time_utc"] + q_cols + ["hhi_base","max_share","neff","top_hhi_share","hhi_rest","hhi_rest_norm"]
].dropna(subset=["time_utc"])

# ============================================================
# 2) INJ: read + filter deltas + merge panel
# ============================================================
inj = pd.read_csv(INJ, low_memory=False)
inj.columns = [c.lower() for c in inj.columns]

need_inj = ["time_utc", "delta", "shift_lwmp", "shift_vwap"]
missing = [c for c in need_inj if c not in inj.columns]
if missing:
    raise ValueError(f"[inj] 缺少列：{missing}\n实际列前30：{list(inj.columns)[:30]}")

inj["time_utc"] = pd.to_datetime(inj["time_utc"], errors="coerce", utc=True).dt.floor("min")
inj["delta"] = pd.to_numeric(inj["delta"], errors="coerce")
inj["shift_lwmp"] = pd.to_numeric(inj["shift_lwmp"], errors="coerce")
inj["shift_vwap"] = pd.to_numeric(inj["shift_vwap"], errors="coerce")

inj = inj.dropna(subset=["time_utc","delta","shift_lwmp","shift_vwap"]).copy()
inj["delta_abs"] = inj["delta"].abs()

keep = np.zeros(len(inj), dtype=bool)
for d in TARGET_DELTAS:
    keep |= np.isclose(inj["delta_abs"].values, d, atol=TOL)
inj = inj[keep].copy()

inj = inj.merge(panel, on="time_utc", how="left")
inj = inj.dropna(subset=q_cols + ["hhi_base","max_share","hhi_rest"]).copy()
for qc in q_cols:
    inj[qc] = inj[qc].astype("Int64")

print("Inj rows after merge:", len(inj))
# ============================================================
# GROUPING SCHEME ROBUSTNESS (beyond 0.5 / quintile)
# Paste AFTER: print("Inj rows after merge:", len(inj))
# ============================================================

GROUP_SCHEMES = [
    "median",          # 0.5 split
    "tercile",         # k=3 quantiles
    "quartile",        # k=4 quantiles
    "quintile",        # k=5 quantiles (baseline)
    "decile",          # k=10 quantiles
    "extreme_tercile", # keep only bottom/top tercile
    "extreme_decile",  # keep only bottom/top decile
]

# 让 “组号越大 = 越集中”
MEASURE_RAW = [
    ("hhi_base",      +1, "HHI (roll if available)"),
    ("max_share",     +1, "max_share"),
    ("neff",          -1, "N_eff = 1/HHI (negated for concentration)"),
    ("top_hhi_share", +1, "TopHHIShare = max^2/HHI"),
    ("hhi_rest",      +1, "HHI_rest = HHI-max^2"),
    ("hhi_rest_norm", +1, "HHI_rest_norm"),
]

def make_groups(series, scheme):
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    if scheme == "median":
        med = float(np.nanmedian(s))
        g = pd.Series(np.where(s <= med, 1, 2), index=s.index, dtype="float")

    elif scheme in ("tercile", "quartile", "quintile", "decile"):
        k = {"tercile": 3, "quartile": 4, "quintile": 5, "decile": 10}[scheme]
        g = pd.qcut(s, k, labels=list(range(1, k+1)), duplicates="drop").astype("float")

    elif scheme == "extreme_tercile":
        q1 = float(np.nanquantile(s, 1/3))
        q2 = float(np.nanquantile(s, 2/3))
        g = pd.Series(np.nan, index=s.index, dtype="float")
        g[s <= q1] = 1
        g[s >= q2] = 3  # keep label as 3 so "top" is larger

    elif scheme == "extreme_decile":
        q1 = float(np.nanquantile(s, 0.1))
        q2 = float(np.nanquantile(s, 0.9))
        g = pd.Series(np.nan, index=s.index, dtype="float")
        g[s <= q1] = 1
        g[s >= q2] = 10

    else:
        raise ValueError(f"Unknown scheme: {scheme}")

    return g

def bin_stats_for_delta(df, g, delta):
    sub = df[np.isclose(df["delta_abs"].values, delta, atol=TOL)].copy()
    if sub.empty:
        return None, None

    sub["g"] = g.loc[sub.index].values
    sub = sub.dropna(subset=["g"]).copy()
    sub["g"] = sub["g"].astype(int)

    # outcomes
    sub["exceed_lwmp"] = (sub["shift_lwmp"].abs() >= (delta - TOL)).astype(int)
    sub["pt_vwap"] = (sub["shift_vwap"].abs() / delta).replace([np.inf, -np.inf], np.nan)
    sub = sub.dropna(subset=["pt_vwap", "exceed_lwmp", "g"]).copy()

    # per-bin table
    rows = []
    for gi, cell in sub.groupby("g", sort=True):
        n = int(len(cell))
        k = int(cell["exceed_lwmp"].sum())
        lo, hi = wilson_ci(k, n)
        p95, p95_lo, p95_hi = bootstrap_p95_ci(cell["pt_vwap"].to_numpy(), B=300, seed=123 + int(delta*1000) + int(gi))

        rows.append(dict(
            delta_abs=delta,
            g=int(gi),
            N=n,
            LWMP_exceed_pct=(k/n)*100 if n>0 else np.nan,
            LWMP_CI_lo_pct=lo*100,
            LWMP_CI_hi_pct=hi*100,
            VWAP_p95_PT=p95,
            VWAP_p95_CI_lo=p95_lo,
            VWAP_p95_CI_hi=p95_hi,
        ))
    bins = pd.DataFrame(rows).sort_values(["delta_abs","g"])

    # summary: top - bottom
    g_min = int(bins["g"].min())
    g_max = int(bins["g"].max())

    b = bins[bins["g"]==g_min].iloc[0]
    t = bins[bins["g"]==g_max].iloc[0]

    dLW = float(t["LWMP_exceed_pct"] - b["LWMP_exceed_pct"])
    dVW = float(t["VWAP_p95_PT"] - b["VWAP_p95_PT"])

    # monotonic trend proxy: spearman corr of g vs outcome (row-level)
    rho_lw = float(sub[["g","exceed_lwmp"]].corr(method="spearman").iloc[0,1])
    rho_vw = float(sub[["g","pt_vwap"]].corr(method="spearman").iloc[0,1])

    summ = dict(
        delta_abs=delta,
        g_low=g_min, g_high=g_max,
        N_low=int(b["N"]), N_high=int(t["N"]),
        dLWMP_exceed_Qhi_Qlo=dLW,
        dVWAP_p95PT_Qhi_Qlo=dVW,
        spearman_g_vs_exceed=rho_lw,
        spearman_g_vs_pt=rho_vw,
    )
    return bins, summ

all_bins = []
all_summ = []

for raw_col, sign, pretty in MEASURE_RAW:
    if raw_col not in inj.columns:
        print(f"[WARN] inj missing {raw_col}, skip.")
        continue

    # sign flip so that higher value = more concentrated
    s_conc = sign * pd.to_numeric(inj[raw_col], errors="coerce")

    for scheme in GROUP_SCHEMES:
        g = make_groups(s_conc, scheme)

        for d in TARGET_DELTAS:
            bins, summ = bin_stats_for_delta(inj, g, d)
            if bins is None:
                continue

            bins["measure_raw"] = raw_col
            bins["measure_pretty"] = pretty
            bins["scheme"] = scheme
            all_bins.append(bins)

            summ["measure_raw"] = raw_col
            summ["measure_pretty"] = pretty
            summ["scheme"] = scheme
            all_summ.append(summ)

bins_df = pd.concat(all_bins, ignore_index=True) if len(all_bins) else pd.DataFrame()
summ_df = pd.DataFrame(all_summ)

OUT_BINS = os.path.join(OUTDIR, "Table_grouping_robustness_bins.csv")
OUT_SUMM = os.path.join(OUTDIR, "Table_grouping_robustness_summary.csv")
safe_to_csv(bins_df, OUT_BINS)
safe_to_csv(summ_df, OUT_SUMM)

print("Saved grouping robustness tables:")
print(" -", OUT_BINS)
print(" -", OUT_SUMM)
# ============================================================

# ============================================================
# 3) 2×2 MECHANISM (top/bottom tercile): max_share × hhi_rest
# ============================================================
ms_low, ms_high, ms_q1, ms_q2 = tercile_low_high_mask(inj["max_share"])
hr_low, hr_high, hr_q1, hr_q2 = tercile_low_high_mask(inj["hhi_rest"])

mask_2x2 = (ms_low | ms_high) & (hr_low | hr_high)
inj_2x2 = inj.loc[mask_2x2].copy()

print("[2x2] rows kept:", len(inj_2x2))
print("[2x2] max_share terciles: q1=", ms_q1, " q2=", ms_q2)
print("[2x2] hhi_rest  terciles: q1=", hr_q1, " q2=", hr_q2)

inj_2x2["ms_grp"] = np.where(ms_low[mask_2x2], "max_share LOW (bottom tercile)", "max_share HIGH (top tercile)")
inj_2x2["hr_grp"] = np.where(hr_low[mask_2x2], "HHI_rest LOW (bottom tercile)", "HHI_rest HIGH (top tercile)")

rows = []
for d in TARGET_DELTAS:
    sub_d = inj_2x2[np.isclose(inj_2x2["delta_abs"].values, d, atol=TOL)].copy()
    if sub_d.empty:
        print(f"[WARN] 2x2 tercile: |delta|={d} no rows.")
        continue

    sub_d["exceed_lwmp"] = (sub_d["shift_lwmp"].abs() >= (d - TOL)).astype(int)
    sub_d["pt_vwap"] = sub_d["shift_vwap"].abs() / d
    sub_d = sub_d.replace([np.inf, -np.inf], np.nan).dropna(subset=["pt_vwap", "exceed_lwmp"])

    for ms in ["max_share LOW (bottom tercile)", "max_share HIGH (top tercile)"]:
        for hr in ["HHI_rest LOW (bottom tercile)", "HHI_rest HIGH (top tercile)"]:
            cell = sub_d[(sub_d["ms_grp"] == ms) & (sub_d["hr_grp"] == hr)]
            n = int(len(cell))
            if n == 0:
                rows.append([d, ms, hr, 0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan])
                continue

            k = int(cell["exceed_lwmp"].sum())
            p = k / n
            lo, hi = wilson_ci(k, n)

            arr = cell["pt_vwap"].to_numpy()
            p0, lo0, hi0 = bootstrap_p95_ci(arr, B=300, seed=123 + int(d*1000), maxn=200_000)

            rows.append([d, ms, hr, n, p*100, lo*100, hi*100, p0, lo0, hi0])

mech = pd.DataFrame(rows, columns=[
    "delta_abs", "max_share_group", "hhi_rest_group", "N",
    "LWMP_exceed_pct", "LWMP_CI_lo_pct", "LWMP_CI_hi_pct",
    "VWAP_p95_PT", "VWAP_p95_CI_lo", "VWAP_p95_CI_hi"
])

OUT_MECH = os.path.join(OUTDIR, "Table_mechanism_2x2_tercile_maxshare_x_hhirest.csv")
safe_to_csv(mech, OUT_MECH, index=False)

# Pretty print
for d in sorted(mech["delta_abs"].dropna().unique()):
    m = mech[mech["delta_abs"] == d].copy()
    print(f"\n[2x2 tercile] delta={d}")
    print(m[["max_share_group","hhi_rest_group","N","LWMP_exceed_pct","VWAP_p95_PT"]])

# ============================================================
# 4) FIG: 2×2 tercile mechanism BAR CHART (delta=0.05 vs 0.10)
#   - IMPORTANT: small-N masking happens BEFORE bar()
# ============================================================
FIG_MECH = os.path.join(OUTDIR, "Figure7_mechanism_2x2_tercile_maxshare_x_hhirest_bars.png")

CELL_ORDER = [
    ("max_share LOW (bottom tercile)",  "HHI_rest LOW (bottom tercile)"),
    ("max_share LOW (bottom tercile)",  "HHI_rest HIGH (top tercile)"),
    ("max_share HIGH (top tercile)",    "HHI_rest LOW (bottom tercile)"),
    ("max_share HIGH (top tercile)",    "HHI_rest HIGH (top tercile)"),
]
XLABELS = ["MS low\nHR low", "MS low\nHR high", "MS high\nHR low", "MS high\nHR high"]

def pull(mech_df, delta, col):
    out = []
    for ms, hr in CELL_ORDER:
        r = mech_df[
            (np.isclose(mech_df["delta_abs"].values, delta, atol=1e-12)) &
            (mech_df["max_share_group"] == ms) &
            (mech_df["hhi_rest_group"] == hr)
        ]
        out.append(np.nan if r.empty else float(r.iloc[0][col]))
    return np.array(out, dtype=float)

def pullN(mech_df, delta):
    return pull(mech_df, delta, "N")

# Pull arrays
lw_05 = pull(mech, 0.05, "LWMP_exceed_pct")
lw_10 = pull(mech, 0.10, "LWMP_exceed_pct")
lw_lo_05 = pull(mech, 0.05, "LWMP_CI_lo_pct")
lw_hi_05 = pull(mech, 0.05, "LWMP_CI_hi_pct")
lw_lo_10 = pull(mech, 0.10, "LWMP_CI_lo_pct")
lw_hi_10 = pull(mech, 0.10, "LWMP_CI_hi_pct")

vw_05 = pull(mech, 0.05, "VWAP_p95_PT")
vw_10 = pull(mech, 0.10, "VWAP_p95_PT")
vw_lo_05 = pull(mech, 0.05, "VWAP_p95_CI_lo")
vw_hi_05 = pull(mech, 0.05, "VWAP_p95_CI_hi")
vw_lo_10 = pull(mech, 0.10, "VWAP_p95_CI_lo")
vw_hi_10 = pull(mech, 0.10, "VWAP_p95_CI_hi")

N05 = pullN(mech, 0.05)
N10 = pullN(mech, 0.10)
Nmin = np.minimum(N05, N10)

# ---- SMALL-N MASKING (关键：在画图前做！) ----
small = np.isfinite(Nmin) & (Nmin < MIN_N_TO_PLOT)

for arr in [lw_05, lw_10, lw_lo_05, lw_hi_05, lw_lo_10, lw_hi_10,
            vw_05, vw_10, vw_lo_05, vw_hi_05, vw_lo_10, vw_hi_10]:
    arr[small] = np.nan

# yerr (non-negative)
lw_err_05 = yerr_from_ci(lw_05, lw_lo_05, lw_hi_05)
lw_err_10 = yerr_from_ci(lw_10, lw_lo_10, lw_hi_10)
vw_err_05 = yerr_from_ci(vw_05, vw_lo_05, vw_hi_05)
vw_err_10 = yerr_from_ci(vw_10, vw_lo_10, vw_hi_10)

# Plot
x = np.arange(len(CELL_ORDER))
w = 0.36
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.0, 7.2), sharex=True)

b1 = ax1.bar(x - w/2, lw_05, width=w, yerr=lw_err_05, capsize=4, label="LWMP δ=0.05")
b2 = ax1.bar(x + w/2, lw_10, width=w, yerr=lw_err_10, capsize=4, label="LWMP δ=0.10")
ax1.set_ylabel("LWMP exceedance (%)")
ax1.grid(True, axis="y", alpha=0.25)

b3 = ax2.bar(x - w/2, vw_05, width=w, yerr=vw_err_05, capsize=4, label="VWAP δ=0.05")
b4 = ax2.bar(x + w/2, vw_10, width=w, yerr=vw_err_10, capsize=4, label="VWAP δ=0.10")
ax2.set_ylabel("VWAP p95 pass-through (|shift|/|δ|)")
ax2.grid(True, axis="y", alpha=0.25)

ax2.set_xticks(x)
ax2.set_xticklabels(XLABELS)
ax2.set_xlabel("Mechanism bins (top/bottom tercile)")

handles = [b1, b2, b3, b4]
labels  = ["LWMP δ=0.05", "LWMP δ=0.10", "VWAP δ=0.05", "VWAP δ=0.10"]
fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.99),
           ncol=4, frameon=False, handlelength=1.8, columnspacing=1.6)

# annotate N for small cells
def annotate_smallN(ax, xs, Ns):
    ymin, ymax = ax.get_ylim()
    y = ymin + (ymax - ymin) * 0.03
    for i, n in enumerate(Ns):
        if np.isfinite(n) and n < MIN_N_TO_PLOT:
            ax.text(xs[i], y, f"N={int(n)}", ha="center", va="bottom", fontsize=9)

# set ylim based on finite bars
ax1_max = np.nanmax(np.r_[lw_05 + lw_err_05[1], lw_10 + lw_err_10[1]])
ax2_max = np.nanmax(np.r_[vw_05 + vw_err_05[1], vw_10 + vw_err_10[1]])
ax1.set_ylim(0, (ax1_max * 1.15) if np.isfinite(ax1_max) else 1.0)
ax2.set_ylim(0, (ax2_max * 1.15) if np.isfinite(ax2_max) else 1.0)

annotate_smallN(ax1, x, Nmin)
annotate_smallN(ax2, x, Nmin)

ax1.set_title("")
ax2.set_title("")
fig.subplots_adjust(top=0.90, hspace=0.18)

safe_savefig(fig, FIG_MECH, dpi=300, bbox_inches="tight")
plt.close(fig)

# ============================================================
# 5) FIG7: robustness vs concentration measure (quintiles), overlay δ=0.05 vs 0.10
# ============================================================
MEASURES = [
    ("HHI (roll if available)", "q_hhi"),
    ("max_share",               "q_maxshare"),
    ("N_eff = 1/HHI",           "q_neff"),
    ("TopHHIShare = max^2/HHI", "q_tophhi"),
    ("HHI_rest = HHI-max^2",    "q_hhirest"),
    ("HHI_rest_norm",           "q_hhirestN"),
]

def compute_by_quintile(inj_df, qcol, delta):
    sub = inj_df[np.isclose(inj_df["delta_abs"].values, delta, atol=TOL)].copy()
    if sub.empty:
        return None

    sub["exceed_lwmp"] = (sub["shift_lwmp"].abs() >= (delta - TOL)).astype(int)
    sub["pt_vwap"] = sub["shift_vwap"].abs() / delta
    sub = sub.replace([np.inf, -np.inf], np.nan).dropna(subset=["pt_vwap","exceed_lwmp",qcol])

    qs = [1,2,3,4,5]
    x = np.array(qs)

    ex = np.full(5, np.nan); ex_lo = np.full(5, np.nan); ex_hi = np.full(5, np.nan); ex_n = np.zeros(5, dtype=int)
    p95 = np.full(5, np.nan); p95_lo = np.full(5, np.nan); p95_hi = np.full(5, np.nan); pt_n = np.zeros(5, dtype=int)

    for i,q in enumerate(qs):
        s = sub[sub[qcol] == q]
        n = int(len(s))
        k = int(s["exceed_lwmp"].sum())
        ex_n[i] = n

        if n > 0:
            p = k / n
            lo, hi = wilson_ci(k, n)
            ex[i] = p
            ex_lo[i] = lo
            ex_hi[i] = hi

        arr = s["pt_vwap"].dropna().to_numpy()
        pt_n[i] = int(len(arr))
        p0, lo0, hi0 = bootstrap_p95_ci(arr, B=300, seed=123 + int(delta*1000) + q, maxn=200_000)
        p95[i] = p0; p95_lo[i] = lo0; p95_hi[i] = hi0

    return dict(
        x=x,
        ex=ex*100.0,
        ex_yerr=yerr_from_ci(ex*100.0, ex_lo*100.0, ex_hi*100.0),
        ex_n=ex_n,
        p95=p95,
        p95_yerr=yerr_from_ci(p95, p95_lo, p95_hi),
        pt_n=pt_n
    )

def plot_dualaxis_overlay(res005, res010, xlab_stub, outpath):
    x = res005["x"]
    fig, axL = plt.subplots(figsize=(9.2, 5.6))
    axR = axL.twinx()

    hL05 = axL.errorbar(x, res005["ex"], yerr=res005["ex_yerr"], fmt="o-",
                        capsize=4, linewidth=2, label="LWMP  δ=0.05")
    c05 = hL05[0].get_color()
    axR.errorbar(x, res005["p95"], yerr=res005["p95_yerr"], fmt="s--",
                 capsize=4, linewidth=2, color=c05, label="VWAP  δ=0.05")

    hL10 = axL.errorbar(x, res010["ex"], yerr=res010["ex_yerr"], fmt="^-",
                        capsize=4, linewidth=2, label="LWMP  δ=0.10")
    c10 = hL10[0].get_color()
    axR.errorbar(x, res010["p95"], yerr=res010["p95_yerr"], fmt="D--",
                 capsize=4, linewidth=2, color=c10, label="VWAP  δ=0.10")

    axL.set_xticks(x)
    axL.set_xticklabels(["Q1 (low)", "Q2", "Q3", "Q4", "Q5 (high)"])
    axL.set_xlabel(f"{xlab_stub} quintile")
    axL.set_ylabel("LWMP exceedance rate (%)")
    axR.set_ylabel("VWAP p95 pass-through (|shift|/|δ|)")
    axL.grid(True, alpha=0.25)

    handles = [hL05[0], hL10[0], axR.lines[0], axR.lines[1]]
    labels  = ["LWMP  δ=0.05", "LWMP  δ=0.10", "VWAP  δ=0.05", "VWAP  δ=0.10"]
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.98),
               ncol=2, frameon=False, handlelength=3.0, columnspacing=1.6)

    axL.set_title("")
    fig.subplots_adjust(top=0.86)

    safe_savefig(fig, outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)

rows_sum = []

for pretty, qcol in MEASURES:
    r05 = compute_by_quintile(inj, qcol, 0.05)
    r10 = compute_by_quintile(inj, qcol, 0.10)
    if (r05 is None) or (r10 is None):
        print(f"[WARN] {pretty}: missing delta results")
        continue

    outfig = os.path.join(OUTDIR, f"Figure7_conc_robust_{qcol}.png")
    plot_dualaxis_overlay(r05, r10, pretty, outfig)

    for delta, rr in [(0.05, r05), (0.10, r10)]:
        for i, q in enumerate([1,2,3,4,5]):
            rows_sum.append(dict(
                measure=qcol, measure_pretty=pretty, delta=delta, quintile=q,
                lwmp_exceed_pct=float(rr["ex"][i]) if np.isfinite(rr["ex"][i]) else np.nan,
                lwmp_ci_low=float(rr["ex"][i]-rr["ex_yerr"][0,i]) if np.isfinite(rr["ex"][i]) else np.nan,
                lwmp_ci_high=float(rr["ex"][i]+rr["ex_yerr"][1,i]) if np.isfinite(rr["ex"][i]) else np.nan,
                vwap_p95_pt=float(rr["p95"][i]) if np.isfinite(rr["p95"][i]) else np.nan,
                vwap_ci_low=float(rr["p95"][i]-rr["p95_yerr"][0,i]) if np.isfinite(rr["p95"][i]) else np.nan,
                vwap_ci_high=float(rr["p95"][i]+rr["p95_yerr"][1,i]) if np.isfinite(rr["p95"][i]) else np.nan,
                N_lwmp=int(rr["ex_n"][i]),
                N_vwap=int(rr["pt_n"][i]),
            ))

    dLW05 = r05["ex"][-1] - r05["ex"][0]
    dLW10 = r10["ex"][-1] - r10["ex"][0]
    dVW05 = r05["p95"][-1] - r05["p95"][0]
    dVW10 = r10["p95"][-1] - r10["p95"][0]
    print(f"  [{qcol}] Δ(LWMP exceed%) Q5-Q1: δ=0.05 {dLW05:.3f}, δ=0.10 {dLW10:.3f}")
    print(f"  [{qcol}] Δ(VWAP p95 PT)  Q5-Q1: δ=0.05 {dVW05:.3f}, δ=0.10 {dVW10:.3f}")

summ = pd.DataFrame(rows_sum)
outcsv = os.path.join(OUTDIR, "Table_concentration_metric_robustness_summary.csv")
safe_to_csv(summ, outcsv, index=False)

# Spearman correlations of measures
corr_cols = ["hhi_base","max_share","neff","top_hhi_share","hhi_rest","hhi_rest_norm"]
corr = panel[corr_cols].dropna().corr(method="spearman")
outcorr = os.path.join(OUTDIR, "Table_concentration_measures_spearman_corr.csv")
safe_to_csv(corr, outcorr, index=True)
import numpy as np
import pandas as pd

def _scheme_to_q(scheme: str):
    m = {
        "median": 2,
        "tercile": 3,
        "quartile": 4,
        "quintile": 5,
        "decile": 10,
        # extreme_*：仍然先按 3/10 分组，再只取两端
        "extreme_tercile": 3,
        "extreme_decile": 10,
    }
    if scheme not in m:
        raise ValueError(f"Unknown scheme: {scheme}")
    return m[scheme]

def _measure_direction(measure_raw: str):
    """
    返回 +1 表示“数值越大越集中”，-1 表示“数值越大越分散，需要取负后再分组”
    你论文里想统一成“g 越大越集中”，那就靠这个。
    """
    # hhi_base/max_share/top_hhi_share/hhi_rest/hhi_rest_norm：大=更集中
    if measure_raw in ["hhi_base", "max_share", "top_hhi_share", "hhi_rest", "hhi_rest_norm"]:
        return +1
    # neff 大=更分散，所以要取负使其“越大越集中”
    if measure_raw in ["neff"]:
        return -1
    # 默认不变
    return +1

def debug_spearman_consistency(inj, measure_raw="hhi_base", scheme="quintile", delta=0.05, tol=1e-12):
    df = inj.copy()

    # 只看某个 delta
    df = df[np.isclose(df["delta_abs"].values, float(delta), atol=tol)].copy()
    if df.empty:
        print("[debug] empty after delta filter")
        return None

    # 构造 exceed / pt_vwap
    df["exceed"] = (df["shift_lwmp"].abs() >= (float(delta) - tol)).astype(int)
    df["pt_vwap"] = df["shift_vwap"].abs() / float(delta)
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["exceed", "pt_vwap", measure_raw]).copy()

    # 统一方向：让“越大越集中”
    direction = _measure_direction(measure_raw)
    df["_m_used"] = direction * pd.to_numeric(df[measure_raw], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["_m_used"]).copy()

    q = _scheme_to_q(scheme)
    # 分组：g=1..q
    g = pd.qcut(df["_m_used"], q=q, labels=list(range(1, q+1)), duplicates="drop")
    df["g"] = g.astype(int)

    # extreme：只取两端
    if scheme.startswith("extreme_"):
        df = df[(df["g"] == 1) | (df["g"] == q)].copy()

    # 组统计：你关心的 p95 和 exceed
    grp = df.groupby("g").agg(
        N=("g", "size"),
        mean_measure_used=("_m_used", "mean"),
        median_measure_used=("_m_used", "median"),
        exceed_rate=("exceed", "mean"),
        pt_mean=("pt_vwap", "mean"),
        pt_median=("pt_vwap", "median"),
        pt_p95=("pt_vwap", lambda x: float(np.nanquantile(x, 0.95))),
    ).reset_index()

    # 打印组表
    print(f"\n=== DEBUG measure={measure_raw} scheme={scheme} delta={delta} ===")
    print("direction used ( +1=no flip, -1=flip ): ", direction)
    print(grp.to_string(index=False))

    # 1) 检查 g 的方向：measure_used 是否随 g 上升
    corr_g_measure = grp["g"].corr(grp["mean_measure_used"], method="spearman")
    print("\n[check] spearman(g, mean_measure_used) =", float(corr_g_measure))

    if corr_g_measure < 0:
        print("  -> WARNING: g 方向可能反了（mean_measure_used 随 g 下降）。请检查你的 g 定义/是否做了取负。")

    # 2) 计算两种 spearman（观测层 vs 组层p95）
    spearman_obs_exceed = df["g"].corr(df["exceed_rate"] if "exceed_rate" in df.columns else df["exceed"], method="spearman")
    spearman_obs_pt     = df["g"].corr(df["pt_vwap"], method="spearman")

    spearman_grp_exceed = grp["g"].corr(grp["exceed_rate"], method="spearman")
    spearman_grp_p95    = grp["g"].corr(grp["pt_p95"], method="spearman")

    print("\n[spearman] OBS-level  corr(g, exceed) =", float(spearman_obs_exceed))
    print("[spearman] OBS-level  corr(g, pt_vwap) =", float(spearman_obs_pt))
    print("[spearman] GRP-level  corr(g, exceed_rate) =", float(spearman_grp_exceed))
    print("[spearman] GRP-level  corr(g, pt_p95) =", float(spearman_grp_p95))

    # 3) Qhi - Qlo 差值（用组层统计）
    g_low = grp["g"].min()
    g_high = grp["g"].max()
    lo = grp[grp["g"] == g_low].iloc[0]
    hi = grp[grp["g"] == g_high].iloc[0]
    d_exceed = (hi["exceed_rate"] - lo["exceed_rate"]) * 100.0
    d_p95 = hi["pt_p95"] - lo["pt_p95"]

    print("\n[diff] Qhi-Qlo exceed_rate (%) =", float(d_exceed))
    print("[diff] Qhi-Qlo pt_p95 =", float(d_p95))

    # 给结论提示
    print("\n[interpretation]")
    if np.sign(d_p95) != np.sign(spearman_grp_p95):
        print("  -> 组层 p95 的 Qhi-Qlo 与 spearman(g, pt_p95) 符号不一致：说明组内走势可能非单调（中间组拐弯）。")
    else:
        print("  -> 组层 p95 的方向与 spearman(g, pt_p95) 一致（单调性 OK）。")

    if np.sign(d_p95) != np.sign(spearman_obs_pt):
        print("  -> 逐观测 spearman(g, pt_vwap) 与尾部差值不一致：这很常见，原因是分布形状/中间组拐弯/厚尾。")
        print("     如果你的主统计是 pt_p95，那么表里更建议报 spearman(g, pt_p95) 而不是 spearman(g, pt_vwap)。")

    return grp
if __name__ == "__main__":
    print("\n[RUN DEBUG] start...")
    # 先核对最关键的：hhi_base + quintile
    debug_spearman_consistency(inj, measure_raw="hhi_base", scheme="quintile", delta=0.05, tol=TOL)
    debug_spearman_consistency(inj, measure_raw="hhi_base", scheme="quintile", delta=0.10, tol=TOL)

    # 再对比一个通常最“顺”的：max_share
    debug_spearman_consistency(inj, measure_raw="max_share", scheme="quintile", delta=0.05, tol=TOL)

    print("[RUN DEBUG] done.\n")

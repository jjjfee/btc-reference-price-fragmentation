import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ======================
# Paths
# ======================
ROOT  = str(Path(__file__).resolve().parents[2])
PANEL = os.path.join(ROOT, "hhi_panel", "btc_1m_panel_with_hhi.csv")
INJ   = os.path.join(ROOT, "experiments", "injection_shift_samples.csv")
OUT   = os.path.join(ROOT, "outputs", "main_text", "figures")
os.makedirs(OUT, exist_ok=True)

FIG5 = os.path.join(OUT, "Figure5_Passthrough_p95_LWMP_vs_VWAP_by_HHIquintile.png")

# ======================
# Helpers
# ======================
def pick_time_col(df):
    cols = list(df.columns)
    cand = []
    if len(cols) and str(cols[0]).lower().startswith("unnamed"):
        cand.append(cols[0])
    for c in cols:
        cl = str(c).lower()
        if any(k in cl for k in ["time","date","datetime","timestamp","ts","open","dt"]):
            cand.append(c)
    # unique keep order
    seen = set()
    cand = [c for c in cand if not (c in seen or seen.add(c))]

    best, best_rate = None, 0.0
    for c in cand:
        s = pd.to_datetime(df[c], errors="coerce", utc=True)
        rate = float(s.notna().mean())
        if rate > best_rate:
            best, best_rate = c, rate
    return best, best_rate

def pick_hhi_roll_col(cols):
    cols_l = [str(c).lower() for c in cols]
    # prioritize exact-like names
    for cand in ["hhi_roll", "hhiroll", "hhi_rolling"]:
        if cand in cols_l:
            return cols[cols_l.index(cand)]
    # fallback: contains both "hhi" and "roll"
    for c, cl in zip(cols, cols_l):
        if ("hhi" in cl) and ("roll" in cl):
            return c
    return None

def block_bootstrap_p95(values_by_day, B=300, q=0.95, seed=123):
    """
    values_by_day: dict(day -> 1d np.array)
    returns: (p_hat, lo, hi)
    """
    rng = np.random.default_rng(seed)
    days = np.array(list(values_by_day.keys()))
    if len(days) == 0:
        return (np.nan, np.nan, np.nan)

    # point estimate on full sample
    full = np.concatenate([values_by_day[d] for d in days if len(values_by_day[d])])
    if full.size == 0:
        return (np.nan, np.nan, np.nan)
    p_hat = np.quantile(full, q)

    # bootstrap by resampling days
    boots = []
    for _ in range(B):
        draw = rng.choice(days, size=len(days), replace=True)
        sample = np.concatenate([values_by_day[d] for d in draw if len(values_by_day[d])])
        if sample.size:
            boots.append(np.quantile(sample, q))
    if len(boots) < 10:
        return (p_hat, np.nan, np.nan)

    lo, hi = np.quantile(np.array(boots), [0.025, 0.975])
    return (p_hat, lo, hi)

# ======================
# 1) Panel -> q (HHI quintile)
# ======================
panel_head = pd.read_csv(PANEL, nrows=5000, low_memory=False)
tcol, trate = pick_time_col(panel_head)
if tcol is None or trate < 0.5:
    raise ValueError(f"[panel] 没找到可解析的时间列（最佳解析率={trate:.2f}），请 print(panel_head.columns)")

hhi_col = pick_hhi_roll_col(panel_head.columns)
if hhi_col is None:
    raise ValueError("[panel] 没找到 hhi_roll 列（列名需包含 hhi 和 roll），请 print(panel_head.columns)")

panel = pd.read_csv(PANEL, low_memory=False)
panel.columns = [c.lower() for c in panel.columns]
tcol_l = str(tcol).lower()
hhi_l  = str(hhi_col).lower()

panel["time_utc"] = pd.to_datetime(panel[tcol_l], errors="coerce", utc=True).dt.floor("min")
x = pd.to_numeric(panel[hhi_l], errors="coerce").replace([np.inf, -np.inf], np.nan)

# quintile
panel["q"] = pd.qcut(x, 5, labels=[1,2,3,4,5], duplicates="drop")
panel = panel[["time_utc", "q"]].dropna()
panel["q"] = panel["q"].astype(int)

# ======================
# 2) Injection samples -> merge q
# ======================
inj = pd.read_csv(INJ, low_memory=False)
inj.columns = [c.lower() for c in inj.columns]

need_cols = ["time_utc", "delta", "shift_lwmp", "shift_vwap"]
missing = [c for c in need_cols if c not in inj.columns]
if missing:
    raise ValueError(f"[inj] 缺少列：{missing}\n实际列：{list(inj.columns)[:30]} ...")

inj["time_utc"] = pd.to_datetime(inj["time_utc"], errors="coerce", utc=True).dt.floor("min")
inj["delta"] = pd.to_numeric(inj["delta"], errors="coerce")
inj["shift_lwmp"] = pd.to_numeric(inj["shift_lwmp"], errors="coerce")
inj["shift_vwap"] = pd.to_numeric(inj["shift_vwap"], errors="coerce")

inj = inj.dropna(subset=["time_utc","delta","shift_lwmp","shift_vwap"]).copy()
inj["delta_abs"] = inj["delta"].abs()

# 你想“只讨论 δ∈{0.02,0.05,0.10}”就开这个；否则就关掉保留全部δ
FILTER_DELTAS = True
TARGET = np.array([0.02, 0.05, 0.10], dtype=float)

if FILTER_DELTAS:
    keep = np.zeros(len(inj), dtype=bool)
    for d in TARGET:
        keep |= np.isclose(inj["delta_abs"].values, d, atol=1e-12)
    inj = inj[keep].copy()

# 打印实际有哪些 δ
dlist = np.sort(inj["delta_abs"].round(6).unique())
print("Available |delta| in inj:", dlist)

inj = inj.merge(panel, on="time_utc", how="left")
inj = inj.dropna(subset=["q"]).copy()
inj["q"] = inj["q"].astype(int)

# ======================
# 3) δ-insensitive metrics: pass-through ratio
# ======================
inj["pt_lwmp"] = inj["shift_lwmp"].abs() / inj["delta_abs"]
inj["pt_vwap"] = inj["shift_vwap"].abs() / inj["delta_abs"]

# 可选：避免极端除法异常（理论上 delta_abs>0）
inj = inj.replace([np.inf, -np.inf], np.nan).dropna(subset=["pt_lwmp","pt_vwap"])

# block bootstrap by day
inj["day"] = inj["time_utc"].dt.floor("D")

# ======================
# 4) p95(pass-through) by quintile with block bootstrap CI
# ======================
B = 300
qs = [1,2,3,4,5]

def p95_by_q(df, col):
    out = []
    for q in qs:
        sub = df[df["q"]==q]
        # build day->values dict
        values_by_day = {}
        for d, g in sub.groupby("day"):
            arr = g[col].dropna().to_numpy()
            if arr.size:
                values_by_day[d] = arr
        p, lo, hi = block_bootstrap_p95(values_by_day, B=B, q=0.95, seed=123+q)
        out.append((p, lo, hi))
    out = np.array(out, dtype=float)
    return out[:,0], out[:,1], out[:,2]

pL, loL, hiL = p95_by_q(inj, "pt_lwmp")
pV, loV, hiV = p95_by_q(inj, "pt_vwap")

# ======================
# 5) Plot Figure 5 (clean)
# ======================
x = np.array(qs)

fig, ax = plt.subplots(figsize=(8.5, 5.5))

# LWMP
yerrL = np.vstack([pL-loL, hiL-pL])
ax.errorbar(x, pL, yerr=yerrL, marker="o", capsize=3, label="LWMP p95(|shift|/|δ|)")

# VWAP
yerrV = np.vstack([pV-loV, hiV-pV])
ax.errorbar(x, pV, yerr=yerrV, marker="s", linestyle="--", capsize=3, label="VWAP p95(|shift|/|δ|)")

ax.set_xticks(x)
ax.set_xticklabels(["Q1 (low)","Q2","Q3","Q4","Q5 (high)"])
ax.set_xlabel("HHI_roll quintile")
ax.set_ylabel("Pass-through ratio  p95(|shift|/|δ|)")
ax.set_title("Pass-through robustness vs liquidity concentration (δ-insensitive)")
ax.grid(True, alpha=0.25)
ax.legend(frameon=False, ncol=2, loc="upper left")

# 可选：在图角落标注“使用了哪些δ”
if FILTER_DELTAS:
    ax.text(0.02, 0.02, f"|δ| in {{{', '.join([f'{d:.2f}' for d in dlist])}}}",
            transform=ax.transAxes, fontsize=9, va="bottom")

fig.tight_layout()
fig.savefig(FIG5, dpi=300)
plt.close(fig)

print("Saved FIG5:", FIG5)
print("LWMP p95 PT:", pL)
print("VWAP p95 PT:", pV)

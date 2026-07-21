import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT  = str(Path(__file__).resolve().parents[2])
PANEL = os.path.join(ROOT, "hhi_panel", "btc_1m_panel_with_hhi.csv")
INJ   = os.path.join(ROOT, "experiments", "injection_shift_samples.csv")
OUTDIR = os.path.join(ROOT, "outputs", "main_text", "figures")
os.makedirs(OUTDIR, exist_ok=True)

OUTFIG = os.path.join(OUTDIR, "Figure6_DualAxis_LWMP_exceed_vs_VWAP_PT_p95_by_HHIquintile.png")

# -------- helpers --------
def pick_time_col(df, min_rate=0.5):
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
    if best is None or best_rate < min_rate:
        return None, best_rate
    return best, best_rate

def pick_hhi_roll_col(cols):
    cols_l = [str(c).lower() for c in cols]
    # prefer common names
    for cand in ["hhi_roll", "hhiroll", "hhi_rolling"]:
        if cand in cols_l:
            return cols[cols_l.index(cand)]
    # fallback: contains both
    for c, cl in zip(cols, cols_l):
        if ("hhi" in cl) and ("roll" in cl):
            return c
    return None

def wilson_ci(k, n, z=1.96):
    # Binomial Wilson CI for proportion k/n
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
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    if x.size > maxn:
        x = rng.choice(x, size=maxn, replace=False)

    p0 = float(np.quantile(x, 0.95))
    n = x.size
    # bootstrap resample indices
    idx = rng.integers(0, n, size=(B, n))
    boot = np.quantile(x[idx], 0.95, axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return (p0, float(lo), float(hi))

# -------- 1) panel -> HHI quintile q --------
panel_head = pd.read_csv(PANEL, nrows=5000, low_memory=False)
tcol, trate = pick_time_col(panel_head, min_rate=0.5)
if tcol is None:
    raise ValueError(f"[panel] 找不到可解析时间列（解析率={trate:.2f}）。请 print(panel_head.columns)")

hhi_col = pick_hhi_roll_col(panel_head.columns)
if hhi_col is None:
    raise ValueError("[panel] 找不到 hhi_roll 列（列名需包含 hhi + roll）。请 print(panel_head.columns)")

panel = pd.read_csv(PANEL, low_memory=False)
panel.columns = [c.lower() for c in panel.columns]
tcol_l = str(tcol).lower()
hhi_l  = str(hhi_col).lower()

panel["time_utc"] = pd.to_datetime(panel[tcol_l], errors="coerce", utc=True).dt.floor("min")
x = pd.to_numeric(panel[hhi_l], errors="coerce").replace([np.inf, -np.inf], np.nan)

panel["q"] = pd.qcut(x, 5, labels=[1,2,3,4,5], duplicates="drop")
panel = panel[["time_utc", "q"]].dropna()
panel["q"] = panel["q"].astype(int)

# -------- 2) injections -> merge q --------
inj = pd.read_csv(INJ, low_memory=False)
inj.columns = [c.lower() for c in inj.columns]

need = ["time_utc", "delta", "shift_lwmp", "shift_vwap"]
missing = [c for c in need if c not in inj.columns]
if missing:
    raise ValueError(f"[inj] 缺少列：{missing}\n实际列前30：{list(inj.columns)[:30]}")

inj["time_utc"] = pd.to_datetime(inj["time_utc"], errors="coerce", utc=True).dt.floor("min")
inj["delta"] = pd.to_numeric(inj["delta"], errors="coerce")
inj["shift_lwmp"] = pd.to_numeric(inj["shift_lwmp"], errors="coerce")
inj["shift_vwap"] = pd.to_numeric(inj["shift_vwap"], errors="coerce")

inj = inj.dropna(subset=["time_utc","delta","shift_lwmp","shift_vwap"]).copy()
inj["delta_abs"] = inj["delta"].abs()

# 只保留你实际有的两档δ（0.05,0.10），并池化
TARGET = np.array([0.05, 0.10])
keep = np.zeros(len(inj), dtype=bool)
for d in TARGET:
    keep |= np.isclose(inj["delta_abs"].values, d, atol=1e-12)
inj = inj[keep].copy()

dlist = np.sort(inj["delta_abs"].round(6).unique())
print("Available |delta| used (pooled):", dlist)

inj = inj.merge(panel, on="time_utc", how="left").dropna(subset=["q"]).copy()
inj["q"] = inj["q"].astype(int)

# ======= REPLACE EVERYTHING FROM HERE (original section 3/4/5) =======

# 目标 delta
TARGET = [0.05, 0.10]
TOL = 1e-12
qs = [1, 2, 3, 4, 5]
x = np.array(qs)

# ---- 先为每个 delta 单独计算：LWMP exceed(%) + Wilson CI；VWAP p95(PT) + bootstrap CI ----
res = {}

for d in TARGET:
    sub = inj[np.isclose(inj["delta_abs"].values, d, atol=TOL)].copy()
    if sub.empty:
        print(f"[WARN] |delta|={d}: no rows found.")
        continue

    # LWMP exceed: |shift_lwmp| >= |delta|
    sub["exceed_lwmp"] = (sub["shift_lwmp"].abs() >= (d - TOL)).astype(int)

    ex_rate = []
    ex_yerr = []   # (2,5) in %
    ex_n = []

    for q in qs:
        s = sub[sub["q"] == q]
        n = int(len(s))
        k = int(s["exceed_lwmp"].sum())
        p = (k / n) if n > 0 else np.nan
        lo, hi = wilson_ci(k, n)
        ex_rate.append(p * 100.0)
        ex_yerr.append([(p - lo) * 100.0, (hi - p) * 100.0])
        ex_n.append(n)

    ex_rate = np.array(ex_rate, dtype=float)
    ex_yerr = np.array(ex_yerr, dtype=float).T  # -> shape (2,5)

    # VWAP pass-through: |shift_vwap|/|delta|，取 p95
    sub["pt_vwap"] = sub["shift_vwap"].abs() / d
    sub = sub.replace([np.inf, -np.inf], np.nan).dropna(subset=["pt_vwap"])

    p95 = []
    p95_yerr = []
    pt_n = []

    for q in qs:
        s = sub[sub["q"] == q]
        arr = s["pt_vwap"].dropna().to_numpy()
        pt_n.append(int(len(arr)))
        p0, lo0, hi0 = bootstrap_p95_ci(arr, B=300, seed=123 + int(d * 1000) + q, maxn=200_000)
        p95.append(p0)
        p95_yerr.append([p0 - lo0, hi0 - p0])

    p95 = np.array(p95, dtype=float)
    p95_yerr = np.array(p95_yerr, dtype=float).T  # (2,5)

    res[d] = {
        "ex": ex_rate,
        "ex_yerr": ex_yerr,
        "ex_n": ex_n,
        "p95": p95,
        "p95_yerr": p95_yerr,
        "pt_n": pt_n
    }

print("Available deltas plotted:", sorted(res.keys()))

# ---- 画图：双轴、无图例、末端标注（终稿风格）----
OUTFIG2 = os.path.join(OUTDIR, "Figure6_DualAxis_delta005_vs_010_endlabels.png")

fig, axL = plt.subplots(figsize=(8.6, 5.4))
axR = axL.twinx()

# 同 delta：LWMP 实线；VWAP 虚线；并且同色
style_L = {0.05: dict(fmt="o-", linewidth=2),
           0.10: dict(fmt="^-", linewidth=2)}
style_R = {0.05: dict(fmt="s--", linewidth=2),
           0.10: dict(fmt="D--", linewidth=2)}

color_map = {}

for d in TARGET:
    if d not in res:
        continue

    # 左轴：LWMP exceed (%)
    hL = axL.errorbar(
        x, res[d]["ex"], yerr=res[d]["ex_yerr"],
        capsize=4, **style_L[d]
    )
    color_map[d] = hL[0].get_color()

    # 右轴：VWAP p95 PT (ratio) —— 强制同色
    axR.errorbar(
        x, res[d]["p95"], yerr=res[d]["p95_yerr"],
        capsize=4, color=color_map[d], **style_R[d]
    )

# 轴标签/网格（终稿更干净：title 留给 caption）
axL.set_title("")
axL.set_xticks(x)
axL.set_xticklabels(["Q1 (low)", "Q2", "Q3", "Q4", "Q5 (high)"])
axL.set_xlabel("HHI_roll quintile")
axL.set_ylabel("LWMP exceedance rate (%)")
axR.set_ylabel("VWAP p95 pass-through (|shift|/|δ|)")
axL.grid(True, alpha=0.25)

# ========= 上方外置标注（替代末端标注 / 无图例）=========
def key_item(ax, x0, y0, color, ls, marker, text):
    ax.plot([x0, x0+0.06], [y0, y0], transform=ax.transAxes,
            color=color, linestyle=ls, linewidth=2, clip_on=False)
    ax.plot([x0+0.03], [y0], transform=ax.transAxes,
            color=color, marker=marker, markersize=7, linestyle="None",
            clip_on=False)
    ax.text(x0+0.07, y0, text, transform=ax.transAxes,
            ha="left", va="center", fontsize=12, color=color)

# 给上方留空间（别用 tight_layout 把它挤没）
fig.subplots_adjust(top=0.82)

c05 = color_map.get(0.05, "C0")
c10 = color_map.get(0.10, "C1")

# 两列两行（y>1 表示画在轴上方）
y_row1, y_row2 = 1.08, 1.03
x_col1, x_col2 = 0.05, 0.55

# LWMP（左列，实线）
key_item(axL, x_col1, y_row1, c05, "-",  "o", "LWMP  δ=0.05")
key_item(axL, x_col1, y_row2, c10, "-",  "^", "LWMP  δ=0.10")

# VWAP（右列，虚线）
key_item(axL, x_col2, y_row1, c05, "--", "s", "VWAP  δ=0.05")
key_item(axL, x_col2, y_row2, c10, "--", "D", "VWAP  δ=0.10")
# ===============================================

# 不需要给右侧留大空白，因为标签在图内
axL.set_xlim(0.85, 5.15)

fig.tight_layout()
fig.savefig(OUTFIG2, dpi=300)
plt.close(fig)

print("Saved:", OUTFIG2)

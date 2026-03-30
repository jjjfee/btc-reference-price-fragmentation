import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT  = r"D:\cilck here\2代目"
PANEL = os.path.join(ROOT, "hhi_panel", "btc_1m_panel_with_hhi.csv")
INJ   = os.path.join(ROOT, "experiments", "injection_shift_samples.csv")
OUTDIR = os.path.join(ROOT, "paper_outputs_frl")
os.makedirs(OUTDIR, exist_ok=True)

DELTAS = [0.02, 0.05, 0.10]
PIVOT_THRESH = 0.5
TOL = 1e-10

# --- helpers ---
def pick_time_col(df, min_parse_rate=0.5):
    cols = list(df.columns)
    cand = []
    if len(cols) > 0 and str(cols[0]).lower().startswith("unnamed"):
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

    if best is None or best_rate < min_parse_rate:
        return None, best_rate
    return best, best_rate

def find_col(cols, candidates, contains_all=None):
    cols_l = [str(c).lower() for c in cols]
    for cand in candidates:
        for i, c in enumerate(cols_l):
            if cand in c:
                return cols[i]
    if contains_all:
        for i, c in enumerate(cols_l):
            ok = True
            for k in contains_all:
                if k not in c:
                    ok = False
                    break
            if ok:
                return cols[i]
    return None

def wilson_ci(k, n, z=1.96):
    # k successes out of n
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = (z*np.sqrt((p*(1-p)/n) + (z*z/(4*n*n)))) / den
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return lo, hi

def bootstrap_p95_ci(x, B=300, rng=None, m=50000):
    # memory-safe bootstrap: sample size m each replicate
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    p0 = float(np.quantile(x, 0.95))
    if rng is None:
        rng = np.random.default_rng(123)
    m = int(min(len(x), m))
    boots = np.empty(B, dtype=float)
    for b in range(B):
        xb = rng.choice(x, size=m, replace=True)
        boots[b] = np.quantile(xb, 0.95)
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return p0, float(lo), float(hi)

# --- 1) load panel: time + max_share regime ---
panel_sample = pd.read_csv(PANEL, nrows=5000, low_memory=False)
time_col, rate = pick_time_col(panel_sample, min_parse_rate=0.5)
if time_col is None:
    raise ValueError(f"panel 里没找到可解析的时间列（最佳解析率={rate:.2f}）。请先 print(panel_sample.columns) 查看。")

panel = pd.read_csv(PANEL, low_memory=False)
panel.columns = [c.lower() for c in panel.columns]
time_col_l = str(time_col).lower()

# 原始 time_col 在全量 panel 里可能大小写不同：用 lower 后重新匹配
real_time_col = None
for c in panel.columns:
    if c == time_col_l:
        real_time_col = c
        break
if real_time_col is None:
    # 兜底：模糊匹配
    for c in panel.columns:
        if time_col_l in c:
            real_time_col = c
            break
if real_time_col is None:
    raise ValueError("panel 时间列匹配失败，请 print(panel.columns) 检查。")

max_share_col = find_col(panel.columns, candidates=["max_share", "maxshare"], contains_all=["max","share"])
if max_share_col is None:
    raise ValueError("panel 里找不到 max_share 列（请 print(panel.columns) 检查列名）。")

panel["time_utc"] = pd.to_datetime(panel[real_time_col], errors="coerce", utc=True).dt.floor("min")
panel["max_share"] = pd.to_numeric(panel[max_share_col], errors="coerce")
panel_small = panel[["time_utc", "max_share"]].dropna().copy()
panel_small["regime"] = np.where(panel_small["max_share"] > PIVOT_THRESH, ">0.5", "<=0.5")

# --- 2) load injection samples ---
inj = pd.read_csv(INJ, low_memory=False)
inj.columns = [c.lower() for c in inj.columns]

inj_time_col = find_col(inj.columns, candidates=["time_utc", "time", "timestamp", "datetime", "open_time"], contains_all=["time"])
if inj_time_col is None:
    raise ValueError("injection_shift_samples.csv 里找不到时间列（如 time_utc）。")

delta_col = find_col(inj.columns, candidates=["delta"])
if delta_col is None:
    raise ValueError("injection_shift_samples.csv 里找不到 delta 列。")

shift_lwmp_col = find_col(inj.columns, candidates=["shift_lwmp"], contains_all=["shift","lwmp"])
shift_vwap_col = find_col(inj.columns, candidates=["shift_vwap"], contains_all=["shift","vwap"])
if shift_lwmp_col is None or shift_vwap_col is None:
    raise ValueError("injection_shift_samples.csv 里找不到 shift_lwmp / shift_vwap 列，请检查列名。")

inj["time_utc"] = pd.to_datetime(inj[inj_time_col], errors="coerce", utc=True).dt.floor("min")
inj["delta"] = pd.to_numeric(inj[delta_col], errors="coerce")
inj["shift_lwmp"] = pd.to_numeric(inj[shift_lwmp_col], errors="coerce")
inj["shift_vwap"] = pd.to_numeric(inj[shift_vwap_col], errors="coerce")

# 合并 regime（按注入发生的分钟对齐 panel 的 max_share）
inj = inj.merge(panel_small, on="time_utc", how="left")
inj = inj.dropna(subset=["regime", "delta"])

# --- 3) make Figure4 for each delta ---
rng = np.random.default_rng(123)

for d in DELTAS:
    sub = inj[np.isclose(inj["delta"].abs(), d, atol=1e-12)].copy()
    sub = sub.dropna(subset=["shift_lwmp", "shift_vwap", "regime"])
    if sub.empty:
        print(f"[WARN] delta={d}: no rows found.")
        continue

    # regimes in fixed order
    regs = ["<=0.5", ">0.5"]

    # Panel A: LWMP jump failures = Pr(|shift_lwmp| >= |delta|)
    sub["jump"] = (sub["shift_lwmp"].abs() >= (sub["delta"].abs() - TOL)).astype(int)

    A_p = []
    A_lo = []
    A_hi = []
    A_n = []

    for r in regs:
        x = sub[sub["regime"] == r]
        n = int(len(x))
        k = int(x["jump"].sum())
        lo, hi = wilson_ci(k, n)
        A_p.append(k / n if n > 0 else np.nan)
        A_lo.append(lo)
        A_hi.append(hi)
        A_n.append(n)

    A_p = np.array(A_p)
    A_lo = np.array(A_lo)
    A_hi = np.array(A_hi)
    A_yerr = np.vstack([(A_p - A_lo)*100, (A_hi - A_p)*100])

    # Panel B: VWAP tail risk = p95(|shift_vwap|) with bootstrap CI
    sub["abs_vwap"] = sub["shift_vwap"].abs()

    B_p = []
    B_lo = []
    B_hi = []
    B_n = []

    for r in regs:
        x = sub.loc[sub["regime"] == r, "abs_vwap"].dropna().to_numpy()
        B_n.append(int(len(x)))
        p0, lo0, hi0 = bootstrap_p95_ci(x, B=300, rng=rng, m=50000)
        B_p.append(p0)
        B_lo.append(lo0)
        B_hi.append(hi0)

    B_p = np.array(B_p) * 100
    B_lo = np.array(B_lo) * 100
    B_hi = np.array(B_hi) * 100
    B_yerr = np.vstack([B_p - B_lo, B_hi - B_p])

    # --- plot: 2 panels vertical ---
    fig, axes = plt.subplots(2, 1, figsize=(7.5, 7.5), sharex=True)

    # x positions
    xs = np.array([1, 2])
    xticklabels = [
        f"max_share ≤ 0.5\nN={A_n[0]:,}",
        f"max_share > 0.5\nN={A_n[1]:,}",
    ]

    # A
    ax = axes[0]
    ax.errorbar(xs, A_p*100, yerr=A_yerr, marker="o", capsize=4, linewidth=2)
    ax.set_ylabel("LWMP jump failures (%)")
    ax.set_ylim(0, np.nanmax(A_p*100 + A_yerr[1]) * 1.20 + 1e-9)
    ax.grid(True, alpha=0.25)

    # B
    ax2 = axes[1]
    ax2.errorbar(xs, B_p, yerr=B_yerr, marker="s", capsize=4, linewidth=2, linestyle="--")
    ax2.set_ylabel("VWAP p95(|shift|) (%)")
    ax2.set_ylim(0, np.nanmax(B_p + B_yerr[1]) * 1.20 + 1e-9)
    ax2.grid(True, alpha=0.25)

    axes[1].set_xticks(xs)
    axes[1].set_xticklabels(xticklabels)
    axes[1].set_xlabel("Liquidity concentration regime (max_share)")

    fig.suptitle(f"Robustness breakdown at pivot-exchange threshold (|δ|={d:.2f})", fontsize=16, y=0.98)
    fig.text(
        0.01, 0.01,
        "Error bars: 95% CI. Panel A uses Wilson CI; Panel B uses bootstrap CI for the 95th percentile.",
        fontsize=9
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.95])

    out_png = os.path.join(OUTDIR, f"Figure4_maxshare_threshold_panels_delta{d:.2f}.png")
    fig.savefig(out_png, dpi=300)
    plt.close(fig)

    print(f"Saved: {out_png}")
    print("Counts:", {"<=0.5": A_n[0], ">0.5": A_n[1]})
    print("LWMP jump_share(%):", np.round(A_p*100, 4))
    print("VWAP p95(%):", np.round(B_p, 4))
    print()

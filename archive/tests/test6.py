import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
evt_path = BASE / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
panel_path = BASE / "hhi_panel" / "btc_1m_panel_with_hhi.csv"
xlsx_path = BASE / "experiments" / "DVonly_Injection_By_HHIrollQuintile.xlsx"

evt = pd.read_csv(evt_path)
evt["time_utc"] = pd.to_datetime(evt["time_utc"], utc=True).dt.floor("min")

panel = pd.read_csv(panel_path)
panel["time_utc"] = pd.to_datetime(panel["time_utc_dt"], utc=True).dt.floor("min")
panel["HHI_roll"] = pd.to_numeric(panel["HHI_roll"], errors="coerce")

LABELS = ["Q1(low)","Q2","Q3","Q4","Q5(high)"]
p2 = panel[["time_utc","HHI_roll"]].dropna().drop_duplicates("time_utc", keep="last").copy()
p2["HHIroll_quintile"] = pd.qcut(p2["HHI_roll"], 5, labels=LABELS)

df = evt.merge(p2[["time_utc","HHIroll_quintile"]], on="time_utc", how="left").dropna(subset=["HHIroll_quintile"])

# 只对重叠 gamma=0.5 做“指纹”
g = 0.5
dfg = df[np.isclose(df["delta_w"], g)].copy()

def summarize(sub):
    out = []
    for q, s in sub.groupby("HHIroll_quintile", observed=True):
        vwap = np.abs(pd.to_numeric(s["shift_vwap"], errors="coerce")).dropna().to_numpy()
        piv = pd.to_numeric(s["pivot_changed"], errors="coerce").dropna().to_numpy()
        out.append({
            "HHIroll_quintile": str(q),
            "VWAP_p95_abs_shift": float(np.quantile(vwap, 0.95)) if len(vwap) else np.nan,
            "pivot_switch_rate": float(piv.mean()) if len(piv) else np.nan,
            "n": int(len(s))
        })
    return pd.DataFrame(out).sort_values("HHIroll_quintile")

for st in ["inflate_only","reallocate_total_fixed"]:
    s = summarize(dfg[dfg["shock_type"]==st])
    print("\nshock_type =", st)
    print(s.to_string(index=False))

# 旧 xlsx 里取 gamma=0.5 的行（列名按你截图的那套）
old = pd.read_excel(xlsx_path)
old = old[np.isclose(old["gamma"], 0.5)]
print("\nold xlsx gamma=0.5")
print(old[["HHIroll_quintile","VWAP_p95_abs_shift","LWMP_pivot_switch_rate","n"]].to_string(index=False))

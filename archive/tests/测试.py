import pandas as pd
import numpy as np

PANEL = str(Path(__file__).resolve().parents[2] / Path("hhi_panel/btc_1m_panel_with_hhi.csv"))

sample = pd.read_csv(PANEL, nrows=5000, low_memory=False)
print("COLUMNS:", list(sample.columns))

def pick_time_col(df):
    cols = list(df.columns)
    # 候选：包含 time/date/ts/dt/timestamp/open 的列 + 第一列是 Unnamed 也算
    cand = []
    if str(cols[0]).lower().startswith("unnamed"):
        cand.append(cols[0])
    for c in cols:
        cl = str(c).lower()
        if any(k in cl for k in ["time","date","datetime","timestamp","ts","open","dt"]):
            cand.append(c)

    # 去重但保序
    seen = set()
    cand = [c for c in cand if not (c in seen or seen.add(c))]

    best, best_rate = None, 0.0
    for c in cand:
        s = pd.to_datetime(df[c], errors="coerce", utc=True)
        rate = float(s.notna().mean())
        if rate > best_rate:
            best, best_rate = c, rate

    return best, best_rate, cand

best, rate, cand = pick_time_col(sample)
print("TIME CANDIDATES:", cand)
print("BEST TIME COL:", best, "PARSE RATE:", rate)

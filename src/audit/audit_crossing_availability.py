# audit_crossing_availability.py
from pathlib import Path
import pandas as pd
import numpy as np

PANEL = Path(r"D:\cilck here\2代目\hhi_panel\btc_1m_panel_with_hhi.csv")
OUTDIR = Path(r"D:\cilck here\2代目\experiments_dvonly\audit_lockin")
OUTDIR.mkdir(parents=True, exist_ok=True)

THR = 0.5

pn = pd.read_csv(PANEL)
tcol = "time_utc_dt" if "time_utc_dt" in pn.columns else "time_utc"
pn["time_utc"] = pd.to_datetime(pn[tcol], errors="coerce", utc=True).dt.floor("min")
pn["max_share"] = pd.to_numeric(pn["max_share"], errors="coerce")
pn = pn.dropna(subset=["time_utc","max_share"]).sort_values("time_utc").reset_index(drop=True)

x = pn["max_share"].to_numpy(float)
lock = (x > THR).astype(int)

# basic share
share_lock = float(lock.mean())
print("share(max_share>0.5) =", share_lock)

# find runs
runs = []
start = 0
cur = lock[0]
for i in range(1, len(lock)):
    if lock[i] != cur:
        runs.append((cur, start, i-1))
        start = i
        cur = lock[i]
runs.append((cur, start, len(lock)-1))

# summarize runs
rows = []
for val, i0, i1 in runs:
    st = pn.loc[i0, "time_utc"]
    ed = pn.loc[i1, "time_utc"]
    dur = int((ed - st) / pd.Timedelta(minutes=1)) + 1
    rows.append({"state_lockin": int(val), "start": st, "end": ed, "dur_min": dur,
                 "min_max_share": float(np.nanmin(x[i0:i1+1])),
                 "med_max_share": float(np.nanmedian(x[i0:i1+1])),
                 "max_max_share": float(np.nanmax(x[i0:i1+1]))})

run_df = pd.DataFrame(rows)
run_df.to_csv(OUTDIR / "audit_runs_lockin_by_maxshare.csv", index=False, encoding="utf-8-sig")

# longest <=0.5 run
below = run_df[run_df["state_lockin"] == 0]
if len(below):
    j = below["dur_min"].idxmax()
    print("longest run max_share<=0.5:", below.loc[j, "dur_min"], "min",
          "from", below.loc[j, "start"], "to", below.loc[j, "end"])
else:
    print("no minutes with max_share<=0.5 at all")

# how many 'up-crossings'
prev = np.r_[0, lock[:-1]]
cross_up = np.where((prev == 0) & (lock == 1))[0]
print("count(up-crossings) =", int(len(cross_up)))

print("saved:", OUTDIR / "audit_runs_lockin_by_maxshare.csv")
# add to your audit script after you built run_df
above = run_df[run_df["state_lockin"] == 1]
below = run_df[run_df["state_lockin"] == 0]

def describe_runs(df, name):
    if len(df) == 0:
        print(f"{name}: none")
        return
    qs = df["dur_min"].quantile([0.5, 0.9, 0.95, 0.99]).to_dict()
    print(f"{name}: count={len(df)}, longest={df['dur_min'].max()} min, "
          f"median={qs[0.5]:.0f}, p90={qs[0.9]:.0f}, p95={qs[0.95]:.0f}, p99={qs[0.99]:.0f}")

describe_runs(below, "runs max_share<=0.5")
describe_runs(above, "runs max_share>0.5")

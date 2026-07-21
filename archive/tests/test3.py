import pandas as pd
from pathlib import Path

csv_path = (Path(__file__).resolve().parents[2] / Path("experiments_dvonly/dvon_injection_shift_samples.csv"))
df = pd.read_csv(csv_path)

print("shape =", df.shape)
print("columns =", df.columns.tolist())

# 1) 时间列能不能解析
t = pd.to_datetime(df["time_utc"], errors="coerce", utc=True)
print("time parse ok rate =", t.notna().mean())

# 2) pivot_changed 是否只有 0/1
print("pivot_changed unique =", sorted(df["pivot_changed"].dropna().unique()))

# 3) 关键列缺失率（按你的叙事）
key_cols = ["gamma","delta","shock_type","exchange_shocked","pivot_exchange_before","pivot_exchange_after","pivot_changed"]
for c in key_cols:
    if c in df.columns:
        print(c, "missing =", df[c].isna().mean())
print("pivot_changed rate =", df["pivot_changed"].mean())
print(df.groupby("gamma")["pivot_changed"].mean().head(20))

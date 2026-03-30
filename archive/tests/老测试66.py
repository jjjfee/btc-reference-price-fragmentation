import pandas as pd

fp = r"D:\cilck here\2代目\experiments_dvonly\exclude_binance\dvon_injection_shift_samples.csv"
df = pd.read_csv(fp)

# 1) Binance 不应出现
print("has Binance shocked:", (df["exchange_shocked"]=="Binance").any())
print("has Binance pivot before:", (df["pivot_exchange_before"]=="Binance").any())
print("has Binance pivot after:", (df["pivot_exchange_after"]=="Binance").any())

# 2) DV-only 恒等式：mean/median shift=0
print("nonzero shift_mean:", (df["shift_mean"]!=0).sum())
print("nonzero shift_median:", (df["shift_median"]!=0).sum())

# 3) pivot_changed=0 => shift_lwmp 应该全为 0（允许极少数浮点误差就设阈值）
tol = 1e-12
bad = df.loc[df["pivot_changed"]==0, "shift_lwmp"].abs().gt(tol).sum()
print("pivot_changed=0 but |shift_lwmp|>tol:", bad)

# 4) inflate_only 且 weight_factor<1 => share_after < share_before（只检查这一类）
sub = df[(df["shock_type"]=="inflate_only") & (df["weight_factor"]<1)]
print("inflate_only factor<1 but share_after>=share_before:", (sub["share_shocked_after"]>=sub["share_shocked_before"]).sum())

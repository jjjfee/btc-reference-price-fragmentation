import pandas as pd
import numpy as np

csv_path = str(Path(__file__).resolve().parents[2] / Path("experiments_dvonly/dvon_injection_shift_samples.csv"))

# 1) 读入
df = pd.read_csv(csv_path, low_memory=False)

# 2) 把关键列转成数值，避免字符串导致奇怪比较
num_cols = ["delta_w", "weight_factor", "share_shocked_before", "share_shocked_after",
            "pivot_margin_before", "pivot_margin_after", "pivot_changed",
            "shift_mean", "shift_median", "shift_vwap", "shift_lwmp"]
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# 3) 计算“理论上应该得到的 share_after”（这就是你想要的 share_after_true）
s = df["share_shocked_before"].to_numpy(dtype=float)
f = df["weight_factor"].to_numpy(dtype=float)

# 公式：s_after_expected = s*f / (s*f + (1-s))
sf = s * f
den = sf + (1.0 - s)

# 防止极端情况下 den=0（理论上不会，但加保护更稳）
s_after_expected = np.where(np.isfinite(den) & (np.abs(den) > 0), sf / den, np.nan)

# ★关键：把它写回 df，否则你后面 df["share_after_true"] 一定 KeyError
df["share_after_true"] = s_after_expected

# 4) 核查 4a：share_after_true 必须在 [0,1]
bad_range = df[(df["share_after_true"] < -1e-12) | (df["share_after_true"] > 1 + 1e-12)]
print("bad_range rows =", len(bad_range))
if len(bad_range):
    print(bad_range[["delta_w","weight_factor","share_shocked_before","share_after_true"]].head(10))

# 5) 核查 4b：你的 CSV 里 share_shocked_after 是否等于理论值 share_after_true
diff = (df["share_shocked_after"] - df["share_after_true"]).abs()
print("\nCheck share_shocked_after vs share_after_true:")
print("  median abs diff =", float(diff.median()))
print("  p95 abs diff    =", float(diff.quantile(0.95)))
print("  max abs diff    =", float(diff.max()))

# 6) 把“差异最大的样本”打印出来（定位到底是哪类行不符合）
top = df.loc[diff.sort_values(ascending=False).head(20).index,
             ["time_utc","shock_type","delta_w","weight_factor","exchange_shocked",
              "share_shocked_before","share_shocked_after","share_after_true",
              "pivot_changed","pivot_exchange_before","pivot_exchange_after"]]
print("\nTop 20 largest diffs:")
print(top.to_string(index=False))

# 7) 看看“不符合公式”的行，是不是集中在某些 shock_type / delta_w
# （这是解释你之前 p95/max 抽象的最有效办法）
df["_absdiff_share"] = diff
grp = df.groupby(["shock_type","delta_w"], dropna=False)["_absdiff_share"].agg(
    n="size",
    median="median",
    p95=lambda x: x.quantile(0.95),
    max="max"
).reset_index().sort_values(["p95","max"], ascending=False)

print("\nDiff by shock_type x delta_w (sorted by p95/max):")
print(grp.head(30).to_string(index=False))

eps = 1e-12
print("max |shift_mean|  =", float(df["shift_mean"].abs().max()))
print("max |shift_median|=", float(df["shift_median"].abs().max()))

bad_mean = df[df["shift_mean"].abs() > eps]
bad_med  = df[df["shift_median"].abs() > eps]
print("rows with |shift_mean|>eps  :", len(bad_mean))
print("rows with |shift_median|>eps:", len(bad_med))

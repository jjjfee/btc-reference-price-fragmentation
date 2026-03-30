import pandas as pd

path = r"D:\cilck here\2代目\experiments_dvonly\pivot_boundary_curve_bins.csv"
df = pd.read_csv(path)
print("shape:", df.shape)
print("columns:", list(df.columns))
print(df.head(3).to_string(index=False))
print("\nunique shock_type:", df["shock_type"].unique() if "shock_type" in df.columns else "N/A")
print("unique gamma:", sorted(df["gamma"].unique()) if "gamma" in df.columns else "N/A")

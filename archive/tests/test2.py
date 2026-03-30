import pandas as pd
from pathlib import Path

csv_path = Path(r"D:\cilck here\2代目\experiments_dvonly\dvon_injection_shift_samples.csv")

print("csv_path =", csv_path)
print("exists?  =", csv_path.exists())      # True/False
print("is_file? =", csv_path.is_file())     # True/False

if not csv_path.exists():
    raise FileNotFoundError(f"File not found: {csv_path}")

df = pd.read_csv(csv_path)
print(df.shape)
print(df.columns.tolist()[:20])

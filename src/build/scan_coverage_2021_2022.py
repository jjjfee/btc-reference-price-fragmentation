# scan_coverage_2021_2022.py
# 目的：扫描每个 CSV 的时间覆盖范围，并统计 2021-2022 区间内的数据量与基本量级
# 你不需要懂 Python：运行后看 Excel 报告即可

from pathlib import Path
import pandas as pd
import numpy as np

INPUT_DIR = Path(r"D:\cilck here\btc交易所数据")
OUTPUT_DIR = Path(r"D:\cilck here\2代目")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 200_000

START = pd.Timestamp("2021-01-01", tz="UTC")
END   = pd.Timestamp("2022-12-31 23:59:00", tz="UTC")

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def pick_col(df: pd.DataFrame, candidates):
    col_map = {}
    for c in df.columns:
        key = str(c).lower().replace(" ", "").replace("_", "")
        col_map[key] = c
    for cand in candidates:
        key = cand.lower().replace(" ", "").replace("_", "")
        if key in col_map:
            return col_map[key]
    return None

def parse_time_column(s: pd.Series) -> pd.Series:
    # 尽量把时间列解析为 UTC datetime
    if np.issubdtype(s.dtype, np.datetime64):
        return s
    out = pd.to_datetime(s, errors="coerce", utc=True)
    if out.notna().mean() > 0.9:
        return out
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().mean() > 0.9:
        med = float(np.nanmedian(x))
        if med > 1e12:
            return pd.to_datetime(x, unit="ms", errors="coerce", utc=True)
        if med > 1e9:
            return pd.to_datetime(x, unit="s", errors="coerce", utc=True)
    return pd.to_datetime(s, errors="coerce", utc=True)

def compute_p_repr(df, col_open, col_high, col_low, col_close):
    o = pd.to_numeric(df[col_open], errors="coerce") if col_open else None
    h = pd.to_numeric(df[col_high], errors="coerce") if col_high else None
    l = pd.to_numeric(df[col_low], errors="coerce") if col_low else None
    c = pd.to_numeric(df[col_close], errors="coerce") if col_close else None
    if (o is not None) and (h is not None) and (l is not None) and (c is not None):
        return (o + h + l + c) / 4.0   # OHLC4
    if (h is not None) and (l is not None):
        return (h + l) / 2.0          # HL2
    if c is not None:
        return c
    raise ValueError("缺少价格列（open/high/low/close）。")

# 水库抽样（保留最多 k 个样本，用来估计中位数，避免内存爆）
def reservoir_update(reservoir, new_values, k, rng):
    new_values = new_values[~np.isnan(new_values)]
    for x in new_values:
        if len(reservoir) < k:
            reservoir.append(float(x))
        else:
            j = rng.integers(0, reservoir.n_seen + 1)
            if j < k:
                reservoir[j] = float(x)
        reservoir.n_seen += 1

class Reservoir(list):
    def __init__(self):
        super().__init__()
        self.n_seen = 0

def main():
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        print("[ERROR] 输入目录下找不到 CSV。")
        return

    rng = np.random.default_rng(42)
    report = []

    for fpath in files:
        ex = fpath.stem.split("_")[-1]
        print(f"\n[INFO] 扫描：{fpath.name}  (Exchange={ex})")

        min_time_all = None
        max_time_all = None
        inrange_rows = 0

        price_res = Reservoir()
        vol_res = Reservoir()
        int_count = 0
        int_total = 0

        # 先读一小块确定列名
        head = normalize_columns(pd.read_csv(fpath, nrows=5))
        time_col = pick_col(head, ["Open time", "opentime", "timestamp", "date", "time", "datetime"])
        col_open = pick_col(head, ["Open", "open"])
        col_high = pick_col(head, ["High", "high"])
        col_low  = pick_col(head, ["Low", "low"])
        col_close= pick_col(head, ["Close", "close"])
        vol_col  = pick_col(head, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

        if time_col is None or vol_col is None:
            print("[WARN] 找不到 time 或 volume 列，跳过。")
            report.append({
                "exchange": ex, "file": fpath.name,
                "time_col": time_col or "", "volume_col": vol_col or "",
                "min_time": "", "max_time": "",
                "rows_2021_2022": 0,
                "median_price_2021_2022_est": np.nan,
                "median_volume_2021_2022_est": np.nan,
                "volume_integer_ratio_2021_2022_est": np.nan,
                "note": "缺少 time/volume 列"
            })
            continue

        # 扫描全文件（分块）
        for chunk in pd.read_csv(fpath, chunksize=CHUNK_SIZE):
            chunk = normalize_columns(chunk)
            t = parse_time_column(chunk[time_col])

            # 更新全样本时间范围
            t_min = t.min()
            t_max = t.max()
            if pd.notna(t_min):
                min_time_all = t_min if min_time_all is None else min(min_time_all, t_min)
            if pd.notna(t_max):
                max_time_all = t_max if max_time_all is None else max(max_time_all, t_max)

            # 过滤到 2021-2022
            m = (t >= START) & (t <= END)
            if m.sum() == 0:
                continue

            sub = chunk.loc[m]
            inrange_rows += len(sub)

            # 代表价 & volume
            p = compute_p_repr(sub, col_open, col_high, col_low, col_close)
            v = pd.to_numeric(sub[vol_col], errors="coerce")

            # 更新抽样（用于估计中位数）
            reservoir_update(price_res, p.to_numpy(dtype=float), k=200_000, rng=rng)
            reservoir_update(vol_res,   v.to_numpy(dtype=float), k=200_000, rng=rng)

            # 估计“整数比例”（识别合约张数很有用）
            vv = v.to_numpy(dtype=float)
            vv = vv[np.isfinite(vv) & (vv > 0)]
            if len(vv) > 0:
                int_total += len(vv)
                int_count += int(np.sum(np.abs(vv - np.round(vv)) < 1e-6))

        median_p = float(np.median(price_res)) if len(price_res) > 0 else np.nan
        median_v = float(np.median(vol_res)) if len(vol_res) > 0 else np.nan
        int_ratio = (int_count / int_total) if int_total > 0 else np.nan

        note = ""
        if inrange_rows < 100_000:
            note = "2021-2022 行数偏少（<10万），可能缺数据或不是主交易对。"
        if pd.notna(median_p) and median_p < 1000:
            note += " 代表价中位数<1000，可能不是BTC价格口径/列映射异常/数据不对应BTCUSD。"

        report.append({
            "exchange": ex,
            "file": fpath.name,
            "time_col": time_col,
            "volume_col": vol_col,
            "min_time": str(min_time_all) if min_time_all is not None else "",
            "max_time": str(max_time_all) if max_time_all is not None else "",
            "rows_2021_2022": int(inrange_rows),
            "median_price_2021_2022_est": median_p,
            "median_volume_2021_2022_est": median_v,
            "volume_integer_ratio_2021_2022_est": int_ratio,
            "note": note.strip()
        })

        print(f"[INFO] 2021-2022 行数：{inrange_rows:,}")
        print(f"[INFO] 2021-2022 代表价中位数(估计)：{median_p}")
        print(f"[INFO] 2021-2022 Volume 中位数(估计)：{median_v}")
        print(f"[INFO] 2021-2022 Volume 整数比例(估计)：{int_ratio}")

    out = OUTPUT_DIR / "coverage_2021_2022_report.xlsx"
    pd.DataFrame(report).to_excel(out, index=False)
    print(f"\n✅ 已输出：{out}")

if __name__ == "__main__":
    main()

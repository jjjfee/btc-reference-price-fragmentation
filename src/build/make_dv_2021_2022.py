# make_dv_2021_2022.py
# 目标：
# 1) 只取 2021-2022
# 2) 自动把不同交易所的“价格尺度”拉到同一口径（用重叠分钟做稳健缩放）
# 3) 再判断 Volume 是 base(BTC数量) 还是 quote_or_contract(合约张数/计价量)
# 4) 输出带 p_usd / DV 的新 CSV + 总报告 Excel

from pathlib import Path
import pandas as pd
import numpy as np

# ========= 你一般不用改 =========
INPUT_DIR = Path(r"D:\cilck here\btc交易所数据")
OUTPUT_DIR = Path(r"D:\cilck here\2代目")
OUT_DV_DIR = OUTPUT_DIR / "dv_ready_2021_2022"
OUT_DV_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 200_000
SAMPLE_TARGET = 200_000  # 用于计算“缩放比例”的样本分钟数（够用且快）

START = pd.Timestamp("2021-01-01", tz="UTC")
END   = pd.Timestamp("2022-12-31 23:59:00", tz="UTC")

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def pick_col(df: pd.DataFrame, candidates):
    """在列名里找最可能的匹配（忽略空格/下划线/大小写）"""
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
    """把时间列转成 UTC datetime（兼容字符串/秒/毫秒时间戳）"""
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
    """代表价：优先 OHLC4，其次 HL2，最后 Close"""
    o = pd.to_numeric(df[col_open], errors="coerce") if col_open else None
    h = pd.to_numeric(df[col_high], errors="coerce") if col_high else None
    l = pd.to_numeric(df[col_low], errors="coerce") if col_low else None
    c = pd.to_numeric(df[col_close], errors="coerce") if col_close else None

    if (o is not None) and (h is not None) and (l is not None) and (c is not None):
        return (o + h + l + c) / 4.0
    if (h is not None) and (l is not None):
        return (h + l) / 2.0
    if c is not None:
        return c
    raise ValueError("缺少价格列（open/high/low/close）。")

def read_sample_2021_2022(csv_path: Path, sample_target: int):
    """
    从超大 CSV 里抽取 2021-2022 区间的样本（最多 sample_target 行）
    只返回 time, p_repr, volume 三列（用于缩放与单位判断）
    """
    head = normalize_columns(pd.read_csv(csv_path, nrows=5))
    time_col = pick_col(head, ["Open time", "opentime", "timestamp", "date", "time", "datetime"])
    col_open = pick_col(head, ["Open", "open"])
    col_high = pick_col(head, ["High", "high"])
    col_low  = pick_col(head, ["Low", "low"])
    col_close= pick_col(head, ["Close", "close"])
    vol_col  = pick_col(head, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

    if time_col is None or vol_col is None:
        raise ValueError(f"{csv_path.name} 找不到 time 或 volume 列，请手动检查列名。")

    parts = []
    got = 0

    for chunk in pd.read_csv(csv_path, chunksize=CHUNK_SIZE):
        chunk = normalize_columns(chunk)
        t = parse_time_column(chunk[time_col])
        m = (t >= START) & (t <= END)
        if m.sum() == 0:
            continue

        sub = chunk.loc[m].copy()
        sub["time_utc"] = t.loc[m].values

        p = compute_p_repr(sub, col_open, col_high, col_low, col_close)
        v = pd.to_numeric(sub[vol_col], errors="coerce")

        out = pd.DataFrame({
            "time_utc": sub["time_utc"],
            "p": pd.to_numeric(p, errors="coerce"),
            "v": v
        }).dropna()

        parts.append(out)
        got += len(out)

        if got >= sample_target:
            break

    if not parts:
        raise ValueError(f"{csv_path.name} 在 2021-2022 没抽到任何样本，请检查时间列解析是否正确。")

    df = pd.concat(parts, ignore_index=True)
    # 去重（同一分钟多行时只保留最后一条）
    df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last")
    return df

def robust_scale_to_anchor(df_anchor, df_other):
    """
    用重叠分钟做稳健缩放：scale = exp(median(log(p_anchor) - log(p_other)))
    这样 df_other.p * scale ≈ df_anchor.p
    """
    merged = df_anchor.merge(df_other, on="time_utc", suffixes=("_a", "_o"))
    merged = merged[(merged["p_a"] > 0) & (merged["p_o"] > 0)]
    if len(merged) < 10_000:
        return np.nan, len(merged)

    logdiff = np.log(merged["p_a"].values) - np.log(merged["p_o"].values)
    scale = float(np.exp(np.median(logdiff)))
    return scale, len(merged)

def decide_anchor_usd_multiplier(anchor_median):
    """
    选择一个 10 的幂倍数，把 anchor 的价格中位数拉到合理 BTC 美元价格区间（1万~10万）。
    这是为了把最终单位落在“美元量级”，否则你会得到“千美元/万美元/ticks”等奇怪口径。
    """
    if not np.isfinite(anchor_median) or anchor_median <= 0:
        return 1.0

    candidates = [10**k for k in range(-6, 7)]  # 1e-6 ... 1e6
    best = 1.0
    for m in candidates:
        x = anchor_median * m
        if 10_000 <= x <= 100_000:
            best = m
            break
    return float(best)

def infer_volume_unit_from_sample(v_series: pd.Series):
    """
    极简但很稳的判断：
    - volume 几乎全是整数（>95%） => quote_or_contract（合约张数/计价量）
    - 否则 => base（BTC数量）
    """
    v = pd.to_numeric(v_series, errors="coerce")
    v = v[np.isfinite(v) & (v > 0)]
    if len(v) < 10_000:
        return "unknown", np.nan

    frac = np.abs(v - np.round(v))
    int_ratio = float((frac < 1e-6).mean())

    if int_ratio > 0.95:
        return "quote_or_contract", int_ratio
    return "base", int_ratio

def process_one_exchange(csv_path: Path, exchange: str, scale_to_anchor: float, anchor_usd_mult: float, unit: str):
    """
    第二遍：全量读取（chunk），过滤 2021-2022，并输出带 p_usd / DV 的新 CSV
    """
    out_csv = OUT_DV_DIR / f"{csv_path.stem}_2021_2022_with_DV.csv"
    if out_csv.exists():
        out_csv.unlink()

    head = normalize_columns(pd.read_csv(csv_path, nrows=5))
    time_col = pick_col(head, ["Open time", "opentime", "timestamp", "date", "time", "datetime"])
    col_open = pick_col(head, ["Open", "open"])
    col_high = pick_col(head, ["High", "high"])
    col_low  = pick_col(head, ["Low", "low"])
    col_close= pick_col(head, ["Close", "close"])
    vol_col  = pick_col(head, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

    first = True
    for chunk in pd.read_csv(csv_path, chunksize=CHUNK_SIZE):
        chunk = normalize_columns(chunk)
        t = parse_time_column(chunk[time_col])
        m = (t >= START) & (t <= END)
        if m.sum() == 0:
            continue

        sub = chunk.loc[m].copy()
        sub["time_utc"] = t.loc[m].values

        p_raw = compute_p_repr(sub, col_open, col_high, col_low, col_close)
        p_raw = pd.to_numeric(p_raw, errors="coerce")

        # 价格先缩放到 anchor 口径，再乘以 anchor_usd_mult 变成美元量级
        p_usd = p_raw * scale_to_anchor * anchor_usd_mult

        v = pd.to_numeric(sub[vol_col], errors="coerce")

        # DV 统一：
        # - base：DV = Volume(BTC) * Price(USD)
        # - quote_or_contract：DV = Volume（默认当“美元计价量/张数”直接用）
        #   如果你确认某交易所“每张合约不是 1 美元”，可在这里乘一个常数 multiplier。
        if unit == "base":
            dv = v * p_usd
        elif unit == "quote_or_contract":
            CONTRACT_MULTIPLIER = 1.0
            dv = v * CONTRACT_MULTIPLIER
        else:
            # unknown：先按 base 处理（但报告里会标 unknown）
            dv = v * p_usd

        sub["p_usd_scaled"] = p_usd
        sub["DV_usd"] = dv
        sub["volume_unit_final"] = unit

        sub.to_csv(out_csv, mode="w" if first else "a", index=False, header=first, encoding="utf-8-sig")
        first = False

    return str(out_csv)

def main():
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        print("[ERROR] 找不到 CSV。")
        return

    # 找 anchor（优先 Binance）
    anchor_file = None
    for f in files:
        if "Binance" in f.name:
            anchor_file = f
            break
    if anchor_file is None:
        anchor_file = files[0]

    print(f"[INFO] Anchor 交易所文件：{anchor_file.name}")

    # 读 anchor 样本
    df_anchor = read_sample_2021_2022(anchor_file, SAMPLE_TARGET)
    anchor_med = float(np.median(df_anchor["p"].values[df_anchor["p"].values > 0]))
    anchor_usd_mult = decide_anchor_usd_multiplier(anchor_med)

    print(f"[INFO] Anchor p_raw 中位数≈{anchor_med:.6f}，选择 USD 倍数 multiplier={anchor_usd_mult:g}（使其落入1万~10万区间）")

    report_rows = []

    # 逐个交易所：先算缩放比例，再推断 volume 单位，再输出全量 DV
    for f in files:
        ex = f.stem.split("_")[-1]
        print(f"\n[INFO] 处理：{f.name} (Exchange={ex})")

        df_other = read_sample_2021_2022(f, SAMPLE_TARGET)

        # 缩放到 anchor 口径（anchor 自己 scale=1）
        if f == anchor_file:
            scale = 1.0
            overlap = len(df_anchor.merge(df_other, on="time_utc"))
        else:
            scale, overlap = robust_scale_to_anchor(df_anchor, df_other)

        if not np.isfinite(scale) or scale <= 0:
            print("[WARN] 与 anchor 的重叠分钟太少或缩放失败，scale 用 1.0（建议你检查时间列是否对齐）。")
            scale = 1.0

        # 判断 volume 单位
        unit, int_ratio = infer_volume_unit_from_sample(df_other["v"])

        # 估计缩放后价格中位数（美元量级）
        p_scaled_med = float(np.median((df_other["p"] * scale * anchor_usd_mult).values[df_other["p"].values > 0]))

        # 输出 DV 文件
        out_csv = process_one_exchange(f, ex, scale, anchor_usd_mult, unit)

        report_rows.append({
            "exchange": ex,
            "file": f.name,
            "overlap_minutes_with_anchor": int(overlap),
            "price_scale_to_anchor": float(scale),
            "anchor_usd_multiplier": float(anchor_usd_mult),
            "median_price_after_scale_usd_est": p_scaled_med,
            "volume_integer_ratio_est": float(int_ratio) if np.isfinite(int_ratio) else np.nan,
            "volume_unit_final": unit,
            "output_csv": out_csv
        })

        print(f"[INFO] scale_to_anchor={scale:.6g}，缩放后价格中位数≈{p_scaled_med:,.2f} USD，volume_unit={unit}")

    out_report = OUTPUT_DIR / "dv_unit_and_price_scale_report.xlsx"
    pd.DataFrame(report_rows).to_excel(out_report, index=False)
    print(f"\n✅ 总报告已输出：{out_report}")
    print(f"✅ DV 文件已输出到：{OUT_DV_DIR}")

if __name__ == "__main__":
    main()

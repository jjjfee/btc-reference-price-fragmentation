# build_aggregated_prices.py
# ============================================================
# 你要做什么？
#   把 7 家交易所的 2021-2022 分钟数据合并成“每分钟一行”的聚合价格序列：
#     1) Mean   : 简单均值
#     2) Median : 不加权中位数
#     3) VWAP   : 以 DV_usd 为权重的加权均值（你论文里定义的基准）
#     4) LWMP   : 以 DV_usd 为权重的加权中位数（你的核心方法）
#
# 你需要准备什么？
#   你之前已经生成了带两列的文件：
#     - time_utc        : UTC 时间（分钟）
#     - p_usd_scaled    : 已对齐尺度的美元价格（非常关键）
#     - DV_usd          : 统一口径的美元交易额权重（或合约名义量权重）
#   这些文件应该在：
#     D:\cilck here\2代目\dv_ready_2021_2022\
#
# 运行完会输出什么？
#   输出目录：
#     D:\cilck here\2代目\agg_ready\
#   输出文件：
#     1) btc_2021_2022_agg_prices.csv
#     2) agg_data_quality_report.xlsx
# ============================================================

from pathlib import Path
import pandas as pd
import numpy as np

# ========= 路径（一般不用改） =========
BASE_DIR = Path(r"D:\cilck here\2代目")
INPUT_DIR = BASE_DIR / "dv_ready_2021_2022"
OUT_DIR = BASE_DIR / "agg_ready"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ========= 你要聚合的核心列名（脚本会自动检查） =========
TIME_COL_CANDIDATES = ["time_utc", "Time_utc", "timestamp", "time"]
PRICE_COL_CANDIDATES = ["p_usd_scaled", "p_usd", "price_usd", "p_scaled"]
WEIGHT_COL_CANDIDATES = ["DV_usd", "DV", "dollar_volume", "dv_usd"]

def pick_existing_column(cols, candidates):
    """在一堆候选列名里，找到当前文件真实存在的那个列"""
    lower_map = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None

def infer_exchange_name(file_path: Path) -> str:
    """
    从文件名里猜交易所名字。
    例如：BTCUSD_1m_Binance_2021_2022_with_DV.csv -> Binance
    """
    name = file_path.stem
    parts = name.split("_")
    # 通常最后会有 with / DV / 2021 / 2022 之类，交易所一般在 BTCUSD_1m_ 后面那段
    # 这里采用：找出最像交易所的部分（优先匹配常见名单）
    known = ["Binance", "Bitfinex", "BitMEX", "Bitstamp", "Coinbase", "KuCoin", "OKX"]
    for k in known:
        if k.lower() in name.lower():
            return k
    # 如果没匹配到，就用倒数第 4/3 个片段兜底
    return parts[2] if len(parts) >= 3 else name

def load_one_exchange(file_path: Path):
    """
    读取某一家交易所的 DV 文件，只保留 time / price / weight 三列，并设置 time 为索引。
    """
    # 先读一小段拿到列名，避免 usecols 因列名不一致报错
    head = pd.read_csv(file_path, nrows=5)
    cols = list(head.columns)

    time_col = pick_existing_column(cols, TIME_COL_CANDIDATES)
    price_col = pick_existing_column(cols, PRICE_COL_CANDIDATES)
    w_col = pick_existing_column(cols, WEIGHT_COL_CANDIDATES)

    if time_col is None or price_col is None or w_col is None:
        raise ValueError(
            f"{file_path.name} 缺少必要列。\n"
            f"找到 time={time_col}, price={price_col}, weight={w_col}\n"
            f"请打开 CSV 检查列名。"
        )

    # 只读必要列，节省内存
    df = pd.read_csv(file_path, usecols=[time_col, price_col, w_col])

    # 解析时间为 UTC datetime（你之前脚本输出的一般已经是 UTC 字符串）
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)

    # 转数值
    df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
    df[w_col] = pd.to_numeric(df[w_col], errors="coerce")

    # 丢掉没时间的行
    df = df.dropna(subset=[time_col])

    # 同一分钟如果有重复行，保留最后一条（保险起见）
    df = df.sort_values(time_col).drop_duplicates(time_col, keep="last")

    df = df.set_index(time_col)
    df = df.rename(columns={price_col: "price", w_col: "weight"})
    return df

def weighted_median_per_row(prices_2d: np.ndarray, weights_2d: np.ndarray) -> np.ndarray:
    """
    计算每一行（每分钟）的加权中位数 LWMP。
    prices_2d: 形状 (N, K)，K=交易所数量
    weights_2d: 同形状
    规则：按价格排序，累计权重首次达到 50% 的价格就是加权中位数
    """
    N, K = prices_2d.shape

    # 无效权重：<=0 或 price 非有限值 都直接剔除（权重设为0）
    valid = np.isfinite(prices_2d) & np.isfinite(weights_2d) & (weights_2d > 0)
    w = np.where(valid, weights_2d, 0.0)

    # 对于 w=0 的位置，我们把价格设为 +inf，这样排序时会被放到最后，不影响累计权重
    p_sort_key = np.where(w > 0, prices_2d, np.inf)

    order = np.argsort(p_sort_key, axis=1)  # 每一行独立排序
    p_sorted = np.take_along_axis(prices_2d, order, axis=1)
    w_sorted = np.take_along_axis(w, order, axis=1)

    cumw = np.cumsum(w_sorted, axis=1)
    totalw = np.sum(w_sorted, axis=1)
    half = 0.5 * totalw

    # 找到第一个 cumw >= half 的位置
    # 注意：如果 totalw=0，则 half=0，此时要输出 NaN（表示这一分钟没有有效交易所）
    hit = (cumw >= half[:, None])
    idx = hit.argmax(axis=1)  # 每行第一个 True 的索引（如果全 False 会返回0，但我们后面会处理 totalw=0）
    out = p_sorted[np.arange(N), idx]

    out = np.where(totalw > 0, out, np.nan)
    return out

def main():
    print(f"[INFO] 输入目录：{INPUT_DIR}")
    print(f"[INFO] 输出目录：{OUT_DIR}")

    if not INPUT_DIR.exists():
        print("[ERROR] 找不到输入目录 dv_ready_2021_2022。请确认你已运行 make_dv_2021_2022.py。")
        return

    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        print("[ERROR] 输入目录里没有任何 CSV。")
        return

    # 读取每家交易所
    exchange_dfs = {}
    quality_rows = []

    for fp in files:
        ex = infer_exchange_name(fp)
        print(f"\n[INFO] 读取：{fp.name}  -> 交易所识别为：{ex}")
        df = load_one_exchange(fp)

        # 基本质量统计（方便写论文）
        n_rows = len(df)
        price_median = float(np.nanmedian(df["price"].values)) if n_rows > 0 else np.nan
        w_median = float(np.nanmedian(df["weight"].values)) if n_rows > 0 else np.nan

        quality_rows.append({
            "exchange": ex,
            "file": fp.name,
            "rows_loaded": n_rows,
            "median_price_usd": price_median,
            "median_weight_DV": w_median,
            "missing_price_ratio": float(df["price"].isna().mean()),
            "missing_weight_ratio": float(df["weight"].isna().mean())
        })

        exchange_dfs[ex] = df

    # 合并成一个“宽表”：index=分钟，列=各交易所 price/weight
    # prices_wide: 每列一个交易所价格
    # weights_wide: 每列一个交易所权重
    prices_wide = pd.DataFrame()
    weights_wide = pd.DataFrame()

    for ex, df in exchange_dfs.items():
        prices_wide[ex] = df["price"]
        weights_wide[ex] = df["weight"]

    # 对齐 index（外连接），这样某分钟缺失的交易所会是 NaN
    # （pandas 会自动对齐 index）
   # ====== 兼容所有 pandas 版本的 index 合并方式 ======
    all_index = None
    for df in exchange_dfs.values():
        if all_index is None:
            all_index = df.index
        else:
            all_index = all_index.union(df.index)

    prices_wide = prices_wide.reindex(all_index).sort_index()
    weights_wide = weights_wide.reindex(all_index).sort_index()


    # 将无效权重置 0，避免影响 VWAP/LWMP
    # 同时：如果某交易所该分钟 price 缺失，则权重也置 0
    p = prices_wide.to_numpy(dtype=float)
    w = weights_wide.to_numpy(dtype=float)

    valid = np.isfinite(p) & np.isfinite(w) & (w > 0)
    w_clean = np.where(valid, w, 0.0)
    p_clean = np.where(valid, p, np.nan)

    # 覆盖交易所数 & 总DV
    n_ex = np.sum(w_clean > 0, axis=1).astype(int)
    total_dv = np.sum(w_clean, axis=1)

    # 1) Mean / Median（不加权）
    mean_price = np.nanmean(p_clean, axis=1)
    median_price = np.nanmedian(p_clean, axis=1)

    # 2) VWAP（DV 权重均值）
    denom = np.sum(w_clean, axis=1)
    vwap_price = np.where(denom > 0, np.nansum(p_clean * w_clean, axis=1) / denom, np.nan)

    # 3) LWMP（DV 加权中位数）
    lwmp_price = weighted_median_per_row(p_clean, w_clean)

    # 输出聚合结果
    out = pd.DataFrame({
        "time_utc": prices_wide.index,
        "n_exchanges_used": n_ex,
        "total_DV_usd": total_dv,
        "P_mean": mean_price,
        "P_median": median_price,
        "P_vwap_DV": vwap_price,
        "P_lwmp_DV": lwmp_price
    })

    out_path = OUT_DIR / "btc_2021_2022_agg_prices.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ 已输出聚合价格文件：{out_path}")

    # 输出数据质量报告（Excel）
    quality_df = pd.DataFrame(quality_rows)
    # 额外加一行：整体覆盖（每分钟至少多少家交易所）
    cover_stats = {
        "exchange": "__OVERALL__",
        "file": "",
        "rows_loaded": len(out),
        "median_price_usd": np.nan,
        "median_weight_DV": np.nan,
        "missing_price_ratio": np.nan,
        "missing_weight_ratio": np.nan
    }
    quality_df = pd.concat([quality_df, pd.DataFrame([cover_stats])], ignore_index=True)

    # 覆盖统计（整体）
    cover_summary = pd.DataFrame({
        "metric": [
            "minutes_total",
            "minutes_with_>=3_exchanges",
            "minutes_with_>=5_exchanges",
            "minutes_with_7_exchanges",
            "share_with_>=3_exchanges",
            "share_with_>=5_exchanges",
            "share_with_7_exchanges"
        ],
        "value": [
            int(len(out)),
            int(np.sum(n_ex >= 3)),
            int(np.sum(n_ex >= 5)),
            int(np.sum(n_ex == p_clean.shape[1])),
            float(np.mean(n_ex >= 3)),
            float(np.mean(n_ex >= 5)),
            float(np.mean(n_ex == p_clean.shape[1]))
        ]
    })

    xlsx_path = OUT_DIR / "agg_data_quality_report.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        quality_df.to_excel(writer, index=False, sheet_name="per_exchange_basic")
        cover_summary.to_excel(writer, index=False, sheet_name="overall_coverage")

    print(f"✅ 已输出数据质量报告：{xlsx_path}")

    # 给你一个“终端可读”的简短总结（你一眼就知道是否正常）
    print("\n[SUMMARY] 聚合完成后的覆盖情况：")
    print(f"  总分钟数：{len(out):,}")
    print(f"  >=3 家交易所可用：{np.sum(n_ex >= 3):,}（占比 {np.mean(n_ex >= 3):.2%}）")
    print(f"  >=5 家交易所可用：{np.sum(n_ex >= 5):,}（占比 {np.mean(n_ex >= 5):.2%}）")
    print(f"  7 家全齐：{np.sum(n_ex == p_clean.shape[1]):,}（占比 {np.mean(n_ex == p_clean.shape[1]):.2%}）")

if __name__ == "__main__":
    main()

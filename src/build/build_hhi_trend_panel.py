# build_hhi_trend_panel.py
# ============================================================
# 目的：
#  1) 把“聚合价格序列”与“分钟级集中度指标(HHI/max_share)”合并成 panel 数据
#  2) 检验你观察到的经验规律：下跌→HHI上升；上涨→HHI下降（方向性统计）
#  3) 输出给后续研究直接复用的干净数据与摘要表
# ============================================================

from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(r"D:\cilck here\2代目")
AGG_PATH = BASE / "agg_ready" / "btc_2021_2022_agg_prices.csv"
HHI_PATH = BASE / "experiments" / "weight_concentration_minute_level.csv"

OUT_DIR = BASE / "hhi_panel"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_PANEL = OUT_DIR / "btc_1m_panel_with_hhi.csv"
OUT_XLSX  = OUT_DIR / "hhi_trend_summary.xlsx"

# 你可以按需要改这些检验窗口（分钟）
HORIZONS = [5, 60, 1440]   # 5分钟、1小时、1天
ROLL_HHI = 60             # HHI 滚动均值窗口（60分钟）

def to_utc_dt(s):
    return pd.to_datetime(s, errors="coerce", utc=True)

def safe_log_return(p):
    p = pd.to_numeric(p, errors="coerce")
    return np.log(p).diff()

def forward_log_return(logp, h):
    # r_{t -> t+h} = logP_{t+h} - logP_t
    return logp.shift(-h) - logp

def main():
    if not AGG_PATH.exists():
        raise FileNotFoundError(f"找不到聚合价文件：{AGG_PATH}")
    if not HHI_PATH.exists():
        raise FileNotFoundError(f"找不到 HHI 文件：{HHI_PATH}")

    print(f"[INFO] 读取聚合价：{AGG_PATH}")
    agg = pd.read_csv(AGG_PATH)

    # 尽量兼容列名：time_utc + lwmp/vwap/mean/median
    # 你的 agg 文件一般会有 time_utc 和 lwmp/vwap 等列
    if "time_utc" not in agg.columns:
        raise ValueError("聚合价文件缺少 time_utc 列。")

    agg["time_utc_dt"] = to_utc_dt(agg["time_utc"])
    agg = agg.dropna(subset=["time_utc_dt"]).sort_values("time_utc_dt").drop_duplicates("time_utc_dt", keep="last")

    # 选一个主价格：优先 LWMP，没有就用 VWAP
    price_cols_priority = ["lwmp_price", "lwmp", "LWMP", "price_lwmp",
                           "vwap_price", "vwap", "VWAP", "price_vwap"]
    price_col = None
    for c in price_cols_priority:
        if c in agg.columns:
            price_col = c
            break
    if price_col is None:
        # 兜底：找包含 lwmp 或 vwap 的列
        for c in agg.columns:
            cl = c.lower()
            if "lwmp" in cl or "vwap" in cl:
                price_col = c
                break
    if price_col is None:
        raise ValueError("聚合价文件里找不到 LWMP/VWAP 相关列名，请打开 CSV 看一下列名。")

    agg["P"] = pd.to_numeric(agg[price_col], errors="coerce")

    print(f"[INFO] 使用主价格列：{price_col}")

    print(f"[INFO] 读取集中度：{HHI_PATH}")
    hhi = pd.read_csv(HHI_PATH)
    if "time_utc" not in hhi.columns:
        raise ValueError("HHI 文件缺少 time_utc 列。")
    if "HHI" not in hhi.columns:
        raise ValueError("HHI 文件缺少 HHI 列。")
    if "max_share" not in hhi.columns:
        raise ValueError("HHI 文件缺少 max_share 列。")

    hhi["time_utc_dt"] = to_utc_dt(hhi["time_utc"])
    hhi = hhi.dropna(subset=["time_utc_dt"]).sort_values("time_utc_dt").drop_duplicates("time_utc_dt", keep="last")

    # 合并
    df = agg.merge(hhi[["time_utc_dt", "HHI", "max_share", "dominant_exchange"]], on="time_utc_dt", how="inner")
    df = df.sort_values("time_utc_dt")

    # 计算收益与 HHI 变化
    df["logP"] = np.log(df["P"])
    df["r_1m"] = df["logP"].diff()
    df["dHHI_1m"] = pd.to_numeric(df["HHI"], errors="coerce").diff()

    # 滚动平滑版本（只是信号可读性增强，不改变原始结构）
    df["HHI_roll"] = pd.to_numeric(df["HHI"], errors="coerce").rolling(ROLL_HHI, min_periods=ROLL_HHI).mean()
    df["dHHI_roll_1m"] = df["HHI_roll"].diff()

    # 未来收益（不同 horizon）
    for h in HORIZONS:
        df[f"r_fwd_{h}m"] = forward_log_return(df["logP"], h)
        df[f"dHHI_fwd_{h}m"] = df["HHI"].shift(-h) - df["HHI"]

    # 保存 panel
    df_out = df[[
        "time_utc_dt", "P", "HHI", "max_share", "dominant_exchange",
        "r_1m", "dHHI_1m", "HHI_roll", "dHHI_roll_1m"
    ] + [f"r_fwd_{h}m" for h in HORIZONS] + [f"dHHI_fwd_{h}m" for h in HORIZONS]]

    df_out.to_csv(OUT_PANEL, index=False, encoding="utf-8-sig")
    print(f"✅ 输出 panel：{OUT_PANEL}")

    # ========= 生成摘要表（让你一眼看方向对不对） =========
    summaries = {}

    # (A) 简单相关：dHHI 与未来收益（你关心“负相关”）
    corr_rows = []
    for h in HORIZONS:
        x = pd.to_numeric(df_out[f"dHHI_fwd_{h}m"], errors="coerce")
        y = pd.to_numeric(df_out[f"r_fwd_{h}m"], errors="coerce")
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 100:
            corr = np.nan
        else:
            corr = float(np.corrcoef(x[m], y[m])[0,1])
        corr_rows.append({"horizon_minutes": h, "corr(dHHI_fwd, r_fwd)": corr, "n": int(m.sum())})
    summaries["corr_future"] = pd.DataFrame(corr_rows)

    # (B) 条件均值：上涨 vs 下跌分钟时，dHHI 的均值（你经验规律的最直观检验）
    cond = df_out[["r_1m", "dHHI_1m"]].dropna()
    up = cond[cond["r_1m"] > 0]["dHHI_1m"]
    dn = cond[cond["r_1m"] < 0]["dHHI_1m"]
    summaries["cond_mean_1m"] = pd.DataFrame([
        {"group": "up (r_1m>0)", "mean_dHHI_1m": float(up.mean()), "median_dHHI_1m": float(up.median()), "n": int(up.shape[0])},
        {"group": "down (r_1m<0)", "mean_dHHI_1m": float(dn.mean()), "median_dHHI_1m": float(dn.median()), "n": int(dn.shape[0])},
    ])

    # (C) 分位分组：按 HHI 分为 5 组，看未来收益均值是否单调
    q = df_out["HHI"].dropna()
    if len(q) > 0:
        bins = pd.qcut(q, 5, labels=["Q1(low)","Q2","Q3","Q4","Q5(high)"])
        tmp = df_out.loc[q.index, ["HHI"]].copy()
        tmp["HHI_quintile"] = bins.values
        df2 = df_out.join(tmp["HHI_quintile"])
        table_rows = []
        for h in HORIZONS:
            g = df2.groupby("HHI_quintile")[f"r_fwd_{h}m"]
            t = g.mean().rename("mean_r_fwd").to_frame()
            t["horizon_minutes"] = h
            t["n"] = g.count().astype(int)
            table_rows.append(t.reset_index())
        summaries["hhi_quintile_future_return"] = pd.concat(table_rows, ignore_index=True)
    else:
        summaries["hhi_quintile_future_return"] = pd.DataFrame()

    # 写 Excel
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
        for name, sdf in summaries.items():
            sdf.to_excel(w, index=False, sheet_name=name[:31])
    print(f"✅ 输出摘要表：{OUT_XLSX}")

    print("\n[DONE] 打开 hhi_trend_summary.xlsx：")
    print("  - corr_future 看 dHHI 与未来收益的相关方向（你预期是负）")
    print("  - cond_mean_1m 看上涨/下跌分钟的 dHHI 平均值是否一正一负")
    print("  - hhi_quintile_future_return 看 HHI 高低分位对应的未来收益是否有单调结构")

if __name__ == "__main__":
    main()

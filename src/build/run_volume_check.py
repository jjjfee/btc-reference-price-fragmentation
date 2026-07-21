# run_volume_check.py
# 作用：
# 1) 自动读取 7 家交易所 BTCUSD 1m 的 CSV
# 2) 判断每家交易所 Volume 更像 base volume（BTC 数量）还是 quote volume（USD 金额/合约张数）
# 3) 统一生成 DV（Dollar Volume，美元交易额权重）并输出新 CSV
# 4) 输出 Excel 报告 + 每家交易所的诊断图（非常直观）

import os
import math
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# =========================
# 你只需要改这两行（一般不用改）
# =========================
INPUT_DIR = (Path(__file__).resolve().parents[2] / "data" / "external" / "raw" / "btc")
OUTPUT_DIR = Path(__file__).resolve().parents[2]

# 每次处理多少行（防止一次性占用太多内存）
CHUNK_SIZE = 200_000

# 诊断时抽样多少行（越大越准，但越慢；建议 200k 足够）
DIAG_SAMPLE_ROWS = 200_000

# =========================
# 工具函数：打印更友好
# =========================
def nice_print(msg: str):
    print(f"[INFO] {msg}")

def warn_print(msg: str):
    print(f"[WARN] {msg}")

def err_print(msg: str):
    print(f"[ERROR] {msg}")

# =========================
# 自动识别列名（尽可能兼容不同 CSV 格式）
# =========================
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # 再做一份小写列名映射，方便匹配
    return df

def pick_col(df: pd.DataFrame, candidates):
    """
    在 df 的列里按候选名寻找最匹配的列（忽略大小写/空格/下划线）
    """
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
    """
    尝试把时间列转成 pandas datetime。
    支持：
    - ISO 字符串
    - 秒级/毫秒级时间戳
    """
    # 如果已经是 datetime
    if np.issubdtype(s.dtype, np.datetime64):
        return s

    # 先尝试直接 to_datetime（适用于字符串）
    try:
        out = pd.to_datetime(s, errors="coerce", utc=True)
        # 如果大部分都能转成功，就用它
        if out.notna().mean() > 0.9:
            return out
    except Exception:
        pass

    # 尝试数字时间戳
    try:
        x = pd.to_numeric(s, errors="coerce")
        if x.notna().mean() < 0.9:
            return pd.to_datetime(s, errors="coerce", utc=True)

        # 判断是秒还是毫秒
        med = float(np.nanmedian(x))
        # 毫秒级通常是 13 位（~1e12）
        if med > 1e12:
            return pd.to_datetime(x, unit="ms", errors="coerce", utc=True)
        # 秒级通常是 10 位（~1e9）
        if med > 1e9:
            return pd.to_datetime(x, unit="s", errors="coerce", utc=True)

        # 其它情况：直接尝试
        return pd.to_datetime(x, errors="coerce", utc=True)
    except Exception:
        return pd.to_datetime(s, errors="coerce", utc=True)

# =========================
# 代表价 p：优先 OHLC4，其次 HL2，再其次 Close
# =========================
def compute_representative_price(df: pd.DataFrame, col_open, col_high, col_low, col_close) -> pd.Series:
    # 转成数值（防止字符串）
    o = pd.to_numeric(df[col_open], errors="coerce") if col_open else None
    h = pd.to_numeric(df[col_high], errors="coerce") if col_high else None
    l = pd.to_numeric(df[col_low], errors="coerce") if col_low else None
    c = pd.to_numeric(df[col_close], errors="coerce") if col_close else None

    if (o is not None) and (h is not None) and (l is not None) and (c is not None):
        return (o + h + l + c) / 4.0  # OHLC4（主推荐）
    if (h is not None) and (l is not None):
        return (h + l) / 2.0         # HL2（备选）
    if c is not None:
        return c                      # Close（最后兜底）
    raise ValueError("找不到可用的价格列（open/high/low/close 都缺失）。")

def compute_range(df: pd.DataFrame, col_high, col_low, p: pd.Series) -> pd.Series:
    if col_high and col_low:
        h = pd.to_numeric(df[col_high], errors="coerce")
        l = pd.to_numeric(df[col_low], errors="coerce")
        rng = (h - l) / p.replace(0, np.nan)
        return rng
    return pd.Series(np.nan, index=df.index)

# =========================
# Volume 单位推断（关键）
# =========================
def infer_volume_unit(exchange_name: str, df_sample: pd.DataFrame, vol_col: str, p: pd.Series):
    """
    改进版：
    1) 先用“是否几乎全是整数”识别合约张数/笔数类 volume
    2) 再用数量级判断 base(BTC) vs quote(USD)
    3) 允许“薄市场”的 base 判定（否则会全是 unknown）
    """
    v = pd.to_numeric(df_sample[vol_col], errors="coerce")
    p_ = pd.to_numeric(p, errors="coerce")

    mask = v.notna() & p_.notna() & (p_ > 0) & (v > 0)
    v = v[mask]
    p_ = p_[mask]

    if len(v) < 2_000:
        return ("unknown", "low", "有效样本过少（<2000），无法可靠判断。")

    v_med = float(np.nanmedian(v))
    v_p95 = float(np.nanpercentile(v, 95))
    price_med = float(np.nanmedian(p_))

    # —— 关键特征：整数比例（合约张数/笔数通常接近全整数）
    frac = np.abs(v - np.round(v))
    int_ratio = float((frac < 1e-6).mean())

    implied_base_med_if_quote = v_med / price_med
    implied_dv_med_if_base = v_med * price_med

    # 列名 hint
    vol_name = vol_col.lower()
    col_hint_quote = any(k in vol_name for k in ["usd", "quote", "usdt", "value", "turnover", "amount"])
    col_hint_base = any(k in vol_name for k in ["btc", "base", "coin", "qty"])

    # 规则 1：强识别“合约/张数/笔数”
    # - int_ratio 很高 + volume 中位数较大 => 更像 contract/quote
    if int_ratio > 0.95 and v_med >= 50:
        rationale = (
            f"Volume 接近整数的比例≈{int_ratio:.2%}，且Volume中位数≈{v_med:,.2f}（偏大），"
            f"更像合约张数/笔数/美元计价量，而非 BTC 数量。"
            f"（若按USD假设，隐含BTC≈{implied_base_med_if_quote:,.4f}）"
        )
        rationale += "（提示：衍生品交易所常见此口径。）"
        return ("quote_or_contract", "high", rationale)

    # 规则 2：识别 base（BTC 数量）——允许薄市场
    # BTC 数量分钟中位数常见在 < 50（薄市场可能 < 5）
    if v_med < 50 and int_ratio < 0.95:
        rationale = (
            f"Volume中位数≈{v_med:,.4f}（偏小且非纯整数），更像 BTC 数量。"
            f"隐含美元DV（若按base）≈{implied_dv_med_if_base:,.2e}。"
        )
        # 如果隐含美元DV很小，说明市场薄，但不等于单位错
        if implied_dv_med_if_base < 5e4:
            rationale += "（该交易对可能较薄，DV 偏小属于市场特征，不代表数据错误。）"
            return ("base", "medium", rationale)
        return ("base", "high", rationale)

    # 规则 3：识别 quote（USD 成交额）—— volume 很大但不是纯整数也可能是 USD
    if v_med >= 50_000 and 0.01 <= implied_base_med_if_quote <= 50_000:
        rationale = (
            f"Volume中位数≈{v_med:,.2f}（很大），且volume/price（隐含BTC）≈{implied_base_med_if_quote:,.2f}，"
            f"更像美元成交额或USD口径成交量。"
        )
        return ("quote_or_contract", "high", rationale)

    # hint 兜底
    if col_hint_quote:
        return ("quote_or_contract", "medium", "列名提示更像 quote/USD 口径，但数量级不够典型，建议人工核对。")
    if col_hint_base:
        return ("base", "medium", "列名提示更像 base/BTC 口径，但数量级不够典型，建议人工核对。")

    rationale = (
        f"判断不够明确：Volume中位数≈{v_med:,.4f}，整数比例≈{int_ratio:.2%}，"
        f"隐含BTC(若USD)≈{implied_base_med_if_quote:,.4f}，隐含DV(若BTC)≈{implied_dv_med_if_base:,.2e}。"
        "建议人工核对数据源的 Volume 定义。"
    )
    # 对 BitMEX/OKX 给额外提醒
    if exchange_name.lower() in ["bitmex", "okx"]:
        rationale += "（注意：该平台很可能为衍生品，Volume 常为张数/美元口径。）"
    return ("unknown", "low", rationale)
# =========================
# 画诊断图：让人一眼看出 volume 是“BTC级”还是“美元级”
# =========================
def save_diagnostic_plots(exchange_name: str, df_sample: pd.DataFrame, time_col: str, vol_col: str, p: pd.Series, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    v = pd.to_numeric(df_sample[vol_col], errors="coerce")
    p_ = pd.to_numeric(p, errors="coerce")
    mask = v.notna() & p_.notna() & (v > 0) & (p_ > 0)

    dfp = df_sample.loc[mask].copy()
    dfp["_vol"] = v[mask]
    dfp["_price"] = p_[mask]
    dfp["_implied_base_if_quote"] = dfp["_vol"] / dfp["_price"]   # 如果 vol 是 USD，则这个是隐含 BTC
    dfp["_implied_dv_if_base"] = dfp["_vol"] * dfp["_price"]      # 如果 vol 是 BTC，则这个是隐含美元DV

    # 时间列尽量解析，便于画 time series（如果解析失败也没关系）
    if time_col:
        dfp["_time"] = parse_time_column(dfp[time_col])
    else:
        dfp["_time"] = pd.NaT

    # 图1：Volume 的直方图（log10），一眼看数量级
    plt.figure()
    x = np.log10(dfp["_vol"].clip(lower=1e-12))
    plt.hist(x, bins=60)
    plt.title(f"{exchange_name} - log10(Volume) distribution")
    plt.xlabel("log10(Volume)")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(out_dir / f"{exchange_name}_01_log10_volume_hist.png", dpi=160)
    plt.close()

    # 图2：两个“隐含量级”对比（取 log10）
    # - implied_base_if_quote：若 volume 是 USD，除以价格应得到 BTC 数量
    # - implied_dv_if_base：若 volume 是 BTC，乘价格应得到美元DV
    plt.figure()
    a = np.log10(dfp["_implied_base_if_quote"].clip(lower=1e-12))
    b = np.log10(dfp["_implied_dv_if_base"].clip(lower=1e-12))
    plt.hist(a, bins=60, alpha=0.6, label="log10(volume/price)  (implied BTC if volume is USD)")
    plt.hist(b, bins=60, alpha=0.6, label="log10(volume*price) (implied USD DV if volume is BTC)")
    plt.title(f"{exchange_name} - implied scale check (two hypotheses)")
    plt.xlabel("log10(value)")
    plt.ylabel("Count")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / f"{exchange_name}_02_implied_scale_hist.png", dpi=160)
    plt.close()

# =========================
# 主流程
# =========================
def main():
    nice_print(f"输入目录：{INPUT_DIR}")
    nice_print(f"输出目录：{OUTPUT_DIR}")

    if not INPUT_DIR.exists():
        err_print("输入目录不存在！请检查路径是否正确。")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    diag_dir = OUTPUT_DIR / "diagnostics"
    dv_dir = OUTPUT_DIR / "dv_ready"
    dv_dir.mkdir(parents=True, exist_ok=True)

    # 找所有 CSV
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        err_print("输入目录下没有找到任何 .csv 文件。")
        return

    nice_print(f"找到 {len(files)} 个 CSV：")
    for f in files:
        nice_print(f"  - {f.name}")

    report_rows = []

    for fpath in files:
        # 从文件名猜交易所名字（如 BTCUSD_1m_Binance.csv -> Binance）
        exchange_name = fpath.stem.split("_")[-1]

        nice_print(f"\n开始处理：{fpath.name}  (Exchange={exchange_name})")

        # 先抽样读取一部分做诊断（避免一次性读两年分钟数据太慢）
        try:
            df_sample = pd.read_csv(fpath, nrows=DIAG_SAMPLE_ROWS)
        except Exception as e:
            err_print(f"读取失败：{e}")
            continue

        df_sample = normalize_columns(df_sample)

        # 自动找列
        time_col = pick_col(df_sample, ["Open time", "opentime", "timestamp", "date", "time", "datetime"])
        col_open = pick_col(df_sample, ["Open", "open"])
        col_high = pick_col(df_sample, ["High", "high"])
        col_low  = pick_col(df_sample, ["Low", "low"])
        col_close= pick_col(df_sample, ["Close", "close"])
        vol_col  = pick_col(df_sample, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

        if vol_col is None:
            err_print("找不到 Volume 列（可能列名不标准）。请打开CSV看一下列名，再把候选列名补进脚本。")
            continue

        # 代表价 & range
        try:
            p = compute_representative_price(df_sample, col_open, col_high, col_low, col_close)
        except Exception as e:
            err_print(f"计算代表价失败：{e}")
            continue

        rng = compute_range(df_sample, col_high, col_low, p)

        # 推断 Volume 单位
        unit, conf, rationale = infer_volume_unit(exchange_name, df_sample, vol_col, p)

        nice_print(f"Volume 推断结果：{unit}（置信度：{conf}）")
        nice_print(f"理由：{rationale}")

        # 保存诊断图（非常直观）
        try:
            save_diagnostic_plots(exchange_name, df_sample, time_col, vol_col, p, diag_dir)
            nice_print(f"已输出诊断图到：{diag_dir}")
        except Exception as e:
            warn_print(f"诊断图输出失败（不影响主流程）：{e}")

        # 报告行（写进 Excel）
        v = pd.to_numeric(df_sample[vol_col], errors="coerce")
        p_ = pd.to_numeric(p, errors="coerce")
        mask = v.notna() & p_.notna() & (v > 0) & (p_ > 0)
        v_med = float(np.nanmedian(v[mask])) if mask.any() else np.nan
        price_med = float(np.nanmedian(p_[mask])) if mask.any() else np.nan

        report_rows.append({
            "exchange": exchange_name,
            "file": fpath.name,
            "time_col": time_col or "",
            "open_col": col_open or "",
            "high_col": col_high or "",
            "low_col": col_low or "",
            "close_col": col_close or "",
            "volume_col": vol_col,
            "median_price": price_med,
            "median_volume": v_med,
            "inferred_volume_unit": unit,
            "confidence": conf,
            "recommended_DV_formula": "DV = Volume * p (if base)" if unit == "base"
                                     else ("DV = Volume (if quote_or_contract)" if unit == "quote_or_contract"
                                           else "UNKNOWN: default DV = Volume * p, but please verify"),
            "rationale": rationale
        })

        # =========================
        # 第二阶段：按推断结果，全量生成 DV 并输出新 CSV（用 chunk 方式，不吃内存）
        # =========================
        out_csv = dv_dir / f"{fpath.stem}_with_DV.csv"
        nice_print(f"开始生成 DV 并输出到：{out_csv}")

        # 如果已存在，先删掉（避免重复追加）
        if out_csv.exists():
            out_csv.unlink()

        first_chunk = True
        try:
            for chunk in pd.read_csv(fpath, chunksize=CHUNK_SIZE):
                chunk = normalize_columns(chunk)

                # 重找列（因为全量 chunk 读取后列名一致）
                col_open2 = pick_col(chunk, ["Open", "open"])
                col_high2 = pick_col(chunk, ["High", "high"])
                col_low2  = pick_col(chunk, ["Low", "low"])
                col_close2= pick_col(chunk, ["Close", "close"])
                vol_col2  = pick_col(chunk, [vol_col]) or pick_col(chunk, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

                p2 = compute_representative_price(chunk, col_open2, col_high2, col_low2, col_close2)
                rng2 = compute_range(chunk, col_high2, col_low2, p2)

                vol2 = pd.to_numeric(chunk[vol_col2], errors="coerce")

                # 按推断统一 DV（美元交易额）
                if unit == "base":
                    dv = vol2 * pd.to_numeric(p2, errors="coerce")
                elif unit == "quote_or_contract":
                    dv = vol2
                else:
                    # unknown：先按 base 处理，但在结果里标注低置信度
                    dv = vol2 * pd.to_numeric(p2, errors="coerce")

                chunk["p_repr"] = p2
                chunk["range_rel"] = rng2
                chunk["volume_unit_inferred"] = unit
                chunk["volume_unit_confidence"] = conf
                chunk["DV"] = dv

                chunk.to_csv(out_csv, mode="w" if first_chunk else "a",
                             index=False, header=first_chunk, encoding="utf-8-sig")
                first_chunk = False

            nice_print("DV 输出完成。")

        except Exception as e:
            err_print(f"全量输出 DV 时出错：{e}")
            continue

    # 输出 Excel 报告
    if report_rows:
        report_df = pd.DataFrame(report_rows)
        report_path = OUTPUT_DIR / "volume_unit_report.xlsx"
        report_df.to_excel(report_path, index=False)
        nice_print(f"\n✅ 已生成总报告：{report_path}")
        nice_print(f"✅ 已生成带 DV 的新数据：{dv_dir}")
        nice_print(f"✅ 已生成诊断图：{diag_dir}")
    else:
        warn_print("没有生成任何报告行，请检查 CSV 是否能正常读取、列名是否能匹配。")

if __name__ == "__main__":
    main()

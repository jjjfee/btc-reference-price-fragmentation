# probe_contract_vs_spot.py
# ============================================================
# 目标：用 OHLCV 分钟数据做“合约 vs 现货”的再检测（概率/证据型）
# 输出：
#   1) contract_spot_probe_report.xlsx
#   2) diagnostics_plots/*.png（每家交易所 2 张图）
# ============================================================

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ======= 你只需要改这里 =======
INPUT_DIR = (Path(__file__).resolve().parents[2] / "data" / "external" / "raw" / "btc")   # 原始 OHLCV 文件目录（7个csv）
OUT_DIR   = (Path(__file__).resolve().parents[2] / Path(r"contract_spot_probe"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR  = OUT_DIR / "diagnostics_plots"
PLOT_DIR.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2021-01-01", tz="UTC")
END   = pd.Timestamp("2022-12-31 23:59:00", tz="UTC")

CHUNK_SIZE = 200_000
SAMPLE_TARGET = 200_000  # 用于快速诊断的采样上限

# ------------------------------------------------------------
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
        return (o + h + l + c) / 4.0
    if (h is not None) and (l is not None):
        return (h + l) / 2.0
    if c is not None:
        return c
    raise ValueError("缺少 open/high/low/close，无法计算代表价。")

def read_sample_2021_2022(csv_path: Path, sample_target: int) -> pd.DataFrame:
    head = normalize_columns(pd.read_csv(csv_path, nrows=5))
    time_col = pick_col(head, ["Open time", "opentime", "timestamp", "date", "time", "datetime"])
    col_open = pick_col(head, ["Open", "open"])
    col_high = pick_col(head, ["High", "high"])
    col_low  = pick_col(head, ["Low", "low"])
    col_close= pick_col(head, ["Close", "close"])
    vol_col  = pick_col(head, ["Volume", "volume", "vol", "qty", "amount", "turnover"])

    if time_col is None or vol_col is None:
        raise ValueError(f"{csv_path.name} 找不到 time 或 volume 列。")

    parts, got = [], 0
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

        out = pd.DataFrame({"time_utc": sub["time_utc"], "p": pd.to_numeric(p, errors="coerce"), "v": v}).dropna()
        parts.append(out)
        got += len(out)
        if got >= sample_target:
            break

    if not parts:
        raise ValueError(f"{csv_path.name} 在 2021-2022 没抽到样本（检查时间列解析）。")

    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last")
    return df

def integer_ratio(v: np.ndarray) -> float:
    v = v[np.isfinite(v) & (v > 0)]
    if v.size == 0:
        return np.nan
    frac = np.abs(v - np.round(v))
    return float((frac < 1e-6).mean())

def save_two_plots(ex: str, df: pd.DataFrame):
    # 图1：log10(volume)直方图
    plt.figure()
    x = np.log10(df["v"].to_numpy().clip(min=1e-12))
    plt.hist(x, bins=60)
    plt.title(f"{ex} log10(Volume) hist")
    plt.tight_layout()
    plt.savefig(PLOT_DIR / f"{ex}_01_log10_volume_hist.png", dpi=160)
    plt.close()

    # 图2：两种假设下的“隐含量级”
    # vol是USD/张数 => implied BTC = v/p
    # vol是BTC      => implied USD DV = v*p
    plt.figure()
    a = np.log10((df["v"] / df["p"]).to_numpy().clip(min=1e-12))
    b = np.log10((df["v"] * df["p"]).to_numpy().clip(min=1e-12))
    plt.hist(a, bins=60, alpha=0.6, label="log10(v/p)  implied BTC if vol is USD/contracts")
    plt.hist(b, bins=60, alpha=0.6, label="log10(v*p) implied USD DV if vol is BTC")
    plt.legend()
    plt.title(f"{ex} scale check (two hypotheses)")
    plt.tight_layout()
    plt.savefig(PLOT_DIR / f"{ex}_02_implied_scale_hist.png", dpi=160)
    plt.close()

def decide_label(v_med, int_ratio_est, implied_btc_med, implied_dv_med):
    """
    输出：label + strength + rationale
    这是“证据型分类”，不是绝对真值。
    """
    # 强合约/计价量特征：几乎全整数 且 中位数较大
    if np.isfinite(int_ratio_est) and int_ratio_est > 0.95 and v_med >= 50:
        return ("contract_or_quote", "high",
                f"整数比例≈{int_ratio_est:.2%} 且 volume中位数≈{v_med:,.2f} 偏大，像张数/计价量。")

    # 典型现货base特征：volume中位数较小且非纯整数
    if v_med < 50 and (not np.isfinite(int_ratio_est) or int_ratio_est < 0.95):
        return ("spot_base_likely", "medium",
                f"volume中位数≈{v_med:,.4f} 偏小且非纯整数（整数比例≈{int_ratio_est:.2%}），更像BTC数量。")

    # 数量级一致性辅助：若假设 vol=USD，则 implied_btc 太离谱
    if np.isfinite(implied_btc_med) and (implied_btc_med > 1e6 or implied_btc_med < 1e-6):
        return ("spot_base_likely", "low",
                f"若把volume当USD/张数，隐含BTC中位数 v/p≈{implied_btc_med:,.3e} 很离谱，倾向vol为BTC。")

    # 若假设 vol=BTC，隐含DV极其离谱（比如中位数大到天文），也可能是USD/张数
    if np.isfinite(implied_dv_med) and implied_dv_med > 1e12:
        return ("contract_or_quote", "medium",
                f"若把volume当BTC，隐含DV中位数 v*p≈{implied_dv_med:,.3e} 过大，倾向vol为USD/张数。")

    return ("unclear", "low", "OHLCV证据不够强，建议结合数据源字段说明或补充衍生品特征字段。")

def main():
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"未找到CSV：{INPUT_DIR}")

    rows = []
    for fp in files:
        ex = fp.stem.split("_")[-1]
        print(f"[INFO] Sampling {fp.name} (exchange={ex})")

        df = read_sample_2021_2022(fp, SAMPLE_TARGET)
        df = df[(df["p"] > 0) & (df["v"] > 0)].copy()
        if len(df) < 2000:
            print(f"[WARN] {ex} 有效样本过少：{len(df)}")
            continue

        v = df["v"].to_numpy()
        p = df["p"].to_numpy()

        v_med = float(np.nanmedian(v))
        v_p95 = float(np.nanpercentile(v, 95))
        p_med = float(np.nanmedian(p))

        int_r = integer_ratio(v)
        implied_btc_med = float(np.nanmedian(v / p))
        implied_dv_med  = float(np.nanmedian(v * p))

        label, strength, rationale = decide_label(v_med, int_r, implied_btc_med, implied_dv_med)

        save_two_plots(ex, df)

        rows.append({
            "exchange": ex,
            "file": fp.name,
            "n_sample": int(len(df)),
            "median_price": p_med,
            "median_volume": v_med,
            "p95_volume": v_p95,
            "integer_ratio": int_r,
            "median_implied_btc_if_quote(v/p)": implied_btc_med,
            "median_implied_usd_dv_if_base(v*p)": implied_dv_med,
            "label": label,
            "strength": strength,
            "rationale": rationale,
        })

    out_xlsx = OUT_DIR / "contract_spot_probe_report.xlsx"
    pd.DataFrame(rows).sort_values(["strength","exchange"]).to_excel(out_xlsx, index=False)
    print(f"\n✅ Saved report: {out_xlsx}")
    print(f"✅ Saved plots : {PLOT_DIR}")

if __name__ == "__main__":
    main()

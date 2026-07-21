# weight_concentration_check_v2.py
# ============================================================
# 目的：
#   1) 计算每分钟权重集中度：max_share、HHI、dominant_exchange
#   2) 输出：
#        - experiments/weight_concentration_report.xlsx (summary)
#        - experiments/weight_concentration_minute_level.csv (全量分钟明细)
#   注意：minute_level 用 CSV，避免 Excel 行数限制
# ============================================================

from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_DIR = BASE_DIR / "dv_ready_2021_2022"
OUT_DIR = BASE_DIR / "experiments"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TIME_COLS = ["time_utc", "timestamp", "time"]
WEIGHT_COLS = ["DV_usd", "DV", "dv_usd", "dollar_volume"]

def pick(cols, cands):
    m = {c.lower(): c for c in cols}
    for x in cands:
        if x.lower() in m:
            return m[x.lower()]
    return None

def ex_name(fp: Path):
    for k in ["Binance","Bitfinex","BitMEX","Bitstamp","Coinbase","KuCoin","OKX"]:
        if k.lower() in fp.name.lower():
            return k
    return fp.stem

def main():
    files = sorted(INPUT_DIR.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"输入目录没有 CSV：{INPUT_DIR}")

    weights = pd.DataFrame()

    # 读取每家交易所的权重列
    for fp in files:
        ex = ex_name(fp)
        head = pd.read_csv(fp, nrows=5)
        tcol = pick(head.columns, TIME_COLS)
        wcol = pick(head.columns, WEIGHT_COLS)
        if tcol is None or wcol is None:
            raise ValueError(f"{fp.name} 缺少 time 或 DV 列：time={tcol}, weight={wcol}")

        df = pd.read_csv(fp, usecols=[tcol, wcol])
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce", utc=True)
        df[wcol] = pd.to_numeric(df[wcol], errors="coerce")
        df = df.dropna(subset=[tcol]).sort_values(tcol).drop_duplicates(tcol, keep="last").set_index(tcol)

        weights[ex] = df[wcol]

    weights = weights.sort_index()

    W = weights.to_numpy(float)
    W = np.where(np.isfinite(W) & (W > 0), W, 0.0)

    total = W.sum(axis=1)
    share = np.where(total[:, None] > 0, W / total[:, None], 0.0)

    max_share = share.max(axis=1)
    hhi = (share ** 2).sum(axis=1)
    dominant_idx = share.argmax(axis=1)
    dominant = np.array(weights.columns)[dominant_idx]

    rep = pd.DataFrame({
        "time_utc": weights.index.astype(str),
        "total_DV": total,
        "max_share": max_share,
        "HHI": hhi,
        "dominant_exchange": dominant
    })

    summary = pd.DataFrame({
        "metric": [
            "minutes_total",
            "share(max_share>0.5)",
            "share(max_share>0.4)",
            "share(max_share>0.3)",
            "median(max_share)",
            "p95(max_share)",
            "median(HHI)",
            "p95(HHI)"
        ],
        "value": [
            int(len(rep)),
            float((rep["max_share"] > 0.5).mean()),
            float((rep["max_share"] > 0.4).mean()),
            float((rep["max_share"] > 0.3).mean()),
            float(rep["max_share"].median()),
            float(rep["max_share"].quantile(0.95)),
            float(rep["HHI"].median()),
            float(rep["HHI"].quantile(0.95)),
        ]
    })

    # 输出 summary（Excel）
    out_xlsx = OUT_DIR / "weight_concentration_report.xlsx"
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        summary.to_excel(w, index=False, sheet_name="summary")
    print(f"✅ 输出 summary：{out_xlsx}")

    # 输出 minute_level（CSV）
    out_csv = OUT_DIR / "weight_concentration_minute_level.csv"
    rep.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"✅ 输出 minute_level：{out_csv}")

if __name__ == "__main__":
    main()

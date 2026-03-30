# audit_04_rebuild_quintile_and_compare.py
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"D:\cilck here\2代目")

EVENT_CSV = ROOT / "experiments_dvonly" / "dvon_injection_shift_samples.csv"
PANEL_CSV = ROOT / "hhi_panel" / "btc_1m_panel_with_hhi.csv"
XLSX_SUM = Path(r"D:\cilck here\2代目\experiments\DVonly_Injection_By_HHIrollQuintile.xlsx")


OUT_REBUILT = ROOT / "experiments_dvonly" / "audit04_rebuilt_quintile_summary.xlsx"
OUT_COMPARE = ROOT / "experiments_dvonly" / "audit04_compare_to_existing.csv"

LABELS = ["Q1(low)","Q2","Q3","Q4","Q5(high)"]
ROLL_COL_CAND = ["HHI_roll","hhi_roll","HHI_ROLL","hhiroll"]

def read_csv_safely(p: Path):
    # 兼容 utf-8-sig/utf-8
    try:
        return pd.read_csv(p, low_memory=False, encoding="utf-8-sig")
    except Exception:
        return pd.read_csv(p, low_memory=False)

def pick_time_col(df):
    for c in df.columns:
        cl = str(c).lower()
        if cl in ["time_utc_dt","time_utc","timestamp","time"]:
            return c
    # 兜底：包含 time 的
    for c in df.columns:
        if "time" in str(c).lower():
            return c
    raise ValueError("Cannot find time column.")

def pick_roll_col(df):
    cols = set(df.columns)
    for c in ROLL_COL_CAND:
        if c in cols:
            return c
    # 兜底模糊
    for c in df.columns:
        if "hhi" in str(c).lower() and "roll" in str(c).lower():
            return c
    raise ValueError("Cannot find HHI_roll column in panel.")

def summarize_abs(x):
    x = pd.to_numeric(x, errors="coerce").to_numpy(float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return (np.nan, np.nan, 0)
    ax = np.abs(x)
    return (float(np.median(ax)), float(np.quantile(ax, 0.95)), int(ax.size))

def main():
    assert EVENT_CSV.exists(), f"Missing {EVENT_CSV}"
    assert PANEL_CSV.exists(), f"Missing {PANEL_CSV}"
    assert XLSX_SUM.exists(), f"Missing {XLSX_SUM}"

    print("[1] Load event-level:", EVENT_CSV)
    ev = read_csv_safely(EVENT_CSV)
    ev["time_utc"] = pd.to_datetime(ev["time_utc"], errors="coerce", utc=True).dt.floor("min")
    ev = ev.dropna(subset=["time_utc"]).copy()

    # 必要列检查
    need = ["delta_w","shock_type","pivot_changed","shift_vwap","shift_lwmp",
            "exchange_shocked","pivot_exchange_after"]
    miss = [c for c in need if c not in ev.columns]
    if miss:
        raise ValueError("Event-level missing columns: " + str(miss))

    ev["delta_w"] = pd.to_numeric(ev["delta_w"], errors="coerce")
    ev["pivot_changed"] = pd.to_numeric(ev["pivot_changed"], errors="coerce").astype("Int64")
    ev["shift_vwap"] = pd.to_numeric(ev["shift_vwap"], errors="coerce")
    ev["shift_lwmp"] = pd.to_numeric(ev["shift_lwmp"], errors="coerce")

    print("[2] Load panel:", PANEL_CSV)
    panel = read_csv_safely(PANEL_CSV)
    tcol = pick_time_col(panel)
    rcol = pick_roll_col(panel)

    panel["time_utc"] = pd.to_datetime(panel[tcol], errors="coerce", utc=True).dt.floor("min")
    panel[rcol] = pd.to_numeric(panel[rcol], errors="coerce")
    panel2 = panel[["time_utc", rcol]].dropna().drop_duplicates("time_utc", keep="last").copy()

    # 用“全体面板分钟”划分五分位（更稳定）
    panel2["HHIroll_quintile"] = pd.qcut(panel2[rcol], 5, labels=LABELS, duplicates="drop").astype(str)

    print("[3] Merge event with quintile...")
    df = ev.merge(panel2[["time_utc","HHIroll_quintile"]], on="time_utc", how="left")
    ok = df["HHIroll_quintile"].notna().mean()
    print(f"    merge success rate = {ok:.2%}")
    df = df.dropna(subset=["HHIroll_quintile"]).copy()

    # pivot_to_shocked 两种定义都算出来：等会儿自动选哪个更像你的 Excel
    df["pivot_to_shocked_uncond"] = (df["pivot_exchange_after"].astype(str) == df["exchange_shocked"].astype(str)).astype(int)
    df["pivot_to_shocked_cond"] = np.where(
        df["pivot_changed"].astype(int) == 1,
        df["pivot_to_shocked_uncond"],
        np.nan
    )

    # --------- 重建 summary（overall）---------
    rows = []
    for (g, q), sub in df.groupby(["delta_w","HHIroll_quintile"], observed=True):
        v_med, v_p95, n1 = summarize_abs(sub["shift_vwap"])
        l_med, l_p95, n2 = summarize_abs(sub["shift_lwmp"])
        n = int(len(sub))

        rows.append(dict(
            gamma=float(g),  # 对齐你 Excel 的 gamma 命名
            HHIroll_quintile=str(q),
            VWAP_median_abs_shift=v_med,
            VWAP_p95_abs_shift=v_p95,
            LWMP_median_abs_shift=l_med,
            LWMP_p95_abs_shift=l_p95,
            LWMP_pivot_switch_rate=float(pd.to_numeric(sub["pivot_changed"], errors="coerce").mean()),
            LWMP_pivot_to_shocked_rate_uncond=float(sub["pivot_to_shocked_uncond"].mean()),
            LWMP_pivot_to_shocked_rate_cond=float(pd.to_numeric(sub["pivot_to_shocked_cond"], errors="coerce").mean()),
            n=n
        ))

    rebuilt = pd.DataFrame(rows).sort_values(["gamma","HHIroll_quintile"]).reset_index(drop=True)

    # --------- 读你已有的 Excel summary 并对比 ---------
    print("[4] Load existing xlsx:", XLSX_SUM)
    # 尝试自动选 sheet：优先第一个
    xls = pd.ExcelFile(XLSX_SUM)
    sheet = xls.sheet_names[0]
    exist = pd.read_excel(XLSX_SUM, sheet_name=sheet)
    exist.columns = [str(c).strip() for c in exist.columns]

    # 兼容列名：gamma / HHIroll_quintile / n 必须有
    if "gamma" not in exist.columns:
        raise ValueError(f"Existing xlsx missing 'gamma'. columns={list(exist.columns)}")
    if "HHIroll_quintile" not in exist.columns:
        raise ValueError(f"Existing xlsx missing 'HHIroll_quintile'. columns={list(exist.columns)}")

    # 判断你 Excel 的 pivot_to_shocked_rate 更像哪一种定义（cond/uncond）
    if "LWMP_pivot_to_shocked_rate" in exist.columns:
        tmp = exist.merge(
            rebuilt[["gamma","HHIroll_quintile","LWMP_pivot_to_shocked_rate_uncond","LWMP_pivot_to_shocked_rate_cond"]],
            on=["gamma","HHIroll_quintile"],
            how="left"
        )
        e = pd.to_numeric(tmp["LWMP_pivot_to_shocked_rate"], errors="coerce").to_numpy()
        u = pd.to_numeric(tmp["LWMP_pivot_to_shocked_rate_uncond"], errors="coerce").to_numpy()
        c = pd.to_numeric(tmp["LWMP_pivot_to_shocked_rate_cond"], errors="coerce").to_numpy()

        def mae(a,b):
            m = np.isfinite(a) & np.isfinite(b)
            return np.nan if m.sum()==0 else float(np.mean(np.abs(a[m]-b[m])))

        mae_u = mae(e,u)
        mae_c = mae(e,c)
        print(f"[INFO] pivot_to_shocked MAE: uncond={mae_u:.6g}, cond={mae_c:.6g}")
        chosen = "uncond" if (mae_u <= mae_c) else "cond"
    else:
        chosen = None

    # 形成“对比表”
    # 尽可能对齐你 Excel 里的列名（若存在）
    key = ["gamma","HHIroll_quintile"]
    compare = exist.merge(rebuilt, on=key, how="left", suffixes=("_xlsx","_rebuilt"))

    # 输出差异（只对共有列）
    diff_cols = []
    for col in ["VWAP_median_abs_shift","VWAP_p95_abs_shift","LWMP_median_abs_shift","LWMP_p95_abs_shift","LWMP_pivot_switch_rate","n"]:
        if col in exist.columns:
            compare[col+"_absdiff"] = np.abs(pd.to_numeric(compare[col+"_xlsx"], errors="coerce") - pd.to_numeric(compare[col+"_rebuilt"], errors="coerce"))
            diff_cols.append(col+"_absdiff")

    if "LWMP_pivot_to_shocked_rate" in exist.columns and chosen is not None:
        usecol = "LWMP_pivot_to_shocked_rate_uncond" if chosen=="uncond" else "LWMP_pivot_to_shocked_rate_cond"
        compare["LWMP_pivot_to_shocked_rate_rebuilt"] = compare[usecol]
        compare["LWMP_pivot_to_shocked_rate_absdiff"] = np.abs(
            pd.to_numeric(compare["LWMP_pivot_to_shocked_rate"], errors="coerce") -
            pd.to_numeric(compare["LWMP_pivot_to_shocked_rate_rebuilt"], errors="coerce")
        )
        diff_cols.append("LWMP_pivot_to_shocked_rate_absdiff")

    # 保存
    with pd.ExcelWriter(OUT_REBUILT, engine="openpyxl") as w:
        rebuilt.to_excel(w, index=False, sheet_name="rebuilt_overall")
        # 额外输出按 shock_type 的版本，方便你发现“是否 Excel 混合了两类 shock”
        rows2 = []
        for (st, g, q), sub in df.groupby(["shock_type","delta_w","HHIroll_quintile"], observed=True):
            v_med, v_p95, _ = summarize_abs(sub["shift_vwap"])
            l_med, l_p95, _ = summarize_abs(sub["shift_lwmp"])
            rows2.append(dict(
                shock_type=str(st),
                gamma=float(g),
                HHIroll_quintile=str(q),
                VWAP_median_abs_shift=v_med,
                VWAP_p95_abs_shift=v_p95,
                LWMP_median_abs_shift=l_med,
                LWMP_p95_abs_shift=l_p95,
                LWMP_pivot_switch_rate=float(pd.to_numeric(sub["pivot_changed"], errors="coerce").mean()),
                n=int(len(sub))
            ))
        pd.DataFrame(rows2).sort_values(["shock_type","gamma","HHIroll_quintile"]).to_excel(
            w, index=False, sheet_name="rebuilt_by_shock_type"
        )

    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")
    print("✅ Rebuilt saved:", OUT_REBUILT)
    print("✅ Compare saved :", OUT_COMPARE)

    if diff_cols:
        mx = compare[diff_cols].max(numeric_only=True)
        print("\n[DIFF MAX] (xlsx vs rebuilt):")
        print(mx.to_string())

if __name__ == "__main__":
    main()

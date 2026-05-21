from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np


BASE_DIR = Path(r"D:\cilck here\2代目\experiments_dvonly\exclude_binance")
BASENAME = "dvon_injection_shift_samples__exclude_Binance"


def find_input_file(base_dir: Path, basename: str) -> Path:
    """
    Search for a file named basename with a supported extension.
    """
    exts = [".csv", ".xlsx", ".xls", ".parquet", ".feather"]
    candidates = []

    for ext in exts:
        p = base_dir / f"{basename}{ext}"
        if p.exists():
            candidates.append(p)

    if not candidates:
        # fallback: fuzzy search
        for p in base_dir.iterdir():
            if p.is_file() and p.stem.lower() == basename.lower():
                candidates.append(p)

    if not candidates:
        raise FileNotFoundError(
            f"未找到输入文件：{basename}.[csv/xlsx/xls/parquet/feather]\n"
            f"搜索目录：{base_dir}"
        )

    # prefer csv/xlsx if multiple files exist
    priority = {".csv": 0, ".xlsx": 1, ".xls": 2, ".parquet": 3, ".feather": 4}
    candidates.sort(key=lambda x: priority.get(x.suffix.lower(), 99))
    return candidates[0]


def read_table(path: Path) -> pd.DataFrame:
    """
    Read a table from a supported file type.
    """
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".feather":
        return pd.read_feather(path)

    raise ValueError(f"不支持的文件格式：{path.suffix}")


def ensure_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """
    Convert selected columns to numeric when present.
    """
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """
    Build grouped summary table.
    """
    required = [
        "pivot_changed",
        "shift_lwmp",
        "shift_vwap",
        "pivot_margin_before",
        "pivot_margin_after",
        "share_shocked_before",
        "share_shocked_after",
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"缺少必要字段：{missing}")

    work = df.copy()

    work["abs_shift_lwmp"] = work["shift_lwmp"].abs()
    work["abs_shift_vwap"] = work["shift_vwap"].abs()
    work["pivot_margin_delta"] = work["pivot_margin_after"] - work["pivot_margin_before"]
    work["share_shocked_delta"] = work["share_shocked_after"] - work["share_shocked_before"]

    grouped = (
        work.groupby(group_cols, dropna=False)
        .agg(
            N=("pivot_changed", "size"),
            pivot_change_rate=("pivot_changed", "mean"),
            median_abs_shift_lwmp=("abs_shift_lwmp", "median"),
            median_abs_shift_vwap=("abs_shift_vwap", "median"),
            mean_abs_shift_lwmp=("abs_shift_lwmp", "mean"),
            mean_abs_shift_vwap=("abs_shift_vwap", "mean"),
            median_pivot_margin_before=("pivot_margin_before", "median"),
            median_pivot_margin_after=("pivot_margin_after", "median"),
            median_pivot_margin_delta=("pivot_margin_delta", "median"),
            median_share_shocked_before=("share_shocked_before", "median"),
            median_share_shocked_after=("share_shocked_after", "median"),
            median_share_shocked_delta=("share_shocked_delta", "median"),
        )
        .reset_index()
    )

    return grouped


def save_outputs(df: pd.DataFrame, out_csv: Path, out_xlsx: Path) -> None:
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    df.to_excel(out_xlsx, index=False)


def main() -> int:
    input_path = find_input_file(BASE_DIR, BASENAME)
    print(f"读取文件：{input_path}")

    df = read_table(input_path)

    numeric_cols = [
        "delta_w",
        "weight_factor",
        "share_shocked_before",
        "share_shocked_after",
        "pivot_margin_before",
        "pivot_margin_after",
        "pivot_changed",
        "shift_mean",
        "shift_median",
        "shift_vwap",
        "shift_lwmp",
    ]
    df = ensure_numeric(df, numeric_cols)

    # 主 summary：Appendix C 最常用
    main_group_cols = ["shock_type", "delta_w", "weight_factor"]
    summary_main = build_summary(df, main_group_cols)

    # 按被冲击交易所进一步拆分
    by_exchange_group_cols = ["shock_type", "delta_w", "weight_factor", "exchange_shocked"]
    if "exchange_shocked" in df.columns:
        summary_by_exchange = build_summary(df, by_exchange_group_cols)
    else:
        summary_by_exchange = pd.DataFrame()

    # overall：和主表类似，但防止后续你想只看更简洁版本
    overall_group_cols = ["shock_type", "delta_w", "weight_factor"]
    summary_overall = build_summary(df, overall_group_cols)

    # 输出
    save_outputs(
        summary_main,
        BASE_DIR / "exclude_binance_summary_main.csv",
        BASE_DIR / "exclude_binance_summary_main.xlsx",
    )

    if not summary_by_exchange.empty:
        save_outputs(
            summary_by_exchange,
            BASE_DIR / "exclude_binance_summary_by_exchange.csv",
            BASE_DIR / "exclude_binance_summary_by_exchange.xlsx",
        )

    save_outputs(
        summary_overall,
        BASE_DIR / "exclude_binance_summary_overall.csv",
        BASE_DIR / "exclude_binance_summary_overall.xlsx",
    )

    print("已输出：")
    print(BASE_DIR / "exclude_binance_summary_main.csv")
    print(BASE_DIR / "exclude_binance_summary_main.xlsx")
    if not summary_by_exchange.empty:
        print(BASE_DIR / "exclude_binance_summary_by_exchange.csv")
        print(BASE_DIR / "exclude_binance_summary_by_exchange.xlsx")
    print(BASE_DIR / "exclude_binance_summary_overall.csv")
    print(BASE_DIR / "exclude_binance_summary_overall.xlsx")

    print("\n主 summary 预览：")
    print(summary_main.head(20).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

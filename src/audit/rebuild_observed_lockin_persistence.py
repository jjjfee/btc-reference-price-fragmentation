from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =========================================================
# 0) PATH CONFIG
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[2]
DV_DIR = BASE_DIR / "dv_ready_2021_2022"
OUT_DIR = BASE_DIR / "outputs" / "main_text" / "tables"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VALID_SUFFIXES = {".csv", ".txt", ".xlsx", ".xls", ".parquet", ".feather"}


# =========================================================
# 1) GENERIC IO
# =========================================================
def find_file_by_keywords(base_dir: Path, keywords: List[str]) -> Path:
    cands = []
    for p in base_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in VALID_SUFFIXES:
            continue
        stem = p.stem.lower()
        if all(k.lower() in stem for k in keywords):
            cands.append(p)
    if not cands:
        raise FileNotFoundError(f"Cannot find file with keywords: {keywords}")
    cands = sorted(cands, key=lambda x: (len(x.parts), len(x.name)))
    return cands[0]


def get_header(path: Path) -> List[str]:
    suf = path.suffix.lower()
    if suf in {".csv", ".txt"}:
        return list(pd.read_csv(path, nrows=0).columns)
    if suf in {".xlsx", ".xls"}:
        return list(pd.read_excel(path, nrows=0).columns)
    if suf == ".parquet":
        return list(pd.read_parquet(path).columns)
    if suf == ".feather":
        return list(pd.read_feather(path).columns)
    raise ValueError(f"Unsupported file type: {path}")


def read_selected(path: Path, usecols: Optional[List[str]] = None) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in {".csv", ".txt"}:
        return pd.read_csv(path, usecols=usecols)
    if suf in {".xlsx", ".xls"}:
        return pd.read_excel(path, usecols=usecols)
    if suf == ".parquet":
        df = pd.read_parquet(path)
        return df if usecols is None else df[usecols]
    if suf == ".feather":
        df = pd.read_feather(path)
        return df if usecols is None else df[usecols]
    raise ValueError(f"Unsupported file type: {path}")


def first_existing(cols: List[str], candidates: List[str]) -> Optional[str]:
    mapper = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in mapper:
            return mapper[cand.lower()]
    return None


# =========================================================
# 2) FIND MAIN FILES
# =========================================================
try:
    weight_file = find_file_by_keywords(BASE_DIR, ["weight", "concentration", "minute", "level"])
except Exception as e:
    print(f"[ERROR] Cannot find weight_concentration_minute_level: {e}")
    sys.exit(1)

try:
    panel_file = find_file_by_keywords(BASE_DIR, ["btc", "1m", "panel", "hhi"])
except Exception as e:
    print(f"[WARN] Cannot find btc_1m_panel_with_hhi: {e}")
    panel_file = None

print(f"[INFO] weight_file = {weight_file}")
print(f"[INFO] panel_file  = {panel_file}")


# =========================================================
# 3) LOAD MINUTE-LEVEL CONCENTRATION PANEL
# =========================================================
weight_cols = get_header(weight_file)
weight_time_col = first_existing(weight_cols, ["time_utc", "time_utc_dt", "time", "timestamp", "datetime"])
weight_max_share_col = first_existing(weight_cols, ["max_share"])
weight_hhi_col = first_existing(weight_cols, ["HHI", "hhi"])
weight_dom_col = first_existing(weight_cols, ["dominant_exchange", "dominant"])
weight_total_dv_col = first_existing(weight_cols, ["total_DV", "total_dv"])

if weight_time_col is None or weight_max_share_col is None or weight_dom_col is None:
    raise ValueError(
        f"weight_file missing required columns. "
        f"Found columns = {weight_cols}"
    )

weight_usecols = [c for c in [weight_time_col, weight_max_share_col, weight_hhi_col, weight_dom_col, weight_total_dv_col] if c is not None]
weight_df = read_selected(weight_file, usecols=weight_usecols).copy()

weight_df = weight_df.rename(columns={
    weight_time_col: "time_raw",
    weight_max_share_col: "max_share",
    weight_hhi_col: "HHI" if weight_hhi_col else None,
    weight_dom_col: "dominant_exchange",
    weight_total_dv_col: "total_DV_file" if weight_total_dv_col else None,
})
weight_df = weight_df.loc[:, [c for c in weight_df.columns if c is not None]]
weight_df["time_utc"] = pd.to_datetime(weight_df["time_raw"], utc=True, errors="coerce")
weight_df = (
    weight_df.drop(columns=["time_raw"])
    .dropna(subset=["time_utc"])
    .sort_values("time_utc")
    .drop_duplicates("time_utc", keep="first")
)

print(f"[INFO] weight_df rows = {len(weight_df):,}")


# =========================================================
# 4) LOAD DV_READY FILES AND REBUILD PIVOT STATE
# =========================================================
dv_files = sorted(DV_DIR.glob("*with_DV*"))
if not dv_files:
    raise FileNotFoundError(f"No DV-ready files found under {DV_DIR}")

print(f"[INFO] Found {len(dv_files)} DV-ready files")

def infer_exchange_from_name(path: Path) -> str:
    # 例如 BTCUSD_1m_Binance_2021_2022_with_DV
    name = path.stem
    m = re.search(r"BTCUSD_1m_(.+?)_2021_2022_with_DV", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"BTCUSD_1m_(.+?)_with_DV", name, re.IGNORECASE)
    if m:
        return m.group(1)
    return name

all_parts = []

for fp in dv_files:
    cols = get_header(fp)

    time_col = first_existing(cols, ["time_utc", "time", "time_utc_dt", "timestamp", "datetime"])
    dv_col = first_existing(cols, ["DV_usd", "dv_usd", "DV_USD", "dv", "DV"])
    price_col = first_existing(cols, ["p_usd_scaled", "p_usd", "price", "p", "mid", "close"])

    if time_col is None or dv_col is None or price_col is None:
        raise ValueError(
            f"Cannot infer required columns in {fp.name}. "
            f"Columns found: {cols}"
        )

    usecols = [time_col, dv_col, price_col]
    tmp = read_selected(fp, usecols=usecols).copy()
    tmp = tmp.rename(columns={
        time_col: "time_raw",
        dv_col: "DV_usd",
        price_col: "price",
    })

    tmp["time_utc"] = pd.to_datetime(tmp["time_raw"], utc=True, errors="coerce")
    tmp["exchange"] = infer_exchange_from_name(fp)
    tmp["DV_usd"] = pd.to_numeric(tmp["DV_usd"], errors="coerce")
    tmp["price"] = pd.to_numeric(tmp["price"], errors="coerce")

    tmp = tmp.drop(columns=["time_raw"])
    tmp = tmp.dropna(subset=["time_utc", "DV_usd", "price"])
    tmp = tmp[tmp["DV_usd"] > 0]

    all_parts.append(tmp[["time_utc", "exchange", "DV_usd", "price"]])

    print(f"[INFO] loaded {fp.name}: {len(tmp):,} rows | exchange={tmp['exchange'].iloc[0]}")

dv_long = pd.concat(all_parts, ignore_index=True)
dv_long = dv_long.sort_values(["time_utc", "price", "exchange"]).reset_index(drop=True)

print(f"[INFO] dv_long rows = {len(dv_long):,}")


def rebuild_minute_state(group: pd.DataFrame) -> pd.Series:
    g = group.sort_values(["price", "exchange"]).copy()
    total_dv = g["DV_usd"].sum()

    if total_dv <= 0 or pd.isna(total_dv):
        return pd.Series({
            "total_DV_rebuilt": np.nan,
            "dominant_exchange_rebuilt": np.nan,
            "max_share_rebuilt": np.nan,
            "pivot_exchange": np.nan,
            "pivot_margin_norm": np.nan,
            "pivot_is_dominant_rebuilt": np.nan,
            "n_exchanges_used": len(g),
        })

    g["share"] = g["DV_usd"] / total_dv

    # dominant exchange: 权重最高者
    idx_dom = g["DV_usd"].idxmax()
    dominant_exchange = g.loc[idx_dom, "exchange"]
    max_share = g.loc[idx_dom, "share"]

    # LWMP pivot: 价格排序后，累计权重首次达到 0.5 的点
    g["cum_share"] = g["share"].cumsum()
    pivot_row = g.loc[g["cum_share"] >= 0.5].iloc[0]
    pivot_exchange = pivot_row["exchange"]
    pivot_margin_norm = float(pivot_row["cum_share"] - 0.5)

    return pd.Series({
        "total_DV_rebuilt": float(total_dv),
        "dominant_exchange_rebuilt": dominant_exchange,
        "max_share_rebuilt": float(max_share),
        "pivot_exchange": pivot_exchange,
        "pivot_margin_norm": pivot_margin_norm,
        "pivot_is_dominant_rebuilt": int(str(pivot_exchange).lower() == str(dominant_exchange).lower()),
        "n_exchanges_used": int(len(g)),
    })


minute_state = (
    dv_long.groupby("time_utc", as_index=False)
    .apply(rebuild_minute_state, include_groups=False)
)

print(f"[INFO] minute_state rows = {len(minute_state):,}")


# =========================================================
# 5) MERGE WITH OBSERVED CONCENTRATION PANEL
# =========================================================
df = weight_df.merge(minute_state, on="time_utc", how="left")

# 诊断 dominant mismatch
if "dominant_exchange" in df.columns and "dominant_exchange_rebuilt" in df.columns:
    both_nonnull = df["dominant_exchange"].notna() & df["dominant_exchange_rebuilt"].notna()
    if both_nonnull.any():
        mismatch_rate = (
            df.loc[both_nonnull, "dominant_exchange"].astype(str).str.lower().str.strip()
            != df.loc[both_nonnull, "dominant_exchange_rebuilt"].astype(str).str.lower().str.strip()
        ).mean()
        print(f"[INFO] dominant_exchange mismatch rate (file vs rebuilt) = {mismatch_rate:.6f}")
    else:
        mismatch_rate = np.nan
else:
    mismatch_rate = np.nan

# observed-market definitions: 优先用 weight_file 的 max_share / dominant_exchange
df["state_A"] = df["max_share"] > 0.5
df["state_B"] = df["state_A"] & (df["pivot_exchange"].astype(str).str.lower().str.strip()
                                 == df["dominant_exchange"].astype(str).str.lower().str.strip())
df["state_C"] = df["state_B"] & (pd.to_numeric(df["pivot_margin_norm"], errors="coerce") > 0)

df_valid = df.dropna(subset=["time_utc", "max_share"]).sort_values("time_utc").reset_index(drop=True)

print(f"[INFO] valid minutes = {len(df_valid):,}")
print(f"[INFO] A share = {df_valid['state_A'].mean():.6f}")
print(f"[INFO] B share = {df_valid['state_B'].mean():.6f}")
print(f"[INFO] C share = {df_valid['state_C'].mean():.6f}")


# =========================================================
# 6) SPELL EXTRACTION
# =========================================================
ONE_MIN = pd.Timedelta(minutes=1)

def extract_spells(data: pd.DataFrame, state_col: str, definition_name: str) -> pd.DataFrame:
    sub = data.loc[data[state_col].fillna(False)].copy()
    if sub.empty:
        return pd.DataFrame(columns=[
            "definition", "spell_id", "start_time", "end_time", "duration_min",
            "median_max_share_within_spell", "max_max_share_within_spell",
            "median_pivot_margin_norm_within_spell", "share_minutes_pivot_eq_dominant",
        ])

    sub = sub.sort_values("time_utc").reset_index(drop=True)
    sub["new_spell"] = sub["time_utc"].diff().ne(ONE_MIN).fillna(True)
    sub["spell_id"] = sub["new_spell"].cumsum()

    grouped = sub.groupby("spell_id", as_index=False)

    out = grouped.agg(
        start_time=("time_utc", "min"),
        end_time=("time_utc", "max"),
        duration_min=("time_utc", "size"),
        median_max_share_within_spell=("max_share", "median"),
        max_max_share_within_spell=("max_share", "max"),
        median_pivot_margin_norm_within_spell=("pivot_margin_norm", "median"),
        share_minutes_pivot_eq_dominant=("state_B", "mean"),  # 对 B/C 会是 1；A 则代表其中有多少分钟 pivot==dominant
    )
    out.insert(0, "definition", definition_name)
    return out


def summarize_spells(spells: pd.DataFrame, total_valid_minutes: int, definition_name: str) -> pd.DataFrame:
    if spells.empty:
        return pd.DataFrame([{
            "definition": definition_name,
            "num_spells": 0,
            "total_minutes_in_state": 0,
            "share_of_valid_minutes_in_state": 0.0,
            "mean_spell_duration_min": np.nan,
            "median_spell_duration_min": np.nan,
            "p90_spell_duration_min": np.nan,
            "p95_spell_duration_min": np.nan,
            "max_spell_duration_min": np.nan,
            "share_spells_ge_60m": np.nan,
            "share_spells_ge_360m": np.nan,
            "share_spells_ge_1440m": np.nan,
        }])

    dur = spells["duration_min"].astype(float)

    return pd.DataFrame([{
        "definition": definition_name,
        "num_spells": int(len(spells)),
        "total_minutes_in_state": int(dur.sum()),
        "share_of_valid_minutes_in_state": float(dur.sum() / total_valid_minutes),
        "mean_spell_duration_min": float(dur.mean()),
        "median_spell_duration_min": float(dur.median()),
        "p90_spell_duration_min": float(dur.quantile(0.90)),
        "p95_spell_duration_min": float(dur.quantile(0.95)),
        "max_spell_duration_min": float(dur.max()),
        "share_spells_ge_60m": float((dur >= 60).mean()),
        "share_spells_ge_360m": float((dur >= 360).mean()),
        "share_spells_ge_1440m": float((dur >= 1440).mean()),
    }])


defs = [
    ("A_maxshare_gt_0p5", "state_A"),
    ("B_maxshare_gt_0p5_and_pivot_eq_dominant", "state_B"),
    ("C_B_and_pivot_margin_norm_gt_0", "state_C"),
]

spell_tables = []
summary_tables = []

for def_name, state_col in defs:
    spells = extract_spells(df_valid, state_col, def_name)
    spell_tables.append(spells)
    summary_tables.append(summarize_spells(spells, len(df_valid), def_name))

spell_detail = pd.concat(spell_tables, ignore_index=True)
summary_all = pd.concat(summary_tables, ignore_index=True)

summary_main = (
    summary_all.set_index("definition")
    .reindex([
        "B_maxshare_gt_0p5_and_pivot_eq_dominant",
        "A_maxshare_gt_0p5",
        "C_B_and_pivot_margin_norm_gt_0",
    ])
    .reset_index()
)


# =========================================================
# 7) EXPORT
# =========================================================
def make_excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64tz_dtype(out[col]):
            out[col] = out[col].dt.tz_localize(None)
    return out


main_csv = OUT_DIR / "table_lockin_persistence_main_rebuilt.csv"
app_csv = OUT_DIR / "table_lockin_persistence_appendix_rebuilt.csv"
detail_csv = OUT_DIR / "lockin_spells_detail_rebuilt.csv"
minute_csv = OUT_DIR / "lockin_minute_panel_rebuilt.csv"
top10_csv = OUT_DIR / "top10_lockin_spells_rebuilt.csv"

main_xlsx = OUT_DIR / "table_lockin_persistence_main_rebuilt.xlsx"
app_xlsx = OUT_DIR / "table_lockin_persistence_appendix_rebuilt.xlsx"

summary_main.to_csv(main_csv, index=False, encoding="utf-8-sig")
summary_all.to_csv(app_csv, index=False, encoding="utf-8-sig")
spell_detail.to_csv(detail_csv, index=False, encoding="utf-8-sig")
df_valid.to_csv(minute_csv, index=False, encoding="utf-8-sig")

top10_B = (
    spell_detail.loc[spell_detail["definition"] == "B_maxshare_gt_0p5_and_pivot_eq_dominant"]
    .sort_values(["duration_min", "start_time"], ascending=[False, True])
    .head(10)
)
top10_B.to_csv(top10_csv, index=False, encoding="utf-8-sig")

with pd.ExcelWriter(main_xlsx, engine="openpyxl") as writer:
    make_excel_safe(summary_main).to_excel(writer, sheet_name="main", index=False)

with pd.ExcelWriter(app_xlsx, engine="openpyxl") as writer:
    make_excel_safe(summary_all).to_excel(writer, sheet_name="summary", index=False)
    make_excel_safe(spell_detail).to_excel(writer, sheet_name="spell_detail", index=False)
    make_excel_safe(top10_B).to_excel(writer, sheet_name="top10_B", index=False)

print(f"[INFO] Exported main_csv  = {main_csv}")
print(f"[INFO] Exported app_csv   = {app_csv}")
print(f"[INFO] Exported detail    = {detail_csv}")
print(f"[INFO] Exported minute    = {minute_csv}")
print(f"[INFO] Exported top10     = {top10_csv}")

# duration ranked plot
plot_spells = spell_detail.loc[spell_detail["definition"] == "B_maxshare_gt_0p5_and_pivot_eq_dominant"].copy()
if plot_spells.empty:
    plot_spells = spell_detail.loc[spell_detail["definition"] == "A_maxshare_gt_0p5"].copy()
    plot_title = "Observed concentration spell durations (A)"
else:
    plot_title = "Observed lock-in spell durations (B)"

if not plot_spells.empty:
    plot_spells = plot_spells.sort_values("duration_min", ascending=False).reset_index(drop=True)
    plot_spells["rank"] = np.arange(1, len(plot_spells) + 1)

    fig_path = OUT_DIR / "fig_lockin_spell_duration_distribution_rebuilt.png"
    plt.figure(figsize=(8, 5))
    plt.plot(plot_spells["rank"], plot_spells["duration_min"])
    plt.xlabel("Spell rank (longest to shortest)")
    plt.ylabel("Duration (minutes)")
    plt.title(plot_title)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=200)
    plt.close()
    print(f"[INFO] Exported fig = {fig_path}")

# runinfo
runinfo = OUT_DIR / "runinfo_rebuilt_lockin_persistence.txt"
with open(runinfo, "w", encoding="utf-8") as f:
    f.write("Rebuilt observed-market lock-in persistence\n")
    f.write("==========================================\n")
    f.write(f"weight_file = {weight_file}\n")
    f.write(f"panel_file = {panel_file}\n")
    f.write(f"DV_DIR = {DV_DIR}\n")
    f.write(f"valid_minutes = {len(df_valid)}\n")
    f.write(f"A_share = {df_valid['state_A'].mean():.6f}\n")
    f.write(f"B_share = {df_valid['state_B'].mean():.6f}\n")
    f.write(f"C_share = {df_valid['state_C'].mean():.6f}\n")
    f.write(f"dominant_mismatch_rate = {mismatch_rate}\n")

print(summary_main.to_string(index=False))

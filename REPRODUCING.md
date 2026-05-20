# Reproducing the Results

This document describes how to reproduce the paper outputs for:

**When Multi-Venue Benchmarks Become Effectively Concentrated: Evidence from Fragmented BTCUSD Markets**

The repository is designed as a replication and output archive. Large raw and intermediate data files are not stored in the repository. Users should obtain the raw data directly from Kaggle and generate the processed files locally.

---

## 1. Data source

Raw data source:

**Comprehensive BTCUSD 1m Data**  
https://www.kaggle.com/datasets/imranbukhari/comprehensive-btcusd-1m-data

Required venue files correspond to the seven BTCUSD venues used in the paper:

- Binance
- Bitfinex
- BitMEX
- Bitstamp
- Coinbase
- KuCoin
- OKX

The raw Kaggle files are not redistributed in this repository. Place the downloaded raw files in a local input directory before running the scripts.

---

## 2. Python environment

Install the project dependencies from the repository root:

```bash
pip install -r requirements.txt
```

The expected dependency set includes:

```text
numpy
pandas
matplotlib
openpyxl
scipy
mpmath
tqdm
numba
```

`openpyxl` is required for Excel input/output through pandas even when it is not explicitly imported in a script.

---

## 3. Local path convention

Most scripts were written for a local Windows working directory and use a `BASE_DIR` variable. The original local path used during development was:

```text
D:\cilck here\2代目
```

To reproduce the results on another machine, edit the `BASE_DIR` or equivalent root-path variable near the top of each script before running it.

Example:

```python
from pathlib import Path

BASE_DIR = Path(r"D:\cilck here\2代目")
```

Change it to your own local project directory, for example:

```python
from pathlib import Path

BASE_DIR = Path(r"C:\Users\YourName\btc_reference_price_work")
```

or:

```python
from pathlib import Path

BASE_DIR = Path(r"/Users/yourname/btc_reference_price_work")
```

The workflow does not require the exact original Windows path. It requires the same folder structure under the chosen local root.

---

## 4. Expected local folder structure

A typical local working directory should contain folders such as:

```text
<BASE_DIR>/
├─ raw/                         # downloaded Kaggle raw files, or your chosen raw-data folder
├─ dv_ready_2021_2022/           # generated venue-level price-volume files
├─ agg_ready/                    # generated aggregate benchmark prices
├─ experiments/                  # concentration and legacy robustness outputs
├─ experiments_dvonly/           # dollar-volume-only perturbation outputs
├─ hhi_panel/                    # merged concentration/price panel
├─ paper_outputs_frl/            # final paper figures, tables, and metadata
└─ scripts or source files        # local copies of the replication scripts
```

The exact raw-data input folder may differ across scripts. Check and edit the relevant input-path variables together with `BASE_DIR`.

---

## 5. Reproduction stages

The workflow is organized into four stages.

### Stage 1: Build venue-level price-volume inputs

Purpose: harmonize exchange-level BTCUSD minute data, align prices to a common BTCUSD scale, and construct dollar-volume proxies.

Representative script:

```text
make_dv_2021_2022.py
```

Expected output:

```text
dv_ready_2021_2022/BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv
```

These files contain synchronized time, scaled BTCUSD price, dollar-volume proxy, and volume-unit diagnostics.

---

### Stage 2: Build aggregate benchmark prices and concentration measures

Purpose: construct VWAP, LWMP, simple mean, simple median, total dollar volume, dominant venue, max share, and HHI measures.

Representative scripts:

```text
build_aggregated_prices.py
weight_concentration_check.py
build_hhi_trend_panel.py
```

Expected outputs include:

```text
agg_ready/btc_2021_2022_agg_prices.csv
agg_ready/agg_data_quality_report.xlsx
experiments/weight_concentration_minute_level.csv
hhi_panel/btc_1m_panel_with_hhi.csv
```

---

### Stage 3: Run mechanism and validation audits

Purpose: evaluate the aggregation-rule mechanisms documented in the paper.

Representative scripts include:

```text
run_dv_only_injection_experiments.py
rebuild_observed_lockin_persistence.py
audit_lockin_and_build_dvonly_inference.py
run_price_displacement_audit.py
robust_inference_ci_methods.py
```

Expected outputs include dollar-volume-only perturbation samples, LWMP lock-in audits, threshold validation outputs, year-subsample validation outputs, structural-exclusion outputs, and settlement pass-through diagnostics.

The main mechanisms are:

- VWAP: continuous dominant-venue exposure.
- LWMP: threshold-pivot lock-in once one venue exceeds half of total weight.
- Settlement audit: fixed-weight dominant-venue price-displacement pass-through.

---

### Stage 4: Generate paper tables and figures

Purpose: generate the final tables and figures used in the main text and appendix.

Representative scripts include:

```text
make_frl_figures_tables.py
make_fig4_by_delta.py
make_fig5_pass_through.py
make_fig6_dualaxis_exceed_vs_pt.py
make_fig7_concentration_metric_robustness.py
```

Expected output folders:

```text
paper_outputs_frl/
outputs/main_text/
outputs/appendix/
outputs/metadata/
```

The GitHub repository contains selected final outputs and metadata. Large intermediate files remain outside the repository.

---

## 6. Notes on BitMEX and volume-unit conventions

Public OHLCV files differ across venues in product conventions and volume units. The analysis treats the synchronized inputs as BTCUSD price-volume proxies for benchmark-mapping purposes. BitMEX is retained after volume-unit diagnostics and handled under the quote-or-contract dollar-volume convention rather than as a base-volume spot venue.

The replication workflow therefore studies aggregation-rule exposure in a harmonized benchmark-mapping panel. It does not claim to construct a regulated investable BTCUSD index.

---

## 7. What is not redistributed

The following objects are intentionally excluded from the repository:

- Raw Kaggle files.
- Large venue-level intermediate files.
- Large perturbation-event samples.
- Local working directories.
- Machine-specific cache files.

The `.gitignore` file excludes the large raw and intermediate folders used during local development.

---

## 8. Practical replication note

The scripts are written as transparent research scripts rather than a packaged Python library. The expected replication procedure is:

1. Download the raw Kaggle files.
2. Place them under your chosen local working directory.
3. Edit `BASE_DIR` and any raw-input path variables at the top of the relevant scripts.
4. Run the scripts in the stage order described above.
5. Compare generated outputs with the selected tables, figures, metadata, and run notes stored in this repository.

For exact paper-output provenance, consult the files under:

```text
docs/runinfo/
docs/diagnostics/
outputs/metadata/
```

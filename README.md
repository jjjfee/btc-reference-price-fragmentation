# When Multi-Venue Benchmarks Become Effectively Concentrated

## Evidence from Fragmented BTCUSD Markets

This repository accompanies the paper:

**When Multi-Venue Benchmarks Become Effectively Concentrated: Evidence from Fragmented BTCUSD Markets**

本仓库是该论文的复现与输出归档仓库。它用于整理论文相关代码、主文与附录输出、运行说明、诊断材料和外部数据说明。大型原始数据与大型中间文件不直接纳入本仓库。

---

## 1. Paper focus

The paper studies effective concentration in formally multi-venue BTCUSD benchmarks. A benchmark may include several venues in its input set while its realized exposure becomes concentrated when trading weights are concentrated.

The paper separates three objects:

1. **Venue coverage**: the exchanges included in the benchmark input set.
2. **Cross-venue price-weight state**: the observed venue-level prices and trading weights at each minute.
3. **Reference price**: the output produced by an aggregation rule.

The main claim is that trading concentration changes how a benchmark rule maps the cross-venue state into a reference price, even when the nominal venue set is unchanged.

The empirical application uses minute-level BTCUSD data from seven exchanges over 2021-2022. The analysis focuses on two rule-specific mechanisms:

- **VWAP**: continuous dominant-venue exposure. As the dominant venue's weight rises, the residual cross-venue component of VWAP becomes less influential.
- **LWMP**: threshold-pivot lock-in. Once a single venue carries more than half of total weight, it becomes the weighted-median pivot.

The design is a benchmark-mapping exercise. It does not estimate the full market-equilibrium effect of concentration. It holds observed venue prices fixed where appropriate and studies how aggregation rules convert observed prices and weights into benchmark outputs.

---

## 2. Data scope and convention

The raw data are obtained from the public Kaggle dataset:

**Comprehensive BTCUSD 1m Data**  
https://www.kaggle.com/datasets/imranbukhari/comprehensive-btcusd-1m-data

The raw Kaggle files are not redistributed in this repository. Users should obtain the raw files directly from Kaggle and then use the scripts and manifests in this repository to reproduce the processed panel and paper outputs.

The analysis uses synchronized BTCUSD price-volume inputs from:

- Binance
- Bitfinex
- BitMEX
- Bitstamp
- Coinbase
- KuCoin
- OKX

Because public OHLCV files differ in product conventions and volume units across venues, the synchronized inputs are treated as BTCUSD price-volume proxies for benchmark-mapping purposes. BitMEX is retained after volume-unit diagnostics and handled under the quote-or-contract dollar-volume convention rather than as a base-volume spot venue. The study is therefore a harmonized aggregation-rule exercise, not the construction of a regulated investable index.

All reported timestamps are handled in UTC.

---

## 3. Manuscript output map

### Main text

The current main text relies primarily on:

- **Table 1**: observed-market persistence of the over-half state.
- **LWMP evidence**: one-half boundary and pivot lock-in.
- **VWAP evidence**: supplementary perturbation-tail diagnostics consistent with continuous dominant-venue exposure.
- **Settlement implication**: fixed-weight dominant-venue price-displacement pass-through.

### Appendix

The appendix is organized as:

- **Appendix A**: definition, measurement, and threshold validation.
- **Appendix B**: year-based subsample validation.
- **Appendix C**: structural-exclusion validation.
- **Appendix D**: LWMP mechanism audit.
- **Appendix E**: supplementary VWAP evidence.
- **Appendix F**: observed-state validation of LWMP lock-in.
- **Appendix G**: settlement-use-case fixed-weight price-displacement audit.

---

## 4. Repository structure

```text
btc-reference-price-fragmentation/
├─ src/
│  ├─ build/          # data construction and panel-building scripts
│  ├─ experiments/    # benchmark perturbation and robustness scripts
│  ├─ audit/          # mechanism audits and validation checks
│  └─ plotting/       # paper figure/table generation scripts
├─ scripts/           # execution helpers and final-run scripts
├─ outputs/
│  ├─ main_text/      # figures and tables used in the main text
│  ├─ appendix/       # appendix figures and tables
│  └─ metadata/       # output metadata and provenance notes
├─ docs/
│  ├─ runinfo/        # run logs and configuration notes
│  └─ diagnostics/    # diagnostic summaries
├─ data/
│  └─ external/
│     └─ manifests/   # source-data manifests; raw data are not redistributed
└─ archive/           # exploratory, duplicate, or deprecated scripts
```

Files under `archive/` are retained for transparency and development history. They are not part of the final replication path unless explicitly referenced by a run note.

---

## 5. Python environment

Install the minimal Python dependencies from:

```bash
pip install -r requirements.txt
```

The expected core dependencies are:

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

`openpyxl` is required for Excel input/output through pandas, even when it is not explicitly imported in individual scripts.

---

## 6. Reproduction logic

The full workflow has four stages:

1. **Prepare venue-level inputs**  
   Harmonize exchange-level BTCUSD minute data and construct dollar-volume proxies.

2. **Build benchmark panels**  
   Construct VWAP, LWMP, concentration measures, dominant-venue shares, and related panel variables.

3. **Run mechanism and validation audits**  
   Execute the dollar-volume-only perturbation exercises, observed-state validation, structural-exclusion checks, and settlement pass-through audit.

4. **Generate paper outputs**  
   Create the tables and figures used in the main text and appendix.

Large processed files are not stored directly in this repository. The manifests and run notes describe how those files are generated and where they enter the workflow.

---

## 7. Data and output policy

- Raw Kaggle files are not redistributed.
- Large intermediate files are excluded from the repository.
- Selected final tables, figures, metadata, and run notes are retained for transparency.
- Source-data manifests document the external data inputs and access information.
- The code is intended to support replication of the paper's benchmark-mapping results, not to provide production benchmark infrastructure.

---

## 8. License and citation

The code in this repository is released under the MIT License. See `LICENSE`.

Citation metadata are provided in `CITATION.cff`. If you use this repository, cite the accompanying paper and this code archive.

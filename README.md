# When Multi-Venue Benchmarks Become Effectively Concentrated: Evidence from Fragmented BTCUSD Markets

This repository contains code, selected outputs, data-source manifests, and validation reports for the current Economics Letters submission. The manuscript is submitted; it is not described here as accepted or published.

## Research question and contribution

The paper asks when a formally multi-venue price benchmark becomes effectively concentrated because trading weight is concentrated. It is a benchmark-mapping exercise: synchronized public price-volume observations are mapped through two aggregation rules, not proposed as a regulated or investable index.

- A volume-weighted average price (VWAP) has continuous exposure to every venue price. Holding weights fixed, the dominant venue's pass-through is its weight.
- A liquidity-weighted median price (LWMP) has a threshold-pivot mechanism. Once one valid venue has more than half of synchronized weight, that venue must be the weighted-median pivot; small weight perturbations may therefore leave the pivot unchanged.

## Main BTCUSD sample

The baseline panel contains one-minute UTC observations for Binance, Bitfinex, BitMEX, Bitstamp, Coinbase, KuCoin, and OKX from 2021-01-01 through 2022-12-31. A minute is valid with at least three finite, positive-weight venues.

| Quantity | Current value |
|---|---:|
| Valid minutes | 1,050,207 |
| All-seven-valid minutes | 1,008,835 |
| Over-half share, pooled valid sample | 55.4973% |
| Over-half share, all-seven-valid sample | 54.5047% |
| Longest pooled over-half spell | 2,982 minutes |

The weights are synchronized price-volume proxy shares. Venue source conventions differ. Base-volume venues use venue price times volume; BitMEX is retained under the audited quote-or-contract dollar-volume convention. The handling is recorded in `data/external/manifests/kaggle_btcusd_manifest.md` and the committed reviewer-check input manifest.

## Pooled DV-only design and headline result

The design samples 100,000 valid minutes without replacement using seed 42. At each minute it selects one valid venue uniformly; that venue is held fixed across two shock types and four magnitudes. This produces 100,000 × 8 = 800,000 equally weighted events. Positive total-preserving shocks are capped at feasibility boundaries rather than rejected.

| Event-level quantity | Exact value |
|---|---:|
| Non-majority pivot-change rate | 0.27927641929248886 |
| Majority pivot-change rate | 0.06767736821244551 |
| Majority minus non-majority | -0.21159905108004334 |
| Rate ratio | 0.24233112263433296 |

The committed source table is `outputs/main_text/tables/headline_pivot_change_rates.csv`. Event construction is documented by `outputs/reviewer_checks/btc_fixed_composition/metadata/btc_event_formula_manifest.md` and Appendix L.

## Fixed composition and structural exclusion

Restricting to the 1,008,835 all-seven-valid minutes gives an over-half share of 0.5450465140483826, pivot-change rates of 0.27671179480422514 and 0.06934753869599544, a difference of -0.2073642561082297, and a maximum spell of 787 minutes. The seed-42 block intervals for that difference are:

- one-day: [-0.2124239332905306, -0.2023178773660607]
- seven-day: [-0.21658581040289163, -0.19744025986563804]

The six-base-volume specification excludes BitMEX and requires all six remaining venues to be valid. Its over-half share is 0.7772763516302911; its pivot-change rates are 0.2660623267459537 and 0.0615629105804158, for a difference of -0.2044994161655379. These are robustness checks, not replacements for the paper's baseline definition.

## Other validations

- The BTCUSD post-2022 replication contains 1,460,823 valid minutes, an over-half share of 0.5865926262113891, and a pivot-change difference of -0.1858240971334107.
- The matched 2021–2022 ETHUSD replication has an over-half share of 0.709308409436834 and a pivot-change difference of -0.16147078883213373.
- Targeted ETH exclusions, leave-one-exchange-out results, fixed-weight price-displacement results, and their audit reports are under `outputs/robustness/`.
- The baseline dependence-robust summaries under `outputs/robustness/bootstrap_1day/` and `outputs/robustness/bootstrap_7day/` use seed 20260710. Appendix L's all-seven intervals above use its documented seed-42 rerun; both provenance records are retained rather than conflated.
- The BTC fixed-composition gate reports exactly 29 PASS / 0 WARN / 0 FAIL in `outputs/reviewer_checks/btc_fixed_composition/metadata/validation_checks.csv`.

## Appendix A–L map

| Appendix | Topic | Repository location |
|---|---|---|
| A | Perturbation and classification sensitivity | `outputs/appendix/A/` |
| B | Subsample and temporal-dependence validation | `outputs/appendix/B/`, `outputs/robustness/bootstrap_1day/`, `outputs/robustness/bootstrap_7day/` |
| C | Structural-exclusion validation | `outputs/appendix/C/` |
| D | LWMP majority-pivot guarantee | `outputs/appendix/D/` |
| E | Supplementary VWAP evidence | `outputs/appendix/E/` |
| F | Majority-state implementation consistency | `outputs/appendix/F/` |
| G | Fixed-weight dominant-price displacement | `outputs/appendix/G/` |
| H | Leave-one-exchange-out validation | `outputs/robustness/leave_one_exchange_out/` |
| I | BTCUSD post-2022 replication | `outputs/robustness/btc_post2022/` |
| J | Matched ETHUSD replication | `outputs/robustness/eth_matched/` |
| K | ETHUSD targeted venue exclusions | `outputs/robustness/eth_exclude_binance/` |
| L | Event construction and fixed-composition BTC checks | `outputs/reviewer_checks/btc_fixed_composition/` |

See `OUTPUT_MANIFEST.md`, `docs/runinfo/appendix_code_map.md`, and `outputs/metadata/output_manifest.json` for script- and file-level mappings.

## Data download and redistribution

The raw BTCUSD and ETHUSD data must be downloaded directly from Kaggle. They are not redistributed here:

- [Comprehensive BTCUSD 1m Data](https://www.kaggle.com/datasets/imranbukhari/comprehensive-btcusd-1m-data)
- [Ethereum ETH, 7 Exchanges, 1m Full Historical Data](https://www.kaggle.com/datasets/imranbukhari/comprehensive-ethusd-1m-data/data)

Expected filenames, columns, sample dates, access dates, conventions, available hashes, and downstream generators are recorded in `data/external/manifests/kaggle_btcusd_manifest.md` and `data/external/manifests/kaggle_ethusd_manifest.md`. Create the untracked raw-data directories described there after download.

## Environment

Python 3.10 or newer is recommended. From the repository root:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Core numerical work uses NumPy and pandas; plotting and PDF output additionally use Matplotlib, Pillow, and ReportLab. Parquet input uses PyArrow.

## Recommended execution order

1. Download and verify the external files using the two source-data manifests.
2. Build venue-level BTC inputs with `src/build/make_dv_2021_2022.py`; then build aggregate and concentration panels with the remaining scripts under `src/build/`.
3. Generate the baseline DV-only events with `src/experiments/run_dv_only_injection_experiments.py` and audit them with `src/audit/audit_lockin_and_build_dvonly_inference.py`.
4. Run the one-day and seven-day block bootstrap with `src/experiments/run_day_block_bootstrap.py`.
5. Run `src/audit/run_btc_fixed_composition_checks.py` for the exact headline gate, all-seven-valid results, six-base-volume exclusion, and reviewer checks.
6. Run the Appendix H–K entry points under `src/audit/` and `src/experiments/` if the corresponding external raw or processed data are available.
7. Validate committed artifacts with `scripts/final/validate_selected_outputs.py`.

Exact commands, inputs, outputs, seeds, and troubleshooting are in `REPLICATION.md`.

## Reproducibility scope and cost

The exact-value validator and `--help` checks run directly from a clone and use only committed files. Figure/table summaries and reports are also provided. Raw-to-panel builds and event-level experiments depend on external files totaling multiple gigabytes and can require substantial memory, disk, and compute; they are not one-click lightweight tests. Large raw files, venue panels, merged event samples, and bootstrap draws are intentionally omitted and ignored. The repository preserves their source and run metadata instead.

## Known limitations

- Public OHLCV product and volume conventions are heterogeneous; results should be interpreted as a harmonized benchmark-mapping exercise.
- The submitted manuscript reports rounded values; committed CSVs retain available precision.
- Appendix B's baseline block-bootstrap run and Appendix L's fixed-composition rerun use different documented seeds. Their close but non-identical intervals should not be treated as the same run.
- Saved VWAP tail summaries arise from related but not identical constructions; labels and manifests identify the relevant construction.
- Full reproduction requires third-party data availability and adequate local resources.

## License and citation

Code and repository materials are released under the MIT License in `LICENSE`. Citation metadata are in `CITATION.cff`. No DOI or journal-publication claim is made.

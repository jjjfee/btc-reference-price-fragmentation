# Output manifest

This manifest maps the paper and online Appendix A–L to the committed code and selected artifacts. Raw files, processed venue panels, and event-level samples are external by design. The machine-readable equivalent is `outputs/metadata/output_manifest.json`.

## Main text

| Paper object | Generator or audit | Principal input | Committed artifact |
|---|---|---|---|
| Figure 1: Liquidity-Weighted Median Price (LWMP) one-half boundary | `src/experiments/run_dv_only_injection_experiments.py`; `src/plotting/plot_lwmp_boundary_single_gamma_maintext.py` | external processed BTC venue panel and DV-only events | `outputs/main_text/figures/Fig_LWMP_boundary_single_gamma1_inflate_only.png` |
| Figure 2: observed VWAP proximity | `src/plotting/plot_vwap_head_proximity_vs_maxshare.py` | external synchronized BTC price/weight panel | `outputs/main_text/figures/Fig_vwap_head_proximity_q95_by_maxshare.png` |
| Table 1: persistence of the over-half state | `src/audit/rebuild_observed_lockin_persistence.py` | external BTC concentration panel | `outputs/main_text/tables/table_lockin_persistence_main_rebuilt.csv` and `.xlsx` |
| Headline pivot-change rates | `src/experiments/run_dv_only_injection_experiments.py`; `src/audit/audit_lockin_and_build_dvonly_inference.py` | external 800,000-row DV-only event sample | `outputs/main_text/tables/headline_pivot_change_rates.csv` |

## Online appendix

| Appendix | Subject | Supported by | Selected outputs |
|---|---|---|---|
| A | Perturbation and classification sensitivity | `src/audit/run_threshold_robustness.py` | `outputs/appendix/A/` |
| B | Subsamples and temporal dependence | `src/audit/run_subsample_robustness.py`; `src/experiments/run_day_block_bootstrap.py` | `outputs/appendix/B/`; `outputs/robustness/bootstrap_1day/`; `outputs/robustness/bootstrap_7day/` |
| C | Structural exclusion | `src/audit/run_exclude_binance.py`; `src/audit/summarize_exclude_binance.py` | `outputs/appendix/C/` |
| D | LWMP majority-pivot guarantee | `src/audit/audit_lockin_and_build_dvonly_inference.py` | `outputs/appendix/D/` |
| E | Supplementary VWAP evidence | `src/audit/make_vwap_degradation_bins_maxshare.py`; `src/audit/plot_vwap_tail_by_maxshare_lambda.py` | `outputs/appendix/E/` |
| F | Majority-state implementation consistency | `src/audit/rebuild_observed_lockin_persistence.py` | `outputs/appendix/F/` |
| G | Fixed-weight price displacement | `src/audit/run_price_displacement_audit.py` | `outputs/appendix/G/`; run metadata in `outputs/robustness/price_displacement/` |
| H | Leave-one-exchange-out validation | `src/audit/run_leave_one_exchange_out_validation.py` | `outputs/robustness/leave_one_exchange_out/` |
| I | BTCUSD post-2022 replication | `src/experiments/run_btc_post2022_replication.py` | `outputs/robustness/btc_post2022/` |
| J | Matched ETHUSD replication | `src/experiments/run_eth_replication.py` | `outputs/robustness/eth_matched/` |
| K | ETHUSD targeted venue exclusions | `src/experiments/run_eth_exclude_binance.py` | `outputs/robustness/eth_matched/results/eth_targeted_exclusion_summary.csv`; `outputs/robustness/eth_exclude_binance/` |
| L | Event construction and fixed-composition BTC checks | `src/experiments/run_dv_only_injection_experiments.py`; `src/audit/run_btc_fixed_composition_checks.py` | `outputs/reviewer_checks/btc_fixed_composition/` |

Each directory retains its available summaries, figures, run manifests, validation checks, and reports. The JSON manifest enumerates every path used by the automated existence check.

# Appendix Code Map

This file maps the confirmed Appendix A-G paper tables and figures to the repository scripts copied under `src/audit/`.

## Appendix A

- Tables/figures: Figure A1, Figure A2, Table A1
- Script: `src/audit/run_threshold_robustness.py`
- Inputs: `experiments_dvonly/audit_lockin/dvonly_inference_dataset.csv`
- Outputs: `threshold_robustness_summary.csv`; `Fig_share_lockin_vs_threshold__{metric}.png`; `Fig_thr_robust__metric_{metric}__shock_{shock}__lockin_{0/1}.png`
- Variables/functions: `parse_thresholds`, `summarize_for_threshold`, `plot_share_lockin`, `plot_rate_vs_threshold`, `lock_in`, `pivot_changed_rate`, `shock_col`, `gamma_col`
- Reproduction status: fully matched

## Appendix B

- Tables/figures: Figure B1, Table B1
- Script: `src/audit/run_subsample_robustness.py`
- Inputs: `experiments_dvonly/dvon_injection_shift_samples.csv`; `hhi_panel/btc_1m_panel_with_hhi.csv`
- Outputs: `subsample_robustness_summary__metric_{metric}__thr_{threshold}__scheme_{scheme}.csv`; `figs/Fig_subsample__metric_{metric}__scheme_{scheme}__shock_{shock}__lockin_{0/1}.png`
- Variables/functions: `subsample_label`, `scheme="year"`, `load_panel`, `lock_in`, `pivot_changed`, `pivot_changed_rate`, `wilson_ci`, `plot_summary`
- Reproduction status: fully matched

## Appendix C

- Tables/figures: Table C1
- Scripts: `src/audit/run_exclude_binance.py`; `src/audit/summarize_exclude_binance.py`
- Inputs: `dv_ready_2021_2022/BTCUSD_1m_*_2021_2022_with_DV.csv`; `experiments_dvonly/exclude_binance/dvon_injection_shift_samples__exclude_Binance.csv`
- Outputs: `dvon_injection_shift_samples__exclude_Binance.csv`; `base_minute_metrics__exclude_Binance.csv`; `exclude_binance_summary_main.csv/.xlsx`; `exclude_binance_summary_by_exchange.csv/.xlsx`; `exclude_binance_summary_overall.csv/.xlsx`
- Variables/functions: `--exclude Binance`, `exch_order`, `compute_concentration_metrics`, `pivot_changed`, `shift_lwmp`, `shift_vwap`, `build_summary`, `BASENAME`
- Reproduction status: partially matched. The structural-exclusion simulation and summary are present; `summarize_exclude_binance.py` now defaults to the excluded-Binance event file name.

## Appendix D

- Tables/figures: Table D1, Figure D1-D3
- Script: `src/audit/audit_lockin_and_build_dvonly_inference.py`
- Inputs: `experiments_dvonly/dvon_injection_shift_samples.csv`; `hhi_panel/btc_1m_panel_with_hhi.csv`; optional fallback `experiments/weight_concentration_minute_level.csv`
- Outputs: `audit_lockin_summary.csv`; `audit_lockin_bins.csv`; `dvonly_inference_dataset.csv`; `Fig_lockin_pivot_is_dominant_rate_by_maxshare.png`; `Fig_lockin_margin_gap_hist.png`; `Fig_lockin_margin_gap_vs_maxshare.png`
- Variables/functions: `LOCKIN_THRESHOLD`, `pivot_is_dominant_before`, `pivot_is_dominant_after`, `gap_norm`, `pivot_changed_rate`, `make_quantile_edges`, `wilson_ci`
- Reproduction status: fully matched

## Appendix E

- Tables/figures: Figure E1, Table E1, Figure E2
- Scripts: `src/audit/plot_vwap_tail_by_maxshare_lambda.py`; `src/audit/make_vwap_degradation_bins_maxshare.py`; `src/audit/plot_vwap_head_proximity_vs_maxshare.py`
- Inputs: `experiments_dvonly/dvon_injection_shift_samples.csv`; `hhi_panel/btc_1m_panel_with_hhi.csv`; `agg_ready/btc_2021_2022_agg_prices.csv`; `dv_ready_2021_2022/BTCUSD_1m_<EX>_2021_2022_with_DV.csv`
- Outputs: `Table_VWAP_tail_over_lambda_by_maxshare_quintile.csv`; `Fig_VWAP_p90_p95_p99_absShift_over_lambda_by_maxshare_quintile.png`; `Fig_VWAP_p90_p95_p99_absShift_by_maxshare_quintile.png`; `vwap_degradation_curve_bins_maxshare_delta1p0.csv`; `Fig_vwap_degradation_q95abs_by_maxshare_delta1p0.png`; `vwap_head_proximity_bins_maxshare.csv`; `Fig_vwap_head_proximity_q95_by_maxshare.png`
- Variables/functions: `QUANTILES`, `compute_lambda_row`, `lambda_eff`, `abs_shift_over_lambda`, `Q_LEVEL`, `shift_vwap`, `q95_rel_gap_dom`, `bootstrap_quantile_ci`
- Reproduction status: partially matched. VWAP tail, q95/q99, degradation, and dominant-venue proximity are implemented; no exact `residual cross-venue` named implementation was found.

## Appendix F

- Tables/figures: Table F1
- Script: `src/audit/rebuild_observed_lockin_persistence.py`
- Inputs: discovered `weight_concentration_minute_level` table; `hhi_panel/btc_1m_panel_with_hhi.csv`; `dv_ready_2021_2022/*with_DV*`
- Outputs: `table_lockin_persistence_main_rebuilt.csv/.xlsx`; `table_lockin_persistence_appendix_rebuilt.csv/.xlsx`; `lockin_spells_detail_rebuilt.csv`; `lockin_minute_panel_rebuilt.csv`; `fig_lockin_spell_duration_distribution_rebuilt.png`
- Variables/functions: `state_A`, `state_B`, `state_C`, `extract_spells`, `summarize_spells`, `duration_min`, `pivot_margin_norm`, `pivot_is_dominant_rebuilt`
- Reproduction status: fully matched

## Appendix G

- Tables/figures: Table G1
- Script: `src/audit/run_price_displacement_audit.py`
- Inputs: `dv_ready_2021_2022/BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv`
- Outputs: `summary_by_state_lambda.csv`; `quantiles_by_state_lambda.csv`; `sanity_checks_by_lambda.csv`; `base_minute_state_for_price_displacement_audit.csv.gz`; optional `price_displacement_audit_events_lambda_*.csv.gz`; `ECDF_kappa_LWMP_lambda_*.png`; `ECDF_kappa_VWAP_lambda_*.png`
- Variables/functions: `dominant_exchange`, `p_dom`, `prices_prime`, `lambda`, `delta_VWAP`, `delta_LWMP`, `kappa_VWAP`, `kappa_LWMP`, `state`, `compute_vwap`, `weighted_median_batch`
- Reproduction status: fully matched

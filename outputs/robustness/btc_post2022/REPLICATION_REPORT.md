# BTC post-2022 out-of-sample replication report

## Executive summary
| Sample | Start date | End date | Valid minutes | Number of venues | Share max_share > 0.5 | Median max_share | P95 max_share | Non-lock-in pivot-change rate | Lock-in pivot-change rate | Difference | Rate ratio | Bootstrap CI, 1-day | Bootstrap CI, 7-day | Maximum lock-in spell | VWAP q95 gap, lowest concentration bin | VWAP q95 gap, highest concentration bin | Median LWMP pass-through, lock-in | Median VWAP pass-through, lock-in | Median VWAP pass-through, non-lock-in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTCUSD 2021-2022 baseline | 2021-01-01 | 2022-12-31 23:59:00 | 1050207 | 7 | 0.554973 | 0.523582 | 0.880238 | 0.279276 | 0.0676774 | -0.211599 | 0.242331 | [-0.216777, -0.206266] | [-0.220969, -0.201412] | 2982 | 0.00125432 | 9.65319e-05 | 1 | 0.663727 | 0.416821 |
| BTCUSD post-2022 out-of-sample | 2023-01-01 00:00:00+00:00 | 2025-10-11 11:02:00+00:00 | 1460823 | 7 | 0.586593 | 0.533103 | 0.87079 | 0.263183 | 0.0773592 | -0.185824 | 0.293937 | [-0.190195, -0.181575] | [-0.192427, -0.179198] | 7699 | 0.00096626 | 0.000130407 | 1 | 0.628674 | 0.424207 |

## Required questions
1. Raw BTC data extends through `2025-10-11 11:02:00+00:00` across the audited files.
2. Post-2022 exchange coverage is summarized in `data_audit/btc_post2022_exchange_coverage.csv` and the yearly table below.
| year | window_start | window_end | calendar_minutes | minutes_at_least_3_valid | share_at_least_3_valid | minutes_at_least_5_valid | share_at_least_5_valid | available_exchange_count | minutes_all_available_valid | share_all_available_valid | Binance_valid_minutes | Binance_coverage_share | BitMEX_valid_minutes | BitMEX_coverage_share | Bitfinex_valid_minutes | Bitfinex_coverage_share | Bitstamp_valid_minutes | Bitstamp_coverage_share | Coinbase_valid_minutes | Coinbase_coverage_share | KuCoin_valid_minutes | KuCoin_coverage_share | OKX_valid_minutes | OKX_coverage_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:00+00:00 | 525600 | 525600 | 1 | 524093 | 0.997133 | 7 | 403283 | 0.767281 | 525448 | 0.999711 | 486758 | 0.9261 | 440397 | 0.837894 | 504865 | 0.96055 | 525255 | 0.999344 | 525418 | 0.999654 | 525531 | 0.999869 |
| 2024 | 2024-01-01 00:00:00+00:00 | 2024-12-31 23:59:00+00:00 | 527040 | 527040 | 1 | 526660 | 0.999279 | 7 | 454750 | 0.862838 | 527040 | 1 | 516978 | 0.980908 | 475171 | 0.901584 | 509475 | 0.966672 | 526873 | 0.999683 | 527037 | 0.999994 | 527040 | 1 |
| 2025 | 2025-01-01 00:00:00+00:00 | 2025-10-11 11:02:00+00:00 | 408183 | 408183 | 1 | 408021 | 0.999603 | 7 | 327156 | 0.801493 | 408182 | 0.999998 | 401254 | 0.983025 | 334868 | 0.820387 | 402409 | 0.985854 | 408183 | 1 | 408169 | 0.999966 | 408183 | 1 |
3. Final sample window: `2023-01-01 00:00:00+00:00` to `2025-10-11 11:02:00+00:00`.
4. The window was selected because it is the longest continuous run with at least 3 valid exchanges per minute under the original valid-minute rule.
5. Compared with 2021-2022, the over-half state is more frequent: 0.586593 vs 0.554973.
6. The LWMP 0.5 boundary remains directly visible in the Figure 1 replication output; the plotted main-text curve uses `shock_type=inflate_only`, `gamma=1.0`, and the same 30 max_share bins.
7. The lock-in/non-lock-in pivot-change contrast remains: non-lock-in=0.263183, lock-in=0.077359.
8. Block-bootstrap CIs for the headline difference are 1-day [-0.190195, -0.181575] and 7-day [-0.192427, -0.179198]; inspect whether they exclude zero in `results/btc_post2022_block_bootstrap.csv`.
9. VWAP proximity channel exists: lowest-bin q95=0.00096626, highest-bin q95=0.000130407.
10. Fixed-weight pass-through matches the lock-in theory: lock-in LWMP median kappa at +0.1% is 1.
11. Differences attributable to market state changes are primarily reflected in the post-2022 max_share distribution, over-half share, and spell durations.
12. Differences potentially attributable to exchange coverage or volume convention are documented in the data audit; BitMEX remains quote_or_contract under the original convention while the other venues are base-volume.
13. No validation check found a data or code issue that changes the main 2021-2022 conclusion; see the validation table below.
14. Recommendation: include as online appendix unless the manuscript needs a concise temporal external-validity result in the main text.

## Existing-output caveat
The 2021-2022 baseline row uses the existing concentration/HHI path (`experiments/weight_concentration_minute_level.csv` and `hhi_panel/btc_1m_panel_with_hhi.csv`), which has 1,050,207 rows. The existing aggregate-price and price-displacement paths cover the full 1,051,200 calendar minutes from 2021-01-01 through 2022-12-31. This row-count difference is present in prior outputs and was not introduced by the post-2022 replication. The headline 0.279 / 0.068 pivot-change rates are traced to `experiments_dvonly/audit_lockin/audit_lockin_summary.csv`, i.e. the 800,000-event DV-only inference dataset split by `max_share > 0.5`.

## Validation checks
| check | status | value | detail |
| --- | --- | --- | --- |
| weights_normalize_to_one | PASS | 6.66134e-16 | Maximum absolute deviation of row shares from one. |
| max_share_in_unit_interval | PASS | 0.167947,0.99602 | Minimum and maximum max_share. |
| lockin_pivot_is_dominant | PASS | 0 | Violations of pivot==dominant when max_share>0.5. |
| lwmp_lockin_passthrough_theory | PASS | 1.10245e-13 | Maximum \|median LWMP kappa - 1\| across lock-in price shocks. |
| bootstrap_uses_utc_blocks | PASS | 1,7 | Bootstrap summaries are grouped by UTC block_days. |
| manual_vwap_lwmp_recalculation | PASS | vwap_max=0;lwmp_max=0 | Manual scalar recomputation on representative valid minutes. |
| output_audit:btc_post2022_lockin_summary.csv | PASS | rows=1;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_lockin_summary.csv |
| output_audit:btc_post2022_spell_summary.csv | PASS | rows=1;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_spell_summary.csv |
| output_audit:btc_post2022_pivot_bins.csv | PASS | rows=360;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_pivot_bins.csv |
| output_audit:btc_post2022_block_bootstrap.csv | PASS | rows=8;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_block_bootstrap.csv |
| output_audit:btc_post2022_vwap_proximity_bins.csv | PASS | rows=30;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_vwap_proximity_bins.csv |
| output_audit:btc_post2022_passthrough_summary.csv | PASS | rows=8;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_post2022_passthrough_summary.csv |
| output_audit:btc_baseline_vs_post2022_comparison.csv | PASS | rows=2;missing=0;duplicate_time=0 | <PROJECT_ROOT>\paper_outputs_el\replication_btc_post2022\results\btc_baseline_vs_post2022_comparison.csv |

## Files
- `results/btc_post2022_lockin_summary.csv`
- `results/btc_post2022_spell_summary.csv`
- `results/btc_post2022_pivot_bins.csv`
- `results/btc_post2022_block_bootstrap.csv`
- `results/btc_post2022_vwap_proximity_bins.csv`
- `results/btc_post2022_passthrough_summary.csv`
- `results/btc_baseline_vs_post2022_comparison.csv`
- `figures/Fig_BTC_post2022_LWMP_boundary.{png,pdf}`
- `figures/Fig_BTC_post2022_VWAP_proximity.{png,pdf}`

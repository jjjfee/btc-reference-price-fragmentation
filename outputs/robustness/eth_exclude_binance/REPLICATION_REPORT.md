# ETH exclude-Binance robustness report

## Sample
- Included venues: BitMEX, Bitfinex, Bitstamp, Coinbase, KuCoin, OKX
- Excluded files: ETHUSD_1m_Binance.csv; ETHUSD_1m_Combined_Index.csv
- Matched sample: 2021-01-01 00:00:00+00:00 to 2022-12-31 23:59:00+00:00

## Coverage
| exchange | matched_valid_minutes | matched_coverage_share | price_median |
| --- | --- | --- | --- |
| BitMEX | 1028064 | 0.977991 | 1755.9 |
| Bitfinex | 1042312 | 0.991545 | 1217.75 |
| Bitstamp | 968061 | 0.92091 | 1582.95 |
| Coinbase | 1051070 | 0.999876 | 1320.71 |
| KuCoin | 1050018 | 0.998876 | 1730.76 |
| OKX | 1049330 | 0.998221 | 1636.79 |

## Dominant Distribution
| dominant_exchange | minutes | share |
| --- | --- | --- |
| BitMEX | 104 | 9.89347e-05 |
| Bitfinex | 37967 | 0.0361178 |
| Bitstamp | 16836 | 0.016016 |
| Coinbase | 746825 | 0.710451 |
| KuCoin | 112541 | 0.10706 |
| OKX | 136925 | 0.130256 |

## Concentration
| valid_minutes | venue_count | median_max_share | p95_max_share | p99_max_share | share_max_share_gt_0p5 | share_max_share_gt_0p4 | share_max_share_gt_0p3 | median_HHI | p95_HHI | over_half_spell_count | spell_duration_median | spell_duration_p95 | spell_duration_p99 | max_spell_minutes | spells_ge_60_minutes | spells_ge_360_minutes | spells_ge_1440_minutes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1051198 | 6 | 0.527257 | 0.829346 | 0.920638 | 0.568681 | 0.836502 | 0.988788 | 0.385317 | 0.702094 | 198995 | 2 | 9 | 21 | 524 | 256 | 1 | 0 |

## LWMP Headline
| non_lockin_pivot_change_rate | lockin_pivot_change_rate | difference_lockin_minus_nonlockin | rate_ratio_lockin_over_nonlockin | n_non_lockin_events | n_lockin_events | n_events |
| --- | --- | --- | --- | --- | --- | --- |
| 0.286682 | 0.112072 | -0.174609 | 0.39093 | 345160 | 454840 | 800000 |

## Bootstrap
| block_days | statistic | point_estimate | bootstrap_mean | bootstrap_se | ci95_low | ci95_high | reps_completed | seed | n_blocks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | rate_nonlock | 0.286682 | 0.286686 | 0.00190982 | 0.28296 | 0.29053 | 5000 | 20260712 | 730 |
| 1 | rate_lock | 0.112072 | 0.112103 | 0.00142847 | 0.109379 | 0.114909 | 5000 | 20260712 | 730 |
| 1 | difference_lock_minus_nonlock | -0.174609 | -0.174582 | 0.00232387 | -0.179164 | -0.170102 | 5000 | 20260712 | 730 |
| 1 | ratio_lock_over_nonlock | 0.39093 | 0.391048 | 0.00549799 | 0.380279 | 0.401826 | 5000 | 20260712 | 730 |
| 7 | rate_nonlock | 0.286682 | 0.286678 | 0.00229225 | 0.282243 | 0.291354 | 5000 | 20260712 | 105 |
| 7 | rate_lock | 0.112072 | 0.112116 | 0.00292699 | 0.106456 | 0.117974 | 5000 | 20260712 | 105 |
| 7 | difference_lock_minus_nonlock | -0.174609 | -0.174562 | 0.00365351 | -0.181781 | -0.16734 | 5000 | 20260712 | 105 |
| 7 | ratio_lock_over_nonlock | 0.39093 | 0.391109 | 0.0105711 | 0.370522 | 0.412309 | 5000 | 20260712 | 105 |

## VWAP Proximity
| bin_id | x_left | x_right | x_center | n | q95_rel_gap_dom | ci_low | ci_high | median_rel_gap_dom |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.203 | 0.329 | 0.266 | 35040 | 0.00105281 | 0.00103643 | 0.00108683 | 0.000262263 |
| 1 | 0.329 | 0.353 | 0.341 | 35040 | 0.00095497 | 0.000928697 | 0.000963057 | 0.000245713 |
| 2 | 0.353 | 0.372 | 0.3625 | 35040 | 0.000941462 | 0.000927761 | 0.000966859 | 0.000233674 |
| 3 | 0.372 | 0.387 | 0.3795 | 35040 | 0.000911689 | 0.000887411 | 0.000929709 | 0.000230515 |
| 4 | 0.387 | 0.401 | 0.394 | 35040 | 0.000894346 | 0.000880384 | 0.00091906 | 0.000221396 |
| 5 | 0.401 | 0.415 | 0.408 | 35040 | 0.000871592 | 0.000851019 | 0.000891479 | 0.000215588 |
| 6 | 0.415 | 0.427 | 0.421 | 35040 | 0.000843954 | 0.00082944 | 0.000860822 | 0.000208492 |
| 7 | 0.427 | 0.44 | 0.4335 | 35040 | 0.00083176 | 0.000812574 | 0.000848703 | 0.000204811 |
| 8 | 0.44 | 0.452 | 0.446 | 35040 | 0.00081597 | 0.000801873 | 0.000838278 | 0.000197699 |
| 9 | 0.452 | 0.464 | 0.458 | 35039 | 0.000797584 | 0.000772713 | 0.000808265 | 0.000190792 |
| 10 | 0.464 | 0.476 | 0.47 | 35040 | 0.000772947 | 0.000760169 | 0.000789258 | 0.000188478 |
| 11 | 0.476 | 0.488 | 0.482 | 35040 | 0.00076035 | 0.000733456 | 0.000772193 | 0.000178974 |
| 12 | 0.488 | 0.501 | 0.4945 | 35040 | 0.000728892 | 0.000712026 | 0.000744713 | 0.000173943 |
| 13 | 0.501 | 0.514 | 0.5075 | 35040 | 0.000718304 | 0.000699919 | 0.0007334 | 0.000165748 |
| 14 | 0.514 | 0.527 | 0.5205 | 35040 | 0.000699971 | 0.000685351 | 0.000716576 | 0.000163217 |
| 15 | 0.527 | 0.541 | 0.534 | 35040 | 0.000671951 | 0.000661962 | 0.000690224 | 0.000156644 |
| 16 | 0.541 | 0.556 | 0.5485 | 35040 | 0.000668292 | 0.000654625 | 0.000686078 | 0.000151314 |
| 17 | 0.556 | 0.571 | 0.5635 | 35040 | 0.00062505 | 0.000608904 | 0.000638054 | 0.000144522 |
| 18 | 0.571 | 0.587 | 0.579 | 35040 | 0.000608163 | 0.000595085 | 0.000627711 | 0.000137951 |
| 19 | 0.587 | 0.604 | 0.5955 | 35039 | 0.000597045 | 0.00057819 | 0.000603604 | 0.000131641 |
| 20 | 0.604 | 0.622 | 0.613 | 35040 | 0.000557815 | 0.000539049 | 0.000563569 | 0.000122862 |
| 21 | 0.622 | 0.641 | 0.6315 | 35040 | 0.000534626 | 0.000519067 | 0.000545131 | 0.000117456 |
| 22 | 0.641 | 0.661 | 0.651 | 35040 | 0.000504217 | 0.000486035 | 0.000511348 | 0.000107618 |
| 23 | 0.661 | 0.683 | 0.672 | 35040 | 0.00047058 | 0.000457616 | 0.000475753 | 0.000100479 |
| 24 | 0.683 | 0.707 | 0.695 | 35040 | 0.000443332 | 0.000434642 | 0.00045829 | 9.20037e-05 |
| 25 | 0.707 | 0.735 | 0.721 | 35040 | 0.00040978 | 0.00040241 | 0.000425199 | 8.2478e-05 |
| 26 | 0.735 | 0.767 | 0.751 | 35040 | 0.000364418 | 0.000357018 | 0.000373103 | 7.16439e-05 |
| 27 | 0.767 | 0.806 | 0.7865 | 35040 | 0.000325751 | 0.000313409 | 0.000329147 | 6.10423e-05 |
| 28 | 0.806 | 0.859 | 0.8325 | 35040 | 0.000258132 | 0.000249886 | 0.000264007 | 4.64297e-05 |
| 29 | 0.859 | 1 | 0.9295 | 35039 | 0.000145112 | 0.000139918 | 0.000148225 | 2.19721e-05 |

## Pass-Through
| lambda | shock_label | state | event_count | VWAP_mean_kappa | VWAP_median_kappa | VWAP_p95_kappa | LWMP_mean_kappa | LWMP_median_kappa | LWMP_p95_kappa | LWMP_zero_share | LWMP_one_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.001 | +0.100% | non_lockin | 453402 | 0.41467 | 0.420529 | 0.491864 | 0.271482 | 0.130371 | 1 | 0.345815 | 0.0605996 |
| 0.001 | +0.100% | lockin | 597796 | 0.652494 | 0.63046 | 0.868549 | 1 | 1 | 1 | 0 | 1 |
| -0.001 | -0.100% | non_lockin | 453402 | 0.41467 | 0.420529 | 0.491864 | 0.274381 | 0.132268 | 1 | 0.292656 | 0.0685043 |
| -0.001 | -0.100% | lockin | 597796 | 0.652494 | 0.63046 | 0.868549 | 1 | 1 | 1 | 0 | 1 |
| 0.01 | +1.000% | non_lockin | 453402 | 0.41467 | 0.420529 | 0.491864 | 0.0379157 | 0.0159396 | 0.144069 | 0.310967 | 0.000121305 |
| 0.01 | +1.000% | lockin | 597796 | 0.652494 | 0.63046 | 0.868549 | 1 | 1 | 1 | 0 | 1 |
| -0.01 | -1.000% | non_lockin | 453402 | 0.41467 | 0.420529 | 0.491864 | 0.0371423 | 0.0151473 | 0.141509 | 0.267756 | 0.000310982 |
| -0.01 | -1.000% | lockin | 597796 | 0.652494 | 0.63046 | 0.868549 | 1 | 1 | 1 | 0 | 1 |

## Direct Comparison
| Specification | Excluded venue | Start date | End date | Valid minutes | Venue count | Share max_share > 0.5 | Share max_share > 0.4 | Median max_share | P95 max_share | Median HHI | P95 HHI | Dominant exchange distribution | Over-half spell count | Median spell duration | P95 spell duration | Maximum spell | Non-lock-in pivot-change rate | Lock-in pivot-change rate | Difference | Rate ratio | Bootstrap CI 1-day | Bootstrap CI 7-day | Lowest-bin VWAP q95 gap | Highest-bin VWAP q95 gap | Highest/lowest VWAP gap ratio | Median LWMP pass-through in lock-in | Median VWAP pass-through in lock-in | Median VWAP pass-through in non-lock-in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ETHUSD all 7 venues |  | 2021-01-01 | 2022-12-31 23:59:00 | 1051200 | 7 | 0.709308 | 0.938213 | 0.571893 | 0.788739 | 0.409679 | 0.63929 | Binance=0.862; Coinbase=0.099; KuCoin=0.017; OKX=0.012; Bitfinex=0.008; Bitstamp=0.003; BitMEX=0.000 | 166241 | 2 | 15 | 365 | 0.236503 | 0.0750318 | -0.161471 | 0.317256 | [-0.166211, -0.156705] | [-0.168085, -0.155064] | 0.000737279 | 0.000134941 | 0.183025 | 1 | 0.623097 | 0.444966 |
| ETHUSD exclude BitMEX | BitMEX | 2021-01-01 00:00:00+00:00 | 2022-12-31 23:59:00+00:00 | 1051200 | 6 | 0.711955 |  | 0.573007 | 0.79024 |  |  | NA_existing_summary_not_available |  |  |  |  | 0.273262 | 0.0878828 | -0.185379 | 0.321607 | NA_existing_summary_not_available | NA_existing_summary_not_available | NA_existing_summary_not_available | NA_existing_summary_not_available | NA_existing_summary_not_available | 1 | 0.62385 | 0.445178 |
| ETHUSD exclude Binance | Binance | 2021-01-01 00:00:00+00:00 | 2022-12-31 23:59:00+00:00 | 1051198 | 6 | 0.568681 | 0.836502 | 0.527257 | 0.829346 | 0.385317 | 0.702094 | Coinbase=0.710; OKX=0.130; KuCoin=0.107; Bitfinex=0.036; Bitstamp=0.016; BitMEX=0.000 | 198995 | 2 | 9 | 524 | 0.286682 | 0.112072 | -0.174609 | 0.39093 | [-0.179164, -0.170102] | [-0.181781, -0.16734] | 0.00105281 | 0.000145112 | 0.137832 | 1 | 0.63046 | 0.420529 |

## Required Answers
1. 实际有效分钟数为 1051198.
2. 至少 3/5/6 所有效分钟比例分别为 0.999998, 0.993853, 0.893786.
3. 主要 dominant venue 为 Coinbase，占比 0.710451.
4. dominant distribution 为 Coinbase=0.710; OKX=0.130; KuCoin=0.107; Bitfinex=0.036; Bitstamp=0.016; BitMEX=0.000；相对七所样本的 Binance=0.862，分布明显转向 Coinbase 且更分散.
5. share(max_share > 0.5) = 0.568681.
6. median max_share = 0.527257, p95 max_share = 0.829346.
7. over-half spell count = 198995, median = 2, p95 = 9.
8. 最长 lock-in spell = 524 minutes.
9. LWMP 0.5 boundary 仍清晰: lock-in rate lower than non-lock-in.
10. non-lock-in pivot-change rate = 0.286682.
11. lock-in pivot-change rate = 0.112072.
12. difference = -0.174609.
13. rate ratio = 0.390930.
14. 1-day bootstrap CI 排除零: [-0.179164, -0.170102].
15. 7-day bootstrap CI 排除零: [-0.181781, -0.16734].
16. VWAP proximity channel 仍存在，highest/lowest ratio = 0.137832.
17. 最低与最高 concentration bin q95 gap 分别为 0.00105281 和 0.000145112.
18. LWMP lock-in median pass-through = 1，等于 1.
19. 相对七所样本，exclude-Binance 的 LWMP headline difference 增强.
20. 与现有 exclude-BitMEX 行相比，exclude-Binance 的完整六所重算结果见 comparison 表；BitMEX 既有行未被覆盖.
21. 七所 ETH 结果不只是由 Binance 驱动，判断依据是六所样本 difference、bootstrap CI 和 pass-through.
22. 未发现新的 volume convention 风险；BitMEX 仍按 quote_or_contract, multiplier=1.0.
23. validation FAIL=0; 若为 0，则未发现削弱跨资产复现可信度的阻断性问题.
24. 建议写入 online appendix，作为 Binance-dominance targeted exclusion 检验.
25. 主文可用一句话提及该检验，并把完整表放入 appendix.
26. 建议继续做完整 ETH leave-one-exchange-out，以避免只围绕 Binance 与 BitMEX 两个 targeted cases.

## Figure And Event Definitions
- Figure subset: `shock_type=inflate_only`, `gamma=1.0`, 30 max_share bins, Wilson intervals, vertical boundary at 0.5.
- Pooled headline dataset: both shock types and all delta_w/gamma values [-0.5, 0.5, 1.0, 2.0].
- Event sampling uses the same sampled-minute logic and seed as the seven-venue ETH run.

## Validation
| check | status | value | detail |
| --- | --- | --- | --- |
| 01_weights_normalize_to_one | PASS | 4.44089e-16 | Valid-minute normalized weights sum to one. |
| 02_max_abs_normalization_error_reported | PASS | 4.44089e-16 | Maximum absolute row-share error. |
| 03_max_share_in_unit_interval | PASS | 0.202559,0.999599 | Minimum and maximum max_share among valid minutes. |
| 04_lockin_pivot_equals_dominant | PASS | 0 | Violations when max_share > 0.5. |
| 05_manual_vwap_recalculation_10_minutes | PASS | 0 | Manual scalar VWAP recomputation. |
| 06_manual_lwmp_recalculation_10_minutes | PASS | 0 | Manual scalar LWMP recomputation. |
| 07_lockin_nonlockin_states_checked | PASS | {"0": 453402, "1": 597796} | Both states present in matched sample. |
| 08_output_missing_values_checked | WARN | 18402 | Missing values are expected in full venue panels for unavailable venue minutes; result tables are separately row-counted. |
| 09_output_duplicate_timestamps_checked | PASS | 0 | Duplicate time_utc count across CSV outputs that contain time_utc. |
| 10_input_duplicate_timestamps_checked | PASS | 0 | Number of input files with duplicated timestamps flagged in audit. |
| 11_abnormal_rows_count_checked | WARN | 109327 | Invalid price/weight rows in matched-sample processing manifest. |
| 12_combined_index_excluded_from_venue_list | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Venue price columns used for aggregation. |
| 13_combined_index_excluded_from_weights | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Weight columns used for aggregation. |
| 14_combined_index_excluded_from_dominant | PASS | 0 | Dominant exchange values. |
| 15_combined_index_excluded_from_pivot | PASS | 0 | Pivot exchange values. |
| 16_bootstrap_utc_blocks_checked | PASS | 1,7 | Bootstrap grouped into 1-day and 7-day UTC blocks. |
| 17_same_minute_events_not_split | PASS | 0 | Same-minute perturbation events map to one UTC-day block. |
| 18_lwmp_lockin_passthrough_theory | PASS | 1.10134e-13 | Maximum \|median LWMP kappa - 1\| in lock-in states. |
| 19_eth_methods_match_btc_pipeline | PASS | OHLC4_HL2_Close;min3;DVonly;Wilson;UTC blocks;kappa | ETH runner imports/reuses BTC helper implementations and constants. |
| 20_filtered_minutes_and_reasons_recorded | PASS | <PROJECT_ROOT>\paper_outputs_el\replication_eth\exclude_binance\metadata\processing_filter_manifest.csv | Processing filter manifest written. |
| 21_price_volume_inf_checked | PASS | 0 | Inf values in processed price and weight matrices. |
| 22_price_volume_negative_checked | PASS | 0 | Negative values in processed price and weight matrices. |
| 23_abnormal_zero_values_checked | WARN | 109327 | Zero processed weights; NaN is used for missing, zero may reflect zero raw volume if present. |
| 24_exchange_fields_used_recorded | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Input file manifest records price and volume fields. |
| 25_bitmex_multiplier_checked | PASS | quote_or_contract;1.0 | BitMEX quote_or_contract rule and multiplier. |
| 26_output_file_row_counts_checked | PASS | eth_exclude_binance_1m_panel.csv:1051200;eth_exclude_binance_1m_panel_with_weights.csv:1051200;eth_exclude_binance_1m_panel_with_benchmarks.csv:1051200;eth_exclude_binance_lockin_summary.csv:1;eth_exclude_binance_spell_summary.csv:1;eth_exclude_binance_pivot_bins.csv:360;eth_exclude_binance_block_bootstrap.csv:8;eth_exclude_binance_vwap_proximity_bins.csv:30;eth_exclude_binance_passthrough_summary.csv:8;eth_exclude_binance_dominant_exchange_distribution.csv:6;eth_exclusion_comparison.csv:3 | Rows in generated CSV outputs. |
| 27_parameter_manifest_consistent | PASS | <PROJECT_ROOT>\paper_outputs_el\replication_eth\exclude_binance\metadata\parameter_manifest.json | Manifest written from actual arguments. |
| 28_random_seed_recorded | PASS | 20260712 | Seed used for bootstrap and event sampling. |
| 29_results_reproducible_from_runner | PASS | <PROJECT_ROOT>\run_eth_exclude_binance.py | Single deterministic exclude-Binance entrypoint with recorded parameters. |
| 30_btc_outputs_not_modified | PASS | read_only | This targeted runner writes only the exclude_binance tree and the requested ETH targeted summary append. |
| 31_binance_excluded_from_venue_list | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Venue price columns used for this run. |
| 32_binance_excluded_from_weight_columns | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Dollar-volume weight columns used for this run. |
| 33_binance_excluded_from_dominant_exchange | PASS | 0 | Dominant venue labels in valid minutes. |
| 34_binance_excluded_from_pivot | PASS | 0 | LWMP pivot labels in valid minutes. |
| 35_binance_excluded_from_input_manifest | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Only six raw exchange CSVs are admitted. |
| 36_combined_index_excluded_from_input_manifest | PASS | BitMEX,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | Combined_Index is not read or benchmarked in this targeted run. |
| 37_figure_subset_and_pooled_dataset_recorded | PASS | shock_type=inflate_only, gamma=1.0, 30 max_share bins, Wilson intervals; both shock types and all delta_w/gamma values from six-venue sampled valid minutes | Figure subset and pooled event definitions are explicitly separated. |
| 38_seed_equals_20260712 | PASS | 20260712 | Bootstrap and event seed manifest. |
| 39_seven_venue_eth_core_outputs_not_modified | PASS | {"added": 0, "changed": 0, "removed": 0} | Excludes the required append to eth_targeted_exclusion_summary.csv and the new exclude_binance tree. |
| 40_existing_exclude_bitmex_row_preserved | PASS | before=1;after=1 | Existing BitMEX targeted-exclusion row remains present. |
| 41_btc_outputs_not_modified | PASS | {"added": 0, "changed": 0, "removed": 0} | BTC output trees were stat-snapshotted before and after this run. |
| 42_validation_status_vocabulary | PASS | PASS,WARN,FAIL | The validation writer emits only the allowed statuses. |

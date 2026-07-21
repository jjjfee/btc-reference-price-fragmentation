# ETH replication report

## Core Results
| valid_minutes | venue_count | median_max_share | p95_max_share | p99_max_share | share_max_share_gt_0p5 | share_max_share_gt_0p4 | share_max_share_gt_0p3 | median_HHI | p95_HHI | over_half_spell_count | spell_duration_median | spell_duration_p95 | spell_duration_p99 | max_spell_minutes | spells_ge_60_minutes | spells_ge_360_minutes | spells_ge_1440_minutes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0512e+06 | 7 | 0.571893 | 0.788739 | 0.860143 | 0.709308 | 0.938213 | 0.998351 | 0.409679 | 0.63929 | 166241 | 2 | 15 | 34 | 365 | 409 | 1 | 0 |

## BTC-ETH comparison
| Asset | Sample | Start date | End date | Valid minutes | Venue count | Share max_share > 0.5 | Share max_share > 0.4 | Median max_share | P95 max_share | Median HHI | P95 HHI | Over-half spell count | Median spell duration | P95 spell duration | Maximum lock-in spell | Non-lock-in pivot-change rate | Lock-in pivot-change rate | Difference | Rate ratio | Bootstrap CI 1-day | Bootstrap CI 7-day | Lowest-bin VWAP q95 gap | Highest-bin VWAP q95 gap | Highest/lowest VWAP gap ratio | Median LWMP pass-through in lock-in | Median VWAP pass-through in lock-in | Median VWAP pass-through in non-lock-in | Dominant exchange distribution summary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTCUSD | BTCUSD 2021-2022 | 2021-01-01 | 2022-12-31 23:59:00 | 1050207 | 7 | 0.554973 | 0.821862 | 0.523582 | 0.880238 | 0.358417 | 0.780778 | 164078 | 1 | 6 | 2982 | 0.279276 | 0.0676774 | -0.211599 | 0.242331 | [-0.216777, -0.206266] | [-0.220969, -0.201412] | 0.00125432 | 9.65319e-05 | 0.0769596 | 1 | 0.663727 | 0.416821 | Binance=0.802; BitMEX=0.130; OKX=0.028; Coinbase=0.026; KuCoin=0.007; Bitfinex=0.006; Bitstamp=0.001 |
| BTCUSD | BTCUSD 2023-01-01 to 2025-10-11 | 2023-01-01 00:00:00+00:00 | 2025-10-11 11:02:00+00:00 | 1460823 | 7 | 0.586593 | 0.852331 | 0.533103 | 0.87079 | 0.370129 | 0.764992 | 270824 | 2 | 8 | 7699 | 0.263183 | 0.0773592 | -0.185824 | 0.293937 | [-0.190195, -0.181575] | [-0.192427, -0.179198] | 0.00096626 | 0.000130407 | 0.13496 | 1 | 0.628674 | 0.424207 | Binance=0.820; Coinbase=0.068; BitMEX=0.059; OKX=0.039; KuCoin=0.007; Bitstamp=0.006; Bitfinex=0.003 |
| ETHUSD | ETHUSD 2021-2022 | 2021-01-01 00:00:00+00:00 | 2022-12-31 23:59:00+00:00 | 1051200 | 7 | 0.709308 | 0.938213 | 0.571893 | 0.788739 | 0.409679 | 0.63929 | 166241 | 2 | 15 | 365 | 0.236503 | 0.0750318 | -0.161471 | 0.317256 | [-0.166211, -0.156705] | [-0.168085, -0.155064] | 0.000737279 | 0.000134941 | 0.183025 | 1 | 0.623097 | 0.444966 | Binance=0.862; Coinbase=0.099; KuCoin=0.017; OKX=0.012; Bitfinex=0.008; Bitstamp=0.003; BitMEX=0.000 |

## Required answers
1. 七个 ETH 文件覆盖见下表：Binance: 2017-08-17 04:00:00+00:00 to 2025-10-11 11:04:00+00:00; Bitfinex: 2017-03-11 00:00:00+00:00 to 2025-10-11 11:03:00+00:00; BitMEX: 2018-08-02 09:07:00+00:00 to 2025-10-11 11:03:00+00:00; Bitstamp: 2017-08-16 16:45:00+00:00 to 2025-10-11 11:04:00+00:00; Coinbase: 2016-09-29 00:00:00+00:00 to 2025-10-11 11:04:00+00:00; KuCoin: 2018-01-01 00:13:00+00:00 to 2025-10-11 11:03:00+00:00; OKX: 2018-01-11 11:12:00+00:00 to 2025-10-11 11:07:00+00:00.
2. 2021-2022 matched sample 质量：至少 3 所有效分钟占比 1.000000，至少 5 所 0.999777，7 所全部有效 0.892891.
3. 至少 3/5/7 所有效分钟比例分别是 1.000000, 0.999777, 0.892891.
4. 每个交易所 price 字段均按 BTC 顺序使用 OHLC4；字段记录在 metadata/input_file_manifest.csv.
5. 每个交易所 volume 字段见 eth_volume_convention_audit.csv.
6. Volume convention 判断基于显式 quote/amount 字段匹配、整数比例和 BTC BitMEX quote_or_contract 规则.
7. BitMEX volume 按 BTC quote_or_contract 逻辑处理，multiplier=1.0.
8. 未发现文件名或列结构中的 ETHUSDT/ETHUSD 混用；但原始文件无 symbol 列，USD/USDT 标签风险记为口径 WARN.
9. 未发现需要价格缩放的异常；价格中位数处于 ETHUSD 量级.
10. Combined_Index 已从全部聚合计算中排除，仅进入审计和 benchmark 辅助列.
11. ETH 有效分钟数为 1051200.
12. ETH over-half state 占比为 0.709308.
13. ETH median max_share=0.571893, p95 max_share=0.788739.
14. ETH 最长 lock-in spell 为 365 分钟.
15. ETH dominant exchange 分布：Binance=0.862; Coinbase=0.099; KuCoin=0.017; OKX=0.012; Bitfinex=0.008; Bitstamp=0.003; BitMEX=0.000.
16. LWMP 0.5 boundary 清晰：lock-in pivot-change rate 低于 non-lock-in.
17. non-lock-in pivot-change rate=0.236503.
18. lock-in pivot-change rate=0.075032.
19. difference=-0.161471.
20. rate ratio=0.317256.
21. 1-day block-bootstrap CI 排除零: [-0.166211, -0.156705].
22. 7-day block-bootstrap CI 排除零: [-0.168085, -0.155064].
23. VWAP proximity channel 存在，最低/最高 bin q95 分别为 0.000737279/0.000134941.
24. 最低和最高集中度 bin 的 q95 gap 分别是 0.000737279 和 0.000134941.
25. LWMP lock-in pass-through median kappa=1，等于 1.
26. ETH 与 BTC 2021-2022 的相同点：同样呈现 over-half lock-in 下 pivot-change rate 明显下降，LWMP pass-through 在 lock-in 下为 1.
27. ETH 与 BTC 2021-2022 的差异见 btc_eth_core_comparison.csv，主要体现在 max_share 分布、dominant venue 分布、VWAP proximity gap 和 spell 持续性.
28. ETH 与 BTC 2023-2025 的差异见同一比较表，重点看 post-2022 BTC 更高/更低的集中度和 spell 指标.
29. 差异更可能来自市场结构与 BitMEX quote_or_contract 口径共同作用；数据覆盖风险已审计.
30. 未发现会影响 BTC 主结论的问题；本脚本不修改 BTC 输出.
31. ETH 复现可信度风险：WARN=3, FAIL=0; 主要风险为原始 symbol 缺失和 BitMEX contract 口径.
32. 已运行针对性排除；结果见 eth_targeted_exclusion_summary.csv.
33. 建议作为 online appendix 的跨资产复现结果，主文可用一句话概括.
34. 若 validation 无 FAIL，可用于投稿版本的附录；主文是否纳入取决于篇幅和 EL 叙事重点.

## Figure and pooled event definitions
- Figure specification: `shock_type=inflate_only`, `gamma=1.0`, original 30 max_share bins, Wilson intervals, 0.5 vertical boundary.
- Pooled headline dataset: all DV-only perturbation events across both shock types and all delta_w/gamma values.
- The Figure and pooled headline summary are generated from the same sampled minutes but not the same filtered event subset.
- Both use the same BTC shock parameters: delta_w/gamma = 0.5, 1.0, 2.0, -0.5 and shock_type = inflate_only, reallocate_total_fixed.

## Bootstrap
| block_days | statistic | point_estimate | bootstrap_mean | bootstrap_se | ci95_low | ci95_high | reps_completed | seed | n_blocks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | rate_nonlock | 0.236503 | 0.236526 | 0.00226982 | 0.232017 | 0.241012 | 5000 | 20260712 | 730 |
| 1 | rate_lock | 0.0750318 | 0.0750414 | 0.00110182 | 0.0728925 | 0.0772522 | 5000 | 20260712 | 730 |
| 1 | difference_lock_minus_nonlock | -0.161471 | -0.161485 | 0.00239025 | -0.166211 | -0.156705 | 5000 | 20260712 | 730 |
| 1 | ratio_lock_over_nonlock | 0.317256 | 0.317288 | 0.00522281 | 0.307178 | 0.327638 | 5000 | 20260712 | 730 |
| 7 | rate_nonlock | 0.236503 | 0.236508 | 0.00276181 | 0.231189 | 0.24203 | 5000 | 20260712 | 105 |
| 7 | rate_lock | 0.0750318 | 0.0751059 | 0.00227064 | 0.0706718 | 0.0796574 | 5000 | 20260712 | 105 |
| 7 | difference_lock_minus_nonlock | -0.161471 | -0.161402 | 0.00333978 | -0.168085 | -0.155064 | 5000 | 20260712 | 105 |
| 7 | ratio_lock_over_nonlock | 0.317256 | 0.31759 | 0.00983164 | 0.298526 | 0.336942 | 5000 | 20260712 | 105 |

## VWAP proximity
| bin_id | x_left | x_right | x_center | n | q95_rel_gap_dom | ci_low | ci_high | median_rel_gap_dom |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.196 | 0.375 | 0.2855 | 35040 | 0.000737279 | 0.000722611 | 0.000770511 | 0.000135072 |
| 1 | 0.375 | 0.403 | 0.389 | 35040 | 0.000743219 | 0.000722785 | 0.00076672 | 0.000132739 |
| 2 | 0.403 | 0.423 | 0.413 | 35040 | 0.000724195 | 0.000708197 | 0.000752587 | 0.000132295 |
| 3 | 0.423 | 0.44 | 0.4315 | 35040 | 0.000701422 | 0.00069317 | 0.000727125 | 0.000131355 |
| 4 | 0.44 | 0.454 | 0.447 | 35040 | 0.000686138 | 0.000674067 | 0.00071012 | 0.000129671 |
| 5 | 0.454 | 0.467 | 0.4605 | 35040 | 0.000692443 | 0.000676062 | 0.000709199 | 0.000127963 |
| 6 | 0.467 | 0.479 | 0.473 | 35040 | 0.000660162 | 0.00064679 | 0.000681214 | 0.000126739 |
| 7 | 0.479 | 0.492 | 0.4855 | 35040 | 0.000633282 | 0.000627965 | 0.000656765 | 0.000122544 |
| 8 | 0.492 | 0.503 | 0.4975 | 35040 | 0.000621454 | 0.000606901 | 0.000633704 | 0.000119304 |
| 9 | 0.503 | 0.515 | 0.509 | 35040 | 0.000604316 | 0.000598902 | 0.000625549 | 0.000118822 |
| 10 | 0.515 | 0.527 | 0.521 | 35040 | 0.000587214 | 0.000571985 | 0.000601741 | 0.000117859 |
| 11 | 0.527 | 0.538 | 0.5325 | 35040 | 0.000552571 | 0.000534857 | 0.000561947 | 0.000114644 |
| 12 | 0.538 | 0.549 | 0.5435 | 35040 | 0.000548383 | 0.000534894 | 0.000564337 | 0.000111689 |
| 13 | 0.549 | 0.561 | 0.555 | 35040 | 0.000529854 | 0.000521708 | 0.000545963 | 0.000110031 |
| 14 | 0.561 | 0.572 | 0.5665 | 35040 | 0.000501053 | 0.000494367 | 0.000520456 | 0.000106684 |
| 15 | 0.572 | 0.583 | 0.5775 | 35040 | 0.000494615 | 0.000475289 | 0.000502046 | 0.000105446 |
| 16 | 0.583 | 0.595 | 0.589 | 35040 | 0.000470878 | 0.000458738 | 0.000482792 | 0.000102459 |
| 17 | 0.595 | 0.607 | 0.601 | 35040 | 0.000452724 | 0.000451204 | 0.000474355 | 0.000101874 |
| 18 | 0.607 | 0.619 | 0.613 | 35040 | 0.000436171 | 0.000423038 | 0.000442842 | 9.76933e-05 |
| 19 | 0.619 | 0.631 | 0.625 | 35040 | 0.000418112 | 0.000412242 | 0.000433452 | 9.47246e-05 |
| 20 | 0.631 | 0.644 | 0.6375 | 35040 | 0.000393343 | 0.000376813 | 0.000396965 | 9.1621e-05 |
| 21 | 0.644 | 0.657 | 0.6505 | 35040 | 0.000371298 | 0.000365015 | 0.000381898 | 8.82103e-05 |
| 22 | 0.657 | 0.671 | 0.664 | 35040 | 0.000348683 | 0.000338938 | 0.000355303 | 8.42358e-05 |
| 23 | 0.671 | 0.687 | 0.679 | 35040 | 0.000332918 | 0.000322345 | 0.000340781 | 7.98655e-05 |
| 24 | 0.687 | 0.704 | 0.6955 | 35040 | 0.000305703 | 0.00030147 | 0.000314252 | 7.60253e-05 |
| 25 | 0.704 | 0.722 | 0.713 | 35040 | 0.000286045 | 0.000277548 | 0.000291833 | 7.14727e-05 |
| 26 | 0.722 | 0.744 | 0.733 | 35040 | 0.000260221 | 0.000252597 | 0.000264568 | 6.55096e-05 |
| 27 | 0.744 | 0.771 | 0.7575 | 35040 | 0.000225604 | 0.000220668 | 0.000230789 | 5.87117e-05 |
| 28 | 0.771 | 0.81 | 0.7905 | 35040 | 0.000188097 | 0.000183945 | 0.000191363 | 4.87604e-05 |
| 29 | 0.81 | 0.986 | 0.898 | 35039 | 0.000134941 | 0.000130431 | 0.000137171 | 3.21775e-05 |

## Pass-through
| lambda | shock_label | state | event_count | VWAP_mean_kappa | VWAP_median_kappa | VWAP_p95_kappa | LWMP_mean_kappa | LWMP_median_kappa | LWMP_p95_kappa | LWMP_zero_share | LWMP_one_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.001 | +0.100% | non_lockin | 305575 | 0.436386 | 0.444966 | 0.494837 | 0.341657 | 0.220807 | 1 | 0.194391 | 0.0836685 |
| 0.001 | +0.100% | lockin | 745625 | 0.636272 | 0.623097 | 0.807357 | 1 | 1 | 1 | 0 | 1 |
| -0.001 | -0.100% | non_lockin | 305575 | 0.436386 | 0.444966 | 0.494837 | 0.185548 | 0.0751674 | 0.9894 | 0.295548 | 0.0483744 |
| -0.001 | -0.100% | lockin | 745625 | 0.636272 | 0.623097 | 0.807357 | 1 | 1 | 1 | 0 | 1 |
| 0.01 | +1.000% | non_lockin | 305575 | 0.436386 | 0.444966 | 0.494837 | 0.0452833 | 0.0230534 | 0.160771 | 0.180028 | 0.00036325 |
| 0.01 | +1.000% | lockin | 745625 | 0.636272 | 0.623097 | 0.807357 | 1 | 1 | 1 | 0 | 1 |
| -0.01 | -1.000% | non_lockin | 305575 | 0.436386 | 0.444966 | 0.494837 | 0.0245225 | 0.00789062 | 0.116733 | 0.285095 | 0.000409065 |
| -0.01 | -1.000% | lockin | 745625 | 0.636272 | 0.623097 | 0.807357 | 1 | 1 | 1 | 0 | 1 |

## Targeted exclusion
| excluded_venue | trigger | remaining_venues | valid_minutes | share_max_share_gt_0p5 | median_max_share | p95_max_share | non_lockin_pivot_change_rate | lockin_pivot_change_rate | difference | rate_ratio | lockin_LWMP_median_kappa_plus0p1 | lockin_VWAP_median_kappa_plus0p1 | nonlockin_VWAP_median_kappa_plus0p1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BitMEX | quote_or_contract_or_uncertain_volume_convention | Binance,Bitfinex,Bitstamp,Coinbase,KuCoin,OKX | 1051200 | 0.711955 | 0.573007 | 0.79024 | 0.273262 | 0.0878828 | -0.185379 | 0.321607 | 1 | 0.62385 | 0.445178 |

## Validation
| check | status | value | detail |
| --- | --- | --- | --- |
| 01_weights_normalize_to_one | PASS | 5.55112e-16 | Valid-minute normalized weights sum to one. |
| 02_max_abs_normalization_error_reported | PASS | 5.55112e-16 | Maximum absolute row-share error. |
| 03_max_share_in_unit_interval | PASS | 0.19614,0.98617 | Minimum and maximum max_share among valid minutes. |
| 04_lockin_pivot_equals_dominant | PASS | 0 | Violations when max_share > 0.5. |
| 05_manual_vwap_recalculation_10_minutes | PASS | 0 | Manual scalar VWAP recomputation. |
| 06_manual_lwmp_recalculation_10_minutes | PASS | 0 | Manual scalar LWMP recomputation. |
| 07_lockin_nonlockin_states_checked | PASS | {"0": 305575, "1": 745625} | Both states present in matched sample. |
| 08_output_missing_values_checked | WARN | 20140 | Missing values are expected in full venue panels for unavailable venue minutes; result tables are separately row-counted. |
| 09_output_duplicate_timestamps_checked | PASS | 0 | Duplicate time_utc count across CSV outputs that contain time_utc. |
| 10_input_duplicate_timestamps_checked | PASS | 0 | Number of input files with duplicated timestamps flagged in audit. |
| 11_abnormal_rows_count_checked | WARN | 109408 | Invalid price/weight rows in matched-sample processing manifest. |
| 12_combined_index_excluded_from_venue_list | PASS | Binance,Bitfinex,BitMEX,Bitstamp,Coinbase,KuCoin,OKX | Venue price columns used for aggregation. |
| 13_combined_index_excluded_from_weights | PASS | Binance,Bitfinex,BitMEX,Bitstamp,Coinbase,KuCoin,OKX | Weight columns used for aggregation. |
| 14_combined_index_excluded_from_dominant | PASS | 0 | Dominant exchange values. |
| 15_combined_index_excluded_from_pivot | PASS | 0 | Pivot exchange values. |
| 16_bootstrap_utc_blocks_checked | PASS | 1,7 | Bootstrap grouped into 1-day and 7-day UTC blocks. |
| 17_same_minute_events_not_split | PASS | 0 | Same-minute perturbation events map to one UTC-day block. |
| 18_lwmp_lockin_passthrough_theory | PASS | 1.10134e-13 | Maximum \|median LWMP kappa - 1\| in lock-in states. |
| 19_eth_methods_match_btc_pipeline | PASS | OHLC4_HL2_Close;min3;DVonly;Wilson;UTC blocks;kappa | ETH runner imports/reuses BTC helper implementations and constants. |
| 20_filtered_minutes_and_reasons_recorded | PASS | <PROJECT_ROOT>\paper_outputs_el\replication_eth\metadata\processing_filter_manifest.csv | Processing filter manifest written. |
| 21_price_volume_inf_checked | PASS | 0 | Inf values in processed price and weight matrices. |
| 22_price_volume_negative_checked | PASS | 0 | Negative values in processed price and weight matrices. |
| 23_abnormal_zero_values_checked | WARN | 109408 | Zero processed weights; NaN is used for missing, zero may reflect zero raw volume if present. |
| 24_exchange_fields_used_recorded | PASS | Binance,Bitfinex,BitMEX,Bitstamp,Coinbase,KuCoin,OKX | Input file manifest records price and volume fields. |
| 25_bitmex_multiplier_checked | PASS | quote_or_contract;1.0 | BitMEX quote_or_contract rule and multiplier. |
| 26_output_file_row_counts_checked | PASS | eth_1m_panel.csv:1051200;eth_1m_panel_with_weights.csv:1051200;eth_1m_panel_with_benchmarks.csv:1051200;eth_lockin_summary.csv:1;eth_spell_summary.csv:1;eth_pivot_bins.csv:360;eth_block_bootstrap.csv:8;eth_vwap_proximity_bins.csv:30;eth_passthrough_summary.csv:8;eth_dominant_exchange_distribution.csv:7;eth_targeted_exclusion_summary.csv:1;btc_eth_core_comparison.csv:3 | Rows in generated CSV outputs. |
| 27_parameter_manifest_consistent | PASS | <PROJECT_ROOT>\paper_outputs_el\replication_eth\metadata\parameter_manifest.json | Manifest written from actual arguments. |
| 28_random_seed_recorded | PASS | 20260712 | Seed used for bootstrap and event sampling. |
| 29_results_reproducible_from_runner | PASS | <PROJECT_ROOT>\run_eth_replication.py | Single deterministic entrypoint with recorded parameters. |
| 30_btc_outputs_not_modified | PASS | read_only | ETH runner writes only under paper_outputs_el/replication_eth and run_eth_replication.py. |
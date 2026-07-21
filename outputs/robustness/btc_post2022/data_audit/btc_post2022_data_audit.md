# BTC post-2022 data audit

## Raw data path
- Raw BTC directory: `data\external\raw\btc`
- Main-sample calibration workbook: `<PROJECT_ROOT>\dv_unit_and_price_scale_report.xlsx`

## Selected sample window
- Start: 2023-01-01 00:00:00+00:00
- End: 2025-10-11 11:02:00+00:00
- Rule: longest continuous UTC-minute run with at least 3 valid exchanges
- Valid calendar minutes in selected run: 1,460,823

## Exchange file coverage
| exchange | file_name | start_time | end_time | total_rows | valid_price_and_volume_minutes | duplicate_timestamps | missing_minute_ratio | volume_field_name | inferred_volume_convention |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Binance | BTCUSD_1m_Binance.csv | 2017-08-17 04:00:00+00:00 | 2025-10-11 11:02:00+00:00 | 4278671 | 4254807 | 0 | 0.00201339 | Volume | base |
| Bitfinex | BTCUSD_1m_Bitfinex.csv | 2013-07-19 00:05:00+00:00 | 2025-10-11 11:02:00+00:00 | 5391322 | 5391322 | 0 | 0.161945 | Volume | base |
| BitMEX | BTCUSD_1m_BitMEX.csv | 2015-09-25 12:35:00+00:00 | 2025-10-11 11:02:00+00:00 | 5283245 | 4682240 | 0 | 4.35337e-06 | Volume | quote_or_contract |
| Bitstamp | BTCUSD_1m_Bitstamp.csv | 2011-08-18 12:37:00+00:00 | 2025-10-11 11:02:00+00:00 | 7441823 | 5936537 | 0 | 4.03127e-07 | Volume | base |
| Coinbase | BTCUSD_1m_Coinbase.csv | 2015-07-20 21:37:00+00:00 | 2025-10-11 11:02:00+00:00 | 5317710 | 5317710 | 0 | 0.0114322 | Volume | base |
| KuCoin | BTCUSD_1m_KuCoin.csv | 2017-12-21 00:11:00+00:00 | 2025-10-11 11:02:00+00:00 | 3908950 | 3880165 | 0 | 0.0480121 | Volume | base |
| OKX | BTCUSD_1m_OKX.csv | 2018-01-11 11:12:00+00:00 | 2025-10-11 11:02:00+00:00 | 4075191 | 4070895 | 0 | 0 | Volume | base |

## Yearly post-2022 coverage
| year | calendar_minutes | minutes_at_least_3_valid | share_at_least_3_valid | minutes_at_least_5_valid | share_at_least_5_valid | available_exchange_count | minutes_all_available_valid | share_all_available_valid |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | 525600 | 525600 | 1 | 524093 | 0.997133 | 7 | 403283 | 0.767281 |
| 2024 | 527040 | 527040 | 1 | 526660 | 0.999279 | 7 | 454750 | 0.862838 |
| 2025 | 408183 | 408183 | 1 | 408021 | 0.999603 | 7 | 327156 | 0.801493 |

## 2021-2022 calibration reused
| exchange | price_scale_to_anchor | anchor_usd_multiplier | volume_unit_final | volume_integer_ratio_est |
| --- | --- | --- | --- | --- |
| Binance | 1 | 1 | base | 0 |
| Bitfinex | 0.999424 | 1 | base | 4.5881e-05 |
| BitMEX | 0.999101 | 1 | quote_or_contract | 1 |
| Bitstamp | 0.999079 | 1 | base | 6.6808e-05 |
| Coinbase | 0.999333 | 1 | base | 2.5403e-06 |
| KuCoin | 0.999997 | 1 | base | 0 |
| OKX | 0.999998 | 1 | base | 4.22656e-06 |

## Notes
- Price representative follows the main code path: OHLC4 if available, then HL2, then close.
- Invalid observations are those with non-finite/non-positive price or non-finite/non-positive weight.
- The post-2022 run reuses the 2021-2022 price-scale and volume-convention calibration.
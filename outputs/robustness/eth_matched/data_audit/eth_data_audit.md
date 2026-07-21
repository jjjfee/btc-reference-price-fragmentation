# ETH data audit

- Raw directory: `data\external\raw\eth`
- Matched sample: `2021-01-01 00:00:00+00:00` to `2022-12-31 23:59:00+00:00`
- Valid-minute rule: at least 3 venues with finite positive price and dollar-volume proxy.
- Combined_Index excluded from all aggregation: yes.

## Exchange coverage
| exchange | utc_start | utc_end | total_rows | matched_valid_minutes | matched_coverage_share | price_median |
| --- | --- | --- | --- | --- | --- | --- |
| Binance | 2017-08-17 04:00:00+00:00 | 2025-10-11 11:04:00+00:00 | 4278673 | 1050126 | 0.998978 | 1584.39 |
| Bitfinex | 2017-03-11 00:00:00+00:00 | 2025-10-11 11:03:00+00:00 | 3817215 | 1042312 | 0.991545 | 1217.75 |
| BitMEX | 2018-08-02 09:07:00+00:00 | 2025-10-11 11:03:00+00:00 | 3782996 | 1028064 | 0.977991 | 1755.9 |
| Bitstamp | 2017-08-16 16:45:00+00:00 | 2025-10-11 11:04:00+00:00 | 4287978 | 968061 | 0.92091 | 1582.95 |
| Coinbase | 2016-09-29 00:00:00+00:00 | 2025-10-11 11:04:00+00:00 | 4633225 | 1051070 | 0.999876 | 1320.71 |
| KuCoin | 2018-01-01 00:13:00+00:00 | 2025-10-11 11:03:00+00:00 | 3827937 | 1050018 | 0.998876 | 1730.76 |
| OKX | 2018-01-11 11:12:00+00:00 | 2025-10-11 11:07:00+00:00 | 4075196 | 1049330 | 0.998221 | 1636.79 |

## Yearly matched-sample coverage
| year | calendar_minutes | minutes_at_least_3_valid | share_at_least_3_valid | minutes_at_least_5_valid | share_at_least_5_valid | minutes_all_7_valid | share_all_7_valid | Binance_valid_minutes | Binance_coverage_share | Bitfinex_valid_minutes | Bitfinex_coverage_share | BitMEX_valid_minutes | BitMEX_coverage_share | Bitstamp_valid_minutes | Bitstamp_coverage_share | Coinbase_valid_minutes | Coinbase_coverage_share | KuCoin_valid_minutes | KuCoin_coverage_share | OKX_valid_minutes | OKX_coverage_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | 525600 | 525600 | 1 | 525562 | 0.999928 | 477048 | 0.907626 | 524526 | 0.997957 | 519590 | 0.988565 | 522320 | 0.99376 | 486831 | 0.926239 | 525516 | 0.99984 | 524703 | 0.998293 | 525159 | 0.999161 |
| 2022 | 525600 | 525600 | 1 | 525404 | 0.999627 | 461559 | 0.878156 | 525600 | 1 | 522722 | 0.994524 | 505744 | 0.962222 | 481230 | 0.915582 | 525554 | 0.999912 | 525315 | 0.999458 | 524171 | 0.997281 |

## Volume convention audit
| exchange | volume_field | quote_volume_field | volume_convention | multiplier | integer_ratio | quote_to_base_price_ratio_median | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Binance | Volume | Quote asset volume | base | 1 | 0.001996 | 1 | Explicit quote/amount field matches Volume * OHLC4 price. |
| Bitfinex | Volume |  | base | 1 | 0.021926 |  | Fractional continuous Volume matches BTC spot/base-volume rule. |
| BitMEX | Volume |  | quote_or_contract | 1 | 1 |  | BTC pipeline treats BitMEX integer Volume as quote_or_contract; same rule reused. |
| Bitstamp | Volume |  | base | 1 | 0.038122 |  | Fractional continuous Volume matches BTC spot/base-volume rule. |
| Coinbase | Volume |  | base | 1 | 0.03664 |  | Fractional continuous Volume matches BTC spot/base-volume rule. |
| KuCoin | Volume | Amount | base | 1 | 0.011622 | 1 | Explicit quote/amount field matches Volume * OHLC4 price. |
| OKX | Volume | Volume (Quote) | base | 1 | 0.000216 | 1.00001 | Explicit quote/amount field matches Volume * OHLC4 price. |
| Combined_Index | Volume |  | not_applicable |  |  |  | Auxiliary combined index only. |

## Combined index auxiliary audit
| exchange | utc_start | utc_end | price_median | price_min | price_max |
| --- | --- | --- | --- | --- | --- |
| Combined_Index | 2016-09-29 00:00:00+00:00 | 2025-10-11 11:07:00+00:00 | 1276.34 | 5.9225 | 4953.93 |

## Sample selection
```json
{
  "sample": "ETHUSD 2021-2022 matched sample",
  "start": "2021-01-01 00:00:00+00:00",
  "end": "2022-12-31 23:59:00+00:00",
  "calendar_minutes": 1051200,
  "minimum_valid_exchanges_per_minute": 3,
  "valid_minutes_at_least_3": 1051200,
  "share_at_least_3_valid": 1.0,
  "valid_minutes_at_least_5": 1050966,
  "share_at_least_5_valid": 0.9997773972602739,
  "valid_minutes_all_7": 938607,
  "share_all_7_valid": 0.8928909817351598,
  "all_exchange_common_coverage_longest_start": "2021-05-19 00:00:00+00:00",
  "all_exchange_common_coverage_longest_end": "2021-05-20 21:11:00+00:00",
  "all_exchange_common_coverage_longest_minutes": 2712,
  "largest_continuous_usable_start": "2021-01-01 00:00:00+00:00",
  "largest_continuous_usable_end": "2022-12-31 23:59:00+00:00",
  "largest_continuous_usable_minutes": 1051200,
  "selected_sample_used_for_replication": "matched_2021_2022",
  "supplemental_window_identified_but_not_used_for_main_results": {
    "start": "2021-01-01 00:00:00+00:00",
    "end": "2022-12-31 23:59:00+00:00",
    "minutes": 1051200,
    "rule": "longest continuous run with at least 3 valid venues"
  }
}
```
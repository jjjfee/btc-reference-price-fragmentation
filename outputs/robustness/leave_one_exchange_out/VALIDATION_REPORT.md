# Leave-One-Exchange-Out Validation Report

## Executive summary
The leave-one-exchange-out validation preserves the main contrast in all 8 scenarios: yes.
Each scenario recomputes the effective minutes, dollar-volume weights, concentration measures, VWAP, LWMP, and pass-through quantities from the processed per-exchange data rather than deleting a venue from already-computed aggregates.
The Binance-excluded sample remains consistent with the mechanism: the LWMP pivot-change rate falls from 0.359 outside lock-in to 0.154 inside lock-in, and the lock-in LWMP kappa median is 1.000.
The BitMEX-excluded sample is also normal: its pivot-change ratio is 0.238, with VWAP lock-in kappa 0.679 and LWMP lock-in kappa 1.000.
The evidence therefore does not depend on Binance, and the validation does not identify any single exchange whose removal overturns the mechanism.
Diagnostics produced 481 PASS, 5 WARNING, and 0 FAIL flags; the warnings are data-quality or reporting cautions rather than failures of the core mechanism.

## Scenario-level findings
- FULL: valid minutes 1,051,200; lock-in share 55.5%; median max share 0.524; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=7, top dominant exchange=Binance (80.1%).
- EXCL_Binance: valid minutes 1,051,199; lock-in share 45.0%; median max share 0.479; verdict Main contrast preserved.
  EXCL_Binance is the central robustness check for venue dependence. It remains preserved, with non-lock-in pivot-change 0.359, lock-in pivot-change 0.154, and lock-in VWAP kappa 0.619.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=BitMEX (43.5%).
- EXCL_Bitfinex: valid minutes 1,051,200; lock-in share 60.1%; median max share 0.543; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (80.6%).
- EXCL_BitMEX: valid minutes 1,051,200; lock-in share 77.9%; median max share 0.624; verdict Main contrast preserved.
  EXCL_BitMEX passes the targeted check: non-lock-in pivot-change 0.302, lock-in pivot-change 0.072, ratio 0.238, VWAP kappa medians 0.442/0.679, and LWMP kappa medians 0.091/1.000.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (92.1%).
- EXCL_Bitstamp: valid minutes 1,051,200; lock-in share 58.2%; median max share 0.535; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (80.2%).
- EXCL_Coinbase: valid minutes 1,051,199; lock-in share 73.2%; median max share 0.603; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (82.3%).
- EXCL_KuCoin: valid minutes 1,051,199; lock-in share 64.2%; median max share 0.563; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (80.7%).
- EXCL_OKX: valid minutes 1,051,200; lock-in share 65.9%; median max share 0.569; verdict Main contrast preserved.
  Scenario summary cross-check: n_exchanges_used=6, top dominant exchange=Binance (82.4%).

## LWMP validation
Across scenarios, the non-lock-in baseline LWMP pivot-change rate ranges from 0.302 to 0.359, whereas the lock-in rate ranges from 0.072 to 0.154.
The lock-in/non-lock-in pivot-change ratio is always below one, ranging from 0.238 to 0.430, which indicates that pivot switchability declines materially in lock-in minutes.
The lock-in LWMP dominant-price pass-through median is 1.000 in every scenario, matching the one-half pivot lock-in prediction.

## VWAP validation
VWAP kappa medians are higher in lock-in than non-lock-in minutes in every scenario. Non-lock-in medians range from 0.397 to 0.443, while lock-in medians range from 0.619 to 0.679.
This is consistent with VWAP as continuous dominant-venue exposure: a dominant venue with larger weight mechanically receives larger pass-through.
The imported diagnostics also show that VWAP kappa equals max_share up to numerical precision in the fixed-weight price-displacement audit.

## Mathematical interpretation
For VWAP, write the dominant venue's share as m and price as p_d. Then

P_vwap = m p_d + (1-m) p_non_dom

so

P_vwap - p_d = (1-m)(p_non_dom - p_d).

In the dominant-price displacement audit with fixed weights, kappa_vwap = max_share.
For LWMP, the weighted median is the price whose cumulative weight first reaches 0.5. If max_share > 0.5, the dominant exchange must be the LWMP pivot, so lock-in dominant-price displacement should produce LWMP pass-through close to 1.

## Diagnostics
Diagnostic flag totals: PASS=481, WARNING=5, FAIL=0.
WARNING / FAIL details:
- WARNING [LOW] ORIG_DIAG_001 INPUT: Binance price_missing_or_nonpositive=0; dv_missing_or_nonpositive=81 (value=81.0; threshold=original run diagnostics status)
- WARNING [LOW] ORIG_DIAG_001 INPUT: BitMEX price_missing_or_nonpositive=0; dv_missing_or_nonpositive=17239 (value=17239.0; threshold=original run diagnostics status)
- WARNING [LOW] ORIG_DIAG_001 INPUT: Bitstamp price_missing_or_nonpositive=0; dv_missing_or_nonpositive=17660 (value=17660.0; threshold=original run diagnostics status)
- WARNING [LOW] ORIG_DIAG_001 INPUT: KuCoin price_missing_or_nonpositive=0; dv_missing_or_nonpositive=1136 (value=1136.0; threshold=original run diagnostics status)
- WARNING [LOW] ORIG_DIAG_001 INPUT: OKX price_missing_or_nonpositive=0; dv_missing_or_nonpositive=1714 (value=1714.0; threshold=original run diagnostics status)
These warnings do not alter the paper conclusion because they do not violate the core scenario, pivot-change, kappa, weight-sum, or event-count checks.

## Data sources
- main_contrast_summary: excel:main_contrast_summary
- diagnostics: excel:diagnostics
- lwmp_pivot_switchability: excel:lwmp_pivot_switchability
- settlement_pass_through: excel:settlement_pass_through
- scenario_summary: excel:scenario_summary
- dominant_distribution: excel:dominant_distribution
- spell_summary: excel:spell_summary
- vwap_proximity_bins: excel:vwap_proximity_bins

## Suggested paper text
### Leave-one-exchange-out validation
We assess whether the concentration mechanism is driven by any single venue by conducting a leave-one-exchange-out validation. For each of the seven exchanges, we remove that venue and recompute the effective minutes, dollar-volume weights, VWAP, LWMP, concentration measures, and dominant-price pass-through from the remaining processed exchange data. The main contrast is preserved in every leave-one-out sample: lock-in minutes exhibit substantially lower LWMP pivot switchability than non-lock-in minutes, while the LWMP dominant-price pass-through remains concentrated near one. Excluding Binance does not overturn the result, indicating that the evidence is not uniquely driven by the largest spot venue in the sample. Similarly, excluding BitMEX or any other individual exchange leaves the benchmark behavior intact. VWAP continues to behave as a continuous dominant-venue exposure rule: its pass-through rises with the dominant venue's dollar-volume share and matches the max-share identity in the fixed-weight displacement audit. LWMP continues to behave as a one-half pivot rule: once a venue's share exceeds one half, the dominant venue becomes the weighted-median pivot and its price displacement is passed through nearly one-for-one. These results support the interpretation that benchmark concentration is an aggregation-rule channel rather than an artifact of any single exchange's inclusion.

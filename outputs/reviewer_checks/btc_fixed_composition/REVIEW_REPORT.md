# BTC fixed-composition review report

## Executive finding

The original 800,000-event headline is exactly reproducible from the verified minute-level inputs and current code path.  The fixed-composition results below separate input availability from venue-weight concentration; no existing BTC, ETH, Word, PDF, or TXT artifact was edited.

## Input lineage and preprocessing

| exchange | raw_source_path | path | volume_convention | deduplicated_minutes |
|---|---|---|---|---|
| Binance | data\external\raw\btc\BTCUSD_1m_Binance.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_Binance_2021_2022_with_DV.csv | base | 1050207 |
| Bitfinex | data\external\raw\btc\BTCUSD_1m_Bitfinex.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_Bitfinex_2021_2022_with_DV.csv | base | 1046023 |
| BitMEX | data\external\raw\btc\BTCUSD_1m_BitMEX.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_BitMEX_2021_2022_with_DV.csv | quote_or_contract | 1051200 |
| Bitstamp | data\external\raw\btc\BTCUSD_1m_Bitstamp.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_Bitstamp_2021_2022_with_DV.csv | base | 1051200 |
| Coinbase | data\external\raw\btc\BTCUSD_1m_Coinbase.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_Coinbase_2021_2022_with_DV.csv | base | 1051053 |
| KuCoin | data\external\raw\btc\BTCUSD_1m_KuCoin.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_KuCoin_2021_2022_with_DV.csv | base | 1051200 |
| OKX | data\external\raw\btc\BTCUSD_1m_OKX.csv | <PROJECT_ROOT>\dv_ready_2021_2022\BTCUSD_1m_OKX_2021_2022_with_DV.csv | base | 1051200 |

- Window: 2021-01-01 00:00 through 2022-12-31 23:59 UTC.
- Representative venue price: OHLC4 when all four fields exist, otherwise HL2, otherwise Close; prices are aligned to the Binance anchor scale by the existing input builder.
- Volume convention: the six non-BitMEX venues are `base`, so `DV_usd = volume x p_usd_scaled`; BitMEX is `quote_or_contract`, so `DV_usd = volume x 1.0`.
- Validity: finite price, finite DV weight, and strictly positive DV weight.  Invalid venue weights are set to zero for that minute; the remaining positive weights are normalized by their minute total.

## Direct answers

1. The original events come from `1,050,207` minutes on the Binance-anchored first-file index with at least three valid venues.  A uniform, unstratified, without-replacement sample selects 100,000 minutes using seed 42.  The remaining 993 calendar minutes are assessed separately in the availability audit.
2. Yes: 800,000 = 100,000 x 8 exactly.
3. Base-minute sampling is simple random sampling without replacement; it is not stratified by lock-in.
4. Each minute generates eight events: two shock types x four gamma values.
5. One venue is drawn uniformly among that minute's valid venues and is held fixed across its eight events; it is not necessarily the dominant or pivot venue.
6. `inflate_only`: `w'_j=(1+gamma)w_j`, others unchanged.  `reallocate_total_fixed`: cap `w'_j` at `(1-1e-9)W`, then scale every other valid venue proportionally so the total remains `W`.
7. The code does not reject or redraw infeasible positive reallocations; it caps them.  All present-grid events remain pooled.
8. Every event has equal weight.  With 100,000 observations in each of eight cells, each cell receives weight 1/8.
9. Reproduced rates are 0.27927641929248886 and 0.067677368212445507; difference -0.21159905108004334; ratio 0.24233112263433296.  All are within 1e-10 of the requested values.
10. Valid-venue-count distribution is shown below.
11. The direction of the over-half gradient across venue counts is visible in the table and Figure `Fig_BTC_overhalf_by_valid_venue_count`: fewer venues have the reported count-specific rates; the conclusion is based on those numeric rates, not a pooled label.
12. All-seven-valid minutes: 1,008,835, or 95.969844% of calendar minutes.
13. All-seven over-half share: 0.545046514048.
14. All-seven longest over-half spell: 787 minutes.
15. All-seven non-lock-in / lock-in rates: 0.276711794804 / 0.069347538696.
16. All-seven difference / ratio: -0.207364256108 / 0.250612875917.
17. All-seven difference CI: 1-day [-0.212423933291, -0.202317877366], 7-day [-0.216585810403, -0.197440259866].  Zero is excluded by both.
18. All-seven VWAP proximity endpoints: q95 0.00125112949737 to 9.92218467539e-05, ratio 0.0793058168336.
19. All-seven lock-in LWMP median pass-through at +0.1%: 1; it is equal to 1 within 1e-8.
20. Only the all-seven exact set meets the 50,000-minute DV-only threshold, and its -0.207364256108 rate difference remains present.  Descriptive exact-set rows never combine active sets.
21. The two additional >=10,000-minute exact-six sets differ visibly in over-half frequency: 0.707084220128 when Bitstamp is missing and 0.940119002405 when BitMEX is missing, versus 0.545046514048 for all seven.  Neither exact-six set is large enough for the pre-specified DV-only headline threshold.
22. Six base-volume venues, all six valid: over-half 0.77727635163; non-lock-in / lock-in rates 0.266062326746 / 0.0615629105804; difference -0.204499416166; ratio 0.231385297322.
23. The shift from baseline over-half 0.554973448092 to all-seven 0.545046514048 is -0.00992693404328 (all-seven minus baseline), or -0.992693 percentage points and -1.78872% relative to baseline.  This restriction comparison is not a causal decomposition, but it shows that input availability explains only a small part of the pooled 55.5% frequency under the maintained weighting definitions.
24. Input missingness does not overturn the mechanism result: the difference moves from -0.21159905108 to -0.207364256108, and both all-seven block CIs exclude zero.
25. Excluding BitMEX and requiring all six base-volume venues valid leaves the exact numeric contrast in item 22, so the BitMEX convention does not overturn the rate ordering.  The older relaxed-availability leave-one-out comparison reported non-lock-in / lock-in 0.301638900176 / 0.071915484269; it is not the same sample restriction.
26. The code audit found disclosure issues, not a hidden event-count mismatch: the headline pool is anchored to Binance and omits 993 calendar minutes absent from its file; total-fixed infeasibility is handled by capping; and the later standalone bootstrap seed (20260710) differs from the event seed (42).  These facts should be stated explicitly.
27. Main text: report the all-seven valid-minute count/share, baseline-to-all-seven over-half change, and all-seven headline difference with 1-day/7-day CIs.
28. Online appendix: full valid-count, exact-composition, cell-count, VWAP-proximity, pass-through, six-base-volume, and validation tables plus both supplementary figures.
29. Additional venue-rescaling sensitivity is not required to answer missingness/fixed-composition once the six-base-volume fixed sample is shown; it is optional only if the referee specifically challenges cross-venue DV scale calibration.
30. The referee concern can be answered if all validation rows are PASS/WARN and no FAIL remains.  Current counts: PASS=29, WARN=0, FAIL=0.

## Valid venue count distribution

| valid_venue_count | minutes | original_valid_minutes | share_of_calendar_minutes | share_of_original_valid_minutes | over_half_minutes | over_half_share | at_or_below_half_minutes | at_or_below_half_share | median_max_share | p95_max_share | dominant_exchange_distribution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 1 | 1 | 9.51293759513e-07 | 9.52193234286e-07 | 1 | 1 | 0 | 0 | 0.857014991051 | 0.857014991051 | {"Binance":1.0} |
| 4 | 42 | 41 | 3.99543378995e-05 | 3.90399226057e-05 | 41 | 0.97619047619 | 1 | 0.0238095238095 | 0.925767666001 | 0.974882461237 | {"Binance":0.9523809523809523,"BitMEX":0.023809523809523808,"Coinbase":0.023809523809523808} |
| 5 | 1695 | 1673 | 0.00161244292237 | 0.00159301928096 | 1597 | 0.942182890855 | 98 | 0.0578171091445 | 0.891180341005 | 0.970929663995 | {"Binance":0.9545722713864306,"BitMEX":0.019469026548672566,"Bitfinex":0.0011799410029498525,"Coinbase":0.01415929203539823,"KuCoin":0.004129793510324484,"OKX":0.006489675516224189} |
| 6 | 40627 | 39657 | 0.0386482115677 | 0.0377611270921 | 31842 | 0.783764491594 | 8785 | 0.216235508406 | 0.753843536966 | 0.944786039402 | {"Binance":0.8585177345115318,"BitMEX":0.08230979397937332,"Bitfinex":0.0038890393088340264,"Bitstamp":0.0009845669136288675,"Coinbase":0.02227582642085313,"KuCoin":0.010165653383218056,"OKX":0.02185738548256086} |
| 7 | 1008835 | 1008835 | 0.959698439878 | 0.960605861511 | 549862 | 0.545046514048 | 458973 | 0.454953485952 | 0.518730369782 | 0.870981853054 | {"Binance":0.7987659032448319,"BitMEX":0.1326183171678223,"Bitfinex":0.006363776038698103,"Bitstamp":0.0013758444145970353,"Coinbase":0.026341274836816725,"KuCoin":0.006449022882830195,"OKX":0.028085861414403744} |

## Eligible fixed-composition descriptive rows

| active_venue_set | missing_venue_set | valid_venue_count | valid_minutes | number_of_UTC_days | share_max_share_gt_0p5 | median_max_share | p95_max_share | median_HHI | p95_HHI | dominant_exchange_distribution | median_spell | p95_spell | maximum_spell | descriptive_threshold_met | dvonly_threshold_met | bootstrap_day_threshold_met |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Binance\|Bitfinex\|BitMEX\|Bitstamp\|Coinbase\|KuCoin\|OKX |  | 7 | 1008835 | 730 | 0.545046514048 | 0.518730369782 | 0.870981853054 | 0.354587107519 | 0.765200920956 | {"Binance":0.7987659032448319,"BitMEX":0.1326183171678223,"Bitfinex":0.006363776038698103,"Bitstamp":0.0013758444145970353,"Coinbase":0.026341274836816725,"KuCoin":0.006449022882830195,"OKX":0.028085861414403744} | 1 | 8 | 787 | True | True | True |
| Binance\|Bitfinex\|BitMEX\|Coinbase\|KuCoin\|OKX | Bitstamp | 6 | 16445 | 643 | 0.707084220128 | 0.642050798421 | 0.924714386041 | 0.469431968788 | 0.857379877833 | {"Binance":0.8248099726360596,"BitMEX":0.10757069017938584,"Bitfinex":0.0044390392216479176,"Coinbase":0.02091821222256005,"KuCoin":0.015567041653998175,"OKX":0.026695044086348433} | 1 | 2 | 55 | True | False | True |
| Binance\|Bitfinex\|Bitstamp\|Coinbase\|KuCoin\|OKX | BitMEX | 6 | 15798 | 489 | 0.940119002405 | 0.864502872945 | 0.956953061135 | 0.75721986249 | 0.916723570704 | {"Binance":0.9698696037473098,"Bitfinex":0.0016457779465755158,"Bitstamp":0.00044309406253956196,"Coinbase":0.014685403215596912,"KuCoin":0.0037979491074819596,"OKX":0.009558171920496265} | 1 | 3 | 281 | True | False | True |

## Eligible fixed-composition pivot rows

| active_venue_set | valid_minutes | non_lockin_pivot_change_rate | lockin_pivot_change_rate | difference_lockin_minus_nonlockin | rate_ratio_lockin_over_nonlockin |
|---|---|---|---|---|---|
| Binance\|Bitfinex\|BitMEX\|Bitstamp\|Coinbase\|KuCoin\|OKX | 1008835 | 0.276711794804 | 0.069347538696 | -0.207364256108 | 0.250612875917 |

## Reproducibility and implementation notes

- Original headline source: `experiments_dvonly/audit_lockin/audit_lockin_summary.csv`.
- Existing event source: `experiments_dvonly/dvon_injection_shift_samples.csv`.
- Event seed: 42.  Existing standalone block-bootstrap seed: 20260710.  New sensitivity bootstrap seed: 42, per the requested fixed-composition command.
- Figure 1 subset is `inflate_only`, gamma=1.0 (100,000 events); the headline is pooled over all eight cells (800,000 events).
- No event is removed for infeasibility.  The total-fixed positive shock is capped when necessary.

## Minimal paper revision

Add one compact main-text paragraph with the all-seven coverage, over-half share, headline contrast, and both block CIs.  Add a methods sentence stating the unstratified 100,000-minute sample, seed 42, uniform valid-venue draw, eight events per minute, proportional total-fixed reallocation with the `(1-1e-9)W` cap, and equal event pooling.  Place the remaining tables and two figures in the online appendix.

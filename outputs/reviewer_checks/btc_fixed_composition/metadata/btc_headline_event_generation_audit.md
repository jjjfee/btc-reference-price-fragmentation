# BTC headline event-generation audit

## Traceable code path

1. `make_dv_2021_2022.py` constructs venue prices by OHLC4 -> HL2 -> Close and DV inputs.
2. `run_dv_only_injection_experiments.py` reads the seven DV-ready files, applies the price/weight-validity rule, samples minutes, chooses the shocked venue, creates eight cells, and writes `experiments_dvonly/dvon_injection_shift_samples.csv`.
3. `audit_lockin_and_build_dvonly_inference.py` merges the events with `experiments/weight_concentration_minute_level.csv` through the HHI panel and defines `lock_in = 1[max_share > 0.5]`.
4. `run_day_block_bootstrap.py` groups events into UTC 1-day or 7-day blocks; all events attached to one minute stay in one block.

Key source locators in `run_dv_only_injection_experiments.py`: seed line 27, sample line 193, venue-draw line 204, inflate line 219, reallocation line 221, pivot-change line 260.

## Sampling and event counts

- Candidate valid minutes: 1,050,207.  The current code obtains this count because the first sorted input (Binance) fixes the DataFrame index before the other six venues are assigned; the 993 calendar minutes absent from Binance never enter the headline candidate pool even when at least three other venues are valid.
- Base minutes: 100,000 (target 100,000).
- Method: unstratified simple random sample without replacement.
- Seed: 42.
- Per-minute events: 2 shock types x 4 gamma values = 8.
- Total events: 800,000.
- Lock-in stratification: none.  Lock-in is attached after sampling from the structural minute panel.
- Sample probability: 0.0952193234286 for every candidate minute.

## Perturbation behavior

`inflate_only` changes only the selected venue's raw DV weight.  `reallocate_total_fixed` changes the selected venue and proportionally rescales all other valid venues; it has no single counterparty.  Positive shocks that would make the selected venue consume the total are capped at `(1 - 1e-9) W`.  Events are not deleted, rejected, or resampled.  See `btc_event_formula_manifest.md` for the equations.

## Pooled headline reproduction

- Non-lock-in rate: 0.27927641929248886.
- Lock-in rate: 0.067677368212445507.
- Lock-in minus non-lock-in: -0.21159905108004334.
- Rate ratio: 0.24233112263433296.
- Row-level key mismatches versus the existing 800,000-event file: 0.
- Maximum shocked-share difference before/after: 4.440892098500626e-16 / 3.219646771412954e-15.

The rates are event-level pooled rates, not the probability that a minute switches under at least one perturbation.  Every event has equal weight.  Since all cells contain the same number of base minutes, each cell has weight `1/8` in the pooled rate.

## Figure subset versus pooled headline

The existing main-text LWMP boundary figure filters to `shock_type=inflate_only` and `gamma=1.0`, i.e. 100,000 events.  The 0.279276 / 0.067677 headline contrast pools all 800,000 events across both shock types and all four gamma values.

## Cell counts

| shock_type | delta_w_or_gamma | base_minute_count | attempted_events | admissible_events | rejected_events | rejection_reason | cap_applied_events | pivot_change_count | pivot_change_rate | lock_in_event_count | non_lock_in_event_count | non_lockin_pivot_change_count | non_lockin_pivot_change_rate | lockin_pivot_change_count | lockin_pivot_change_rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| inflate_only | 0.5 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 0 | 9302 | 0.09302 | 55506 | 44494 | 8000 | 0.179799523531 | 1302 | 0.0234569235758 |
| inflate_only | 1 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 0 | 14598 | 0.14598 | 55506 | 44494 | 11944 | 0.268440688632 | 2654 | 0.0478146506684 |
| inflate_only | 2 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 0 | 21848 | 0.21848 | 55506 | 44494 | 16575 | 0.372522137816 | 5273 | 0.0949987388751 |
| inflate_only | -0.5 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 0 | 11595 | 0.11595 | 55506 | 44494 | 9520 | 0.213961433002 | 2075 | 0.0373833459446 |
| reallocate_total_fixed | 0.5 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 3946 | 11635 | 0.11635 | 55506 | 44494 | 9813 | 0.220546590552 | 1822 | 0.0328252801499 |
| reallocate_total_fixed | 1 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 7935 | 17855 | 0.17855 | 55506 | 44494 | 13978 | 0.31415471749 | 3877 | 0.0698483046878 |
| reallocate_total_fixed | 2 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 14906 | 26672 | 0.26672 | 55506 | 44494 | 19028 | 0.427653166719 | 7644 | 0.137714841639 |
| reallocate_total_fixed | -0.5 | 100000 | 100000 | 100000 | 0 | none; infeasible positive reallocations are capped, not rejected | 0 | 15956 | 0.15956 | 55506 | 44494 | 10551 | 0.237133096597 | 5405 | 0.0973768601593 |

## Bootstrap distinction

The original event generator's seed is 42. The standalone Appendix B block-bootstrap files now archived under `outputs/robustness` use seed 20260710. New fixed-composition bootstraps use seed 42 while preserving the same UTC-block algorithm.

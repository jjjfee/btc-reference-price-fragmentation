# BTC DV-only event formula manifest

- Executed source lineage: `<PROJECT_ROOT>\run_dv_only_injection_experiments.py` (`main`, sampling, and shock loop).
- Event seed: `42`.
- Base-minute target: `100,000`.
- Candidate index: the actual generator anchors its wide DataFrame to the first sorted file (Binance), so later venues do not expand the time index.  Within that 1,050,207-timestamp index, minutes must have at least three valid venues.
- Sampling: uniform simple random sample without replacement from that candidate index; no lock-in stratification.
- Shocked venue: one venue drawn uniformly among the valid venues of each sampled minute, then held fixed across that minute's eight cells.
- Shock types: `['inflate_only', 'reallocate_total_fixed']`.
- Gamma order: `[0.5, 1.0, 2.0, -0.5]`.  `gamma` is the fractional change in the shocked venue's raw DV weight; factors are `1 + gamma`.

## `inflate_only`

For shocked venue `j`, `w'_j = (1 + gamma) w_j`; for every `k != j`, `w'_k = w_k`.  Prices are fixed.  The total DV changes and aggregator weights are normalized internally by their new total.

## `reallocate_total_fixed`

Let `W = sum_k w_k`, `r = W - w_j`, and `raw = (1 + gamma) w_j`.  The implemented code first sets `w'_j = min(raw, (1 - 1e-9) W)`.  For every `k != j`, `w'_k = w_k (W - w'_j) / r`.  Thus all other valid venues jointly serve as the counterparty in proportion to their original weights and the total remains `W` (up to floating point error).

There is no row-level rejection, deletion, or resampling rule.  Positive reallocations that would exhaust the other venues are capped; all eight cells remain in the pooled dataset.  The present gamma grid has `1 + gamma > 0`, so negative weights are not created.

The existing generator has no separate Boolean admissibility predicate: every attempted event on the present grid is retained and therefore counted as admissible.  Initial venues already satisfy finite price, finite weight, and strictly positive weight; the gamma grid preserves nonnegative shocked weights, and the cap makes positive total-fixed shocks executable.

## Pivot and pooling

Liquidity-Weighted Median Price (LWMP) uses synchronized dollar-volume proxy weights to represent relative venue liquidity. Under the lower weighted-median convention, LWMP sorts valid venue prices stably and selects the first price whose cumulative raw DV weight reaches at least half the raw total.  `pivot_changed = 1` exactly when both pre/post pivots exist and their venue-column indices differ.  The headline rates are event-weighted means over all eight cells.  Because every sampled minute contributes exactly one event to every cell and no event is removed, this is also an equal `1/8` weighting of the cells, but it is not minute-level any-shock switchability.

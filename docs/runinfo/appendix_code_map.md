# Appendix A–L code map

| Appendix | Current heading | Entry point | Repository evidence |
|---|---|---|---|
| A | Perturbation and Classification Sensitivity | `src/audit/run_threshold_robustness.py` | `outputs/appendix/A/` |
| B | Subsample and Temporal-Dependence Validation | `src/audit/run_subsample_robustness.py`, `src/experiments/run_day_block_bootstrap.py` | `outputs/appendix/B/`, `outputs/robustness/bootstrap_1day/`, `outputs/robustness/bootstrap_7day/` |
| C | Structural-Exclusion Validation | `src/audit/run_exclude_binance.py` | `outputs/appendix/C/` |
| D | LWMP Mechanism Audit: Majority-Weight Pivot Guarantee | `src/audit/audit_lockin_and_build_dvonly_inference.py` | `outputs/appendix/D/` |
| E | Supplementary VWAP Evidence: Observed Proximity and Perturbation Responses | VWAP audit and plotting scripts under `src/audit/` | `outputs/appendix/E/` |
| F | Implementation Consistency of the Majority-Weight State | `src/audit/rebuild_observed_lockin_persistence.py` | `outputs/appendix/F/` |
| G | Fixed-Weight Dominant-Price Displacement Pass-Through | `src/audit/run_price_displacement_audit.py` | `outputs/appendix/G/` |
| H | Leave-One-Exchange-Out Validation | `src/audit/run_leave_one_exchange_out_validation.py` | `outputs/robustness/leave_one_exchange_out/` |
| I | BTCUSD Post-2022 Out-of-Sample Replication | `src/experiments/run_btc_post2022_replication.py` | `outputs/robustness/btc_post2022/` |
| J | Matched ETHUSD Cross-Asset Replication | `src/experiments/run_eth_replication.py` | `outputs/robustness/eth_matched/` |
| K | ETHUSD Targeted Venue Exclusions | `src/experiments/run_eth_exclude_binance.py` | `outputs/robustness/eth_exclude_binance/` |
| L | Event Construction and Fixed-Composition BTCUSD Checks | `src/audit/run_btc_fixed_composition_checks.py` | `outputs/reviewer_checks/btc_fixed_composition/` |

The authoritative file-level list is `outputs/metadata/output_manifest.json`. Large source and event-level files are intentionally not represented as committed artifacts.

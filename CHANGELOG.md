# Changelog

## Unreleased

### Reviewer-check reproducibility repair

- Corrected the fixed-composition checker’s audited source path and removed machine-specific raw-path inference.
- Added explicit `--input-dir` and `--raw-dir` handling with differentiated path, venue, and column diagnostics.
- Added a synthetic standard-library smoke test and a lightweight GitHub Actions workflow.
- Documented no-data validation versus high-cost raw reconstruction and recorded the tested environment.
- Added a local external-input hashing utility and clearly qualified current-snapshot BTC/ETH hashes.

## 0.3.0 - 2026-07-21

### Economics Letters submission replication update

- Reconciled repository claims with the current submitted manuscript and online Appendix A–L.
- Added selected later-BTCUSD, matched-ETHUSD, targeted ETH exclusion, and leave-one-exchange-out validation materials.
- Added all-seven-valid and six-base-volume/exclude-BitMEX fixed-composition checks.
- Added one-day and seven-day block-bootstrap summaries and fixed-weight dominant-price displacement materials.
- Added the 29-PASS reviewer-check report and metadata.
- Parameterized or replaced machine-specific paths and added portable defaults.
- Added source-data manifests, an A–L code/output map, a machine-readable output manifest, and lightweight exact-value validation.

## 0.2.0 - 2026-05-21

- Initial public replication and selected-output archive for the BTCUSD analysis.

# Kaggle ETHUSD source-data manifest

## Source

- Dataset: Ethereum ETH, 7 Exchanges, 1m Full Historical Data
- URL: https://www.kaggle.com/datasets/imranbukhari/comprehensive-ethusd-1m-data/data
- Access date used in the manuscript: 13 July 2026
- Reported dataset license: CC BY-SA 4.0
- Target frequency and window: one minute, UTC, 2021-01-01 through 2022-12-31
- Redistribution: raw files are not included in this repository.

## Expected files

Expected venue files are `ETHUSD_1m_<Venue>.csv` for Binance, Bitfinex, BitMEX, Bitstamp, Coinbase, KuCoin, and OKX. `ETHUSD_1m_Combined_Index.csv` may also be present, but it is audit-only: it is never admitted to the venue set, weights, dominant venue, pivot, VWAP, LWMP, max share, or HHI.

Expected fields include a minute timestamp, Open, High, Low, Close, and Volume. Some files also include quote-volume fields. The runner records the actual columns in `outputs/robustness/eth_matched/data_audit/eth_column_schema.csv` and uses OHLC4 where the four price fields are available.

Base-volume venues use `DV = Volume × venue price`. BitMEX uses the audited quote-or-contract convention. Invalid prices or weights are excluded venue-by-venue; no missing venue observation is interpolated.

Raw-file cryptographic hashes were not retained by the saved ETH workflow, so this manifest does not invent them. File sizes, row counts, columns, filters, date coverage, and volume conventions are preserved under `outputs/robustness/eth_matched/data_audit/` and `outputs/robustness/eth_matched/metadata/`.

## Downstream generators

- `src/experiments/run_eth_replication.py`
- `src/experiments/run_eth_exclude_binance.py`

Selected summaries and reports are committed under `outputs/robustness/eth_matched/` and `outputs/robustness/eth_exclude_binance/`; processed and event-level files are excluded.

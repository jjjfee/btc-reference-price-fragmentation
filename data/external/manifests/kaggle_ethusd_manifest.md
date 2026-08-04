# Kaggle ETHUSD source-data manifest

## Source

- Dataset: Ethereum ETH, 7 Exchanges, 1m Full Historical Data
- URL: https://www.kaggle.com/datasets/imranbukhari/comprehensive-ethusd-1m-data/data
- Access date used for the paper: 13 July 2026
- Reported dataset license: CC BY-SA 4.0
- Target frequency and window: one minute, UTC, 2021-01-01 through 2022-12-31
- Redistribution: raw files are not included in this repository.

## Expected files

Expected venue files are `ETHUSD_1m_<Venue>.csv` for Binance, Bitfinex, BitMEX, Bitstamp, Coinbase, KuCoin, and OKX. `ETHUSD_1m_Combined_Index.csv` may also be present, but it is audit-only: it is never admitted to the venue set, weights, dominant venue, pivot, VWAP, LWMP, max share, or HHI.

Expected fields include a minute timestamp, Open, High, Low, Close, and Volume. Some files also include quote-volume fields. The runner records the actual columns in `outputs/robustness/eth_matched/data_audit/eth_column_schema.csv` and uses OHLC4 where the four price fields are available.

Base-volume venues use `DV = Volume × venue price`. BitMEX uses the audited quote-or-contract convention. Invalid prices or weights are excluded venue-by-venue; no missing venue observation is interpolated.

Raw-file cryptographic hashes were not retained by the saved ETH workflow, so this manifest does not invent them. File sizes, row counts, columns, filters, date coverage, and volume conventions are preserved under `outputs/robustness/eth_matched/data_audit/` and `outputs/robustness/eth_matched/metadata/`.

## Current retained local snapshot (not historical proof)

On 23 July 2026, the eight raw ETH CSVs still retained in the analysis workspace were hashed with
`scripts/final/hash_external_inputs.py`. The eighth file is the audit-only Combined Index described
above. These values identify the files present on that date; because hashes were not captured at the
original access/run date, they do **not** establish byte identity with a historical Kaggle version or
the paper input.

No Kaggle version identifier was retained with these local files, so none is inferred.

| Filename | Bytes | Current-snapshot SHA-256 |
|---|---:|---|
| `ETHUSD_1m_Binance.csv` | 551391849 | `36ab123cad8b1031e00edb1a90a9b63887ef034f0f54b51aa5c843740efbd84c` |
| `ETHUSD_1m_Bitfinex.csv` | 235790952 | `e0d4585357592e18e3cbeb57ec277a8ec5f39fd1077bd4ce30d967ac9c89e948` |
| `ETHUSD_1m_BitMEX.csv` | 209305778 | `2392ac3521e41e9d78bc3638dad3d981c9aef7189bbec467ea6976485fe44313` |
| `ETHUSD_1m_Bitstamp.csv` | 246009265 | `993c0b2ebad80ee8b221d9eda68e3457e97d5d597661e4904b55dcea79a5b326` |
| `ETHUSD_1m_Coinbase.csv` | 283607924 | `93e34936889dd12e3ddde990a135c80ff077e94ea7f4d35c3e824fda89564d7e` |
| `ETHUSD_1m_Combined_Index.csv` | 303704833 | `4e15fdcd2473c5a2710a271680a8a57e5a81dcc985acac7cb4b76377f108ab85` |
| `ETHUSD_1m_KuCoin.csv` | 297223210 | `5e14109ec360269788e8fa18d3988c5642f20985fcb2ff002d7931ba86ee0e5b` |
| `ETHUSD_1m_OKX.csv` | 378105119 | `7d1502ffa4618a6c3e7bcfe9dfd9d66b0cfe72d9cdfac3cc59238f7f1cfa927d` |

Users can hash their own download without storing absolute paths:

```bash
python scripts/final/hash_external_inputs.py --raw-dir data/external/raw/eth --output local_eth_hashes.json
```

## Downstream generators

- `src/experiments/run_eth_replication.py`
- `src/experiments/run_eth_exclude_binance.py`

Selected summaries and reports are committed under `outputs/robustness/eth_matched/` and `outputs/robustness/eth_exclude_binance/`; processed and event-level files are excluded.

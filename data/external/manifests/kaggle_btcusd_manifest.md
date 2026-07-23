# Kaggle BTCUSD source-data manifest

## Source

- Dataset: Comprehensive BTCUSD 1m Data
- URL: https://www.kaggle.com/datasets/imranbukhari/comprehensive-btcusd-1m-data
- Access date used in the manuscript: 16 May 2026
- Reported license: CC BY-SA 4.0
- Target frequency and window: one minute, UTC, 2021-01-01 through 2022-12-31 for the baseline; later observations are used by Appendix I.
- Redistribution: raw files are not included in this repository.

## Expected files and columns

Expected raw names are `BTCUSD_1m_<Venue>.csv` for Binance, Bitfinex, BitMEX, Bitstamp, Coinbase, KuCoin, and OKX. Preprocessing detects the timestamp and OHLC/close/volume fields, harmonizes prices, removes duplicate minutes, and does not interpolate missing venue observations.

The processed convention is `time_utc`, `p_usd_scaled`, `DV_usd`, and a volume-unit diagnostic. Base-volume venues use price × volume. BitMEX is handled as quote-or-contract dollar volume after diagnostics.

## Available downstream hashes

The saved workflow did not preserve raw-file hashes, so none are invented. It did preserve SHA-256 hashes for the seven processed 2021–2022 venue files:

| Venue | Processed SHA-256 |
|---|---|
| Binance | `d7fe8f54ab0d1249c844df27422f16150c46564f62f31edbbd13dddde043acba` |
| Bitfinex | `c025317fd381e6c67bbfc52fc24244d193dec5af58973cf37b0e7a5b5969379c` |
| BitMEX | `d2a97c2dbcd418c7c09f3458264add23130ca5a5691f0a6ac9a7a5a961d829f4` |
| Bitstamp | `d9f71681dcb7b9271fefc01e098e81dbc097145ece9595be4fc2433ee921a6e8` |
| Coinbase | `7fc88bc24901754b5cb7421393621c12ad1e2379da4bf162d0cdc698c08bc9dc` |
| KuCoin | `a67512ff4b63cc7870988a6288ffff27a3a75df284e3243887d139209ff014df` |
| OKX | `1392af608a6a8334b1d6782feb9bf27b0c53e761aa1dfbb759fa3a40afa1639e` |

The complete saved file-size, row-count, schema, and convention record is `outputs/reviewer_checks/btc_fixed_composition/metadata/btc_input_file_manifest.csv`.

## Current retained local snapshot (not historical proof)

On 23 July 2026, the seven raw BTC CSVs still retained in the analysis workspace were hashed with
`scripts/final/hash_external_inputs.py`. These values identify those files as they existed on that
date. Because raw hashes were not captured at the original manuscript access/run date, they do
**not** prove that a later download, a Kaggle dataset version, or the historical manuscript input is
byte-identical.

No Kaggle version identifier was retained with these local files, so none is inferred.

| Filename | Bytes | Current-snapshot SHA-256 |
|---|---:|---|
| `BTCUSD_1m_Binance.csv` | 585317938 | `d28d8c6880a0a1078a784ebeb16068fc3dc47e91c0f01755979a7e601be31420` |
| `BTCUSD_1m_Bitfinex.csv` | 345495655 | `7daf95a9d0cd1c6818df36e5c670a710e84acd5c5b8abd607bd3409eb8beacf9` |
| `BTCUSD_1m_BitMEX.csv` | 309762241 | `78a63dff925d2ba98f364844dbceca99724efcce7a7092de969cf0fefb2af6b8` |
| `BTCUSD_1m_Bitstamp.csv` | 438763448 | `1fcf4c5b4f456c1c667f22470145bdf27657a921bccf7f601b90c5b399c4a6e2` |
| `BTCUSD_1m_Coinbase.csv` | 339813545 | `60feb25fabd35e06c2ea9e72e2873970e85179ea104fddba55c1e79886c988fa` |
| `BTCUSD_1m_KuCoin.csv` | 309912036 | `7d8511821383bc4ab6cadf8286deb5d1bd9bd59a483585e1377091760601f2ff` |
| `BTCUSD_1m_OKX.csv` | 400789585 | `f0469574ad8c5d7f5cc2594b1b63b158f1f34ce5a4d92bdc53ea710e1e0fb7cf` |

Users can hash their own download without storing absolute paths:

```bash
python scripts/final/hash_external_inputs.py --raw-dir data/external/raw/btc --output local_btc_hashes.json
```

## Downstream generators

- `src/build/make_dv_2021_2022.py`
- `src/build/build_aggregated_prices.py`
- `src/build/weight_concentration_check.py`
- `src/build/build_hhi_trend_panel.py`
- `src/experiments/run_dv_only_injection_experiments.py`
- `src/experiments/run_btc_post2022_replication.py`

Generated raw-derived panels and event-level files remain outside version control.

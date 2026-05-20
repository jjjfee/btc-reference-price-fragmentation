# Kaggle BTCUSD Source-Data Manifest

This manifest documents the external raw data source used for the paper:

**When Multi-Venue Benchmarks Become Effectively Concentrated: Evidence from Fragmented BTCUSD Markets**

The raw data are not redistributed in this repository. This file records the source, access information, expected venue files, and data-convention notes needed to reproduce the processed BTCUSD benchmark-mapping panel.

---

## 1. External data source

Dataset name:

**Comprehensive BTCUSD 1m Data**

Dataset URL:

https://www.kaggle.com/datasets/imranbukhari/comprehensive-btcusd-1m-data

Access date used in the paper:

**16 May 2026**

License reported in the manuscript data-availability statement:

**CC BY-SA 4.0**

Users should download the raw files directly from Kaggle. The raw files are intentionally excluded from this repository.

---

## 2. Venue coverage

The empirical panel uses BTCUSD minute-level files for seven venues:

| Venue | Expected raw-file naming pattern |
|---|---|
| Binance | `BTCUSD_1m_Binance.csv` |
| Bitfinex | `BTCUSD_1m_Bitfinex.csv` |
| BitMEX | `BTCUSD_1m_BitMEX.csv` |
| Bitstamp | `BTCUSD_1m_Bitstamp.csv` |
| Coinbase | `BTCUSD_1m_Coinbase.csv` |
| KuCoin | `BTCUSD_1m_KuCoin.csv` |
| OKX | `BTCUSD_1m_OKX.csv` |

The exact filenames may differ depending on the Kaggle download package. If filenames differ, update the input-path or exchange-name parsing logic in the relevant preprocessing script.

---

## 3. Sample period and frequency

Target sample period:

```text
2021-01-01 to 2022-12-31
```

Frequency:

```text
1 minute
```

Timestamp convention:

```text
UTC
```

The preprocessing scripts parse timestamps to UTC, align exchange-level observations to a common minute grid, and do not interpolate missing venue-minute observations.

---

## 4. Raw data redistribution policy

The following files are not redistributed in this repository:

- raw Kaggle CSV files;
- full venue-level processed files;
- large benchmark-panel files;
- large dollar-volume-only perturbation samples;
- large intermediate audit files.

Users should obtain the raw Kaggle files directly and run the preprocessing scripts locally.

---

## 5. Processed file convention

The main preprocessing stage produces venue-level files with a naming convention such as:

```text
dv_ready_2021_2022/BTCUSD_1m_<Exchange>_2021_2022_with_DV.csv
```

Key processed fields include:

| Field | Meaning |
|---|---|
| `time_utc` | UTC minute timestamp |
| `p_usd_scaled` | venue price aligned to a common BTCUSD scale |
| `DV_usd` | synchronized dollar-volume or dollar-volume-proxy weight |
| `volume_unit_final` | inferred volume-unit convention used during preprocessing |

These files are generated locally and are not stored in the GitHub repository.

---

## 6. Price and volume conventions

Public OHLCV files can differ across exchanges in product conventions, price scale, and volume units. The replication workflow treats the synchronized inputs as BTCUSD price-volume proxies for benchmark-mapping purposes.

The preprocessing stage performs:

1. timestamp parsing and UTC alignment;
2. price-scale harmonization across venues;
3. volume-unit diagnostics;
4. construction of dollar-volume or dollar-volume-proxy weights;
5. exclusion of invalid venue-minute observations from the aggregation weight in that minute.

BitMEX is retained after volume-unit diagnostics and handled under the quote-or-contract dollar-volume convention rather than as a base-volume spot venue.

The resulting panel is a harmonized benchmark-mapping panel. It is not intended to be a regulated investable benchmark input file.

---

## 7. Downstream files generated from this source

Representative downstream outputs include:

```text
agg_ready/btc_2021_2022_agg_prices.csv
agg_ready/agg_data_quality_report.xlsx
experiments/weight_concentration_minute_level.csv
hhi_panel/btc_1m_panel_with_hhi.csv
experiments_dvonly/dvon_injection_shift_samples.csv
```

Selected final figures, tables, metadata, and run notes are kept in the repository under:

```text
outputs/
docs/runinfo/
docs/diagnostics/
```

Large intermediate files remain local and are excluded by `.gitignore`.

---

## 8. Relation to the paper

The source data support the paper's benchmark-mapping exercise. The main empirical objects constructed from the raw files are:

- VWAP reference prices;
- LWMP reference prices;
- dominant venue and dominant share;
- HHI concentration measures;
- LWMP pivot and pivot-switchability diagnostics;
- VWAP dominant-venue exposure diagnostics;
- fixed-weight price-displacement pass-through diagnostics.

The analysis studies how aggregation rules convert observed cross-venue price-weight states into reference prices under trading concentration.

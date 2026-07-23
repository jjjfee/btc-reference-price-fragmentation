# Replication guide

This guide separates lightweight verification of committed evidence from computationally expensive reconstruction using externally downloaded data.

## 1. Environment

Use Python 3.10+ from the repository root:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` retains portable lower bounds. `environment-tested.txt` records the exact
Windows/Python/pip package snapshot used for the repository smoke checks on 23 July 2026; it is
an observed environment, not a cross-platform lock or a guarantee that every package combination
will behave identically.

Confirm entry points without loading data:

```bash
python scripts/final/validate_selected_outputs.py --help
python src/experiments/run_day_block_bootstrap.py --help
python src/audit/run_btc_fixed_composition_checks.py --help
python src/audit/run_leave_one_exchange_out_validation.py --help
python src/audit/run_price_displacement_audit.py --help
python src/experiments/run_btc_post2022_replication.py --help
python src/experiments/run_eth_replication.py --help
python src/experiments/run_eth_exclude_binance.py --help
python scripts/final/hash_external_inputs.py --help
```

## 2. Data preparation

Download BTCUSD and ETHUSD files directly from the sources recorded in:

- `data/external/manifests/kaggle_btcusd_manifest.md`
- `data/external/manifests/kaggle_ethusd_manifest.md`

Create these untracked directories under the repository root and place the expected CSV files there:

```text
data/external/raw/btc/
data/external/raw/eth/
```

The fixed-composition gate also consumes seven generated, synchronized BTC inputs. By default it
looks in:

```text
dv_ready_2021_2022/
```

Raw data, generated venue panels, and event-level files are not committed. Do not place
credentials or Kaggle tokens in the repository. `--raw-dir` identifies downloaded source CSVs;
`--input-dir` identifies the seven generated DV-ready CSVs; `--out-dir` identifies newly created
reviewer-check evidence. These roles are not interchangeable.

To record hashes for files you downloaded, without claiming that they are identical to a historical
manuscript download:

```bash
python scripts/final/hash_external_inputs.py --raw-dir data/external/raw/btc --output local_btc_hashes.json
```

The utility records filenames, byte sizes, and SHA-256 values for the current local snapshot only.

## 3. Path configuration

Supported entry points infer the repository root with `pathlib.Path`. Raw-data and output locations can be overridden with `--raw-dir`, `--input-dir`, `--root`, or `--out-dir` where exposed. Run `--help` for the exact interface.

Some older build and figure scripts remain transparent research scripts with repository-relative constants near the top. They no longer point to a personal machine, but they require the documented generated folders. They are not claimed to be a single packaged pipeline.

## 4. Execution stages

### Stage A — venue-level BTC inputs

```bash
python src/build/scan_coverage_2021_2022.py
python src/build/run_volume_check.py
python src/build/make_dv_2021_2022.py
```

Inputs: seven external BTC CSV files. Output: large, ignored venue-level synchronized files under the generated BTC panel directory. Seed: none. Cost: high disk I/O; size scales with the full minute history.

### Stage B — aggregate prices and concentration

```bash
python src/build/build_aggregated_prices.py
python src/build/weight_concentration_check.py
python src/build/build_hhi_trend_panel.py
```

Inputs: generated venue-level BTC files. Outputs: ignored aggregate and concentration panels. Seed: none. Cost: full-panel memory and I/O.

### Stage C — pooled DV-only design

```bash
python src/experiments/run_dv_only_injection_experiments.py
python src/audit/audit_lockin_and_build_dvonly_inference.py
```

Inputs: generated BTC venue panel. Outputs: large ignored 800,000-event sample plus selected summaries. Sampling seed: 42. Construction: 100,000 minutes without replacement; one uniformly selected valid venue per minute; selected venue fixed over two shock types × four magnitudes; all events equally weighted; positive total-preserving shocks capped.

Expected exact rates are 0.27927641929248886 and 0.06767736821244551; difference -0.21159905108004334; ratio 0.24233112263433296.

### Stage D — temporal dependence

The event-level inference dataset is too large for the repository. Point the bootstrap runner to the generated CSV or Parquet file:

```bash
python src/experiments/run_day_block_bootstrap.py PATH_TO_EVENT_FILE --block-days 1 --reps 5000 --seed 20260710
python src/experiments/run_day_block_bootstrap.py PATH_TO_EVENT_FILE --block-days 7 --reps 5000 --seed 20260710
```

Inputs: event-level inference dataset with UTC timestamp, lock-in state, and pivot-change outcome. Outputs default to `outputs/robustness/bootstrap_1day/` or `outputs/robustness/bootstrap_7day/`. Cost: moderate-to-high CPU and memory; rows sharing a sampled UTC block remain together.

### Stage E — fixed composition and reviewer gate

```bash
python src/audit/run_btc_fixed_composition_checks.py \
  --project-root . \
  --input-dir dv_ready_2021_2022 \
  --raw-dir data/external/raw/btc \
  --out-dir outputs/reviewer_checks/btc_fixed_composition \
  --bootstrap-reps 5000 \
  --seed 42
```

Inputs: generated synchronized BTC venue files and baseline artifacts. Outputs: `outputs/reviewer_checks/btc_fixed_composition/`. Seed: 42. Cost: high; reconstructs fixed-composition events and 5,000-repetition block summaries. Expected gate: 29 PASS / 0 WARN / 0 FAIL.

For the exact headline gate without the later fixed-composition and bootstrap stages:

```bash
python src/audit/run_btc_fixed_composition_checks.py \
  --project-root . \
  --input-dir dv_ready_2021_2022 \
  --raw-dir data/external/raw/btc \
  --out-dir outputs/reviewer_checks/btc_headline_verification \
  --headline-only \
  --bootstrap-reps 100 \
  --seed 42
```

`--headline-only` still needs the seven generated inputs, the seven named raw-source files, and the
saved baseline/event artifacts used by the gate. It only skips the later fixed-composition,
leave-composition, inference, and bootstrap work. Point `--out-dir` to a new directory when
verifying an existing package; the runner stops before later work if the exact headline differs.

### Stage F — Appendix G and H audits

```bash
python src/audit/run_price_displacement_audit.py --root .
python src/audit/run_leave_one_exchange_out_validation.py --root . --no-event-level
```

Inputs: generated synchronized BTC venue files. Outputs: fixed-weight price-displacement and leave-one-exchange-out directories under `outputs/robustness/`. The `--no-event-level` switch avoids writing the very large LOO event sample.

### Stage G — later BTCUSD

```bash
python src/experiments/run_btc_post2022_replication.py --root . --raw-dir data/external/raw/btc
```

Inputs: external BTC files with post-2022 coverage plus baseline calibration artifacts. Default outputs: `outputs/robustness/btc_post2022/`. Bootstrap seed: 20260710; event seed: 42. Expected valid minutes: 1,460,823; expected pivot-change difference: -0.1858240971334107.

### Stage H — matched ETHUSD and targeted exclusion

```bash
python src/experiments/run_eth_replication.py --root . --raw-dir data/external/raw/eth
python src/experiments/run_eth_exclude_binance.py --root . --raw-dir data/external/raw/eth
```

Inputs: seven ETH venue files; the combined-index file is audit-only and excluded from venue, weight, dominant, pivot, VWAP, LWMP, max-share, and HHI calculations. Defaults: 5,000 bootstrap repetitions; bootstrap and event seeds 20260712. Outputs: `outputs/robustness/eth_matched/` and `outputs/robustness/eth_exclude_binance/`.

## 5. Lightweight validation without external data

Without external data:

```bash
python scripts/final/validate_selected_outputs.py
python -m compileall -q src scripts archive tests
python -m unittest discover -s tests -p "test_*.py" -v
```

The validator checks committed manifest paths, exact manuscript-facing values, the saved 29-check
gate, and personal absolute-path hygiene. The unittest suite constructs tiny synthetic venue files
in a temporary directory and checks path resolution, input loading, panel calculations, and a small
event construction. Neither command downloads Kaggle data or claims to reconstruct the full raw
analysis. The same no-data checks and documented `--help` commands run in
`.github/workflows/reviewer-smoke.yml`.

This lightweight route validates the committed evidence package. Raw-to-final reconstruction is a
separate, high-I/O/high-memory workflow consisting of Stages A onward. The repository intentionally
does not imply that a clean clone can reconstruct all manuscript outputs without obtaining external
data and regenerating excluded intermediates.

## 6. Expected committed evidence

- main tables/figures: `outputs/main_text/`
- Appendix A–G: `outputs/appendix/`
- Appendix H–K: `outputs/robustness/`
- Appendix L/reviewer gate: `outputs/reviewer_checks/btc_fixed_composition/`
- machine-readable map: `outputs/metadata/output_manifest.json`

The repository does not contain raw data, multi-hundred-megabyte processed panels, full event samples, or bootstrap draws.

## 7. Troubleshooting

- **No raw files found:** compare names and columns with the relevant Kaggle manifest; pass an explicit `--raw-dir` if files are elsewhere.
- **No default inference dataset:** provide the event CSV or Parquet path as the positional argument to the bootstrap runner.
- **Import error from an experiment entry point:** invoke the script from a complete repository checkout; the runners add the sibling build directory for shared preprocessing helpers.
- **Parquet engine error:** install the complete requirements, including PyArrow.
- **Font unavailable:** current figure routines try DejaVu Sans and fall back to Pillow's default font.
- **Memory pressure:** process stages separately, retain generated intermediates outside version control, and use `--no-event-level` for leave-one-out validation.
- **Intervals differ slightly:** verify the recorded seed and construction. Appendix B's baseline run uses seed 20260710; Appendix L's fixed-composition run uses seed 42.

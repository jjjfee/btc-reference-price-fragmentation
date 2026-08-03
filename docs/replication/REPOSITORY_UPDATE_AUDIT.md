# Repository update audit

- Audit date: 2026-07-21
- Target repository: `jjjfee/btc-reference-price-fragmentation`
- Remote base commit audited: `b37ddd7df039bdbc6b816818ed98907701e6255b`
- Update commit: reported in the pull request and repository handoff for the commit containing this report

## Initial repository state

The supplied local working directory was an experimental project directory, not a usable checkout: `git status`, `git branch`, `git log`, and `git remote -v` all failed because the local `.git` directory was incomplete. Two read-only clone attempts failed because the GitHub network connection was unavailable/reset. The remote repository was therefore audited at the exact base commit above through the authenticated GitHub integration, while a separate controlled staging tree was created locally. No `git add -A` was run in the experimental directory.

The remote `main` branch was public and writable. Its latest ten-commit request yielded eight available commits, with `b37ddd7` as the head. The README described the earlier A–G workflow; `REPRODUCING.md` instructed users to edit a personal Windows path; the title metadata was current but the paper-scope statement and H–L support were absent. A source scan found machine-specific paths in 34 of 36 remotely enumerated Python files.

## Claim-to-evidence audit

| Paper claim or appendix item | Supporting script | Supporting output | Pre-update status | Current destination/status |
|---|---|---|---|---|
| Seven-venue 2021–2022 BTC sample; 1,050,207 valid minutes; 55.4973% over half; max spell 2,982 | `src/audit/run_btc_fixed_composition_checks.py` | availability/composition comparison CSV | Local only / missing from public map | Present under `outputs/reviewer_checks/btc_fixed_composition/results/` |
| 1,008,835 all-seven minutes; 54.5047%; max spell 787 | same | fixed-composition summary CSV | Missing | Present |
| Pooled 100,000-minute, seed-42, 800,000-event construction | `src/experiments/run_dv_only_injection_experiments.py` | headline CSV and event-formula/sampling manifests | Script present but documentation stale | Present and documented in Appendix L map |
| Exact pooled rates, difference, and ratio | baseline generator and lock-in audit | `outputs/main_text/tables/headline_pivot_change_rates.csv` | Present but scoped to the earlier repository framing | Present and exact-value validated |
| All-seven pivot rates and difference | fixed-composition runner | fixed-composition pivot summary | Missing | Present |
| All-seven one-day and seven-day intervals | fixed-composition runner | fixed-composition bootstrap CSV | Missing | Present |
| Six base-volume/exclude-BitMEX check | fixed-composition runner | basevolume6 summaries | Missing | Present |
| Baseline one-day and seven-day block bootstrap | `src/experiments/run_day_block_bootstrap.py` | two bootstrap summary/run-info pairs | Missing/stale map | Present under `outputs/robustness/` |
| Fixed-weight price displacement | `src/audit/run_price_displacement_audit.py` | Appendix G summaries and run info | Partially present | Present and mapped |
| Leave-one-exchange-out validation | `src/audit/run_leave_one_exchange_out_validation.py` | summary CSVs and validation report | Missing | Present as Appendix H evidence |
| Later BTCUSD replication | `src/experiments/run_btc_post2022_replication.py` | selected results, figures, audits, metadata, report | Missing | Present as Appendix I evidence |
| Matched ETHUSD replication | `src/experiments/run_eth_replication.py` | selected results, figures, audits, metadata, report | Missing | Present as Appendix J evidence |
| Targeted ETH exclusions | `src/experiments/run_eth_exclude_binance.py` | targeted summary and exclude-Binance package | Missing | Present as Appendix K evidence |
| Reviewer gate 29 PASS / 0 WARN / 0 FAIL | fixed-composition runner | validation CSV and review report | Missing | Present and validated |
| Appendix A–G legacy evidence | audit and plotting scripts | `outputs/appendix/A/` through `G/` | Present but incompletely mapped | Retained and mapped |
| Appendix A–L complete map | multiple | JSON and Markdown manifests | Missing; stopped at G | Present in three synchronized maps |

## Files added

- Current Appendix H–L entry points and selected output packages under `src/experiments/`, `src/audit/`, `outputs/robustness/`, and `outputs/reviewer_checks/`.
- `README.md`, `REPLICATION.md`, `OUTPUT_MANIFEST.md`, `CHANGELOG.md`, and this audit.
- `outputs/metadata/output_manifest.json` and `docs/runinfo/appendix_code_map.md`.
- BTCUSD and ETHUSD external-source manifests under `data/external/manifests/`.
- `scripts/final/validate_selected_outputs.py` and the repository path helper.
- Diagnostic and archive indexes.

## Files modified

- Existing build, audit, experiment, plotting, and archived test scripts were changed only for portable path/default handling, cross-platform relative-path separators, local import resolution, and font fallback. Statistical definitions, shock construction, seeds, event weighting, and numerical outputs were not changed.
- `.gitignore`, `requirements.txt`, `CITATION.cff`, and `REPRODUCING.md` were updated for the current workflow.
- Historical selected-output metadata were sanitized to replace personal absolute paths with `<PROJECT_ROOT>` or repository-relative external-data paths. Numerical content was not changed.

## Files archived

No tracked source file was deleted. Existing exploratory tests remain under `archive/tests/` and are explicitly outside the supported final workflow. No additional file was moved solely to make the update appear cleaner.

## Files intentionally omitted

Raw Kaggle data and large generated intermediates were not copied. Audited examples include:

| Omitted object | Audited size (bytes) | Reason |
|---|---:|---|
| Leave-one-exchange-out event sample | 743,572,275 | Event-level intermediate; selected summaries/report retained |
| Merged DV-only audit events | 292,067,796 | Event-level intermediate |
| DV-only inference dataset | 155,117,384 | External input to block bootstrap; summaries retained |
| Minute-level fixed-composition venue-count panel | 150,123,567 | Row-level audit intermediate |
| Later-BTC processed panel archive | 94,905,440 | Generated intermediate |
| Price-displacement base-state archive | 55,821,387 | Generated intermediate |

Individual raw BTC and ETH venue CSVs are hundreds of megabytes and remain at their third-party source. Their manifests, schemas, sizes, conventions, and available downstream hashes are retained instead.

## Checks run and passed

- `python -m compileall -q src scripts archive`: PASS.
- `python scripts/final/validate_selected_outputs.py`: PASS; 43 mapped artifacts exist, exact paper-facing values match, and 186 text files were scanned.
- Requirements install followed by `python -m pip check`: PASS; no broken requirements.
- `--help` smoke checks for the final validator, block bootstrap, reviewer runner, leave-one-out runner, price-displacement runner, later-BTC runner, matched-ETH runner, targeted-ETH runner, and two argument-driven plotting generators: PASS.
- Absolute-path scan over tracked text: PASS. Current scripts, current output metadata, and user-facing instructions contain no personal drive-root, user-home, desktop, or downloads path. Fifteen pre-existing source manifests and run-info/provenance records retain their historical project paths deliberately as audit records; the validator permits only those exact files.
- Sensitive-string scan for tokens, passwords, API keys, private keys, local usernames, and private URLs: PASS after reviewing non-secret documentation terms and generated audit labels.
- Large-file scan: PASS; no file above 50 MB in the staged tree.
- PDF audit performed against the local authoritative paper and online appendix: 12 and 15 pages respectively; Appendix headings A–L and the paper-facing numerical claims were extracted and visually spot-checked. The PDFs themselves are not required replication outputs and were not added.

## Remaining limitations

- Full raw-to-final reruns were intentionally not performed because the user prohibited unnecessary expensive experiments and the required raw/event-level files are external or too large for the repository.
- Appendix B's baseline bootstrap uses seed 20260710, while the Appendix L fixed-composition rerun uses seed 42; both saved runs are retained and labeled.
- Related VWAP q95 summaries use construction-specific definitions; their labels and provenance must be consulted before comparison.
- The raw data source must remain available, and users need substantial local disk and memory for full reconstruction.
- Direct `git fetch` attempts were blocked/reset by the environment's GitHub network path. The exact remote base and review-branch SHA were independently confirmed through the authenticated GitHub integration, and the identical base commit was reconstructed and SHA-verified from the immediately preceding local clone plus GitHub's one-file diff. The repository update itself uses one normal `git push` and a reviewable branch/PR.

## Repository update record

The exact final branch commit is recorded by Git and reported in the pull request and repository handoff. It cannot be embedded in the same one-commit update without changing its own SHA. The update is intentionally proposed through a draft pull request because it is broad, adds new Appendix H–L evidence, and changes public replication documentation.

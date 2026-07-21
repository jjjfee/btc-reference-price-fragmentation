#!/usr/bin/env python3
"""Validate committed artifacts and exact manuscript-facing numerical claims."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOL = 1e-12

# These pre-existing files are provenance records, not executable defaults. Their
# historical paths are retained deliberately so the archived run can be audited.
ALLOWED_ABSOLUTE_PATH_AUDIT_RECORDS = {
    "archive/exploratory/vwap_degradation/vwap_degradation_runinfo_maxshare_delta1p0.txt",
    "data/external/manifests/agg_ready_manifest.md",
    "data/external/manifests/dv_ready_2021_2022_manifest.md",
    "data/external/manifests/dv_ready_manifest.md",
    "data/external/manifests/experiments_dvonly_manifest.md",
    "data/external/manifests/experiments_manifest.md",
    "data/external/manifests/hhi_panel_manifest.md",
    "docs/runinfo/lwmp_boundary_single_gamma1_inflate_only_runinfo.txt",
    "docs/runinfo/pivot_boundary_runinfo_hhiroll.txt",
    "docs/runinfo/pivot_boundary_runinfo_maxshare.txt",
    "docs/runinfo/runinfo_rebuilt_lockin_persistence.txt",
    "docs/runinfo/vwap_degradation_runinfo_maxshare_delta1p0.txt",
    "docs/runinfo/vwap_head_alignment_runinfo_maxshare.txt",
    "docs/runinfo/vwap_head_proximity_runinfo_maxshare.txt",
    "outputs/metadata/vwap_head_proximity_runinfo_maxshare.txt",
}


def read_rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def assert_close(actual: str | float, expected: float, label: str) -> None:
    value = float(actual)
    if not math.isclose(value, expected, rel_tol=0.0, abs_tol=TOL):
        raise AssertionError(f"{label}: expected {expected!r}, found {value!r}")


def validate_manifest() -> int:
    path = ROOT / "outputs" / "metadata" / "output_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    artifacts = [Path(item) for section in manifest["appendices"] for item in section["artifacts"]]
    artifacts += [Path(item) for item in manifest["main_text_artifacts"]]
    missing = [str(item) for item in artifacts if not (ROOT / item).is_file()]
    if missing:
        raise AssertionError("Manifest paths missing: " + ", ".join(missing))
    return len(artifacts)


def validate_numbers() -> None:
    headline = read_rows("outputs/main_text/tables/headline_pivot_change_rates.csv")
    rates = {row["lock_in"]: row["pivot_changed_rate"] for row in headline}
    assert_close(rates["0"], 0.27927641929248886, "pooled non-majority rate")
    assert_close(rates["1"], 0.06767736821244551, "pooled majority rate")
    assert_close(float(rates["1"]) - float(rates["0"]), -0.21159905108004334, "pooled difference")
    assert_close(float(rates["1"]) / float(rates["0"]), 0.24233112263433296, "pooled ratio")

    comparison = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_availability_and_composition_comparison.csv")
    baseline = next(row for row in comparison if row["Specification"] == "BTC baseline valid-minute sample")
    if int(baseline["Valid minutes"]) != 1_050_207 or int(baseline["Maximum spell"]) != 2_982:
        raise AssertionError("Baseline sample size or maximum spell does not match the manuscript")
    assert_close(baseline["Share max_share > 0.5"], 0.5549734480916619, "baseline over-half share")

    all7 = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_fixed_composition_summary.csv")[0]
    if int(all7["valid_minutes"]) != 1_008_835 or int(all7["maximum_spell"]) != 787:
        raise AssertionError("All-seven sample size or maximum spell does not match Appendix L")
    assert_close(all7["share_max_share_gt_0p5"], 0.5450465140483826, "all-seven over-half share")

    all7_pivot = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_fixed_composition_pivot_summary.csv")[0]
    assert_close(all7_pivot["non_lockin_pivot_change_rate"], 0.27671179480422514, "all-seven non-majority rate")
    assert_close(all7_pivot["lockin_pivot_change_rate"], 0.06934753869599544, "all-seven majority rate")
    assert_close(all7_pivot["difference_lockin_minus_nonlockin"], -0.2073642561082297, "all-seven difference")
    if int(all7_pivot["base_minute_count"]) != 100_000 or int(all7_pivot["total_event_count"]) != 800_000:
        raise AssertionError("All-seven event construction is not 100,000 minutes x 8 events")

    boot = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_fixed_composition_bootstrap.csv")
    diffs = {int(row["block_days"]): row for row in boot if row["statistic"] == "difference_lock_minus_nonlock"}
    assert_close(diffs[1]["ci95_low"], -0.2124239332905306, "all-seven one-day lower CI")
    assert_close(diffs[1]["ci95_high"], -0.2023178773660607, "all-seven one-day upper CI")
    assert_close(diffs[7]["ci95_low"], -0.21658581040289163, "all-seven seven-day lower CI")
    assert_close(diffs[7]["ci95_high"], -0.19744025986563804, "all-seven seven-day upper CI")

    base6 = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_basevolume6_lockin_summary.csv")[0]
    base6_pivot = read_rows("outputs/reviewer_checks/btc_fixed_composition/results/btc_basevolume6_pivot_summary.csv")[0]
    assert_close(base6["share_max_share_gt_0p5"], 0.7772763516302911, "six-base-volume over-half share")
    assert_close(base6_pivot["non_lockin_pivot_change_rate"], 0.2660623267459537, "six-base-volume non-majority rate")
    assert_close(base6_pivot["lockin_pivot_change_rate"], 0.0615629105804158, "six-base-volume majority rate")
    assert_close(base6_pivot["difference_lockin_minus_nonlockin"], -0.2044994161655379, "six-base-volume difference")

    later_btc = read_rows("outputs/robustness/btc_post2022/results/btc_post2022_lockin_summary.csv")[0]
    later_btc_pivot = read_rows("outputs/robustness/btc_post2022/results/btc_post2022_pivot_contrast_summary.csv")[0]
    if int(later_btc["valid_minutes"]) != 1_460_823:
        raise AssertionError("Later-BTC valid-minute count changed")
    assert_close(later_btc["share_max_share_gt_0p5"], 0.5865926262113891, "later-BTC over-half share")
    assert_close(later_btc_pivot["difference_lockin_minus_nonlockin"], -0.1858240971334107, "later-BTC difference")

    eth = read_rows("outputs/robustness/eth_matched/results/eth_lockin_summary.csv")[0]
    eth_pivot = read_rows("outputs/robustness/eth_matched/results/eth_pivot_contrast_summary.csv")[0]
    assert_close(eth["share_max_share_gt_0p5"], 0.709308409436834, "matched-ETH over-half share")
    assert_close(eth_pivot["difference_lockin_minus_nonlockin"], -0.16147078883213373, "matched-ETH difference")

    checks = read_rows("outputs/reviewer_checks/btc_fixed_composition/metadata/validation_checks.csv")
    statuses = [row["status"] for row in checks]
    if len(checks) != 29 or statuses.count("PASS") != 29 or any(s != "PASS" for s in statuses):
        raise AssertionError("Reviewer-check gate is not exactly 29 PASS / 0 WARN / 0 FAIL")


def validate_text_hygiene() -> int:
    extensions = {".py", ".md", ".txt", ".json", ".csv", ".cff", ".yml", ".yaml"}
    user_dir = "/" + "Users" + "/"
    home_dir = "/" + "home" + "/"
    old_workspace = "cilck" + " here"
    pattern = re.compile(
        rf"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|{re.escape(user_dir)}|{re.escape(home_dir)}|{re.escape(old_workspace)})",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in extensions:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        relative = path.relative_to(ROOT).as_posix()
        if pattern.search(text) and relative not in ALLOWED_ABSOLUTE_PATH_AUDIT_RECORDS:
            offenders.append(relative)
    if offenders:
        raise AssertionError("Personal absolute paths remain: " + ", ".join(offenders))
    return scanned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-text-scan", action="store_true", help="Skip the repository text-path scan.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifacts = validate_manifest()
    validate_numbers()
    scanned = 0 if args.skip_text_scan else validate_text_hygiene()
    print(f"PASS: {artifacts} manifest artifacts exist; exact values match; {scanned} text files scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

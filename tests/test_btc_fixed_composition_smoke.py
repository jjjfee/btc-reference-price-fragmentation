"""Small, synthetic smoke coverage for the BTC reviewer-check entry point."""

from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "src" / "audit" / "run_btc_fixed_composition_checks.py"
SPEC = importlib.util.spec_from_file_location("btc_fixed_composition_checks", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot import smoke-test target: {SCRIPT}")
CHECKS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKS
SPEC.loader.exec_module(CHECKS)


class BtcFixedCompositionSmokeTest(unittest.TestCase):
    def _make_inputs(self, base: Path) -> tuple[Path, Path]:
        input_dir = base / "generated"
        raw_dir = base / "raw"
        input_dir.mkdir()
        raw_dir.mkdir()
        times = pd.date_range("2021-01-01", periods=3, freq="min", tz="UTC")
        weights = [
            [60.0, 10.0, 8.0, 7.0, 6.0, 5.0, 4.0],
            [10.0, 15.0, 20.0, 10.0, 15.0, 20.0, 10.0],
            [5.0, 5.0, 5.0, 5.0, 65.0, 10.0, 5.0],
        ]
        for venue_index, exchange in enumerate(CHECKS.EXCHANGES):
            frame = pd.DataFrame(
                {
                    "time_utc": times,
                    "p_usd_scaled": [
                        100.0 + venue_index,
                        101.0 + venue_index,
                        102.0 + venue_index,
                    ],
                    "DV_usd": [row[venue_index] for row in weights],
                    "volume_unit_final": ["synthetic_quote_value"] * len(times),
                }
            )
            frame.to_csv(input_dir / f"BTCUSD_1m_{exchange}_with_DV.csv", index=False)
            (raw_dir / f"BTCUSD_1m_{exchange}.csv").write_text(
                "synthetic raw placeholder\n",
                encoding="utf-8",
            )
        return input_dir, raw_dir

    def test_paths_loader_panel_and_small_event_construction(self) -> None:
        self.assertTrue(PROJECT_ROOT.is_dir())
        self.assertTrue(SCRIPT.is_file())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_dir, raw_dir = self._make_inputs(base)
            args = CHECKS.parse_args(
                [
                    "--project-root",
                    str(PROJECT_ROOT),
                    "--input-dir",
                    str(input_dir),
                    "--raw-dir",
                    str(raw_dir),
                    "--out-dir",
                    "outputs/reviewer_checks/synthetic-smoke",
                ]
            )
            paths = CHECKS.resolve_project_paths(args)
            CHECKS.validate_repository_paths(paths)
            self.assertEqual(paths.input_dir, input_dir.resolve())
            self.assertEqual(paths.raw_dir, raw_dir.resolve())
            self.assertEqual(
                paths.out_dir,
                (PROJECT_ROOT / "outputs" / "reviewer_checks" / "synthetic-smoke").resolve(),
            )

            start = CHECKS.utc_timestamp("2021-01-01")
            end = CHECKS.utc_timestamp("2021-01-01 00:02:00")
            prices, weights, manifest, first_index = CHECKS.load_minute_inputs(
                paths.input_dir,
                paths.raw_dir,
                start,
                end,
            )
            self.assertEqual(list(prices.columns), CHECKS.EXCHANGES)
            self.assertEqual(list(weights.columns), CHECKS.EXCHANGES)
            self.assertEqual(set(manifest["exchange"]), set(CHECKS.EXCHANGES))
            self.assertEqual(len(first_index), 3)
            self.assertTrue(
                all(Path(value).parent == raw_dir.resolve() for value in manifest["raw_source_path"])
            )

            panel, arrays = CHECKS.compute_panel(prices, weights, CHECKS.EXCHANGES, min_exchanges=3)
            self.assertTrue(np.isfinite(panel["P_vwap_DV"]).all())
            self.assertTrue(np.isfinite(panel["P_lwmp_DV"]).all())
            self.assertTrue(set(panel["pivot_exchange"]).issubset(set(CHECKS.EXCHANGES)))
            events, sampled, cells = CHECKS.generate_events(
                panel=panel,
                arrays=arrays,
                exchanges=CHECKS.EXCHANGES,
                candidate_mask=np.ones(len(panel), dtype=bool),
                event_seed=42,
                sample_target=3,
                delta_ws=[0.5],
                shock_types=["inflate_only"],
            )
            self.assertGreaterEqual(len(events), 1)
            self.assertEqual(len(sampled), 3)
            self.assertEqual(len(cells), 1)
            self.assertTrue(events["exchange_shocked"].isin(CHECKS.EXCHANGES).all())
            self.assertTrue(math.isfinite(float(events["shift_vwap"].iloc[0])))
            self.assertTrue(math.isfinite(float(events["shift_lwmp"].iloc[0])))
            self.assertFalse(paths.out_dir.exists(), "Smoke test must not write formal outputs")

    def test_missing_inputs_are_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaisesRegex(CHECKS.GeneratedInputMissingError, "Generated input missing"):
                CHECKS.discover_dv_ready_files(base / "not-generated")
            input_dir, _ = self._make_inputs(base)
            with self.assertRaisesRegex(CHECKS.ExternalRawDataMissingError, "External raw data missing"):
                CHECKS.load_minute_inputs(
                    input_dir,
                    base / "not-raw",
                    CHECKS.utc_timestamp("2021-01-01"),
                    CHECKS.utc_timestamp("2021-01-01 00:02:00"),
                )


if __name__ == "__main__":
    unittest.main()

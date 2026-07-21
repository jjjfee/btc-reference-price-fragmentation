"""Repository-relative path helpers for lightweight orchestration scripts."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RAW_BTC_DIR = REPOSITORY_ROOT / "data" / "external" / "raw" / "btc"
RAW_ETH_DIR = REPOSITORY_ROOT / "data" / "external" / "raw" / "eth"
OUTPUTS_DIR = REPOSITORY_ROOT / "outputs"

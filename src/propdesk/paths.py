"""Repository paths."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("PROPDESK_ROOT", Path(__file__).resolve().parents[2]))
SAMPLE_CSV = REPO_ROOT / "data" / "sample_rth_mnq_mes.csv"

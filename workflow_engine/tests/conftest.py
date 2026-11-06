"""Put workflow_engine on sys.path first so ``import tests.helpers`` resolves (pytest + pyrefly)."""

from __future__ import annotations

import sys
from pathlib import Path

_WF_ENGINE = Path(__file__).resolve().parents[1]
if str(_WF_ENGINE) not in sys.path:
    sys.path.insert(0, str(_WF_ENGINE))

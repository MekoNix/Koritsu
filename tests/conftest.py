"""Делает `packages/` корнем импорта для тестов (без установки пакета)."""

import os
import sys

_PACKAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'packages')
if _PACKAGES not in sys.path:
    sys.path.insert(0, _PACKAGES)

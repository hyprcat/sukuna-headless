"""Compatibility import for API-key scope checks.

The canonical decorator lives in `apps.core.decorators`, matching the Phase 2
checklist. Keep this module so existing imports do not break.
"""

from __future__ import annotations

from apps.core.decorators import requires_scope

__all__ = ["requires_scope"]

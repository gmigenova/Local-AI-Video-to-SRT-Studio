"""Shared ORM helpers: UUID primary keys and timestamp defaults (section 7).

Timestamps are stored as naive wall-clock ``DateTime`` values. SQLite has no
timezone support (offsets are stripped on round-trip), the app is local-first,
and a naive-UTC value serialised by the API would be re-parsed as local time
by the browser - shifting every displayed timestamp by the UTC offset. Storing
local wall-clock time keeps what the UI shows in sync with the user's clock.
"""

from __future__ import annotations

import uuid
from datetime import datetime


def new_id() -> str:
    """Generate a UUID string primary key (``String(36)``, section 7)."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Current wall-clock timestamp used for column defaults.

    Despite the historical name this returns naive *local* time - see the
    module docstring for why.
    """
    return datetime.now()

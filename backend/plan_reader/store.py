# backend/plan_reader/store.py
# Tiny in-memory store for uploaded plan bytes so the placement step can
# re-open the SAME file/page the extraction step used, without persisting
# anything to disk or a DB. Bounded LRU-ish (drops oldest) to cap memory.

from __future__ import annotations

import time
import uuid
from collections import OrderedDict

_MAX = 25
_TTL = 60 * 60  # 1 hour
_STORE: "OrderedDict[str, dict]" = OrderedDict()


def put(entry: dict) -> str:
    plan_id = uuid.uuid4().hex[:12]
    entry["_ts"] = time.time()
    _STORE[plan_id] = entry
    _STORE.move_to_end(plan_id)
    while len(_STORE) > _MAX:
        _STORE.popitem(last=False)
    return plan_id


def get(plan_id: str) -> dict | None:
    entry = _STORE.get(plan_id)
    if not entry:
        return None
    if time.time() - entry.get("_ts", 0) > _TTL:
        _STORE.pop(plan_id, None)
        return None
    _STORE.move_to_end(plan_id)
    return entry

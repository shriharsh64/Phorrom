"""Deterministic feature encoding for the token/quality estimators.

Problem solved: turn a (task_type, size_hint, provider, model) tuple into a fixed-length numeric
vector the regressors can consume. Uses a stable task-type one-hot, the (log) size, the model's
capability-profile signal for the task, and a small hashed provider/model bucket so unseen
free-tier models still map somewhere sensible (catalogs change — ADR-0002).
"""

from __future__ import annotations

import hashlib
import math

from ..orchestrator.profiles import TASK_TYPES, get_profile

_HASH_BUCKETS = 8
FEATURE_NAMES = (
    [f"type_{t}" for t in TASK_TYPES]
    + ["log_size", "profile_quality", "unlimited", "cost"]
    + [f"id_bucket_{i}" for i in range(_HASH_BUCKETS)]
)


def _hash_bucket(provider: str, model: str) -> int:
    h = hashlib.md5(f"{provider}/{model}".encode()).hexdigest()
    return int(h, 16) % _HASH_BUCKETS


def encode(task_type: str, size_hint: int, provider: str, model: str) -> list[float]:
    prof = get_profile(provider, model)
    vec = [1.0 if task_type == t else 0.0 for t in TASK_TYPES]
    vec.append(math.log1p(max(0, size_hint)))
    vec.append(prof.quality_for(task_type))
    vec.append(1.0 if prof.unlimited else 0.0)
    vec.append(prof.cost_per_ktok)
    bucket = _hash_bucket(provider, model)
    vec.extend(1.0 if i == bucket else 0.0 for i in range(_HASH_BUCKETS))
    return vec

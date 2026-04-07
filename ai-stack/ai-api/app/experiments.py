import hashlib
from typing import Dict, Tuple

from .config import (
    AB_EXPERIMENT_ENABLED,
    AB_MODEL_ADVISOR,
    AB_MODEL_CONCISE,
    AB_MODEL_CONTROL,
    AB_VARIANTS,
)


def _bucket_id(subject: str) -> int:
    digest = hashlib.sha1(subject.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def choose_experiment_variant(user_id: str, channel: str) -> Tuple[str, str]:
    if not AB_EXPERIMENT_ENABLED:
        return "control", AB_MODEL_CONTROL

    variants = AB_VARIANTS or ["control"]
    token = f"{channel}:{user_id or 'anonymous'}"
    idx = _bucket_id(token) % len(variants)
    variant = variants[idx]

    model_map: Dict[str, str] = {
        "control": AB_MODEL_CONTROL,
        "concise": AB_MODEL_CONCISE,
        "advisor": AB_MODEL_ADVISOR,
    }
    model = model_map.get(variant, AB_MODEL_CONTROL)
    return variant, model

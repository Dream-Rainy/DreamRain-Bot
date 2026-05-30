from __future__ import annotations

from collections.abc import MutableMapping, MutableSequence, MutableSet

from nonebot import logger

from .storage import PCR_DATA_FILE


def apply_pcr_data_override() -> bool:
    if not PCR_DATA_FILE.exists():
        return False

    namespace: dict[str, object] = {}
    try:
        code = compile(PCR_DATA_FILE.read_text(encoding="utf-8"), str(PCR_DATA_FILE), "exec")
        exec(code, namespace)
    except Exception as e:
        logger.warning(f"failed to load priconne pcr data override: {e}")
        return False

    from . import _pcr_data

    for key, value in namespace.items():
        if key.startswith("__"):
            continue

        old_value = getattr(_pcr_data, key, None)
        if isinstance(old_value, MutableMapping) and isinstance(value, dict):
            old_value.clear()
            old_value.update(value)
        elif isinstance(old_value, MutableSequence) and isinstance(value, list):
            old_value[:] = value
        elif isinstance(old_value, MutableSet) and isinstance(value, set):
            old_value.clear()
            old_value.update(value)
        else:
            setattr(_pcr_data, key, value)

    return True

"""CEMT inland waterway classes and their ordering."""

from __future__ import annotations

# FIS codes, smallest to largest. "_0" is small craft only (not CEMT proper).
CODES = ("_0", "I", "II", "III", "IV", "V_A", "V_B", "VI_A", "VI_B", "VI_C", "VII")
RANK = {code: i for i, code in enumerate(CODES)}

_ALIASES = {"0": "_0", "VA": "V_A", "VB": "V_B", "VIA": "VI_A", "VIB": "VI_B", "VIC": "VI_C"}


def normalize(cls: str | int | None) -> str | None:
    """Return the FIS code for ``cls``.

    Accepts FIS codes (``"V_A"``), common spellings (``"Va"``, ``"v a"``) and
    ranks (``4`` -> ``"IV"``). ``None`` stays ``None``.
    """
    if cls is None:
        return None
    if isinstance(cls, int):
        if not 0 <= cls < len(CODES):
            raise ValueError(f"unknown CEMT rank: {cls}")
        return CODES[cls]
    key = str(cls).strip().upper().replace(" ", "").replace("_", "")
    code = _ALIASES.get(key, key)
    if code not in RANK:
        raise ValueError(f"unknown CEMT class: {cls!r}")
    return code


def rank(cls: str | int | None) -> int | None:
    """Return the rank of ``cls`` (0 for ``"_0"``), or ``None``."""
    code = normalize(cls)
    return None if code is None else RANK[code]

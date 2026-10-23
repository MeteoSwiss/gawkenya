"""Convert literal ACOEM NE-300 operation codes (4035) to GAW Kenya QC flags.

The instrument's state 1 (zero calibration) and state 2 (span calibration)
are *transient* periods: both receive quality flag 2 (uncertain/transient).
States 3–6 are single completion records, and do not retrospectively change
the preceding calibration period. Codes outside 0–6 remain unmapped.

After a nonzero operation, returning to state 0 triggers the existing
post-transition uncertainty window, without overriding explicit operation
states or completion records. Pure Python for independent unit testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

OPERATION_TO_FLAG: dict[int, int] = {
    0: 0,   # normal monitoring
    1: 2,   # zero calibration: uncertain / transient
    2: 2,   # span calibration: uncertain / transient
    3: 3,   # zero adjustment completed
    4: 5,   # zero check completed
    5: 4,   # span calibration completed
    6: 6,   # span check completed
}


def flags_for_operations(
    operations: Sequence[int | None],
    timestamps: Sequence[datetime],
    *,
    minutes_after_transition: int = 10,
    assume_null_is_normal: bool = True,
) -> list[int | None]:
    """Flag chronologically sorted NE-300 records, preserving completion states.

    This is strictly row-wise: no inference from later completion records is
    performed for state 1/2 periods. Only a return to normal monitoring may
    change a state-0 row to the transient flag 2.
    """
    if len(operations) != len(timestamps):
        raise ValueError("operations and timestamps must have equal lengths")
    if minutes_after_transition < 0:
        raise ValueError("minutes_after_transition must be non-negative")
    if any(timestamps[i] < timestamps[i - 1] for i in range(1, len(timestamps))):
        raise ValueError("timestamps must be sorted chronologically")

    state = [int(v) if v is not None else (0 if assume_null_is_normal else None)
             for v in operations]
    flags: list[int | None] = [OPERATION_TO_FLAG.get(s) for s in state]

    last_return: datetime | None = None
    interval = timedelta(minutes=minutes_after_transition)
    for i, s in enumerate(state):
        if i > 0 and s == 0 and state[i - 1] not in (None, 0):
            last_return = timestamps[i]
        if s == 0 and last_return is not None:
            if timedelta(0) <= timestamps[i] - last_return <= interval:
                flags[i] = 2
    return flags

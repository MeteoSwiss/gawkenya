"""Pure NE-300 4035 instrument-state mapping and transition regressions."""
from datetime import UTC, datetime, timedelta

import pytest

from processing.ne300_operation_flags import flags_for_operations, OPERATION_TO_FLAG


def ts(n: int) -> list[datetime]:
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    return [t0 + timedelta(minutes=i) for i in range(n)]


def test_literal_4035_mapping() -> None:
    assert OPERATION_TO_FLAG == {0: 0, 1: 2, 2: 2, 3: 3, 4: 5, 5: 4, 6: 6}
    operations = [0, 1, 2, 3, 4, 5, 6, 7]
    # No return-to-ambient rows after a calibration, hence no transition mask.
    assert flags_for_operations(operations, ts(len(operations))) == [0, 2, 2, 3, 5, 4, 6, None]


def test_zero_check_does_not_retroactively_change_transient_rows() -> None:
    operations = [0, 1, 1, 1, 4, 0, 0]
    assert flags_for_operations(operations, ts(len(operations))) == [0, 2, 2, 2, 5, 2, 2]


def test_span_check_does_not_retroactively_change_transient_rows() -> None:
    operations = [0, 2, 2, 6, 0]
    assert flags_for_operations(operations, ts(len(operations))) == [0, 2, 2, 6, 2]


def test_adjustment_completion_states_do_not_override_calibration_rows() -> None:
    operations = [0, 1, 1, 3, 0, 2, 2, 5, 0]
    assert flags_for_operations(operations, ts(len(operations))) == [0, 2, 2, 3, 2, 2, 2, 4, 2]


def test_transition_window_affects_only_normal_rows() -> None:
    operations = [0, 1, 4, 0, 0, 0, 6]
    timestamps = [ts(1)[0] + timedelta(minutes=delta) for delta in [0, 1, 2, 3, 13, 14, 15]]
    assert flags_for_operations(operations, timestamps) == [0, 2, 5, 2, 2, 0, 6]


def test_unknown_and_null_states_are_not_invented() -> None:
    assert flags_for_operations([7, None], ts(2), assume_null_is_normal=False) == [None, None]
    assert flags_for_operations([None], ts(1)) == [0]


def test_invalid_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        flags_for_operations([0, 1], ts(1))
    with pytest.raises(ValueError):
        flags_for_operations([0], ts(1), minutes_after_transition=-1)
    with pytest.raises(ValueError):
        flags_for_operations([0, 1], list(reversed(ts(2))))

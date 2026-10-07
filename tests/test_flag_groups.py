from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from toolbox.flag_groups import (
    active_flag_source,
    expand_linked_variables,
    load_flag_groups,
    synchronize_group_from_variable,
)


def test_load_flag_groups_and_expand_three_member_group(tmp_path: Path) -> None:
    config = tmp_path / "flag_groups.yml"
    config.write_text(
        """flag_groups:\n  example:\n    - a\n    - b\n    - c\n""",
        encoding="utf-8",
    )

    groups = load_flag_groups(config)

    assert groups == {"example": ("a", "b", "c")}
    assert expand_linked_variables("b", groups) == ["b", "a", "c"]


def test_variable_may_not_occur_in_two_groups(tmp_path: Path) -> None:
    config = tmp_path / "flag_groups.yml"
    config.write_text(
        """flag_groups:\n  first:\n    - a\n    - b\n  second:\n    - b\n    - c\n""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="occurs in both"):
        load_flag_groups(config)


def test_active_flag_source_uses_another_group_member() -> None:
    groups = {"example": ("a", "b", "c")}
    frame = pl.DataFrame(
        {
            "a": [1.0],
            "b": [2.0],
            "c": [3.0],
            "f_c": [2],
        }
    )

    assert active_flag_source(frame, "a", groups) == "f_c"


def test_synchronize_group_uses_edited_member_as_authority() -> None:
    groups = {"example": ("a", "b", "c")}
    frame = pl.DataFrame(
        {
            "a": [1.0, 2.0],
            "b": [3.0, 4.0],
            "c": [5.0, 6.0],
            "f_b": [1, None],
            "f_c": [2, 2],
        }
    )

    result = synchronize_group_from_variable(frame, "b", groups)

    assert result.get_column("f_a").to_list() == [1, None]
    assert result.get_column("f_b").to_list() == [1, None]
    assert result.get_column("f_c").to_list() == [1, None]

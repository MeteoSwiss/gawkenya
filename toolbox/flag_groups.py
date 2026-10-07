from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias

import polars as pl
import yaml


FlagGroups: TypeAlias = dict[str, tuple[str, ...]]

DEFAULT_FLAG_GROUPS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "flag_groups.yml"
)


def load_flag_groups(path: Path | None = None) -> FlagGroups:
    """Load and validate symmetric linked-flag groups from YAML.

    The YAML structure is::

        flag_groups:
          group_name:
            - variable_a
            - variable_b

    A variable may belong to at most one group. Flag propagation is symmetric:
    flagging any member applies the same flag to all other members that are
    present in the dataframe.
    """
    config_path = path or DEFAULT_FLAG_GROUPS_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"Linked-flag configuration not found: {config_path}")

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Linked-flag configuration must be a mapping: {config_path}")

    raw_groups = loaded.get("flag_groups")
    if not isinstance(raw_groups, Mapping):
        raise ValueError("Linked-flag configuration requires a flag_groups mapping.")

    groups: FlagGroups = {}
    owner_by_variable: dict[str, str] = {}

    for raw_name, raw_members in raw_groups.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("Every linked-flag group must have a non-empty string name.")
        group_name = raw_name.strip()

        if (
            not isinstance(raw_members, Sequence)
            or isinstance(raw_members, (str, bytes))
        ):
            raise ValueError(
                f"Linked-flag group {group_name!r} must be a list of variable names."
            )

        members: list[str] = []
        for raw_member in raw_members:
            if not isinstance(raw_member, str) or not raw_member.strip():
                raise ValueError(
                    f"Linked-flag group {group_name!r} contains an invalid variable."
                )
            member = raw_member.strip()
            if member in members:
                raise ValueError(
                    f"Linked-flag group {group_name!r} contains duplicate {member!r}."
                )

            previous_group = owner_by_variable.get(member)
            if previous_group is not None:
                raise ValueError(
                    f"Variable {member!r} occurs in both {previous_group!r} "
                    f"and {group_name!r}."
                )

            members.append(member)
            owner_by_variable[member] = group_name

        if len(members) < 2:
            raise ValueError(
                f"Linked-flag group {group_name!r} must contain at least two variables."
            )

        groups[group_name] = tuple(members)

    return groups


def group_for_variable(
    variable: str | None,
    groups: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...] | None:
    """Return the linked group containing ``variable``, if any."""
    if variable is None:
        return None

    for members in groups.values():
        if variable in members:
            return members
    return None


def expand_linked_variables(
    variables: str | Sequence[str],
    groups: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """Expand variables to all configured linked members, preserving order."""
    requested = [variables] if isinstance(variables, str) else list(variables)
    expanded: list[str] = []

    for variable in requested:
        if variable not in expanded:
            expanded.append(variable)

        members = group_for_variable(variable, groups)
        if members is None:
            continue

        for member in members:
            if member not in expanded:
                expanded.append(member)

    return expanded


def active_flag_source(
    frame: pl.DataFrame,
    variable: str,
    groups: Mapping[str, tuple[str, ...]],
    *,
    flag_prefix: str = "f_",
) -> str | None:
    """Return an existing flag column suitable for displaying ``variable``."""
    own_flag = f"{flag_prefix}{variable}"
    if own_flag in frame.columns:
        return own_flag

    members = group_for_variable(variable, groups)
    if members is None:
        return None

    for member in members:
        if member == variable:
            continue
        candidate = f"{flag_prefix}{member}"
        if candidate in frame.columns:
            return candidate

    return None


def synchronize_group_from_variable(
    frame: pl.DataFrame,
    variable: str | None,
    groups: Mapping[str, tuple[str, ...]],
    *,
    flag_prefix: str = "f_",
) -> pl.DataFrame:
    """Copy one member's flag column to all present members of its group."""
    if variable is None:
        return frame

    members = group_for_variable(variable, groups)
    if members is None:
        return frame

    source = f"{flag_prefix}{variable}"
    if source not in frame.columns:
        return frame

    expressions = [
        pl.col(source).alias(f"{flag_prefix}{member}")
        for member in members
        if member != variable and member in frame.columns
    ]
    return frame.with_columns(expressions) if expressions else frame

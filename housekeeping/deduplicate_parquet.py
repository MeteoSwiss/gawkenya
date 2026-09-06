#!/usr/bin/env python3
"""Safely identify and resolve duplicate timestamps in Parquet files.

The utility is deliberately conservative:

* A dry run is the default. Files are rewritten only with ``--write``.
* Rows that are exactly equal are collapsed automatically.
* Rows with the same timestamp are merged automatically only when every column
  has at most one distinct non-null value across the rows.
* If non-null values conflict, an interactive write lets the user select the
  authoritative/base row. Values from the other rows fill nulls in the selected
  row only where those other values agree; conflicting values never overwrite a
  value chosen by the user.
* Null timestamps are reported but never deduplicated.
* Rewrites are atomic (temporary file + os.replace) and preserve column order
  and Polars dtypes. A second run after successful cleanup makes no changes.

Examples
--------
Scan a complete Level-1 tree without changing anything::

    python housekeeping/deduplicate_parquet.py /path/to/gawkenyadata/level1

Resolve safe cases and interactively decide conflicting cases::

    python housekeeping/deduplicate_parquet.py /path/to/gawkenyadata/level1 --write

Process one file and explicitly name its time column::

    python housekeeping/deduplicate_parquet.py data.parquet --time-column dtm --write

For scripted/non-interactive execution, conflicting groups are left untouched::

    python housekeeping/deduplicate_parquet.py /path/to/data --write --non-interactive
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Iterable

import polars as pl


TIME_COLUMN_CANDIDATES = (
    "dtm",
    "timestamp",
    "datetime",
    "date_time",
    "time",
    "ts",
)


class UserAbort(RuntimeError):
    """Raised when the user aborts an interactive cleanup run."""


@dataclass
class FileStats:
    path: Path
    rows: int = 0
    null_timestamps: int = 0
    duplicate_groups: int = 0
    duplicate_rows: int = 0
    exact_groups: int = 0
    mergeable_groups: int = 0
    conflict_groups: int = 0
    resolved_groups: int = 0
    unresolved_groups: int = 0
    rows_removed: int = 0
    changed: bool = False
    time_column: str | None = None
    error: str | None = None


@dataclass
class DuplicateGroup:
    frame: pl.DataFrame
    timestamp: Any
    kind: str  # exact | mergeable | conflict
    differing_columns: list[str]
    conflicting_columns: list[str]


def _is_datetime_dtype(dtype: pl.DataType) -> bool:
    return isinstance(dtype, pl.Datetime) or dtype == pl.Date


def find_time_column(schema: dict[str, pl.DataType], requested: str | None) -> str:
    """Return the timestamp column, preferring the project's ``dtm`` convention."""
    if requested:
        if requested not in schema:
            raise ValueError(
                f"Requested time column {requested!r} is not present. "
                f"Available columns: {', '.join(schema)}"
            )
        return requested

    by_lower = {name.lower(): name for name in schema}
    for candidate in TIME_COLUMN_CANDIDATES:
        if candidate in by_lower:
            return by_lower[candidate]

    datetime_columns = [name for name, dtype in schema.items() if _is_datetime_dtype(dtype)]
    if len(datetime_columns) == 1:
        return datetime_columns[0]
    if not datetime_columns:
        raise ValueError(
            "No timestamp column could be identified. Use --time-column COLUMN."
        )
    raise ValueError(
        "Several datetime columns are present and none has a standard timestamp name: "
        f"{', '.join(datetime_columns)}. Use --time-column COLUMN."
    )


def _value_key(value: Any) -> Any:
    """Return a hashable equality key, treating repeated NaN values as equal."""
    if value is None:
        return ("none",)
    if isinstance(value, float) and math.isnan(value):
        return ("nan",)
    if isinstance(value, dict):
        return (
            "dict",
            tuple(sorted((str(key), _value_key(item)) for key, item in value.items())),
        )
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_value_key(item) for item in value))
    if isinstance(value, set):
        return ("set", tuple(sorted(_value_key(item) for item in value)))
    if isinstance(value, (datetime, date, Decimal, bytes, str, bool, int, float)):
        return (type(value).__name__, value)
    try:
        hash(value)
    except TypeError:
        return (type(value).__name__, repr(value))
    return (type(value).__name__, value)


def _rows_equal(left: dict[str, Any], right: dict[str, Any], columns: Iterable[str]) -> bool:
    return all(_value_key(left[column]) == _value_key(right[column]) for column in columns)


def _column_distinct_non_null(rows: list[dict[str, Any]], column: str) -> dict[Any, Any]:
    values: dict[Any, Any] = {}
    for row in rows:
        value = row[column]
        if value is None:
            continue
        values.setdefault(_value_key(value), value)
    return values


def classify_group(frame: pl.DataFrame, time_column: str, order_column: str) -> DuplicateGroup:
    """Classify one repeated-timestamp group."""
    data_columns = [name for name in frame.columns if name != order_column]
    rows = frame.to_dicts()
    timestamp = rows[0][time_column]

    exact = all(_rows_equal(rows[0], row, data_columns) for row in rows[1:])

    differing_columns: list[str] = []
    conflicting_columns: list[str] = []
    for column in data_columns:
        all_keys = {_value_key(row[column]) for row in rows}
        if len(all_keys) > 1:
            differing_columns.append(column)
        if len(_column_distinct_non_null(rows, column)) > 1:
            conflicting_columns.append(column)

    if exact:
        kind = "exact"
    elif conflicting_columns:
        kind = "conflict"
    else:
        kind = "mergeable"

    return DuplicateGroup(
        frame=frame,
        timestamp=timestamp,
        kind=kind,
        differing_columns=differing_columns,
        conflicting_columns=conflicting_columns,
    )


def _safe_merged_row(
    rows: list[dict[str, Any]],
    columns: list[str],
    base_index: int = 0,
) -> dict[str, Any]:
    """Merge nulls where all available non-null values agree.

    The selected base row is authoritative. Its non-null values are never
    overwritten. A null in the base row is filled only when all non-null values
    in the group for that column agree on one value.
    """
    merged = dict(rows[base_index])
    for column in columns:
        if merged[column] is not None:
            continue
        distinct = _column_distinct_non_null(rows, column)
        if len(distinct) == 1:
            merged[column] = next(iter(distinct.values()))
    return merged


def _format_value(value: Any, max_len: int = 80) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        text = repr(value)
    else:
        text = str(value)
    text = text.replace("\n", "\\n")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _print_conflict(
    group: DuplicateGroup,
    order_column: str,
    time_column: str,
    *,
    conflict_number: int | None = None,
    conflict_total: int | None = None,
) -> None:
    """Display complete candidate rows before asking the user to choose.

    A decision about a conflicting measurement often depends on fields that are
    identical between the duplicate rows (for example source identifiers, flags,
    instrument status, or auxiliary measurements).  Therefore the interactive
    display shows every data column, not only the columns that differ.

    Prefixes make the important differences visible in wide records:

    * ``!`` = two or more different non-null values exist (real conflict)
    * ``+`` = rows differ only because of NULL/complementary information
    * blank = the value is common to all candidate rows
    """
    rows = group.frame.to_dicts()
    display_columns = [
        name for name in group.frame.columns if name not in {order_column, time_column}
    ]
    conflicting = set(group.conflicting_columns)
    differing = set(group.differing_columns)

    print()
    if conflict_number is not None and conflict_total is not None:
        heading = f"CONFLICT {conflict_number}/{conflict_total}"
    else:
        heading = "CONFLICT"
    print(f"{heading} at timestamp {_format_value(group.timestamp)} ({len(rows)} rows)")
    print("Conflicting non-null columns: " + ", ".join(group.conflicting_columns))
    print("Markers: ! conflicting value, + complementary/different value")

    for option, row in enumerate(rows, start=1):
        source_row = int(row[order_column]) + 1
        print(f"  [{option}] parquet row {source_row}")
        for column in display_columns:
            if column in conflicting:
                marker = "!"
            elif column in differing:
                marker = "+"
            else:
                marker = " "
            print(f"      {marker} {column}: {_format_value(row[column])}")
    print(
        "Choose a base row. Its non-null values win; its nulls are filled only "
        "where the remaining rows agree."
    )


def _choose_conflict_row(
    group: DuplicateGroup,
    order_column: str,
    time_column: str,
    *,
    conflict_number: int | None = None,
    conflict_total: int | None = None,
) -> int | None:
    _print_conflict(
        group,
        order_column=order_column,
        time_column=time_column,
        conflict_number=conflict_number,
        conflict_total=conflict_total,
    )
    row_count = group.frame.height
    while True:
        answer = input(f"Select 1-{row_count}, s=skip, q=abort: ").strip().lower()
        if answer in {"s", "skip"}:
            return None
        if answer in {"q", "quit", "abort"}:
            raise UserAbort("Cleanup aborted by user.")
        try:
            selected = int(answer)
        except ValueError:
            selected = 0
        if 1 <= selected <= row_count:
            return selected - 1
        print("Invalid choice.")




def _preference_signature(
    group: DuplicateGroup,
    *,
    column: str,
    order_column: str,
) -> tuple[str, frozenset[Any]] | None:
    """Return a stable identity for a conflict distinguished by *column*.

    A preference is reusable only when every candidate has a non-null, unique
    value in the distinguishing column.  This prevents an instruction such as
    "keep source B" from ambiguously matching two candidate rows.
    """
    if column not in group.conflicting_columns or column not in group.frame.columns:
        return None
    rows = group.frame.to_dicts()
    keys = [_value_key(row[column]) for row in rows if row[column] is not None]
    if len(keys) != len(rows) or len(set(keys)) != len(rows):
        return None
    return (column, frozenset(keys))


def _row_matching_preference(
    group: DuplicateGroup,
    *,
    column: str,
    preferred_key: Any,
) -> int | None:
    rows = group.frame.to_dicts()
    matches = [
        index for index, row in enumerate(rows)
        if _value_key(row[column]) == preferred_key
    ]
    return matches[0] if len(matches) == 1 else None


def _remaining_matching_preferences(
    groups: list[DuplicateGroup],
    *,
    column: str,
    signature: tuple[str, frozenset[Any]],
    order_column: str,
) -> int:
    return sum(
        group.kind == "conflict"
        and _preference_signature(
            group, column=column, order_column=order_column
        ) == signature
        for group in groups
    )


def _ask_remember_preference(
    *,
    column: str,
    value: Any,
    remaining: int,
) -> bool:
    print(
        f"The same {column!r} alternatives occur in {remaining} remaining "
        f"conflict group{'s' if remaining != 1 else ''}."
    )
    prompt = (
        f"Keep {column}={_format_value(value)} for those conflicts as well? "
        "[y/N]: "
    )
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        print("Please answer y or n.")


def _row_frame(row: dict[str, Any], schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Create one row while retaining the original Polars schema."""
    return pl.DataFrame([row], schema=schema, strict=False)


def _atomic_write(frame: pl.DataFrame, path: Path) -> None:
    """Write *frame* beside *path* and atomically replace the original."""
    path = path.resolve()
    original_mode = stat.S_IMODE(path.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp.parquet", dir=path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        frame.write_parquet(temp_path)

        # Verify row count and schema before touching the source file.
        check = pl.scan_parquet(temp_path)
        written_schema = dict(check.collect_schema())
        expected_schema = dict(frame.schema)
        if written_schema != expected_schema:
            raise RuntimeError(
                "Temporary Parquet schema differs from the in-memory dataframe schema."
            )
        written_rows = int(check.select(pl.len().alias("n")).collect().item())
        if written_rows != frame.height:
            raise RuntimeError(
                f"Temporary Parquet row count mismatch: {written_rows} != {frame.height}."
            )

        # mkstemp creates mode 0600; retain the original file permissions.
        os.chmod(temp_path, original_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def iter_parquet_files(targets: list[Path]) -> list[Path]:
    """Resolve files/directories to a deterministic, duplicate-free file list."""
    result: set[Path] = set()
    for target in targets:
        target = target.expanduser()
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_file():
            if target.suffix.lower() != ".parquet":
                raise ValueError(f"Not a Parquet file: {target}")
            result.add(target.resolve())
        else:
            result.update(path.resolve() for path in target.rglob("*.parquet") if path.is_file())
    return sorted(result, key=lambda item: str(item).lower())


def process_file(
    path: Path,
    *,
    requested_time_column: str | None,
    write: bool,
    interactive: bool,
    verbose: bool,
) -> FileStats:
    stats = FileStats(path=path)
    try:
        # First scan only the timestamp column. Most files are expected to be
        # clean, so this avoids loading every measurement column into memory.
        lazy = pl.scan_parquet(path)
        schema = dict(lazy.collect_schema())
        time_column = find_time_column(schema, requested_time_column)
        stats.time_column = time_column
        time_stats = lazy.select(
            pl.len().alias("rows"),
            pl.col(time_column).null_count().alias("nulls"),
            pl.col(time_column).drop_nulls().n_unique().alias("unique_non_null"),
        ).collect().row(0, named=True)
        stats.rows = int(time_stats["rows"])
        stats.null_timestamps = int(time_stats["nulls"])
        non_null_rows = stats.rows - stats.null_timestamps
        unique_non_null = int(time_stats["unique_non_null"])

        if non_null_rows == unique_non_null:
            if verbose:
                print(f"OK       {path}  rows={stats.rows:,}  time={time_column}")
            return stats

        # Full data are needed only for files that actually contain duplicates.
        frame = pl.read_parquet(path)
        order_column = "__dedupe_source_row__"
        while order_column in frame.columns:
            order_column = "_" + order_column
        indexed = frame.with_row_index(order_column)

        duplicate_rows = indexed.filter(
            pl.col(time_column).is_not_null() & pl.col(time_column).is_duplicated()
        )

        groups = [
            classify_group(group, time_column=time_column, order_column=order_column)
            for group in duplicate_rows.partition_by(
                time_column, as_dict=False, maintain_order=True
            )
        ]
        stats.duplicate_groups = len(groups)
        stats.duplicate_rows = sum(group.frame.height for group in groups)
        stats.exact_groups = sum(group.kind == "exact" for group in groups)
        stats.mergeable_groups = sum(group.kind == "mergeable" for group in groups)
        stats.conflict_groups = sum(group.kind == "conflict" for group in groups)

        print(
            f"DUPLICATE {path}  time={time_column}  groups={stats.duplicate_groups}  "
            f"rows={stats.duplicate_rows}  exact={stats.exact_groups}  "
            f"mergeable={stats.mergeable_groups}  conflicts={stats.conflict_groups}"
        )

        if not write:
            conflict_number = 0
            for group in groups:
                if group.kind == "conflict":
                    conflict_number += 1
                    _print_conflict(
                        group,
                        order_column=order_column,
                        time_column=time_column,
                        conflict_number=conflict_number,
                        conflict_total=stats.conflict_groups,
                    )
            stats.unresolved_groups = stats.conflict_groups
            return stats

        original_schema = dict(indexed.schema)
        resolved_frames: list[pl.DataFrame] = []
        removed_indexes: list[int] = []
        remembered_preferences: dict[tuple[str, frozenset[Any]], Any] = {}
        conflict_number = 0

        if interactive and stats.conflict_groups:
            print(
                f"Interactive review: {stats.conflict_groups} conflict group"
                f"{'s' if stats.conflict_groups != 1 else ''} already exist in this file. "
                "Selections do not create additional conflicts; the file is not "
                "rewritten until this review is complete."
            )

        for group_index, group in enumerate(groups):
            rows = group.frame.to_dicts()
            columns = [name for name in group.frame.columns if name != order_column]
            selected_index: int | None

            if group.kind == "exact":
                selected_index = 0
            elif group.kind == "mergeable":
                selected_index = 0
            elif interactive:
                conflict_number += 1
                source_signature = _preference_signature(
                    group, column="source", order_column=order_column
                )
                selected_index = None
                if source_signature is not None and source_signature in remembered_preferences:
                    preferred_key = remembered_preferences[source_signature]
                    selected_index = _row_matching_preference(
                        group, column="source", preferred_key=preferred_key
                    )
                    if selected_index is not None:
                        selected_source = rows[selected_index]["source"]
                        print(
                            f"AUTO      conflict {conflict_number}/{stats.conflict_groups} "
                            f"at {_format_value(group.timestamp)}: keeping "
                            f"source={_format_value(selected_source)} "
                            "(remembered choice)"
                        )

                if selected_index is None:
                    selected_index = _choose_conflict_row(
                        group,
                        order_column=order_column,
                        time_column=time_column,
                        conflict_number=conflict_number,
                        conflict_total=stats.conflict_groups,
                    )

                    if selected_index is not None and source_signature is not None:
                        remaining = _remaining_matching_preferences(
                            groups[group_index + 1 :],
                            column="source",
                            signature=source_signature,
                            order_column=order_column,
                        )
                        if remaining:
                            selected_source = rows[selected_index]["source"]
                            if _ask_remember_preference(
                                column="source",
                                value=selected_source,
                                remaining=remaining,
                            ):
                                remembered_preferences[source_signature] = _value_key(
                                    selected_source
                                )
            else:
                selected_index = None
                print(
                    f"UNRESOLVED {path}: conflict at {_format_value(group.timestamp)} "
                    "(non-interactive mode)"
                )

            if selected_index is None:
                stats.unresolved_groups += 1
                continue

            merged = _safe_merged_row(rows, columns=columns, base_index=selected_index)
            # Put the resolved row at the position of the first duplicate occurrence,
            # regardless of which row was selected as authoritative.
            merged[order_column] = min(int(row[order_column]) for row in rows)
            resolved_frames.append(_row_frame(merged, original_schema))
            removed_indexes.extend(int(row[order_column]) for row in rows)
            stats.resolved_groups += 1
            stats.rows_removed += len(rows) - 1

        if not resolved_frames:
            return stats

        untouched = indexed.filter(~pl.col(order_column).is_in(removed_indexes))
        output = pl.concat([untouched, *resolved_frames], how="vertical").sort(order_column)
        output = output.drop(order_column)

        _atomic_write(output, path)
        stats.changed = True
        print(
            f"WRITTEN   {path}  {frame.height:,} -> {output.height:,} rows  "
            f"resolved={stats.resolved_groups}  unresolved={stats.unresolved_groups}"
        )
        return stats

    except UserAbort:
        raise
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {exc}"
        print(f"ERROR     {path}: {stats.error}", file=sys.stderr)
        return stats


def print_summary(stats: list[FileStats], write: bool) -> None:
    files_with_duplicates = sum(item.duplicate_groups > 0 for item in stats)
    files_changed = sum(item.changed for item in stats)
    errors = sum(item.error is not None for item in stats)
    print()
    print("Summary")
    print("-------")
    print(f"Parquet files scanned : {len(stats)}")
    print(f"Files with duplicates : {files_with_duplicates}")
    print(f"Duplicate groups       : {sum(item.duplicate_groups for item in stats)}")
    print(f"  exact groups         : {sum(item.exact_groups for item in stats)}")
    print(f"  mergeable groups     : {sum(item.mergeable_groups for item in stats)}")
    print(f"  conflict groups      : {sum(item.conflict_groups for item in stats)}")
    print(f"Resolved groups        : {sum(item.resolved_groups for item in stats)}")
    print(f"Unresolved groups      : {sum(item.unresolved_groups for item in stats)}")
    print(f"Rows removed           : {sum(item.rows_removed for item in stats)}")
    print(f"Files changed          : {files_changed}")
    print(f"Errors                 : {errors}")
    if not write and files_with_duplicates:
        print("Mode                   : dry run (no files changed; add --write to clean)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find and safely eliminate duplicate timestamps in one Parquet file "
            "or recursively below one or more directories."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Parquet file(s) and/or directory tree(s) to inspect.",
    )
    parser.add_argument(
        "--time-column",
        help=(
            "Timestamp column to use. By default the utility prefers dtm and then "
            "common timestamp names, or an unambiguous datetime column."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite files with resolved duplicate groups. Default is dry-run only.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Never prompt for conflicting duplicate rows. Exact/mergeable groups are "
            "still cleaned with --write; conflicts remain unchanged."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also report files that contain no duplicate timestamps.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        files = iter_parquet_files(args.paths)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    if not files:
        print("No Parquet files found.")
        return 0

    interactive = bool(args.write and not args.non_interactive and sys.stdin.isatty())
    if args.write and not args.non_interactive and not sys.stdin.isatty():
        print(
            "stdin is not interactive; conflicting groups will be left unresolved. "
            "Run from a terminal to choose rows, or use --non-interactive explicitly."
        )

    results: list[FileStats] = []
    try:
        for path in files:
            results.append(
                process_file(
                    path,
                    requested_time_column=args.time_column,
                    write=args.write,
                    interactive=interactive,
                    verbose=args.verbose,
                )
            )
    except UserAbort as exc:
        print(str(exc), file=sys.stderr)
        print_summary(results, write=args.write)
        return 130

    print_summary(results, write=args.write)

    if any(item.error for item in results):
        return 2
    if args.write and any(item.unresolved_groups for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""One-off NE-300 4035 quality-flag correction using literal instrument states.

    0 -> 0 (normal), 1/2 -> 2 (uncertain/transient), 3 -> 3 (zero),
    4 -> 5 (zero check), 5 -> 4 (span), 6 -> 6 (span check).

The preceding state-1/2 measurements are NOT retrospectively categorized as
zero/span or check based on later completion records. The live processor and
this backfill share processing.ne300_operation_flags.flags_for_operations.

Safe defaults:
* DRY RUN unless --write; atomic writes and optional --backup.
* Only numeric scattering channels 1,000,000..8,000,000.
* Only state 1..6 is eligible. Existing state-0 and unknown-state flags
  are never changed by the backfill.
* Replace null, 0, or 2, plus known wrong auto-flag values from earlier
  packages. Preserve all other non-null QC values (notably manual invalid=1).
* Because manually edited QC flags are not distinguishable from previously
  auto-generated wrong flags, inspect the dry-run report before --write.

Usage:
    python -m housekeeping.backfill_ne300_flags --root /product_data/data/pay/Kenya/git/gawkenyadata/level1/mkn
    python -m housekeeping.backfill_ne300_flags --root /product_data/data/pay/Kenya/git/gawkenyadata/level1/mkn --write --backup
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from processing.ne300_operation_flags import flags_for_operations


@dataclass(frozen=True)
class BackfillResult:
    status: str   # skipped, unchanged, would-update, updated
    changed_flags: int
    applicable_rows: int
    target_columns: tuple[str, ...]


def measurement_columns(df: pl.DataFrame, *, low: int = 1_000_000,
                        high: int = 8_000_000) -> tuple[str, ...]:
    return tuple(c for c in df.columns if c.isdigit() and low <= int(c) <= high)


def reflag_ne300(
    df: pl.DataFrame, *, overwrite_all: bool = False,
) -> tuple[pl.DataFrame, BackfillResult]:
    """Return reflagged frame and per-channel change counts without IO.

    Preserves source row order, measurements, unrelated flags, and dtypes.
    Recognized wrong automatic QC mappings from earlier patches are corrected
    by default, but manual invalid and unrelated explicit flags are preserved.
    """
    if "4035" not in df.columns or "dtm" not in df.columns:
        return df, BackfillResult("skipped", 0, 0, ())
    targets = measurement_columns(df)
    if not targets or df.is_empty():
        return df, BackfillResult("unchanged", 0, 0, targets)

    row_id = "__ne300_original_row__"
    helper = "__ne300_target_flag__"
    if any(x in df.columns for x in (row_id, helper)):
        raise ValueError("Reserved NE-300 helper column already exists")
    ordered = df.with_row_index(row_id).sort("dtm")
    raw_state = ordered.get_column("4035").cast(pl.Int64, strict=False)
    desired = flags_for_operations(
        raw_state.to_list(), ordered.get_column("dtm").to_list(),
        assume_null_is_normal=False,
    )
    state = pl.col("4035").cast(pl.Int64, strict=False)
    applicable = state.is_in([1, 2, 3, 4, 5, 6])
    count = int(ordered.select(applicable.sum()).item() or 0)
    if not count:
        return df, BackfillResult("unchanged", 0, 0, targets)

    ordered = ordered.with_columns(pl.Series(helper, desired, dtype=pl.Int8))
    target = pl.col(helper)
    updates: list[pl.Expr] = []
    change_exprs: list[pl.Expr] = []
    for name in targets:
        fcol = f"f_{name}"
        current = (pl.col(fcol).cast(pl.Int8, strict=False)
                   if fcol in ordered.columns else pl.lit(None, dtype=pl.Int8))
        if overwrite_all:
            replaceable = pl.lit(True)
        else:
            # Earlier versions assigned zero/span or check flags directly
            # to the transient states 1 and 2. Another version exchanged
            # states 3 and 4 and treated state 5 as a zero check. Correct
            # these *known old automatic outputs* without indiscriminately
            # replacing unrelated manual quality-control decisions.
            replaceable = (
                current.is_null() | current.is_in([0, 2])
                | ((state == 1) & current.is_in([3, 5]))
                | ((state == 2) & current.is_in([4, 6]))
                | ((state == 3) & (current == 5))
                | ((state == 4) & (current == 3))
                | ((state == 5) & (current == 5))
                | ((state == 6) & (current == 4))
            )
        eligible = applicable & target.is_not_null() & replaceable
        revised = pl.when(eligible).then(target).otherwise(current).cast(pl.Int8)
        old_dtype = ordered.schema.get(fcol, pl.Int8)
        keep_dtype = pl.Int8 if old_dtype == pl.Null else old_dtype
        updates.append(revised.cast(keep_dtype).alias(fcol))
        change_exprs.append((~current.eq_missing(revised)).sum().alias(fcol))

    changed = sum(int(v or 0) for v in ordered.select(change_exprs).row(0))
    if not changed:
        return df, BackfillResult("unchanged", 0, count, targets)
    result = ordered.with_columns(updates).sort(row_id).drop([row_id, helper])
    return result, BackfillResult("would-update", changed, count, targets)


def process_file(path: Path, *, write: bool = False, backup: bool = False,
                 overwrite_all: bool = False) -> BackfillResult:
    """Apply verified atomic Parquet update; --backup protects original file."""
    source = pl.read_parquet(path)
    revised, outcome = reflag_ne300(source, overwrite_all=overwrite_all)
    if outcome.status != "would-update" or not write:
        return outcome

    if backup:
        backup_path = path.with_name(path.name + ".bak")
        if backup_path.exists():
            raise FileExistsError(f"Backup exists, refusing overwrite: {backup_path}")
        shutil.copy2(path, backup_path)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".parquet", prefix=f".{path.stem}-",
            dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
        revised.write_parquet(temporary)
        if not pl.read_parquet(temporary).equals(revised):
            raise RuntimeError(f"Parquet verification failed for {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return BackfillResult(
        "updated", outcome.changed_flags, outcome.applicable_rows, outcome.target_columns
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="Directory containing monthly NE-300 Parquet files")
    parser.add_argument("--write", action="store_true", help="Apply changes (dry-run by default)")
    parser.add_argument("--backup", action="store_true", help="Keep ne300.parquet.bak originals")
    parser.add_argument("--overwrite-all", action="store_true",
                        help="Override all existing QC flags at operation 1..6 rows")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"Not a directory: {args.root}")
    files = sorted(args.root.rglob("ne300.parquet"))
    if not files:
        print(f"No ne300.parquet files found under {args.root}")
        return 1

    changes = rows = errors = 0
    for path in files:
        try:
            result = process_file(path, write=args.write, backup=args.backup,
                                  overwrite_all=args.overwrite_all)
        except Exception as exc:
            errors += 1
            print(f"ERROR         {path}: {exc}")
            continue
        changes += result.changed_flags
        rows += result.applicable_rows
        print(f"{result.status.upper():<12} {path}  eligible={result.applicable_rows:,} "
              f"changed flags={result.changed_flags:,}")
    print(f"TOTAL         files={len(files)} eligible={rows:,} "
          f"changed flags={changes:,} errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

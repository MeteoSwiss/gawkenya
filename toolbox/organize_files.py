# import hashlib
import logging
import re
import shutil
import zlib
from datetime import datetime
from pathlib import Path


def organize_files_by_date(source: Path, target: Path, logger: logging.Logger) -> None:
    """
    Organize files from source to target directory based on datetime stamp in filenames.

    - Files with 10+ digits are organized by day; else by month.
    - Duplicates with identical content are not copied and removed from source.
    - Modified duplicates are renamed and retained.
    - A report is written under `source/files_not_moved.log`.

    Args:
        source (Path): Root folder to scan recursively.
        target (Path): Destination root.
        logger (Logger): Logger instance.
    """
    removed = []
    skipped = []
    duplicates = []

    for file in source.rglob("*"):
        if not file.is_file():
            continue

        try:
            digits = _extract_datetime_digits(file)
            if not digits:
                logger.warning(f"⚠️ No datetime pattern found in {file.name}, skipping.")
                continue

            # Heuristic for datetime granularity
            if "aerosol" in file.parts:
                timestamp = digits[:8]
                dt_format = "%Y%m%d"
            else:
                timestamp = digits[:14] if len(digits) >= 12 else digits[:10]
                dt_format = "%Y%m%d%H%M" if len(timestamp) > 10 else "%Y%m%d"

            dt = datetime.strptime(timestamp, dt_format)
            subfolder = Path(str(dt.year), f"{dt.month:02d}", f"{dt.day:02d}" if len(timestamp) > 10 else "")
            dst_folder = target / subfolder
            dst_folder.mkdir(parents=True, exist_ok=True)
            dst_file = dst_folder / file.name

            if dst_file.exists():
                same_size = file.stat().st_size == dst_file.stat().st_size
                same_mtime = int(file.stat().st_mtime) == int(dst_file.stat().st_mtime)
                if same_size and same_mtime:
                    # Treat this as duplicate, remove from source
                    logger.info(f"Identical file found at target. Removing {file}")
                    file.unlink()
                    removed.append(file)
                    continue

                if _hash(file) == _hash(dst_file):
                    logger.info(f"Same content at target. Removing {file}")
                    file.unlink()
                    removed.append(file)
                    continue

                # Actual different content, preserve both
                renamed = dst_file.with_stem(dst_file.stem + "_dup")
                counter = 1
                while renamed.exists():
                    renamed = dst_file.with_stem(f"{dst_file.stem}_dup{counter}")
                    counter += 1

                logger.info(f"Duplicate detected. Moving {file} to {renamed}")
                shutil.move(str(file), renamed)
                duplicates.append((file, renamed))
            else:
                logger.info(f"Moving {file} → {dst_file}")
                shutil.move(str(file), dst_file)

        except Exception as e:
            logger.warning(f"⚠ Failed to move file {file}: {e}")

    remove_empty_dirs(source, logger)
    remove_empty_dirs(target, logger)
    _log_issues_with_files(source, removed, skipped, duplicates, logger)


def remove_empty_dirs(base: Path, logger: logging.Logger) -> None:
    for dirpath in sorted(base.rglob("*"), reverse=True):
        if dirpath.is_dir() and not any(dirpath.iterdir()):
            try:
                dirpath.rmdir()
                logger.info(f"Removed empty folder: {dirpath}")
            except Exception:
                pass


def _extract_datetime_digits(file: Path) -> str | None:
    """Extract a datetime digit string from a filename, assuming it's preceded by '-' or '_' or '.'."""
    match = re.search(r"[-_.](\d{8}(?:T\d{6}Z|\d{4})?)", file.name)
    return match.group(1) if match else None


def _hash(path: Path, chunk_size: int = 8192) -> int:
    """Fast CRC32 hash for file comparison."""
    crc = 0
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            crc = zlib.crc32(chunk, crc)
    return crc
# def _hash(path: Path, chunk_size: int = 8192) -> str:
#     h = hashlib.sha256()
#     with open(path, "rb") as f:
#         while chunk := f.read(chunk_size):
#             h.update(chunk)
#     return h.hexdigest()


def _log_issues_with_files(
    source: Path,
    removed: list[Path],
    skipped: list[Path],
    duplicates: list[tuple[Path, Path]],
    logger: logging.Logger,
) -> None:
    log_file = source / "files_not_moved.log"
    try:
        with open(log_file, "w", encoding="utf-8") as fh:
            fh.write("# Files Not Moved Report\n")

            if removed:
                fh.write("\n## Removed (already present in target)\n")
                for f in removed:
                    fh.write(f"{f}\n")
                    logger.info(f"Removed duplicate: {f}")

            if skipped:
                fh.write("\n## Skipped (unhandled)\n")
                for f in skipped:
                    fh.write(f"{f}\n")
                    logger.info(f"Skipped: {f}")

            if duplicates:
                fh.write("\n## Duplicates (kept both versions)\n")
                for original, renamed in duplicates:
                    fh.write(f"{original} -> {renamed}\n")
                    logger.warning(f"Duplicate: {original} renamed to {renamed}")

        logger.info(f"✍ File movement report written to {log_file}")
    except Exception as err:
        logger.error(f"⚠ Failed to write movement report: {err}")

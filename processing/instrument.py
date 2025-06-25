from __future__ import annotations

import os
import json
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional
from charset_normalizer import from_path
import polars as pl

from toolbox.utils import pl_simplify_dtypes, setup_logging


class Instrument(ABC):
    """
    Abstract base class for processing instrument data files into Parquet format.

    Subclasses must implement the `extract_to_dataframe` method.
    This class provides a standard workflow for reading, validating, compiling,
    and archiving files containing time series measurements.
    """

    def __init__(
        self,
        name: str,
        dtm: str = "dtm",
        logger_name: Optional[str] = None,
    ) -> None:
        """
        Initialize the BaseInstrument.

        Args:
            name (str): Instrument name, used in output file naming.
            dtm (str): Column name for the datetime field. Defaults to "dtm".
            logger_name (Optional[str]): Name of the logger. Defaults to instrument name.
        """
        self.name = name
        self.dtm = dtm
        self.logger = setup_logging(logger_name or name)

    def compile_to_parquet(
        self,
        source: str | Path,
        target: str | Path,
        archive: Optional[str | Path] = None,
        issues: Optional[str | Path] = None,
        append_parquet: bool = True,
        split: str = "year",
    ) -> tuple[pl.DataFrame, dict]:
        """
        Compile raw instrument files under `source` into Parquet files organized by `split`.

        Args:
            source (str | Path): Path to directory to search recursively.
            target (str | Path): Root path to write output files.
            archive (Optional[str | Path]): Where to move successfully processed files.
            issues (Optional[str | Path]): Where to move files that raised exceptions.
            append_parquet (bool): If True, existing parquet files will be extended.
            split (str): Either "year" or "month", determining folder structure.

        Returns:
            tuple[pl.DataFrame, dict]: Combined dataframe and dictionary of errors.
        """
        source = Path(source)
        target = Path(target)
        archive = Path(archive) if archive else None
        issues = Path(issues) if issues else None

        split = split.lower()
        if split not in {"year", "month"}:
            self.logger.warning(f"Unsupported split mode '{split}'. Using 'year'.")
            split = "year"

        errors = {}
        result = pl.DataFrame()

        for root, _, files in os.walk(source):
            root_path = Path(root)
            rel_path = root_path.relative_to(source)

            for file in files:
                src = root_path / file
                try:
                    df, err = self.extract_to_dataframe(src)
                except Exception as e:
                    df, err = pl.DataFrame(), str(e)

                if err:
                    errors[file] = err
                    if issues:
                        dst = issues / rel_path
                        dst.mkdir(parents=True, exist_ok=True)
                        shutil.move(src, dst / file)
                    continue

                if archive:
                    dst = archive / rel_path
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.move(src, dst / file)

                result = pl.concat([result, df], how="diagonal")

            try:
                root_path.rmdir()
            except (PermissionError, OSError):
                pass

        if result.is_empty():
            self.logger.warning("No valid data extracted.")
            return result, errors

        result = result.with_columns([
            pl.col(self.dtm).cast(pl.Datetime("us", "UTC")),
            pl.col(self.dtm).dt.year().alias("year"),
            pl.col(self.dtm).dt.month().alias("month")
        ]).unique().sort(self.dtm)

        group_keys = ["year"] if split == "year" else ["year", "month"]

        for keys, group in result.group_by(group_keys, maintain_order=True):
            if isinstance(keys, tuple) and len(keys) == 2:
                year, month = keys
                folder = target / str(year) / f"{month:02d}"
            elif isinstance(keys, (tuple, list)) and len(keys) == 1:
                year = keys[0]
                folder = target / str(year)
            else:
                year = keys  # fallback if keys is not a tuple
                folder = target / str(year)

            folder.mkdir(parents=True, exist_ok=True)
            parquet_file = folder / f"{self.name}.parquet"

            if append_parquet and parquet_file.exists():
                existing = pl.read_parquet(parquet_file)
                group = pl.concat([existing, group], how="diagonal").unique().sort(self.dtm)

            group = pl_simplify_dtypes(group)
            group.write_parquet(parquet_file)
            self.logger.info(f"✔ Written {len(group)} rows to {parquet_file}")

        if errors:
            target.mkdir(parents=True, exist_ok=True)
            error_file = target / f"{self.name}.errors.json"
            with open(error_file, "w") as fh:
                json.dump(errors, fh, indent=2)

        return result, errors


    def read_text_lines(self, path: Path) -> list[str]:
        """
        Read a text file with smart encoding detection using charset_normalizer.
        Falls back to UTF-8 if detection fails.

        Args:
            path (Path): File path to read

        Returns:
            list[str]: List of text lines
        """
        try:
            raw = path.read_bytes()
            result = from_path(path).best()
            encoding = result.encoding if result else "utf-8"
            text = raw.decode(encoding)
            return text.splitlines()

        except Exception as e:
            self.logger.error(f"Failed to read text lines from {path}: {e}")
            return []


    @abstractmethod
    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, Optional[str]]:
        """
        Subclasses must implement logic to extract raw data from a file to a DataFrame.

        Args:
            path (Path): Full path to the file.

        Returns:
            tuple: DataFrame and optional error string.
        """
        pass


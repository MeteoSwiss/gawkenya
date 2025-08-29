from __future__ import annotations

import os
import json
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from charset_normalizer import from_path
import polars as pl
import re
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
        log_file: Optional[str] = None,
    ) -> None:
        """
        Initialize the Instrument base class.

        Args:
            name (str): Instrument name, used in output file naming.
            dtm (str): Column name for the datetime field. Defaults to "dtm".
            log_file (Optional[str]): Path of the log file. Defaults to instrument name.
        """
        self.name = name
        self.dtm = dtm
        self.logger = setup_logging(logger_name=name, log_file=log_file)


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

        split = self._validate_split(split)
        errors = {}
        result = pl.DataFrame()

        for root, _, files in os.walk(source):
            root_path = Path(root)
            rel_path = root_path.relative_to(source)

            for file in files:
                self.logger.info(f"Processing {file}")
                src = root_path / file
                df, err = self._handle_file(src)

                try:
                    result = pl.concat([result, df], how="diagonal")
                except Exception as err:
                    self.logger.error(f"Error concatenating content from {file} to existing dataframe: {err}")
                    # err = str(err)
                    continue

                if err:
                    self._handle_issue_file(src, file, rel_path, issues, errors, err)
                    continue

                if archive:
                    self._archive_file(src, file, rel_path, archive)

            # clean up empty folders in source, except the source foulder itself
            if root_path != source:
                try:
                    root_path.rmdir()
                except (PermissionError, OSError):
                    pass

        if result.is_empty():
            self.logger.warning("No valid data extracted.")
            return result, errors

        self._write_parquet(result, target, split, append_parquet)

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


    def amend_path_from_filename(self, path: Path, filename: str) -> Path:
        """
        Appends year/month/day subfolders to a path based on a datetime string
        found in the filename after a '-' or '.', formatted as %Y%m%d[%H%M].

        The split level (year/month/day) is inferred from the length of the matched string:
        - 8+ digits: year/month/day
        - 6 digits:  year/month
        - 4 digits:  year

        Args:
            path (Path): The base path.
            filename (str): Filename containing a datetime string.

        Returns:
            Path: Updated path with inferred subfolders appended.
        """
        match = re.search(r"[-.](\d{4})(\d{2})(\d{2})(\d{0,4})", filename)
        if not match:
            return path

        year, month, day = match.group(1), match.group(2), match.group(3)

        path = path / year / month
        if match.group(4):
            path = path / day

        return path


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


    def _validate_split(self, split: str) -> str:
        split = split.lower()
        if split not in {"year", "month"}:
            self.logger.warning(f"Unsupported split mode '{split}'. Using 'year'.")
            return "year"
        return split


    def _handle_file(self, src: Path) -> tuple[pl.DataFrame, Optional[str]]:
        try:
            df, err, _ = self.extract_to_dataframe(src)
        except Exception as e:
            df, err = pl.DataFrame(), str(e)
        return df, err


    def _handle_issue_file(self, src: Path, file: str, rel_path: Path, issues: Optional[Path], errors: dict, err: str) -> None:
        errors[file] = err
        if issues:
            dst = issues / rel_path
            try:
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(src, dst / file)
                self.logger.warning(f"Issue with file: {src} > {dst / file}")
            except (PermissionError, OSError):
                self.logger.warning(f"Permission error, cannot move file: {src} > {dst / file} failed.")


    def _archive_file(self, src: Path, file: str, rel_path: Path, archive: Path) -> None:
        if str(rel_path) in str(archive):
            dst = archive
        else:
            dst = archive / rel_path
        dst = self.amend_path_from_filename(dst, file)
        try:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst / file)
        except (PermissionError, OSError):
            self.logger.warning(f"Permission error, cannot archive file: {src} > {dst / file} failed.")


    def _write_parquet(self, result: pl.DataFrame, target: Path, split: str, append_parquet: bool) -> None:
        # result = result.with_columns([
        #     pl.col(self.dtm).cast(pl.Datetime("us", "UTC")),
        #     pl.col(self.dtm).dt.year().alias("_year"),
        #     pl.col(self.dtm).dt.month().alias("_month")
        # ]).unique().sort(self.dtm)
        null_rows = result.filter(pl.col(self.dtm).is_null())
        if not null_rows.is_empty():
            self.logger.warning(f"{len(null_rows)} rows with null '{self.dtm}' column found")

        # Ensure dtm is present and typed first
        result = (
            result
            .filter(pl.col(self.dtm).is_not_null())
            .with_columns([
                pl.col(self.dtm).cast(pl.Datetime("us", "UTC")).alias(self.dtm),
                pl.col(self.dtm).dt.year().alias("_year"),
                pl.col(self.dtm).dt.month().alias("_month"),
            ])
        )

        # --- NEW: coerce any Null-typed columns BEFORE unique() ---
        null_cols = [c for c, dt in result.schema.items() if dt == pl.Null and c != self.dtm]
        if null_cols:
            str_cols = [c for c in null_cols if c in {"id", "checksum"}]
            num_cols = [c for c in null_cols if c not in {"id", "checksum"}]
            if str_cols:
                result = result.with_columns([pl.col(c).cast(pl.Utf8) for c in str_cols])
            if num_cols:
                result = result.with_columns([pl.col(c).cast(pl.Float64) for c in num_cols])

        # --- NEW: de-duplicate on a safe subset (timestamp) ---
        # If your records are unique by timestamp alone, this is sufficient.
        # If you need stronger uniqueness, add more fields to the subset list.
        result = (
            result
            .unique(subset=[self.dtm], keep="last")   # or keep="first"
            .sort(self.dtm)
        )

        group_keys = ["_year"] if split == "year" else ["_year", "_month"]

        for keys, group in result.group_by(group_keys, maintain_order=True):
            if isinstance(keys, tuple) and len(keys) == 2:
                year, month = keys
                folder = target / str(year) / f"{month:02d}"
            else:
                year = keys[0] if isinstance(keys, (tuple, list)) else keys
                folder = target / str(year)

            folder.mkdir(parents=True, exist_ok=True)
            parquet_file = folder / f"{self.name}.parquet"
            existing = pl.DataFrame()
            
            group = pl_simplify_dtypes(group).drop(["_year", "_month"])
            if append_parquet and parquet_file.exists():
                existing = pl_simplify_dtypes(pl.read_parquet(parquet_file)).drop(["year", "month"])
                group = pl.concat([existing, group], how="diagonal").unique().sort(self.dtm)

            group.write_parquet(parquet_file)
            self.logger.info(f"✔ Written {len(group) - len(existing)} new rows to {parquet_file}")

# from __future__ import annotations

# import os
# import json
# import shutil
# from abc import ABC, abstractmethod
# from datetime import datetime
# from pathlib import Path
# from typing import Optional, Tuple
# from charset_normalizer import from_path
# import polars as pl
# import re
# from toolbox.utils import pl_simplify_dtypes, setup_logging


# class Instrument(ABC):
#     """
#     Abstract base class for processing instrument data files into Parquet format.

#     Subclasses must implement the `extract_to_dataframe` method.
#     This class provides a standard workflow for reading, validating, compiling,
#     and archiving files containing time series measurements.
#     """

#     def __init__(
#         self,
#         name: str,
#         dtm: str = "dtm",
#         log_file: Optional[str] = None,
#     ) -> None:
#         """
#         Initialize the BaseInstrument.

#         Args:
#             name (str): Instrument name, used in output file naming.
#             dtm (str): Column name for the datetime field. Defaults to "dtm".
#             log_file (Optional[str]): Name of the logger. Defaults to instrument name.
#         """
#         self.name = name
#         self.dtm = dtm
#         self.logger = setup_logging(log_file or name)

#     def compile_to_parquet(
#         self,
#         source: str | Path,
#         target: str | Path,
#         archive: Optional[str | Path] = None,
#         issues: Optional[str | Path] = None,
#         append_parquet: bool = True,
#         split: str = "year",
#     ) -> tuple[pl.DataFrame, dict]:
#         """
#         Compile raw instrument files under `source` into Parquet files organized by `split`.

#         Args:
#             source (str | Path): Path to directory to search recursively.
#             target (str | Path): Root path to write output files.
#             archive (Optional[str | Path]): Where to move successfully processed files.
#             issues (Optional[str | Path]): Where to move files that raised exceptions.
#             append_parquet (bool): If True, existing parquet files will be extended.
#             split (str): Either "year" or "month", determining folder structure.

#         Returns:
#             tuple[pl.DataFrame, dict]: Combined dataframe and dictionary of errors.
#         """
#         source = Path(source)
#         target = Path(target)
#         archive = Path(archive) if archive else None
#         issues = Path(issues) if issues else None

#         split = split.lower()
#         if split not in {"year", "month"}:
#             self.logger.warning(f"Unsupported split mode '{split}'. Using 'year'.")
#             split = "year"

#         errors = {}
#         result = pl.DataFrame()

#         for root, _, files in os.walk(source):
#             root_path = Path(root)
#             rel_path = root_path.relative_to(source)

#             for file in files:
#                 self.logger.info(f"Processing {file}")
#                 src = root_path / file
#                 try:
#                     df, err, file_type = self.extract_to_dataframe(src)
#                 except Exception as e:
#                     df, err = pl.DataFrame(), str(e)

#                 if err:
#                     errors[file] = err
#                     if issues:
#                         dst = issues / rel_path
#                         try:
#                             dst.mkdir(parents=True, exist_ok=True)
#                             shutil.move(src, dst / file)
#                             self.logger.warning(f"Issue with file: {src} > {dst / file}")
#                         except (PermissionError, OSError):
#                             self.logger.warning(f"Permission error, cannot move file: {src} > {dst / file} failed.")
#                             pass
#                     continue

#                 if archive:
#                     if str(rel_path) in str(archive):
#                         dst = archive
#                     else:
#                         dst = archive / rel_path

#                     dst = self.amend_path_from_filename(dst, file)

#                     try:
#                         dst.mkdir(parents=True, exist_ok=True)
#                         shutil.move(src, dst / file)
#                     except (PermissionError, OSError):
#                         self.logger.warning(f"Permission error, cannot archive file: {src} > {dst / file} failed.")
#                         pass

#                 result = pl.concat([result, df], how="diagonal")

#             try:
#                 root_path.rmdir()
#             except (PermissionError, OSError):
#                 pass

#         if result.is_empty():
#             self.logger.warning("No valid data extracted.")
#             return result, errors

#         result = result.with_columns([
#             pl.col(self.dtm).cast(pl.Datetime("us", "UTC")),
#             pl.col(self.dtm).dt.year().alias("year"),
#             pl.col(self.dtm).dt.month().alias("month")
#         ]).unique().sort(self.dtm)

#         group_keys = ["year"] if split == "year" else ["year", "month"]

#         for keys, group in result.group_by(group_keys, maintain_order=True):
#             if isinstance(keys, tuple) and len(keys) == 2:
#                 year, month = keys
#                 folder = target / str(year) / f"{month:02d}"
#             elif isinstance(keys, (tuple, list)) and len(keys) == 1:
#                 year = keys[0]
#                 folder = target / str(year)
#             else:
#                 year = keys  # fallback if keys is not a tuple
#                 folder = target / str(year)

#             folder.mkdir(parents=True, exist_ok=True)
#             parquet_file = folder / f"{self.name}.parquet"

#             if append_parquet and parquet_file.exists():
#                 existing = pl.read_parquet(parquet_file)
#                 existing = pl_simplify_dtypes(existing)
#                 group = pl.concat([existing, group], how="diagonal").unique().sort(self.dtm)

#             group = pl_simplify_dtypes(group)
#             group.write_parquet(parquet_file)
#             self.logger.info(f"✔ Written {len(group)} rows to {parquet_file}")

#         if errors:
#             target.mkdir(parents=True, exist_ok=True)
#             error_file = target / f"{self.name}.errors.json"
#             with open(error_file, "w") as fh:
#                 json.dump(errors, fh, indent=2)

#         return result, errors


#     def read_text_lines(self, path: Path) -> list[str]:
#         """
#         Read a text file with smart encoding detection using charset_normalizer.
#         Falls back to UTF-8 if detection fails.

#         Args:
#             path (Path): File path to read

#         Returns:
#             list[str]: List of text lines
#         """
#         try:
#             raw = path.read_bytes()
#             result = from_path(path).best()
#             encoding = result.encoding if result else "utf-8"
#             text = raw.decode(encoding)
#             return text.splitlines()

#         except Exception as e:
#             self.logger.error(f"Failed to read text lines from {path}: {e}")
#             return []


#     def amend_path_from_filename(self, path: Path, filename: str) -> Path:
#         """
#         Appends year/month/day subfolders to a path based on a datetime string
#         found in the filename after a '-' or '.', formatted as %Y%m%d[%H%M].

#         The split level (year/month/day) is inferred from the length of the matched string:
#         - 8+ digits: year/month/day
#         - 6 digits:  year/month
#         - 4 digits:  year

#         Args:
#             path (Path): The base path.
#             filename (str): Filename containing a datetime string.

#         Returns:
#             Path: Updated path with inferred subfolders appended.
#         """
#         match = re.search(r"[-.](\d{4})(\d{2})(\d{2})(\d{0,4})", filename)
#         if not match:
#             return path

#         year, month, day = match.group(1), match.group(2), match.group(3)

#         path = path / year / month
#         if match.group(4):  # time info implies full date is present
#             path = path / day

#         return path
#     # def amend_path_from_filename(self, path: Path, filename: str, split: str = "year") -> Path:
#     #     """
#     #     Amends a base path by appending year/month/day subfolders based on a datetime
#     #     string (format %Y%m%d[%H%M]) found after a '-' or '.' in the filename.

#     #     Args:
#     #         path (Path): Base path to be amended.
#     #         filename (str): Filename containing the datetime.
#     #         split (str): One of 'year', 'month', or 'day'.

#     #     Returns:
#     #         Path: Amended path including year/month/day as specified.

#     #     Raises:
#     #         ValueError: If datetime string is not found or invalid split argument is used.
#     #     """
#     #     match = re.search(r"[-.](\d{4})(\d{2})(\d{2})\d{0,4}", filename)

#     #     if not match:
#     #         return path

#     #     year, month, day = match.group(1), match.group(2), match.group(3)

#     #     match split:
#     #         case "year":
#     #             return path / year
#     #         case "month":
#     #             return path / year / month
#     #         case "day":
#     #             return path / year / month / day
#     #         case _:
#     #             return path  # or raise ValueError(f"Invalid split option: {split}")
        

#     @abstractmethod
#     def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, Optional[str]]:
#         """
#         Subclasses must implement logic to extract raw data from a file to a DataFrame.

#         Args:
#             path (Path): Full path to the file.

#         Returns:
#             tuple: DataFrame and optional error string.
#         """
#         pass


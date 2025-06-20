import logging
import os
import re
import shutil
from pathlib import Path

import polars as pl

from toolbox.utils import load_config, pl_simplify_dtypes, setup_logging


class FIDAS:
    config: dict
    name: str

    def __init__(self, config: dict, name: str='fidas') -> None:
        self.name = name
        self.logger: logging.Logger      # config['logging']
        self.root: str                   # config['root']
        self.incoming: str               # config['branches']['incoming']
        self.archive: str                # config['branches']['archive']
        self.issues: str                 # config['branches']['issues']

        try:
            # configure logging
            self.logger = logging.getLogger(f"{config['logging'].split('.')[0]}.{__name__}")
            self.logger.info("Initialize FIDAS class.")

            self.name = name
            self.root = config['root']
            self.incoming = config['branches']['incoming']
            self.archive = config['branches']['archive']
            self.issues = config['branches']['issues']

        except Exception as err:
            self.logger.error(err)


    def _move_file(self, src: str, dst: str, split: str = "month") -> Path:
        """create destination path and move file.

        Args:
            src (str): Full path to source file.
            dst (str): Destination root path.
            split (str, optional): File organization in dst. One of 'year|month|day'. Defaults to 'month'.

        Returns:
            Path: Full path to destination.
        """
        try:
            src = Path(src)
            match = re.search(r"-(\d{4})(\d{2})(\d{2})\d+\.parquet$", src.name)

            if not match:
                shutil.move(src, Path(dst) / src.name)
                return Path(dst) / src.name  # Default case if no timestamp match

            year, month, day = match.group(1, 2, 3)
            dst = Path(dst) / year / month / day
            split_map = {
                "year": dst.parents[2],
                "month": dst.parent,
                "day": dst,
            }
            dst = split_map.get(split, dst)
            dst.mkdir(parents=True, exist_ok=True)

            # print(f"shutil.move({src}, {Path(dst) / src.name}")
            shutil.move(src, dst / src.name)            
            self.logger.info(f"file moved: {src} > {dst / src.name}")
            
            return dst / src.name
        
        except Exception as err:
            self.logger.error("_move_file: %s produced exception: %s", src, err)
            

    def append_parquet(self, df: pl.DataFrame, target: Path, dtm: str = "dtm",
                    split: str = "month", file_name: str = "fidas.parquet") -> list[Path]:
        """
        Efficiently appends data to parquet files organized by time, using group_by_dynamic for fast time-based grouping.

        Args:
            df (pl.DataFrame): The input data frame.
            target (Path): Base target folder.
            dtm (str): The datetime column name.
            split (str): One of 'year', 'month', or 'day'.
            file_name (str): Output parquet file name.

        Returns:
            list[Path]: List of written file paths.
        """
        try:
            if df.is_empty():
                return []

            assert split in {"year", "month", "day"}, "split must be 'year', 'month', or 'day'"

            df = pl_simplify_dtypes(df).with_columns(
                pl.col(dtm).cast(pl.Datetime("us", "UTC"))
            ).sort(by="dtm")

            interval = {"year": "1y", "month": "1mo", "day": "1d"}[split]
            written_paths = []

            for _, group_df in df.group_by_dynamic(dtm, every=interval, period=interval):
                if group_df.is_empty():
                    continue

                ts = group_df[dtm][0]
                year = f"{ts.year:04d}"
                month = f"{ts.month:02d}"
                day = f"{ts.day:02d}"

                if split == "year":
                    folder = target / year
                elif split == "month":
                    folder = target / f"{year}/{month}"
                else:  # split == "day"
                    folder = target / f"{year}/{month}/{day}"

                folder.mkdir(parents=True, exist_ok=True)
                file_path = folder / file_name

                if file_path.exists():
                    existing = pl.read_parquet(file_path)
                    combined = pl.concat([existing, group_df], how="diagonal").unique().sort(dtm)
                else:
                    combined = group_df.unique().sort(dtm)

                combined.write_parquet(file_path)
                written_paths.append(file_path)

            return written_paths

        except Exception as err:
            self.logger.error(f"append_parquet: writing to {target / file_name} failed with: {err}")
            return []

    # def append_parquet(self, df: pl.DataFrame, target: Path, dtm: str="dtm",
    #                    split: str="month", file_name: str="fidas.parquet") -> Path:
    #     try:
    #         assert split in {"year", "month", "day"}, "split must be 'year', 'month', or 'day'"

    #         df = pl_simplify_dtypes(df)
    #         start_date, end_date = df[dtm].min().date(), df[dtm].max().date()
    #         date_ranges = pl.date_range(start_date, end_date, interval="1d", eager=True)

    #         for date in date_ranges:
    #             year, month, day = str(date.year), f"{date.month:02d}", f"{date.day:02d}"
    #             dst = target / year / month / day
    #             split_map = {
    #                 "year": dst.parents[2],
    #                 "month": dst.parent,
    #                 "day": dst,
    #             }
    #             dst = split_map.get(split, dst)
    #             dst.mkdir(parents=True, exist_ok=True)

    #             df_filtered = df.filter(
    #                 (pl.col(dtm).dt.year() == date.year)
    #                 & (split != "year" or (pl.col(dtm).dt.month() == date.month))
    #                 & (split != "month" or (pl.col(dtm).dt.date() == date))
    #             )   # [TODO] handle case where df extends across split?

    #             file_path = dst / file_name
    #             if file_path.exists():
    #                 df_existing = pl.read_parquet(file_path)
    #                 rows_existing = len(df_existing)
    #                 df_combined = pl.concat([df_existing, df_filtered], how="diagonal").unique().sort(dtm)
    #             else:
    #                 rows_existing = 0
    #                 df_combined = df_filtered.unique().sort(dtm)
    #             rows_combined = len(df_combined)

    #             df_combined.write_parquet(file_path)
            
    #         self.logger.info(f"{file_path}: rows added: {rows_combined - rows_existing}")
    #         return file_path
    #     except Exception as err:
    #         self.logger.error("append_parquet: %s produced exception: %s", target / file_name, err)
    #         return str()


    def compile_files_to_parquet(self, source: str=str(), target: str=str(),
                                 move_processed_files: bool=True, archive: str=str(), issues: str=str(), 
                                 split: str="month", dtm: str="dtm"):
        """
        Harvest a folder and its sub-folders, compile data into .parquet files, and organize them.
        
        Args:
            source (str, optional): Folder to harvest. Defaults to self.root / self.incoming / self.name.
            target (str, optional): Folder for .parquet files. Defaults to 'data/level1'.
            dtm (str, optional): Timestamp column name. Defaults to 'dtm'.
            move_processed_files (bool, optional): Move processed files? Defaults to True.
        """
        try:
            source = Path(source or (Path(self.root) / self.incoming / self.name))
            archive = Path(archive or (Path(self.root) / self.archive / self.name))
            issues = Path(issues or (Path(self.root) / self.issues / self.name))
            target = Path(target or (Path(self.root) / target))
            if not source.exists():
                return

            src = Path()
            self.logger.info(f"Processing {source} ...")
            files_processed = int()
            for root, dirs, files in os.walk(source):
                for file in files:
                    if not file.startswith("fidas-"):
                        continue

                    files_processed += 1
                    _dst = issues  # Default destination

                    src = Path(root) / file
                    df = pl.read_parquet(source=src)
                    if not df.is_empty():
                        parquet = self.append_parquet(df=df, target=target, dtm=dtm, split=split)
                        if parquet:
                            _dst = archive  # Success
                    if move_processed_files:
                        dst = self._move_file(src=src, dst=_dst, split=split)

                if Path(root) != source:
                    try:
                        Path(root).rmdir()
                    except OSError:
                        pass

                if files_processed:
                    self.logger.info(f"Finished: {files_processed} files processed.")
                else:
                    self.logger.info("No files found to process.")
                    
        except Exception as err:
            self.logger.error(f"[compile_files_to_parquet] file: {src} produced error: {err}")



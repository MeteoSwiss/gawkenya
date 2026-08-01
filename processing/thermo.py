from __future__ import annotations

"""Thermo 49C/49I raw-data processor.

This drop-in replacement supports both generations of files used in gawkenya:

* legacy whitespace-delimited files beginning with ``pcdate``;
* current pydaq comma-delimited files beginning with ``dtm``;
* plain text files and ZIP archives containing a text member;
* instrument aliases ``49c``/``tei49c`` and ``49i``/``tei49i``.

The extractor returns the standard ``(DataFrame, error)`` tuple expected by
``processing.instrument.Instrument.compile_to_parquet``.
"""

import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import polars as pl

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


class Thermo(Instrument):
    """Processor for Thermo 49C and 49I ozone-analyser data files."""

    _ALIASES = {
        "49c": "tei49c",
        "tei49c": "tei49c",
        "49i": "tei49i",
        "tei49i": "tei49i",
    }

    _LEGACY_HEADERS = {
        "tei49c": [
            "pcdate",
            "pctime",
            "time",
            "date",
            "o3",
            "flags",
            "cellai",
            "cellbi",
            "bncht",
            "lmpt",
            "o3lt",
            "flowa",
            "flowb",
            "pres",
        ],
        "tei49i": [
            "pcdate",
            "pctime",
            "time",
            "date",
            "flags",
            "o3",
            "hio3",
            "cellai",
            "cellbi",
            "bncht",
            "lmpt",
            "o3lt",
            "flowa",
            "flowb",
            "pres",
        ],
    }

    # Current pydaq emits the same modern layout for both instruments. 49C has
    # an empty hio3 field, which is dropped after parsing when entirely null.
    _MODERN_HEADER = [
        "dtm",
        "time",
        "date",
        "o3",
        "flags",
        "hio3",
        "cellai",
        "cellbi",
        "bncht",
        "lmpt",
        "o3lt",
        "flowa",
        "flowb",
        "pres",
    ]

    _FLOAT_COLUMNS = {
        "o3",
        "hio3",
        "bncht",
        "lmpt",
        "o3lt",
        "flowa",
        "flowb",
        "pres",
    }
    _INTEGER_COLUMNS = {"cellai", "cellbi"}
    _TEXT_COLUMNS = {"pcdate", "pctime", "time", "date", "flags", "source"}
    _PREFERRED_MEMBER_SUFFIXES = {".csv", ".dat", ".txt"}

    def __init__(self, name: str = "thermo", log_file: str = str()) -> None:
        # Preserve the caller-supplied name because Instrument uses it for the
        # compiled parquet filename. Instrument type is resolved separately.
        super().__init__(name=name, log_file=log_file)

        # Public compatibility attributes retained from the previous class.
        self.headers = {
            "tei49c": list(self._LEGACY_HEADERS["tei49c"]),
            "49c": list(self._LEGACY_HEADERS["tei49c"]),
            "tei49i": list(self._LEGACY_HEADERS["tei49i"]),
            "49i": list(self._LEGACY_HEADERS["tei49i"]),
        }
        self.modern_headers = {
            alias: list(self._MODERN_HEADER)
            for alias in ("tei49c", "49c", "tei49i", "49i")
        }

        legacy_49c_types = (
            [pl.Utf8] * 4
            + [pl.Float32]
            + [pl.Utf8]
            + [pl.Int32] * 2
            + [pl.Float32] * 6
        )
        legacy_49i_types = (
            [pl.Utf8] * 5
            + [pl.Float32] * 2
            + [pl.Int32] * 2
            + [pl.Float32] * 6
        )
        modern_types = (
            [pl.Utf8] * 3
            + [pl.Float32]
            + [pl.Utf8]
            + [pl.Float32]
            + [pl.Int32] * 2
            + [pl.Float32] * 6
        )
        self.dtypes = {
            "tei49c": list(legacy_49c_types),
            "49c": list(legacy_49c_types),
            "tei49i": list(legacy_49i_types),
            "49i": list(legacy_49i_types),
        }
        self.modern_dtypes = {
            alias: list(modern_types)
            for alias in ("tei49c", "49c", "tei49i", "49i")
        }

    @staticmethod
    def _clean_field_name(value: str) -> str:
        """Normalize a source header field to a stable lowercase name."""
        return str(value).strip().lstrip("\ufeff").lower()

    @classmethod
    def _normalize_model_name(cls, value: str) -> str | None:
        """Resolve a supported instrument alias to ``tei49c`` or ``tei49i``."""
        normalized = str(value).strip().lower().replace("_", "").replace("-", "")
        if normalized == "thermo":
            return None
        if normalized in {"49c", "tei49c"}:
            return "tei49c"
        if normalized in {"49i", "tei49i"}:
            return "tei49i"
        return cls._ALIASES.get(str(value).strip().lower())

    def _detect_model(self, path: Path) -> str:
        """Determine the Thermo model from the filename and configured name.

        A model encoded in the source filename takes precedence because one
        generic ``Thermo()`` instance may be used to inspect either model.
        """
        filename = path.name.lower()
        match = re.search(r"(?:^|[^a-z0-9])(?:tei)?49([ci])(?=[^a-z0-9]|$)", filename)
        filename_model = f"tei49{match.group(1)}" if match else None
        configured_model = self._normalize_model_name(self.name)

        if filename_model and configured_model and filename_model != configured_model:
            self.logger.warning(
                "%s: filename indicates %s but processor name %r indicates %s; using filename",
                path.name,
                filename_model,
                self.name,
                configured_model,
            )

        model = filename_model or configured_model
        if model is None:
            raise ValueError(
                "Could not determine Thermo model. Use Thermo(name='49c'), "
                "Thermo(name='tei49c'), Thermo(name='49i'), or "
                "Thermo(name='tei49i'), or provide a filename containing 49c/49i."
            )
        return model

    def _read_raw_text(self, path: Path, model: str) -> tuple[str, str | None]:
        """Read a plain text file or the best data member from a ZIP archive."""
        member_name: str | None = None

        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as archive:
                members = [
                    name
                    for name in archive.namelist()
                    if not name.endswith("/")
                    and not name.startswith("__MACOSX/")
                    and Path(name).name != ".DS_Store"
                ]
                if not members:
                    raise ValueError("ZIP archive does not contain a readable data member.")

                def member_rank(name: str) -> tuple[int, int, str]:
                    member_path = Path(name)
                    suffix_rank = 0 if member_path.suffix.lower() in self._PREFERRED_MEMBER_SUFFIXES else 1
                    model_token = "49c" if model == "tei49c" else "49i"
                    model_rank = 0 if model_token in member_path.name.lower() else 1
                    return suffix_rank, model_rank, name

                members.sort(key=member_rank)
                member_name = members[0]
                if len(members) > 1:
                    self.logger.info(
                        "%s: selected ZIP member %r from %d candidates",
                        path.name,
                        member_name,
                        len(members),
                    )
                raw = archive.read(member_name)
        else:
            raw = path.read_bytes()

        decode_errors: list[str] = []
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding), member_name
            except UnicodeDecodeError as err:
                decode_errors.append(f"{encoding}: {err}")

        raise ValueError("Could not decode source data: " + "; ".join(decode_errors))

    @staticmethod
    def _nonempty_lines(text: str) -> list[str]:
        """Return non-empty lines while preserving source order."""
        return [line for line in text.splitlines() if line.strip()]

    @staticmethod
    def _try_parse_datetime(value: str) -> datetime | None:
        """Parse a timestamp and normalize it to timezone-aware UTC."""
        text = str(value).strip()
        if not text:
            return None

        iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            parsed = datetime.fromisoformat(iso_text)
        except ValueError:
            parsed = None

        if parsed is None:
            formats = (
                "%Y/%m/%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
                "%m/%d/%Y %H:%M:%S.%f",
                "%m/%d/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
            )
            for fmt in formats:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue

        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _detect_layout(
        self,
        lines: list[str],
        model: str,
    ) -> tuple[str, list[str], bool]:
        """Detect layout and return ``(layout, columns, has_header)``."""
        if not lines:
            raise ValueError("Source file is empty.")

        first = lines[0].strip().lstrip("\ufeff")
        csv_fields = next(csv.reader([first], skipinitialspace=True))
        csv_fields = [field.strip() for field in csv_fields]

        if csv_fields and self._clean_field_name(csv_fields[0]) == "dtm":
            columns = [self._clean_field_name(field) for field in csv_fields]
            return "modern", columns, True

        if len(csv_fields) > 1 and self._try_parse_datetime(csv_fields[0]) is not None:
            if len(csv_fields) == len(self._MODERN_HEADER):
                return "modern", list(self._MODERN_HEADER), False
            if len(csv_fields) == len(self._MODERN_HEADER) - 1:
                columns = [column for column in self._MODERN_HEADER if column != "hio3"]
                return "modern", columns, False

        whitespace_fields = first.split()
        if whitespace_fields and self._clean_field_name(whitespace_fields[0]) == "pcdate":
            columns = [self._clean_field_name(field) for field in whitespace_fields]
            return "legacy", columns, True

        # Headerless legacy files are accepted when the first two tokens form a
        # valid date/time and the field count matches the instrument schema.
        legacy_columns = list(self._LEGACY_HEADERS[model])
        if len(whitespace_fields) == len(legacy_columns):
            combined = f"{whitespace_fields[0]} {whitespace_fields[1]}"
            if self._try_parse_datetime(combined) is not None:
                return "legacy", legacy_columns, False

        raise ValueError(
            "Unsupported Thermo layout. Expected a modern CSV header beginning "
            "with 'dtm' or a legacy whitespace header beginning with 'pcdate'."
        )

    def _extract_modern_records(
        self,
        lines: list[str],
        columns: list[str],
        has_header: bool,
        path: Path,
    ) -> list[dict[str, str]]:
        """Extract comma-delimited modern records using the actual header."""
        if len(set(columns)) != len(columns):
            raise ValueError(f"Duplicate modern header fields after normalization: {columns}")
        if "dtm" not in columns:
            raise ValueError("Modern Thermo input is missing the required 'dtm' column.")

        required = {"dtm", "o3", "flags"}
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"Modern Thermo input is missing required columns: {', '.join(missing)}")

        records: list[dict[str, str]] = []
        reader = csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True)
        header_consumed = not has_header
        expected_fields = len(columns)

        for line_number, raw_fields in enumerate(reader, start=1):
            fields = [field.strip() for field in raw_fields]
            if not fields or not any(fields):
                continue

            if not header_consumed:
                header_consumed = True
                continue

            if self._clean_field_name(fields[0]) == "dtm":
                # Repeated headers can occur in concatenated text exports.
                continue

            while len(fields) > expected_fields and fields[-1] == "":
                fields.pop()

            if len(fields) != expected_fields:
                self.logger.warning(
                    "%s:%d: skipped modern row with %d fields; expected %d",
                    path.name,
                    line_number,
                    len(fields),
                    expected_fields,
                )
                continue

            records.append(dict(zip(columns, fields)))

        return records

    def _extract_legacy_records(
        self,
        lines: list[str],
        columns: list[str],
        has_header: bool,
        path: Path,
    ) -> list[dict[str, str]]:
        """Extract whitespace-delimited legacy records."""
        if len(set(columns)) != len(columns):
            raise ValueError(f"Duplicate legacy header fields after normalization: {columns}")

        required = {"pcdate", "pctime", "o3", "flags"}
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"Legacy Thermo input is missing required columns: {', '.join(missing)}")

        records: list[dict[str, str]] = []
        expected_fields = len(columns)
        header_consumed = not has_header

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            fields = stripped.split()

            if not header_consumed:
                header_consumed = True
                continue
            if fields and self._clean_field_name(fields[0]) == "pcdate":
                continue

            if len(fields) != expected_fields:
                self.logger.warning(
                    "%s:%d: skipped legacy row with %d fields; expected %d",
                    path.name,
                    line_number,
                    len(fields),
                    expected_fields,
                )
                continue

            records.append(dict(zip(columns, fields)))

        return records

    def _records_to_dataframe(
        self,
        records: list[dict[str, str]],
        model: str,
        layout: str,
        path: Path,
    ) -> pl.DataFrame:
        """Normalize parsed records and construct the final dataframe."""
        normalized_records: list[dict[str, str]] = []
        timestamps: list[datetime] = []

        for row_number, record in enumerate(records, start=1):
            if layout == "modern":
                parsed = self._try_parse_datetime(record.get("dtm", ""))
            else:
                parsed = self._try_parse_datetime(
                    f"{record.get('pcdate', '')} {record.get('pctime', '')}"
                )

            if parsed is None:
                self.logger.warning(
                    "%s: skipped record %d because its timestamp could not be parsed",
                    path.name,
                    row_number,
                )
                continue

            cleaned = {self._clean_field_name(key): str(value).strip() for key, value in record.items()}
            cleaned.pop("dtm", None)

            # Modern files do not contain pcdate/pctime. Derive them to retain
            # the stable legacy-compatible output schema used downstream. For
            # legacy files, preserve the original pcdate/pctime strings.
            if layout == "modern":
                cleaned["pcdate"] = parsed.strftime("%Y-%m-%d")
                cleaned["pctime"] = parsed.strftime("%H:%M:%S")

            normalized_records.append(cleaned)
            timestamps.append(parsed)

        if not normalized_records:
            raise ValueError("No valid Thermo records remained after timestamp parsing.")

        all_columns: list[str] = []
        seen: set[str] = set()
        for record in normalized_records:
            for column in record:
                if column not in seen:
                    seen.add(column)
                    all_columns.append(column)

        # Start with strings. Known measurement fields are cast below.
        data = {
            column: [record.get(column) for record in normalized_records]
            for column in all_columns
        }
        df = pl.DataFrame(data)
        df = df.with_columns(
            [
                pl.Series(
                    self.dtm,
                    timestamps,
                    dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
                ),
                pl.lit(str(path)).alias("source"),
            ]
        )

        float_columns = [column for column in self._FLOAT_COLUMNS if column in df.columns]
        if float_columns:
            df = df.with_columns(
                [
                    pl.col(column)
                    .cast(pl.Utf8, strict=False)
                    .str.strip_chars()
                    .cast(pl.Float64, strict=False)
                    .alias(column)
                    for column in float_columns
                ]
            )

        integer_columns = [column for column in self._INTEGER_COLUMNS if column in df.columns]
        if integer_columns:
            integer_exprs: list[pl.Expr] = []
            for column in integer_columns:
                source = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
                as_float = source.cast(pl.Float64, strict=False)
                integer_exprs.append(
                    pl.when(
                        as_float.is_not_null()
                        & ((as_float - as_float.round(0)).abs() < 1e-6)
                    )
                    .then(as_float.round(0))
                    .otherwise(None)
                    .cast(pl.Int64, strict=False)
                    .alias(column)
                )
            df = df.with_columns(integer_exprs)

        text_columns = [column for column in self._TEXT_COLUMNS if column in df.columns]
        if text_columns:
            df = df.with_columns(
                [pl.col(column).cast(pl.Utf8, strict=False).alias(column) for column in text_columns]
            )

        # 49C's current pydaq layout includes an empty hio3 placeholder. Drop it
        # when it has no information so legacy and modern 49C schemas align.
        if "hio3" in df.columns and df["hio3"].null_count() == df.height:
            df = df.drop("hio3")

        canonical = list(self._LEGACY_HEADERS[model])
        if "hio3" not in df.columns:
            canonical = [column for column in canonical if column != "hio3"]
        extras = [
            column
            for column in df.columns
            if column not in canonical and column not in {"source", self.dtm}
        ]
        ordered = [
            column
            for column in [*canonical, *extras, "source", self.dtm]
            if column in df.columns
        ]

        df = df.select(ordered).sort(self.dtm)
        return pl_simplify_dtypes(df)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """Extract one legacy or modern Thermo source file.

        Args:
            path: Plain source file or ZIP archive.

        Returns:
            ``(dataframe, None)`` on success, otherwise an empty dataframe and
            an explanatory error string.
        """
        path = Path(path)
        try:
            model = self._detect_model(path)
            text, member_name = self._read_raw_text(path, model=model)
            lines = self._nonempty_lines(text)
            layout, columns, has_header = self._detect_layout(lines, model=model)

            source_description = path.name
            if member_name:
                source_description += f"::{member_name}"
            self.logger.info(
                "%s: detected model=%s layout=%s header=%s",
                source_description,
                model,
                layout,
                has_header,
            )

            if layout == "modern":
                records = self._extract_modern_records(
                    lines,
                    columns=columns,
                    has_header=has_header,
                    path=path,
                )
            else:
                records = self._extract_legacy_records(
                    lines,
                    columns=columns,
                    has_header=has_header,
                    path=path,
                )

            if not records:
                raise ValueError(f"No valid {layout} Thermo data records found.")

            df = self._records_to_dataframe(
                records,
                model=model,
                layout=layout,
                path=path,
            )
            self.logger.info(
                "%s: extracted %d row(s), %d column(s)",
                source_description,
                df.height,
                df.width,
            )
            return df, None

        except Exception as err:
            self.logger.error("Failed to extract %s: %s", path.name, err)
            return pl.DataFrame(), str(err)

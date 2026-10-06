from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import polars as pl
import yaml

from processing.instrument import Instrument
from toolbox.utils import pl_simplify_dtypes


DEFAULT_AE33_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "instruments" / "ae33.yml"
)


def load_ae33_config(path: Path | None = None) -> dict[str, Any]:
    """Load the standard AE33 scientific-processing configuration.

    Args:
        path: Optional alternative YAML path. If omitted, load
            ``config/instruments/ae33.yml`` from the repository.

    Returns:
        Parsed AE33 configuration mapping.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        ValueError: If the YAML root is not a mapping.
    """
    config_path = path or DEFAULT_AE33_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"AE33 configuration not found: {config_path}")

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"AE33 configuration must be a mapping: {config_path}")

    return dict(loaded)


def add_absorption_coefficients(
    df: pl.DataFrame,
    config: Mapping[str, Any] | None = None,
) -> pl.DataFrame:
    """Add AE33 absorption coefficients and propagate existing BC flags.

    The calculation is mandatory for AE33 Level-1 processing, while the
    scientific coefficients remain configurable in
    ``config/instruments/ae33.yml``.

    The stored BC channels are in ng/m3. With SG in m2/g, division by 1000
    converts the result to Mm-1:

        b_abs [Mm-1] = BC [ng/m3] * SG [m2/g] / H* / 1000

    If ``f_BCn`` exists, ``f_bn_abs`` is created or replaced as an exact copy.
    If ``f_BCn`` does not exist, no absorption flag column is created.

    Args:
        df: AE33 dataframe containing any subset of BC1 ... BC7.
        config: AE33 processing configuration. If omitted, the standard
            repository configuration is loaded automatically.

    Returns:
        Dataframe with the available b1_abs ... b7_abs columns and coupled
        flag columns added or replaced.

    Raises:
        ValueError: If the absorption-correction configuration is missing or
            invalid.
    """
    active_config = load_ae33_config() if config is None else config

    correction = active_config.get("absorption_correction")
    if not isinstance(correction, Mapping):
        raise ValueError("AE33 config requires an absorption_correction mapping.")

    filter_type = correction.get("filter_type")
    if not isinstance(filter_type, str) or not filter_type.strip():
        raise ValueError("AE33 absorption_correction.filter_type must be defined.")

    if correction.get("bc_unit") != "ng/m3":
        raise ValueError("AE33 absorption_correction.bc_unit must be 'ng/m3'.")
    if correction.get("output_unit") != "Mm-1":
        raise ValueError("AE33 absorption_correction.output_unit must be 'Mm-1'.")

    try:
        h_star = float(correction["h_star"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "AE33 absorption_correction.h_star must be a positive number."
        ) from exc
    if not math.isfinite(h_star) or h_star <= 0.0:
        raise ValueError(
            "AE33 absorption_correction.h_star must be a positive finite number."
        )

    sg_values = correction.get("sg_m2_g")
    if not isinstance(sg_values, Mapping):
        raise ValueError("AE33 absorption_correction.sg_m2_g must be a mapping.")

    expressions: list[pl.Expr] = []
    for channel in range(1, 8):
        bc = f"BC{channel}"
        absorption = f"b{channel}_abs"
        bc_flag = f"f_{bc}"
        absorption_flag = f"f_{absorption}"

        if bc in df.columns:
            try:
                sg = float(sg_values[bc])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Missing or invalid AE33 SG coefficient for {bc}."
                ) from exc
            if not math.isfinite(sg) or sg <= 0.0:
                raise ValueError(
                    f"AE33 SG coefficient for {bc} must be a positive finite number."
                )

            expressions.append(
                (
                    pl.col(bc).cast(pl.Float64)
                    * pl.lit(sg)
                    / pl.lit(h_star)
                    / pl.lit(1000.0)
                ).alias(absorption)
            )

        if bc_flag in df.columns:
            expressions.append(pl.col(bc_flag).alias(absorption_flag))

    return df.with_columns(expressions) if expressions else df

class AE33(Instrument):
    """Processor for AE33 aethalometer data files.

    Input:
        - ``.zip`` containing a single AE33 measurement ``.csv`` or ``.dat`` file.
        - Raw ``.csv`` or ``.dat`` files.

    Output contract:
        - Returns ``(df, None)`` on successful extraction.
        - Returns ``(empty_df, "error message")`` on extraction failure.

    Notes:
        The ACTRIS exporter writes EBAS NASA-Ames FFI 1001 level-0 files
        following the current EBAS AE33 filter-absorption-photometer template.
    """

    _COLS_TEMPLATE: tuple[str, ...] = (
        "Inst_SN",
        "row_id",
        "DateTime_1",
        "{dtm}",
        "unclear",
        "DateTime_2",
        "RefCh1",
        "Sen1Ch1",
        "Sen2Ch1",
        "RefCh2",
        "Sen1Ch2",
        "Sen2Ch2",
        "RefCh3",
        "Sen1Ch3",
        "Sen2Ch3",
        "RefCh4",
        "Sen1Ch4",
        "Sen2Ch4",
        "RefCh5",
        "Sen1Ch5",
        "Sen2Ch5",
        "RefCh6",
        "Sen1Ch6",
        "Sen2Ch6",
        "RefCh7",
        "Sen1Ch7",
        "Sen2Ch7",
        "BC11",
        "BC12",
        "BC1",
        "BC21",
        "BC22",
        "BC2",
        "BC31",
        "BC32",
        "BC3",
        "BC41",
        "BC42",
        "BC4",
        "BC51",
        "BC52",
        "BC5",
        "BC61",
        "BC62",
        "BC6",
        "BC71",
        "BC72",
        "BC7",
        "K1",
        "K2",
        "K3",
        "K4",
        "K5",
        "K6",
        "K7",
        "BB",
        "Pressure",
        "Temperature",
        "Flow1",
        "Flow2",
        "FlowC",
        "ContTemp",
        "SupplyTemp",
        "LedTemp",
        "ContStatus",
        "LedStatus",
        "DetectStatus",
        "ValveStatus",
        "Status",
        "TapeAdvCount",
        "TapeAdvLeft",
        "unclear_4",
        "unclear_5",
        "unclear_6",
    )
    _LEGACY_COLUMN_ALIASES: dict[str, str] = {
        "unclear_2": "BB",
        "Pres": "Pressure",
        "Temp": "Temperature",
        "Temp_1": "ContTemp",
        "Temp_2": "SupplyTemp",
        "Temp_3": "LedTemp",
        "Stat_1": "ContStatus",
        "Stat_2": "LedStatus",
        "Stat_3": "DetectStatus",
        "Stat_4": "ValveStatus",
        "Stat_5": "Status",
        "unclear_3": "TapeAdvLeft",
    }
    _DTYPES: list[pl.DataType] = (
        [pl.Utf8, pl.Int64, pl.Utf8, pl.Utf8, pl.Int32, pl.Utf8]
        + [pl.Int64] * 42
        + [pl.Float64] * 10
        + [pl.Int64] * 3
        + [pl.Float64] * 3
        + [pl.Int64] * 10
    )
    _DTM_FORMATS: tuple[str, ...] = (
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
    )
    _DATA_SUFFIXES: frozenset[str] = frozenset({".csv", ".dat", ".zip"})

    _WAVELENGTHS_NM: tuple[float, ...] = (
        370.0,
        470.0,
        525.0,
        590.0,
        660.0,
        880.0,
        950.0,
    )
    _DEFAULT_MAC_M2_G: tuple[float, ...] = (
        18.47,
        14.54,
        13.14,
        11.58,
        10.35,
        7.77,
        7.19,
    )

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        log_file: Optional[str] = None,
    ) -> None:
        super().__init__(name="ae33", log_file=log_file)
        self.config = (
            dict(config)
            if config is not None
            else load_ae33_config()
        )

    def should_process_file(self, path: Path) -> bool:
        """Return whether ``path`` is an AE33 measurement file."""
        name = path.name.casefold()
        return (
            name.startswith("ae33-")
            and not name.startswith("ae33-log-")
            and path.suffix.casefold() in self._DATA_SUFFIXES
        )

    @staticmethod
    def _read_bytes_zip_or_file(path: Path) -> tuple[bytes, Optional[str]]:
        """Read bytes from ``path``, supporting AE33 zip archives."""
        if path.suffix.lower() != ".zip":
            return path.read_bytes(), None

        with zipfile.ZipFile(path) as zf:
            members = [
                name
                for name in zf.namelist()
                if not name.endswith("/") and "__MACOSX" not in name
            ]
            if not members:
                raise ValueError(f"No files found inside zip: {path}")

            data_members = [
                name
                for name in members
                if Path(name).suffix.casefold() in {".csv", ".dat"}
            ]
            if len(data_members) == 1:
                member = data_members[0]
            elif len(data_members) > 1:
                stem = path.stem.casefold()
                matches = [
                    name
                    for name in data_members
                    if Path(name).stem.casefold() == stem
                ]
                member = matches[0] if matches else data_members[0]
            else:
                member = members[0]

            return zf.read(member), member

    @staticmethod
    def _first_data_line(raw: bytes) -> str:
        """Return the first non-empty, non-comment data line."""
        text = raw.decode("utf-8-sig", errors="replace")
        for line in text.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                return line
        return ""

    @classmethod
    def _detect_separator(cls, raw: bytes) -> str:
        """Detect the AE33 field separator used by legacy and current files."""
        line = cls._first_data_line(raw)
        if not line:
            return ","
        return "|" if line.count("|") > line.count(",") else ","

    @classmethod
    def _first_csv_record(cls, raw: bytes, separator: str = ",") -> list[str]:
        """Return the first non-empty, non-comment delimited record."""
        line = cls._first_data_line(raw)
        if not line:
            return []
        return [
            value.strip()
            for value in next(csv.reader([line], delimiter=separator))
        ]

    def _canonical_columns(self) -> list[str]:
        return [column.format(dtm=self.dtm) for column in self._COLS_TEMPLATE]

    def _canonicalize_header(self, header: list[str]) -> list[str]:
        """Map a legacy or current pydaq header to the canonical AE33 schema."""
        canonical = []
        for name in header:
            clean = name.strip().lstrip("\ufeff")
            if clean == "dtm":
                clean = self.dtm
            canonical.append(self._LEGACY_COLUMN_ALIASES.get(clean, clean))
        return canonical

    def _parse_dtm(self, df: pl.DataFrame) -> pl.DataFrame:
        """Normalize the processor timestamp to UTC microsecond datetimes."""
        dtm = self.dtm
        if dtm not in df.columns:
            raise ValueError(f"AE33 dataframe is missing datetime column {dtm!r}.")

        dtype = df.schema[dtm]
        if isinstance(dtype, pl.Datetime):
            expr = pl.col(dtm).dt.cast_time_unit("us")
            if dtype.time_zone is None:
                expr = expr.dt.replace_time_zone("UTC")
            else:
                expr = expr.dt.convert_time_zone("UTC")
        else:
            text = pl.col(dtm).cast(pl.Utf8)
            parsed = pl.coalesce(
                [
                    text.str.strptime(pl.Datetime, fmt, strict=False)
                    for fmt in self._DTM_FORMATS
                ]
            )
            expr = (
                parsed.dt.cast_time_unit("us")
                .dt.replace_time_zone("UTC")
            )

        normalized = df.with_columns(expr.alias(dtm))
        null_count = normalized.get_column(dtm).null_count()
        if null_count:
            raise ValueError(
                f"AE33 datetime parsing failed for {null_count}/{normalized.height} rows "
                f"in column {dtm!r}."
            )
        return normalized

    def canonicalize_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """Normalize legacy AE33 column names and timestamps.

        This method is intentionally public so existing ``ae33.parquet`` files
        can be migrated with the same mapping used for newly ingested raw data.
        Unrelated columns (for example source or flag columns) are preserved.
        """
        normalized = df
        for legacy, canonical in self._LEGACY_COLUMN_ALIASES.items():
            if legacy not in normalized.columns:
                continue
            if canonical in normalized.columns:
                conflicts = normalized.filter(
                    pl.col(legacy).is_not_null()
                    & pl.col(canonical).is_not_null()
                    & (pl.col(legacy) != pl.col(canonical))
                ).height
                if conflicts:
                    raise ValueError(
                        f"AE33 columns {legacy!r} and {canonical!r} contain "
                        f"{conflicts} conflicting rows."
                    )
                normalized = normalized.with_columns(
                    pl.coalesce([pl.col(canonical), pl.col(legacy)]).alias(canonical)
                ).drop(legacy)
            else:
                normalized = normalized.rename({legacy: canonical})

        normalized = self._parse_dtm(normalized)
        normalized = add_absorption_coefficients(normalized, self.config)
        return pl_simplify_dtypes(normalized)

    def extract_to_dataframe(self, path: Path) -> tuple[pl.DataFrame, str | None]:
        """Extract a legacy or current pydaq AE33 file to canonical Level-1 data."""
        df = pl.DataFrame()
        member: str | None = None

        try:
            cols = self._canonical_columns()
            if len(cols) != len(self._DTYPES):
                raise ValueError(
                    f"AE33 schema mismatch: cols={len(cols)} "
                    f"dtypes={len(self._DTYPES)}"
                )

            raw, member = self._read_bytes_zip_or_file(path)
            separator = self._detect_separator(raw)
            first_record = self._first_csv_record(raw, separator)
            has_header = bool(first_record and first_record[0] == "Inst_SN")

            if has_header:
                incoming_columns = self._canonicalize_header(first_record)
                if incoming_columns != cols:
                    if len(incoming_columns) != len(cols):
                        raise ValueError(
                            "AE33 header width mismatch: "
                            f"expected {len(cols)} columns, got {len(incoming_columns)}."
                        )
                    differences = [
                        f"{index + 1}:{actual!r}!={expected!r}"
                        for index, (actual, expected) in enumerate(
                            zip(incoming_columns, cols, strict=True)
                        )
                        if actual != expected
                    ]
                    raise ValueError(
                        "Unexpected AE33 header after alias normalization: "
                        + ", ".join(differences[:10])
                    )
                new_columns = incoming_columns
            else:
                new_columns = cols

            schema_overrides = dict(zip(new_columns, self._DTYPES, strict=True))
            df = pl.read_csv(
                source=io.BytesIO(raw),
                has_header=has_header,
                separator=separator,
                comment_prefix="#",
                new_columns=new_columns,
                schema_overrides=schema_overrides,
                ignore_errors=True,
            )
            if df.is_empty():
                raise ValueError("AE33 input contained no data rows.")

            df = self.canonicalize_dataframe(df)
            return df, None

        except Exception as err:
            src = f"{path}{'::' + member if member else ''}"
            msg = f"{type(err).__name__}: {err}"
            self.logger.error(f"Failed to extract {src}: {msg}")
            return pl.DataFrame(), msg

    def export_actris_level0(
        self,
        df: pl.DataFrame,
        output: Path,
        metadata: Path | Mapping[str, Any],
        *,
        attenuation_state_path: Path | None = None,
        bootstrap_attenuation: bool | None = None,
        revision_datetime: datetime | None = None,
    ) -> Path:
        """Export AE33 data as an ACTRIS/EBAS NASA-Ames level-0 file.

        The output follows the EBAS filter-absorption-photometer AE33 level-0
        template. The exporter performs the unit conversions needed by that
        template:

        - ``Pressure``: Pa -> hPa
        - ``Temperature``, ``ContTemp``, ``SupplyTemp`` and ``LedTemp``: degC -> K
        - ``Flow1`` ... ``FlowC``: mL/min -> L/min
        - ``BC*``: ng/m3 -> ug/m3

        ``BB`` is the AE33 biomass-burning fraction (%). ``TapeAdvLeft`` is the
        instrument estimate of remaining tape advances. External-device fields
        ``unclear_4`` ... ``unclear_6`` are intentionally not guessed. To include relative humidity, first map
        it to a named dataframe column and set ``columns.relative_humidity`` in
        the YAML template.

        AE33 attenuation coefficients require subtraction of the unloaded-filter
        baseline, ATN0. For operational hourly exports, pass a persistent
        ``attenuation_state_path`` (or configure one in the YAML). The state is
        carried across files and reset when ``TapeAdvCount`` changes.

        Args:
            df: AE33 dataframe from this processor.
            output: Output ``.nas`` path, or a directory in which the canonical
                EBAS filename will be generated.
            metadata: Path to the user-editable YAML metadata file, or an
                equivalent mapping.
            attenuation_state_path: Optional state JSON path overriding the YAML
                setting.
            bootstrap_attenuation: If true and no prior attenuation state exists,
                use the first row as ATN0. Only use this when the first row is at
                the beginning of a fresh tape spot.
            revision_datetime: UTC revision timestamp. Defaults to current UTC;
                injectable for deterministic tests.

        Returns:
            Path to the written NASA-Ames file.

        Raises:
            ValueError: If required metadata or dataframe columns are missing.
        """
        if df.is_empty():
            raise ValueError("Cannot export an empty AE33 dataframe.")

        config = self._load_actris_metadata(metadata)
        self._validate_actris_metadata(config)

        required_columns = {
            self.dtm,
            "DateTime_1",
            "Pressure",
            "Temperature",
            "Flow1",
            "Flow2",
            "FlowC",
            "ContTemp",
            "SupplyTemp",
            "LedTemp",
            "ContStatus",
            "LedStatus",
            "DetectStatus",
            "ValveStatus",
            "Status",
            "TapeAdvCount",
            "BB",
        }
        for channel in range(1, 8):
            required_columns.update(
                {
                    f"RefCh{channel}",
                    f"Sen1Ch{channel}",
                    f"Sen2Ch{channel}",
                    f"BC{channel}1",
                    f"BC{channel}2",
                    f"BC{channel}",
                    f"K{channel}",
                }
            )

        columns_config = self._mapping(config.get("columns", {}), "columns")
        rh_column = self._optional_str(columns_config.get("relative_humidity"))
        flag_column = self._optional_str(columns_config.get("ebas_flag"))
        if rh_column is not None:
            required_columns.add(rh_column)
        if flag_column is not None:
            required_columns.add(flag_column)

        missing_columns = sorted(required_columns.difference(df.columns))
        if missing_columns:
            raise ValueError(
                "AE33 dataframe is missing required ACTRIS columns: "
                + ", ".join(missing_columns)
            )

        sample_seconds = self._sample_duration_seconds(config)
        ordered = df.sort(self.dtm)
        first_row = ordered.row(0, named=True)
        first_end = self._as_utc_datetime(first_row[self.dtm], self.dtm)
        first_start = self._measurement_start(
            first_row.get("DateTime_1"), first_end, sample_seconds
        )

        revision = revision_datetime or datetime.now(UTC)
        if revision.tzinfo is None:
            revision = revision.replace(tzinfo=UTC)
        else:
            revision = revision.astimezone(UTC)

        output_path = self._resolve_actris_output_path(
            output=output,
            config=config,
            start=first_start,
            revision=revision,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if attenuation_state_path is None:
            state_value = self._optional_str(
                self._mapping(config.get("export", {}), "export").get(
                    "attenuation_state_file"
                )
            )
            if state_value:
                candidate = Path(state_value)
                attenuation_state_path = (
                    candidate
                    if candidate.is_absolute()
                    else output_path.parent / candidate
                )

        if bootstrap_attenuation is None:
            bootstrap_attenuation = bool(
                self._mapping(config.get("export", {}), "export").get(
                    "bootstrap_attenuation", False
                )
            )

        variable_specs = self._actris_variable_specs(config, rh_column is not None)
        short_names = ["starttime"] + [spec["short_name"] for spec in variable_specs]
        special_lines = self._actris_special_metadata_lines(
            config=config,
            output_name=output_path.name,
            start=first_start,
            revision=revision,
            short_names=short_names,
        )
        header_lines = self._actris_header_lines(
            config=config,
            start=first_start,
            revision=revision,
            variable_specs=variable_specs,
            special_lines=special_lines,
        )

        state = self._load_attenuation_state(attenuation_state_path)
        ref_date = datetime(first_start.year, 1, 1, tzinfo=UTC)

        with output_path.open("w", encoding="ascii", newline="\n") as stream:
            stream.write("\n".join(header_lines))
            stream.write("\n")

            for row in ordered.iter_rows(named=True):
                end = self._as_utc_datetime(row[self.dtm], self.dtm)
                start = self._measurement_start(
                    row.get("DateTime_1"), end, sample_seconds
                )
                start_days = (start - ref_date).total_seconds() / 86400.0
                end_days = (end - ref_date).total_seconds() / 86400.0

                attenuation, state = self._attenuation_for_row(
                    row=row,
                    state=state,
                    bootstrap=bootstrap_attenuation,
                )
                values = self._actris_row_values(
                    row=row,
                    end_days=end_days,
                    attenuation=attenuation,
                    rh_column=rh_column,
                    flag_column=flag_column,
                )

                fields = [f"{start_days:.6f}"]
                for value, spec in zip(values, variable_specs, strict=True):
                    fields.append(self._format_actris_value(value, spec))
                stream.write(" ".join(fields))
                stream.write("\n")

        self._write_attenuation_state(attenuation_state_path, state)
        return output_path

    @staticmethod
    def _load_actris_metadata(
        metadata: Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Load ACTRIS exporter metadata from YAML or a mapping."""
        if isinstance(metadata, Mapping):
            return dict(metadata)

        loaded = yaml.safe_load(metadata.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("ACTRIS metadata YAML must contain a mapping.")
        return loaded

    @classmethod
    def _validate_actris_metadata(cls, config: Mapping[str, Any]) -> None:
        """Validate the metadata required to construct an EBAS level-0 file."""
        required_paths = (
            "general.principal_investigators",
            "general.organization",
            "general.framework",
            "file.period_code",
            "file.resolution_code",
            "file.sample_duration",
            "file.orig_time_res",
            "station.code",
            "station.platform_code",
            "station.name",
            "station.latitude",
            "station.longitude",
            "station.altitude_m",
            "station.wmo_region",
            "laboratory.code",
            "instrument.name",
            "instrument.manufacturer",
            "instrument.model",
            "instrument.serial_number",
            "instrument.method_ref",
            "instrument.standard_method",
            "instrument.inlet_type",
            "instrument.inlet_description",
            "instrument.nominal_flow_l_min",
            "instrument.filter_type",
            "ae33.leakage_factor_zeta",
            "submission.originators",
            "submission.submitters",
        )
        for path in required_paths:
            value = cls._nested(config, path)
            if value is None or value == "" or value == []:
                raise ValueError(f"Missing required ACTRIS metadata: {path}")
            if isinstance(value, str) and (
                "REPLACE_ME" in value or value.strip().upper().startswith("TODO")
            ):
                raise ValueError(f"ACTRIS metadata still contains placeholder: {path}")

        for path in (
            "general.principal_investigators",
            "submission.originators",
            "submission.submitters",
        ):
            values = cls._nested(config, path)
            if not isinstance(values, list):
                raise ValueError(f"{path} must be a list.")
            for value in values:
                text = str(value)
                if "REPLACE_ME" in text or text.strip().upper().startswith("TODO"):
                    raise ValueError(
                        f"ACTRIS metadata still contains placeholder: {path}"
                    )

        model = str(cls._nested(config, "instrument.model"))
        if model.casefold() != "ae33":
            raise ValueError(
                f"ACTRIS AE33 exporter requires instrument.model=AE33, got {model!r}"
            )

    @staticmethod
    def _nested(mapping: Mapping[str, Any], dotted_path: str) -> Any:
        """Return a nested value addressed by ``a.b.c``."""
        value: Any = mapping
        for key in dotted_path.split("."):
            if not isinstance(value, Mapping) or key not in value:
                return None
            value = value[key]
        return value

    @staticmethod
    def _mapping(value: Any, name: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a mapping.")
        return value

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _sample_duration_seconds(cls, config: Mapping[str, Any]) -> int:
        """Convert EBAS duration codes such as 1mn or 1h to seconds."""
        file_config = cls._mapping(config.get("file", {}), "file")
        explicit = file_config.get("sample_duration_seconds")
        if explicit is not None:
            seconds = int(explicit)
            if seconds <= 0:
                raise ValueError("file.sample_duration_seconds must be > 0.")
            return seconds

        code = str(file_config["sample_duration"]).strip().lower()
        units = (
            ("mn", 60),
            ("s", 1),
            ("h", 3600),
            ("d", 86400),
        )
        for suffix, multiplier in units:
            if code.endswith(suffix):
                amount = int(code[: -len(suffix)])
                if amount <= 0:
                    break
                return amount * multiplier
        raise ValueError(
            "Unsupported file.sample_duration code. "
            "Use e.g. 1mn, 60s, 1h, or set sample_duration_seconds."
        )

    def _resolve_actris_output_path(
        self,
        *,
        output: Path,
        config: Mapping[str, Any],
        start: datetime,
        revision: datetime,
    ) -> Path:
        """Resolve a directory to the canonical EBAS file name."""
        if output.suffix.casefold() == ".nas":
            return output

        station = self._mapping(config["station"], "station")
        laboratory = self._mapping(config["laboratory"], "laboratory")
        instrument = self._mapping(config["instrument"], "instrument")
        file_config = self._mapping(config["file"], "file")

        station_code = str(station["code"])
        lab_code = str(laboratory["code"])
        instrument_name = f"{lab_code}_{instrument['name']}"
        method_ref = str(instrument["method_ref"])
        if not method_ref.startswith(f"{lab_code}_"):
            method_ref = f"{lab_code}_{method_ref}"

        filename = (
            f"{station_code}.{start:%Y%m%d%H%M%S}."
            f"{revision:%Y%m%d%H%M%S}."
            "filter_absorption_photometer..aerosol."
            f"{file_config['period_code']}.{file_config['resolution_code']}."
            f"{instrument_name}.{method_ref}.lev0.nas"
        )
        return output / filename

    @classmethod
    def _actris_variable_specs(
        cls,
        config: Mapping[str, Any],
        include_rh: bool,
    ) -> list[dict[str, Any]]:
        """Build dependent-variable specifications in EBAS template order."""
        ae33 = cls._mapping(config.get("ae33", {}), "ae33")

        exposed_area = float(ae33.get("exposed_filter_area_cm2", 0.785))
        detection_limit = float(ae33.get("detection_limit_ug_m3", 0.03))
        detection_limit_expl = str(
            ae33.get(
                "detection_limit_explanation",
                "Adapted from manufacturer specification",
            )
        )
        spot_uncertainty = float(ae33.get("spot_uncertainty_percent", 100.0))
        final_uncertainty = float(ae33.get("final_uncertainty_percent", 20.0))
        correction_factor = float(ae33.get("multi_scattering_correction_factor", 1.57))

        mac_value = ae33.get("mass_absorption_cross_section_m2_g")
        if mac_value is None:
            macs = cls._DEFAULT_MAC_M2_G
        else:
            if not isinstance(mac_value, list) or len(mac_value) != 7:
                raise ValueError(
                    "ae33.mass_absorption_cross_section_m2_g must have 7 values."
                )
            macs = tuple(float(value) for value in mac_value)

        specs: list[dict[str, Any]] = [
            {
                "short_name": "endtime",
                "description": "end_time of measurement, days from the file reference point",
                "missing": "999.999999",
                "format": ".6f",
            }
        ]
        if include_rh:
            specs.append(
                {
                    "short_name": "rh_inlet",
                    "description": (
                        "relative_humidity, %, Location=instrument external, "
                        "Matrix=instrument"
                    ),
                    "missing": "999.9999",
                    "format": ".4f",
                }
            )

        specs.extend(
            [
                {
                    "short_name": "ref_pres",
                    "description": (
                        "pressure, hPa, Location=instrument internal, Matrix=instrument"
                    ),
                    "missing": "9999",
                    "format": ".2f",
                },
                {
                    "short_name": "ref_temp",
                    "description": (
                        "temperature, K, Location=instrument internal, Matrix=instrument"
                    ),
                    "missing": "9999.99",
                    "format": ".2f",
                },
                {
                    "short_name": "flow_1",
                    "description": (
                        "flow_rate, l/min, Location=filter spot 1, Matrix=instrument"
                    ),
                    "missing": "99.999",
                    "format": ".3f",
                },
                {
                    "short_name": "flow_2",
                    "description": (
                        "flow_rate, l/min, Location=filter spot 2, Matrix=instrument"
                    ),
                    "missing": "99.999",
                    "format": ".3f",
                },
                {
                    "short_name": "flow_c",
                    "description": (
                        "flow_rate, l/min, Location=total sample flow, Matrix=instrument"
                    ),
                    "missing": "99.999",
                    "format": ".3f",
                },
                {
                    "short_name": "temp_ctrl",
                    "description": (
                        "temperature, K, Location=control board, Matrix=instrument"
                    ),
                    "missing": "9999.99",
                    "format": ".2f",
                },
                {
                    "short_name": "temp_supply",
                    "description": (
                        "temperature, K, Location=power supply board, Matrix=instrument"
                    ),
                    "missing": "9999.99",
                    "format": ".2f",
                },
                {
                    "short_name": "temp_led",
                    "description": (
                        "temperature, K, Location=LED board, Matrix=instrument"
                    ),
                    "missing": "9999.99",
                    "format": ".2f",
                },
                {
                    "short_name": "status_inst",
                    "description": (
                        "status, no unit, Status type=overall instrument status, "
                        "Matrix=instrument"
                    ),
                    "missing": "999",
                    "format": "d",
                },
                {
                    "short_name": "status_ctrl",
                    "description": (
                        "status, no unit, Status type=controller, Matrix=instrument"
                    ),
                    "missing": "9",
                    "format": "d",
                },
                {
                    "short_name": "status_det",
                    "description": (
                        "status, no unit, Status type=detector, Matrix=instrument"
                    ),
                    "missing": "999",
                    "format": "d",
                },
                {
                    "short_name": "status_led",
                    "description": (
                        "status, no unit, Status type=light source, Matrix=instrument"
                    ),
                    "missing": "999",
                    "format": "d",
                },
                {
                    "short_name": "status_valve",
                    "description": (
                        "status, no unit, Status type=valves, Matrix=instrument"
                    ),
                    "missing": "9",
                    "format": "d",
                },
                {
                    "short_name": "tape_cnt",
                    "description": "filter_number, no unit, Matrix=instrument",
                    "missing": "9999",
                    "format": "d",
                },
                {
                    "short_name": "frac_bb",
                    "description": "biomass_burning_aerosol_fraction, %",
                    "missing": "9999.9",
                    "format": ".1f",
                },
            ]
        )

        for channel, (wavelength, mac) in enumerate(
            zip(cls._WAVELENGTHS_NM, macs, strict=True),
            start=1,
        ):
            ebc_common = (
                f"Exposed filter area={exposed_area:g} cm2, "
                f"Detection limit={detection_limit:g} ug/m3, "
                f"Detection limit expl.={detection_limit_expl}, "
            )
            ebc_tail = (
                f"Mass absorption cross section={mac:g} m2/g, "
                f"Multi-scattering correction factor={correction_factor:g}"
            )
            specs.extend(
                [
                    {
                        "short_name": f"sens_w{channel}_ref",
                        "description": (
                            f"reference_beam_signal, no unit, "
                            f"Wavelength={wavelength:.1f} nm"
                        ),
                        "missing": "9999999",
                        "format": "d",
                    },
                    {
                        "short_name": f"sens_w{channel}_sp1",
                        "description": (
                            f"sensing_beam_signal, no unit, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 1"
                        ),
                        "missing": "9999999",
                        "format": "d",
                    },
                    {
                        "short_name": f"sens_w{channel}_sp2",
                        "description": (
                            f"sensing_beam_signal, no unit, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 2"
                        ),
                        "missing": "9999999",
                        "format": "d",
                    },
                    {
                        "short_name": f"ebc_w{channel}_sp1",
                        "description": (
                            "equivalent_black_carbon, ug/m3, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 1, "
                            f"{ebc_common}"
                            f"Measurement uncertainty={spot_uncertainty:.1f} %, "
                            f"{ebc_tail}"
                        ),
                        "missing": "9.999",
                        "format": ".3f",
                    },
                    {
                        "short_name": f"ebc_w{channel}_sp2",
                        "description": (
                            "equivalent_black_carbon, ug/m3, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 2, "
                            f"{ebc_common}"
                            f"Measurement uncertainty={spot_uncertainty:.1f} %, "
                            f"{ebc_tail}"
                        ),
                        "missing": "9.999",
                        "format": ".3f",
                    },
                    {
                        "short_name": f"ebc_w{channel}",
                        "description": (
                            "equivalent_black_carbon, ug/m3, "
                            f"Wavelength={wavelength:.1f} nm, "
                            f"Detection limit={detection_limit:g} ug/m3, "
                            f"Detection limit expl.={detection_limit_expl}, "
                            f"Measurement uncertainty={final_uncertainty:.1f} %, "
                            f"{ebc_tail}"
                        ),
                        "missing": "9.999",
                        "format": ".3f",
                    },
                    {
                        "short_name": f"comp_w{channel}",
                        "description": (
                            "filter_loading_compensation_parameter, no unit, "
                            f"Wavelength={wavelength:.1f} nm"
                        ),
                        "missing": "9.999999999",
                        "format": ".9f",
                    },
                    {
                        "short_name": f"attn_w{channel}_sp1",
                        "description": (
                            "attenuation_coefficient, no unit, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 1"
                        ),
                        "missing": "999.999999999999999",
                        "format": ".15f",
                    },
                    {
                        "short_name": f"attn_w{channel}_sp2",
                        "description": (
                            "attenuation_coefficient, no unit, "
                            f"Wavelength={wavelength:.1f} nm, "
                            "Location=filter spot 2"
                        ),
                        "missing": "999.999999999999999",
                        "format": ".15f",
                    },
                ]
            )

        specs.append(
            {
                "short_name": "flag",
                "description": "numflag, no unit",
                "missing": "9.999",
                "format": ".3f",
            }
        )
        return specs

    @classmethod
    def _actris_header_lines(
        cls,
        *,
        config: Mapping[str, Any],
        start: datetime,
        revision: datetime,
        variable_specs: list[dict[str, Any]],
        special_lines: list[str],
    ) -> list[str]:
        """Construct NASA-Ames FFI 1001 header lines."""
        general = cls._mapping(config["general"], "general")
        investigators_value = general["principal_investigators"]
        if not isinstance(investigators_value, list):
            raise ValueError("general.principal_investigators must be a list.")
        investigators = "; ".join(str(value) for value in investigators_value)

        source_name = str(general.get("source_name") or investigators)
        organization = str(general["organization"])
        framework = str(general["framework"])
        nv = len(variable_specs)
        nscoml = 0
        nncoml = len(special_lines)
        nlhead = 14 + nv + nscoml + nncoml
        ref_date = datetime(start.year, 1, 1, tzinfo=UTC)

        header = [
            f"{nlhead} 1001",
            investigators,
            organization,
            source_name,
            framework,
            "1 1",
            (
                f"{ref_date:%Y %m %d} "
                f"{revision:%Y %m %d}"
            ),
            "0",
            "days from file reference point",
            str(nv),
            " ".join("1" for _ in variable_specs),
            " ".join(str(spec["missing"]) for spec in variable_specs),
        ]
        header.extend(str(spec["description"]) for spec in variable_specs)
        header.append(str(nscoml))
        header.append(str(nncoml))
        header.extend(special_lines)
        return header

    @classmethod
    def _actris_special_metadata_lines(
        cls,
        *,
        config: Mapping[str, Any],
        output_name: str,
        start: datetime,
        revision: datetime,
        short_names: list[str],
    ) -> list[str]:
        """Construct EBAS-specific normal-comment metadata lines."""
        file_config = cls._mapping(config["file"], "file")
        station = cls._mapping(config["station"], "station")
        laboratory = cls._mapping(config["laboratory"], "laboratory")
        instrument = cls._mapping(config["instrument"], "instrument")
        submission = cls._mapping(config["submission"], "submission")
        ae33 = cls._mapping(config.get("ae33", {}), "ae33")

        method_ref = str(instrument["method_ref"])
        lab_code = str(laboratory["code"])
        if not method_ref.startswith(f"{lab_code}_"):
            method_ref = f"{lab_code}_{method_ref}"

        creation = revision.strftime("%Y%m%d%H%M%S%f")
        revision_string = revision.strftime("%Y%m%d%H%M%S")
        start_string = start.strftime("%Y%m%d%H%M%S")

        pairs: list[tuple[str, Any]] = [
            ("Data definition", "EBAS_1.1"),
            ("Set type code", file_config.get("set_type_code", "TI")),
            ("Timezone", "UTC"),
            ("File name", output_name),
            ("File creation", creation),
            ("Startdate", start_string),
            ("Revision date", revision_string),
            ("Version", file_config.get("version", 1)),
            (
                "Version description",
                file_config.get("version_description", "initial revision"),
            ),
            ("Statistics", file_config.get("statistics", "arithmetic mean")),
            ("Data level", 0),
            ("Period code", file_config["period_code"]),
            ("Resolution code", file_config["resolution_code"]),
            ("Sample duration", file_config["sample_duration"]),
            ("Orig. time res.", file_config["orig_time_res"]),
            ("Station code", station["code"]),
            ("Platform code", station["platform_code"]),
            ("Station name", station["name"]),
            ("Station WDCA-ID", station.get("wdca_id")),
            ("Station GAW-ID", station.get("gaw_id")),
            ("Station GAW-Name", station.get("gaw_name")),
            ("Station other IDs", station.get("other_ids")),
            ("Station land use", station.get("land_use")),
            ("Station setting", station.get("setting")),
            ("Station GAW type", station.get("gaw_type")),
            ("Station WMO region", station["wmo_region"]),
            ("Station latitude", station["latitude"]),
            ("Station longitude", station["longitude"]),
            ("Station altitude", f"{station['altitude_m']} m"),
            ("Regime", station.get("regime")),
            ("Component", ""),
            ("Unit", "no unit"),
            ("Matrix", "aerosol"),
            ("Laboratory code", laboratory["code"]),
            ("Instrument type", "filter_absorption_photometer"),
            ("Instrument name", instrument["name"]),
            ("Instrument manufacturer", instrument["manufacturer"]),
            ("Instrument model", instrument["model"]),
            ("Instrument serial number", instrument["serial_number"]),
            ("Method ref", method_ref),
            ("Standard method", instrument["standard_method"]),
            ("Inlet type", instrument["inlet_type"]),
            ("Inlet description", instrument["inlet_description"]),
            ("Flow rate", f"{instrument['nominal_flow_l_min']} l/min"),
            ("Filter type", instrument["filter_type"]),
            (
                "Humidity/temperature control",
                instrument.get("humidity_temperature_control"),
            ),
            (
                "Humidity/temperature control description",
                instrument.get("humidity_temperature_control_description"),
            ),
            (
                "Volume std. temperature",
                f"{instrument.get('volume_standard_temperature_k', 273.15)} K",
            ),
            (
                "Volume std. pressure",
                f"{instrument.get('volume_standard_pressure_hpa', 1013.25)} hPa",
            ),
            (
                "Measurement uncertainty expl.",
                ae33.get(
                    "measurement_uncertainty_explanation",
                    "typical value of unit-to-unit variability",
                ),
            ),
            (
                "Zero/negative values code",
                ae33.get(
                    "zero_negative_values_code",
                    "Zero/negative possible",
                ),
            ),
            (
                "Zero/negative values",
                ae33.get(
                    "zero_negative_values",
                    "Zero and neg. values may appear due to statistical "
                    "variations at very low concentrations",
                ),
            ),
            ("Maximum attenuation", ae33.get("maximum_attenuation", 100.0)),
            ("Leakage factor zeta", ae33.get("leakage_factor_zeta")),
            (
                "Compensation threshold attenuation 1",
                ae33.get("compensation_threshold_attenuation_1", 10.0),
            ),
            (
                "Compensation threshold attenuation 2",
                ae33.get("compensation_threshold_attenuation_2", 30.0),
            ),
            (
                "Compensation parameter k min",
                ae33.get("compensation_parameter_k_min", -0.005),
            ),
            (
                "Compensation parameter k max",
                ae33.get("compensation_parameter_k_max", 0.015),
            ),
        ]

        lines = []
        for key, value in pairs:
            if value is None:
                continue
            if str(value) == "" and key != "Component":
                continue
            lines.append(f"{key + ':':<30}{value}")

        originators = submission["originators"]
        submitters = submission["submitters"]
        if not isinstance(originators, list) or not isinstance(submitters, list):
            raise ValueError(
                "submission.originators and submission.submitters must be lists."
            )
        lines.extend(
            f"{'Originator:':<30}{originator}" for originator in originators
        )
        lines.extend(
            f"{'Submitter:':<30}{submitter}" for submitter in submitters
        )

        acknowledgement = submission.get(
            "acknowledgement",
            "Request acknowledgement details from data originator",
        )
        if acknowledgement:
            lines.append(f"{'Acknowledgement:':<30} {acknowledgement}")

        extra_metadata = submission.get("extra_metadata")
        if extra_metadata is not None:
            if not isinstance(extra_metadata, Mapping):
                raise ValueError("submission.extra_metadata must be a mapping.")
            for key, value in extra_metadata.items():
                if value is not None and str(value) != "":
                    lines.append(f"{str(key) + ':':<30} {value}")

        lines.append(" ".join(short_names))
        return lines

    def _actris_row_values(
        self,
        *,
        row: Mapping[str, Any],
        end_days: float,
        attenuation: Mapping[str, float | None],
        rh_column: str | None,
        flag_column: str | None,
    ) -> list[Any]:
        """Map one processed AE33 row to EBAS variable order."""
        values: list[Any] = [end_days]
        if rh_column is not None:
            values.append(row.get(rh_column))

        values.extend(
            [
                self._divide(row.get("Pressure"), 100.0),
                self._offset(row.get("Temperature"), 273.15),
                self._divide(row.get("Flow1"), 1000.0),
                self._divide(row.get("Flow2"), 1000.0),
                self._divide(row.get("FlowC"), 1000.0),
                self._offset(row.get("ContTemp"), 273.15),
                self._offset(row.get("SupplyTemp"), 273.15),
                self._offset(row.get("LedTemp"), 273.15),
                row.get("Status"),
                row.get("ContStatus"),
                row.get("DetectStatus"),
                row.get("LedStatus"),
                row.get("ValveStatus"),
                row.get("TapeAdvCount"),
                row.get("BB"),
            ]
        )

        for channel in range(1, 8):
            values.extend(
                [
                    row.get(f"RefCh{channel}"),
                    row.get(f"Sen1Ch{channel}"),
                    row.get(f"Sen2Ch{channel}"),
                    self._divide(row.get(f"BC{channel}1"), 1000.0),
                    self._divide(row.get(f"BC{channel}2"), 1000.0),
                    self._divide(row.get(f"BC{channel}"), 1000.0),
                    row.get(f"K{channel}"),
                    attenuation.get(f"w{channel}_sp1"),
                    attenuation.get(f"w{channel}_sp2"),
                ]
            )

        values.append(row.get(flag_column) if flag_column else 0.0)
        return values

    @staticmethod
    def _divide(value: Any, divisor: float) -> float | None:
        number = AE33._finite_float(value)
        return None if number is None else number / divisor

    @staticmethod
    def _offset(value: Any, offset: float) -> float | None:
        number = AE33._finite_float(value)
        return None if number is None else number + offset

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _format_actris_value(
        cls,
        value: Any,
        spec: Mapping[str, Any],
    ) -> str:
        """Format a value or emit the variable-specific NASA-Ames missing code."""
        number = cls._finite_float(value)
        if number is None:
            return str(spec["missing"])

        fmt = str(spec["format"])
        if fmt == "d":
            return str(int(round(number)))
        return format(number, fmt)

    @classmethod
    def _measurement_start(
        cls,
        value: Any,
        end: datetime,
        sample_seconds: int,
    ) -> datetime:
        """Return instrument interval start, falling back to end-duration."""
        if isinstance(value, datetime):
            start = cls._as_utc_datetime(value, "DateTime_1")
        elif value is not None:
            start = None
            for fmt in cls._DTM_FORMATS:
                try:
                    start = datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
            if start is None:
                start = end - timedelta(seconds=sample_seconds)
        else:
            start = end - timedelta(seconds=sample_seconds)

        if start >= end:
            start = end - timedelta(seconds=sample_seconds)
        return start

    @staticmethod
    def _as_utc_datetime(value: Any, column: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{column} must contain datetime values, got {value!r}.")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _attenuation_for_row(
        cls,
        *,
        row: Mapping[str, Any],
        state: dict[str, Any],
        bootstrap: bool,
    ) -> tuple[dict[str, float | None], dict[str, Any]]:
        """Calculate baseline-corrected AE33 attenuation for one row."""
        tape_value = row.get("TapeAdvCount")
        tape_number = cls._finite_float(tape_value)
        tape_count = int(round(tape_number)) if tape_number is not None else None

        raw: dict[str, float | None] = {}
        for channel in range(1, 8):
            ref = cls._finite_float(row.get(f"RefCh{channel}"))
            for spot in (1, 2):
                sensing = cls._finite_float(row.get(f"Sen{spot}Ch{channel}"))
                key = f"w{channel}_sp{spot}"
                if (
                    ref is None
                    or sensing is None
                    or ref <= 0.0
                    or sensing <= 0.0
                ):
                    raw[key] = None
                else:
                    raw[key] = -100.0 * math.log(sensing / ref)

        state_tape = state.get("tape_count")
        atn0_value = state.get("atn0", {})
        atn0 = (
            dict(atn0_value)
            if isinstance(atn0_value, Mapping)
            else {}
        )

        if tape_count is None:
            return {key: None for key in raw}, state

        if state_tape is None:
            state["tape_count"] = tape_count
            if bootstrap:
                atn0 = {
                    key: value for key, value in raw.items() if value is not None
                }
                state["atn0"] = atn0
        elif int(state_tape) != tape_count:
            atn0 = {
                key: value for key, value in raw.items() if value is not None
            }
            state = {"tape_count": tape_count, "atn0": atn0}

        corrected: dict[str, float | None] = {}
        for key, raw_value in raw.items():
            baseline = cls._finite_float(atn0.get(key))
            corrected[key] = (
                None
                if raw_value is None or baseline is None
                else raw_value - baseline
            )
        return corrected, state

    @staticmethod
    def _load_attenuation_state(path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {"tape_count": None, "atn0": {}}

        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Invalid AE33 attenuation state: {path}")
        return loaded

    @staticmethod
    def _write_attenuation_state(
        path: Path | None,
        state: Mapping[str, Any],
    ) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(state), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
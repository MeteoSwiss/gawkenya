import pytest
from processing.instrument import Instrument
from pathlib import Path

TEST_DATA_DIR = Path("tests/data/instrument")  # e.g. include UTF-8 and broken files


class DummyInstrument(Instrument):
    def __init__(self):
        super().__init__(name="dummy")
        self.logger = DummyLogger()

    def extract_to_dataframe(self, file_path: str, dtm: str = "dtm"):
        raise NotImplementedError("DummyInstrument doesn't extract data.")
    

class DummyLogger:
    def error(self, msg): pass
    def warning(self, msg): pass


def test_read_text_lines_utf8():
    instr = DummyInstrument()
    path = TEST_DATA_DIR / "utf8.txt"
    lines = instr.read_text_lines(path)
    assert "Hello" in lines[0]


def test_read_text_lines_fallback():
    instr = DummyInstrument()
    path = TEST_DATA_DIR / "weird_encoding.txt"
    lines = instr.read_text_lines(path)
    assert lines


def test_read_text_lines_empty_file():
    instr = DummyInstrument()
    path = TEST_DATA_DIR / "empty.txt"
    lines = instr.read_text_lines(path)
    assert lines == []

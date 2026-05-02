import pytest
from marimo_mcp.discovery import _extract_port


def test_extract_port_flag_space():
    cmdline = ["python", "-m", "marimo", "edit", "--port", "2718", "nb.py"]
    assert _extract_port(cmdline) == 2718


def test_extract_port_flag_equals():
    cmdline = ["marimo", "edit", "--port=3042", "nb.py"]
    assert _extract_port(cmdline) == 3042


def test_extract_port_short_flag():
    cmdline = ["marimo", "edit", "-p", "9000", "nb.py"]
    assert _extract_port(cmdline) == 9000


def test_extract_port_missing():
    cmdline = ["marimo", "edit", "nb.py"]
    assert _extract_port(cmdline) is None


def test_extract_port_invalid_value():
    cmdline = ["marimo", "--port", "notanumber", "nb.py"]
    assert _extract_port(cmdline) is None

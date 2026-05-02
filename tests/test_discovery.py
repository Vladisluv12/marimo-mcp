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


import asyncio
import time
from unittest.mock import MagicMock, patch

import respx
import httpx

from marimo_mcp.discovery import NotebookInfo, discover_notebooks, resolve_notebook, _clear_cache


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_cache()
    yield
    _clear_cache()


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_returns_running():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={
            "files": [{"name": "nb.py", "path": "/home/user/nb.py", "sessionId": "abc123"}]
        })
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        result = await discover_notebooks()

    assert len(result) == 1
    assert result[0].path == "/home/user/nb.py"
    assert result[0].session_id == "abc123"
    assert result[0].port == 2718


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_skips_unreachable_port():
    respx.post("http://localhost:9999/api/home/running_notebooks").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[9999]):
        result = await discover_notebooks()

    assert result == []


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_skips_missing_session_id():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={
            "files": [{"name": "nb.py", "path": "/home/user/nb.py", "sessionId": None}]
        })
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        result = await discover_notebooks()

    assert result == []


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_uses_cache():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={
            "files": [{"name": "nb.py", "path": "/home/user/nb.py", "sessionId": "abc"}]
        })
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]) as mock_find:
        await discover_notebooks()
        await discover_notebooks()
        assert mock_find.call_count == 1  # second call used cache


@respx.mock
@pytest.mark.asyncio
async def test_resolve_by_path():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={
            "files": [{"name": "nb.py", "path": "/home/user/nb.py", "sessionId": "abc123"}]
        })
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        nb = await resolve_notebook("/home/user/nb.py")

    assert nb.session_id == "abc123"


@respx.mock
@pytest.mark.asyncio
async def test_resolve_by_port():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={
            "files": [{"name": "nb.py", "path": "/home/user/nb.py", "sessionId": "abc123"}]
        })
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        nb = await resolve_notebook("2718")

    assert nb.port == 2718


@respx.mock
@pytest.mark.asyncio
async def test_resolve_not_found_raises():
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        with pytest.raises(ValueError, match="No running notebook"):
            await resolve_notebook("missing.py")

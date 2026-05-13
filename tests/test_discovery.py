import pytest
from unittest.mock import patch
import respx
import httpx

from marimo_mcp.discovery import (
    NotebookInfo,
    _clear_cache,
    _extract_port,
    discover_notebooks,
    resolve_notebook,
)

_SERVER_TOKEN_HTML = '<marimo-server-token data-token="tok-abc" hidden></marimo-server-token>'


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


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_cache()
    yield
    _clear_cache()


@pytest.fixture(autouse=True)
def no_bridge(monkeypatch):
    """Disable LSP bridge in all discovery tests."""
    async def _unavailable():
        return False
    monkeypatch.setattr("marimo_mcp.lsp_client.bridge_available", _unavailable)


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_returns_running():
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
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
    respx.get("http://localhost:9999/").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[9999]):
        result = await discover_notebooks()

    assert result == []


@respx.mock
@pytest.mark.asyncio
async def test_discover_notebooks_skips_missing_session_id():
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
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
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
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
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
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
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
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
    respx.get("http://localhost:2718/").mock(
        return_value=httpx.Response(200, text=_SERVER_TOKEN_HTML)
    )
    respx.post("http://localhost:2718/api/home/running_notebooks").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    with patch("marimo_mcp.discovery._find_marimo_ports", return_value=[2718]):
        with pytest.raises(ValueError, match="No running notebook"):
            await resolve_notebook("missing.py")

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

import httpx
import psutil

from marimo_mcp import lsp_client

CACHE_TTL = 5.0

_cache: list[NotebookInfo] = []
_cache_time: float = 0.0
_failed_ports: set[int] = set()

_SERVER_TOKEN_RE = re.compile(
    r'<marimo-server-token[^>]+data-token="([^"]*)"', re.IGNORECASE
)


@dataclass
class NotebookInfo:
    path: str
    port: int
    session_id: str
    name: str
    server_token: str = field(default="")
    notebook_uri: str = field(default="")
    lsp_cells: list[dict] = field(default_factory=list)

    @property
    def is_lsp(self) -> bool:
        return bool(self.notebook_uri)


def _clear_cache() -> None:
    global _cache, _cache_time, _failed_ports
    _cache.clear()
    _cache_time = 0.0
    _failed_ports.clear()


def _extract_port(cmdline: list[str]) -> int | None:
    for i, arg in enumerate(cmdline):
        if arg in ("--port", "-p") and i + 1 < len(cmdline):
            try:
                return int(cmdline[i + 1])
            except ValueError:
                return None
        if arg.startswith("--port="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _find_marimo_ports() -> list[int]:
    ports: list[int] = []
    seen: set[int] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
            if not any("marimo" in part for part in cmdline):
                continue
            port = _extract_port(cmdline) or 2718
            if port not in seen:
                ports.append(port)
                seen.add(port)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return ports


async def _fetch_server_token(
    client: httpx.AsyncClient, port: int, auth_token: str | None
) -> str:
    """Fetch the skew-protection token embedded in the marimo HTML page."""
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    try:
        resp = await client.get(
            f"http://localhost:{port}/",
            headers=headers,
            timeout=2.0,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        m = _SERVER_TOKEN_RE.search(resp.text)
        return m.group(1) if m else ""
    except (httpx.ConnectError, httpx.TimeoutException):
        return ""


async def _ping_port(
    client: httpx.AsyncClient, port: int, auth_token: str | None
) -> list[NotebookInfo]:
    server_token = await _fetch_server_token(client, port, auth_token)
    if not server_token:
        _failed_ports.add(port)
        return []
    headers: dict[str, str] = {"Marimo-Server-Token": server_token}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    url = f"http://localhost:{port}/api/home/running_notebooks"
    try:
        resp = await client.post(url, headers=headers, timeout=2.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for f in data.get("files", []):
            if f.get("sessionId"):
                results.append(
                    NotebookInfo(
                        path=f["path"],
                        port=port,
                        session_id=f["sessionId"],
                        name=f["name"],
                        server_token=server_token,
                    )
                )
        return results
    except (httpx.ConnectError, httpx.TimeoutException):
        return []


async def _discover_lsp_notebooks() -> list[NotebookInfo]:
    """Return notebooks open in VS Code (via the bridge extension), if available."""
    if not await lsp_client.bridge_available():
        return []
    try:
        raw = await lsp_client.list_lsp_notebooks()
    except Exception:
        return []
    results: list[NotebookInfo] = []
    for nb in raw:
        uri = nb.get("uri", "")
        path = nb.get("path", "")
        name = path.split("/")[-1] if path else uri
        results.append(
            NotebookInfo(
                path=path,
                port=0,
                session_id="",
                name=name,
                notebook_uri=uri,
                lsp_cells=nb.get("cells", []),
            )
        )
    return results


async def discover_notebooks(auth_token: str | None = None) -> list[NotebookInfo]:
    global _cache, _cache_time, _failed_ports
    if time.time() - _cache_time < CACHE_TTL:
        return _cache
    ports = _find_marimo_ports()
    results: list[NotebookInfo] = []
    _failed_ports.clear()
    async with httpx.AsyncClient() as client:
        port_results, lsp_notebooks = await asyncio.gather(
            asyncio.gather(*[_ping_port(client, port, auth_token) for port in ports]),
            _discover_lsp_notebooks(),
        )
    for batch in port_results:
        results.extend(batch)
    http_paths = {nb.path for nb in results}
    for nb in lsp_notebooks:
        if nb.path not in http_paths:
            results.append(nb)
    _cache = results
    _cache_time = time.time()
    return results


async def resolve_notebook(notebook: str, auth_token: str | None = None) -> NotebookInfo:
    notebooks = await discover_notebooks(auth_token)
    try:
        port = int(notebook)
    except ValueError:
        pass
    else:
        for nb in notebooks:
            if nb.port == port:
                return nb
        raise ValueError(f"No running notebook found on port {port}")
    for nb in notebooks:
        if nb.path == notebook or nb.path.endswith("/" + notebook):
            return nb
    running = [nb.path for nb in notebooks]
    hint = ""
    if _failed_ports:
        hint = (
            f" (ports {sorted(_failed_ports)} found but could not authenticate — "
            "start marimo with --no-token or set MARIMO_TOKEN env var)"
        )
    raise ValueError(
        f"No running notebook found for: {notebook!r}. Running: {running}{hint}"
    )

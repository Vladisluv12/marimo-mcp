from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import psutil

CACHE_TTL = 5.0

_cache: list[NotebookInfo] = []
_cache_time: float = 0.0


@dataclass
class NotebookInfo:
    path: str
    port: int
    session_id: str
    name: str


def _clear_cache() -> None:
    global _cache, _cache_time
    _cache = []
    _cache_time = 0.0


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


async def _ping_port(
    client: httpx.AsyncClient, port: int, token: str | None
) -> list[NotebookInfo]:
    url = f"http://localhost:{port}/api/home/running_notebooks"
    params = {"token": token} if token else {}
    try:
        resp = await client.post(url, params=params, timeout=2.0)
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
                    )
                )
        return results
    except (httpx.ConnectError, httpx.TimeoutException):
        return []


async def discover_notebooks(token: str | None = None) -> list[NotebookInfo]:
    global _cache, _cache_time
    if time.time() - _cache_time < CACHE_TTL:
        return _cache
    ports = _find_marimo_ports()
    results: list[NotebookInfo] = []
    async with httpx.AsyncClient() as client:
        for port in ports:
            results.extend(await _ping_port(client, port, token))
    _cache = results
    _cache_time = time.time()
    return results


async def resolve_notebook(notebook: str, token: str | None = None) -> NotebookInfo:
    notebooks = await discover_notebooks(token)
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
    raise ValueError(
        f"No running notebook found for: {notebook!r}. Running: {running}"
    )

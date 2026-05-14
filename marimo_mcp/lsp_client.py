from __future__ import annotations

import asyncio
import json
import os
import tempfile
import textwrap

import httpx

BRIDGE_URL = "http://127.0.0.1:42018"

_http = httpx.AsyncClient()


async def bridge_available() -> bool:
    try:
        resp = await _http.get(f"{BRIDGE_URL}/health", timeout=1.0)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


async def list_lsp_notebooks() -> list[dict]:
    resp = await _http.get(f"{BRIDGE_URL}/notebooks", timeout=5.0)
    resp.raise_for_status()
    return resp.json()


async def call_api(method: str, params: dict) -> object:
    resp = await _http.post(
        f"{BRIDGE_URL}/api",
        json={"method": method, "params": params},
        timeout=30.0,
    )
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise
    if "error" in data:
        raise RuntimeError(data["error"])
    resp.raise_for_status()
    return data.get("result")


async def execute_cells(notebook_uri: str, cell_ids: list[str], codes: list[str]) -> object:
    return await call_api("execute-cells", {
        "notebookUri": notebook_uri,
        "cellIds": cell_ids,
        "codes": codes,
    })


def _wrap_code(code: str, output_path: str) -> str:
    indented = textwrap.indent(code, "    ")
    lines = [
        "import sys as _mcp_sys, io as _mcp_io, json as _mcp_json, traceback as _mcp_tb",
        "_mcp_out, _mcp_err = _mcp_io.StringIO(), _mcp_io.StringIO()",
        "_mcp_sys.stdout, _mcp_sys.stderr = _mcp_out, _mcp_err",
        "try:",
        indented,
        "except Exception:",
        "    _mcp_err.write(_mcp_tb.format_exc())",
        "finally:",
        "    _mcp_sys.stdout, _mcp_sys.stderr = _mcp_sys.__stdout__, _mcp_sys.__stderr__",
        "with open(" + repr(output_path) + ", 'w') as _mcp_f:",
        '    _mcp_json.dump({"stdout": _mcp_out.getvalue(), "stderr": _mcp_err.getvalue()}, _mcp_f)',
    ]
    return "\n".join(lines) + "\n"


async def execute_and_get_output(
    notebook_uri: str,
    cell_id: str,
    code: str,
    poll_interval: float = 0.3,
    timeout: float = 15.0,
) -> dict:
    out_path = os.path.join(tempfile.gettempdir(), f"marimo_mcp_{cell_id}.json")

    try:
        os.unlink(out_path)
    except FileNotFoundError:
        pass

    await execute_cells(notebook_uri, [cell_id], [_wrap_code(code, out_path)])

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(poll_interval)
        try:
            with open(out_path) as f:
                result = json.load(f)
            os.unlink(out_path)
            return result
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    return {"stdout": "", "stderr": f"Timeout: no output after {timeout:.0f}s"}


def format_output(result: dict) -> str:
    parts: list[str] = []
    if result.get("stdout"):
        parts.append(result["stdout"].rstrip())
    if result.get("stderr"):
        parts.append(f"[stderr]\n{result['stderr'].rstrip()}")
    return "\n".join(parts) if parts else "(no output)"


async def execute_and_get_visual_output(
    notebook_uri: str,
    cell_id: str,
    code: str,
    timeout: float = 15.0,
) -> dict:
    result = await call_api("execute-and-poll-outputs", {
        "notebookUri": notebook_uri,
        "cellId": cell_id,
        "code": code,
        "timeout": int(timeout * 1000),
    })
    return result if isinstance(result, dict) else {}


async def delete_cell_lsp(notebook_uri: str, cell_id: str) -> object:
    return await call_api("delete-cell", {
        "notebookUri": notebook_uri,
        "cellId": cell_id,
    })


async def add_cell_lsp(notebook_uri: str, cell_id: str, code: str, after_cell_id: str | None, cell_type: str = "code") -> dict:
    return await call_api("add-cell", {
        "notebookUri": notebook_uri,
        "cellId": cell_id,
        "code": code,
        "afterCellId": after_cell_id,
        "cellType": cell_type,
    })

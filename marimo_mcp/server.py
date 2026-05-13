from __future__ import annotations

import json
import asyncio
import os
from collections.abc import Awaitable

import httpx
from mcp.server.fastmcp import FastMCP

from marimo_mcp import lsp_client
from marimo_mcp.client import MarimoClient, generate_cell_id
from marimo_mcp.discovery import NotebookInfo, _clear_cache, _failed_ports, discover_notebooks, resolve_notebook
from marimo_mcp.tools.create import create_notebook_file
from marimo_mcp.static_analysis import get_deps_static, get_variables_static

mcp = FastMCP("marimo-mcp")


def _token() -> str | None:
    return os.environ.get("MARIMO_TOKEN")


def _client(nb: NotebookInfo) -> MarimoClient:
    return MarimoClient(port=nb.port, session_id=nb.session_id, auth_token=_token(), server_token=nb.server_token)


async def _safe(coro: Awaitable[str]) -> str:
    try:
        return await coro
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            return (
                "Error: 403 Unauthorized. "
                "Set MARIMO_TOKEN env var or start marimo with --no-token."
            )
        if e.response.status_code == 404:
            _clear_cache()
            return "Error: Session not found. The notebook may have been restarted. Try again."
        return f"Error: HTTP {e.response.status_code} — {e.response.text[:200]}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"


@mcp.tool()
async def list_notebooks() -> str:
    """List all running marimo notebooks with their paths and ports."""
    notebooks = await discover_notebooks(_token())
    if not notebooks:
        if _failed_ports:
            return (
                f"No notebooks found. Ports {sorted(_failed_ports)} are running marimo "
                "but require authentication. Start marimo with --no-token, or set "
                "MARIMO_TOKEN env var to the token from the startup URL."
            )
        return "No running marimo notebooks found. Open a notebook in VS Code first."
    return json.dumps(
        [
            {
                "name": nb.name,
                "path": nb.path,
                "port": nb.port if not nb.is_lsp else None,
                "via": "vscode" if nb.is_lsp else "http",
            }
            for nb in notebooks
        ],
        indent=2,
    )


@mcp.tool()
async def create_notebook(path: str) -> str:
    """Create a new marimo notebook at the given absolute path.

    Args:
        path: Absolute path where the .py notebook file will be created.
    """
    try:
        create_notebook_file(path)
        return f"Created notebook at {path}"
    except FileExistsError as e:
        return f"Error: {e}"
    except OSError as e:
        return f"Error: {e}"


@mcp.tool()
async def get_cells(notebook: str) -> str:
    """Get all cells with their IDs, code, and runtime state.

    Args:
        notebook: Path to the notebook file or port number (e.g. "analysis.py" or "2718").
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            # Bridge returns cells with stableId — no runtime state available
            return json.dumps(
                [{"cell_id": c["cellId"], "code": c["code"]} for c in nb.lsp_cells],
                indent=2,
            )
        client = _client(nb)
        result = await client.invoke_tool(
            "get_cell_runtime_data",
            {"sessionId": nb.session_id, "cellIds": []},
        )
        return json.dumps(result, indent=2)

    return await _safe(_run())


@mcp.tool()
async def get_cell_outputs(notebook: str, cell_ids: list[str] | None = None) -> str:
    """Get visual output and console streams for cells.

    Args:
        notebook: Path to the notebook file or port number.
        cell_ids: List of cell IDs to get outputs for. If empty, returns all cells.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            return "Error: get_cell_outputs is not available for VS Code notebooks (no HTTP runtime). Use edit_and_run_cell and check results directly."
        client = _client(nb)
        result = await client.invoke_tool(
            "get_cell_outputs",
            {"sessionId": nb.session_id, "cellIds": cell_ids or []},
        )
        return json.dumps(result, indent=2)

    return await _safe(_run())


@mcp.tool()
async def get_errors(notebook: str) -> str:
    """Get all errors in the notebook, grouped by cell.

    Args:
        notebook: Path to the notebook file or port number.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            return "Error: get_errors is not available for VS Code notebooks (no HTTP runtime)."
        client = _client(nb)
        result = await client.invoke_tool(
            "get_notebook_errors",
            {"sessionId": nb.session_id},
        )
        return json.dumps(result, indent=2)

    return await _safe(_run())


@mcp.tool()
async def get_variables(notebook: str) -> str:
    """Get all variable values and data tables in the notebook.

    Args:
        notebook: Path to the notebook file or port number.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            if not nb.path:
                return "Error: notebook path not available"
            return await asyncio.get_running_loop().run_in_executor(None, get_variables_static, nb.path)
        client = _client(nb)
        result = await client.invoke_tool(
            "get_tables_and_variables",
            {"sessionId": nb.session_id, "variableNames": []},
        )
        return json.dumps(result, indent=2)

    return await _safe(_run())


@mcp.tool()
async def get_deps(notebook: str, cell_id: str | None = None) -> str:
    """Get the cell dependency graph showing which cells depend on which variables.

    Args:
        notebook: Path to the notebook file or port number.
        cell_id: Optional cell ID to get deps for a specific cell only.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            if not nb.path:
                return "Error: notebook path not available"
            return await asyncio.get_running_loop().run_in_executor(
                None, get_deps_static, nb.path, cell_id
            )
        client = _client(nb)
        result = await client.invoke_tool(
            "get_cell_dependency_graph",
            {"sessionId": nb.session_id, "cellId": cell_id, "depth": None},
        )
        return json.dumps(result, indent=2)

    return await _safe(_run())


@mcp.tool()
async def edit_and_run_cell(notebook: str, cell_id: str, code: str) -> str:
    """Edit a cell's code and run it. Waits for completion and returns outputs.

    This does NOT require --mcp flag or agent mode.

    Args:
        notebook: Path to the notebook file or port number.
        cell_id: The cell ID to edit (get IDs from get_cells first).
        code: New Python code for the cell.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            result = await lsp_client.execute_and_get_output(nb.notebook_uri, cell_id, code)
            return json.dumps({
                "output": lsp_client.format_output(result),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
            }, indent=2)

        client = _client(nb)
        await client.run_cells([cell_id], [code])

        for _ in range(20):
            await asyncio.sleep(0.5)
            runtime_data = await client.invoke_tool(
                "get_cell_runtime_data",
                {"sessionId": nb.session_id, "cellIds": [cell_id]},
            )
            cells = runtime_data.get("data", [])
            if cells:
                state = (cells[0].get("metadata") or {}).get("runtimeState")
                if state == "idle":
                    break

        outputs = await client.invoke_tool(
            "get_cell_outputs",
            {"sessionId": nb.session_id, "cellIds": [cell_id]},
        )
        return json.dumps(outputs, indent=2)

    return await _safe(_run())


@mcp.tool()
async def delete_cell(notebook: str, cell_id: str) -> str:
    """Delete a cell from a running notebook.

    Args:
        notebook: Path to the notebook file or port number.
        cell_id: The cell ID to delete (get IDs from get_cells first).
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        if nb.is_lsp:
            await lsp_client.delete_cell_lsp(nb.notebook_uri, cell_id)
            return f"Deleted cell {cell_id}"
        client = _client(nb)
        await client.delete_cell(cell_id, nb.path)
        return f"Deleted cell {cell_id}"

    return await _safe(_run())



@mcp.tool()
async def add_cell(notebook: str, code: str, after_cell_id: str | None = None) -> str:
    """Add a new cell to a notebook without executing it.

    Args:
        notebook: Path to the notebook file or port number.
        code: Python code for the new cell (can be empty string).
        after_cell_id: Insert after this cell ID. If None, appends at end.
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        cell_id = generate_cell_id()

        if nb.is_lsp:
            await lsp_client.add_cell_lsp(nb.notebook_uri, cell_id, code, after_cell_id)
            return json.dumps({"cell_id": cell_id})

        # HTTP: translate after_cell_id → before_cell_id using cell order
        before_cell_id: str | None = None
        if after_cell_id is not None:
            runtime_data = await _client(nb).invoke_tool(
                "get_cell_runtime_data",
                {"sessionId": nb.session_id, "cellIds": []},
            )
            cells = runtime_data.get("result", {}).get("data", [])
            cell_ids_ordered = [c["cell_id"] for c in cells]
            if after_cell_id not in cell_ids_ordered:
                raise ValueError(f"Cell {after_cell_id!r} not found in notebook")
            idx = cell_ids_ordered.index(after_cell_id)
            before_cell_id = cell_ids_ordered[idx + 1] if idx + 1 < len(cell_ids_ordered) else None

        await _client(nb).create_cell(cell_id, code, before_cell_id)
        return json.dumps({"cell_id": cell_id})

    return await _safe(_run())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

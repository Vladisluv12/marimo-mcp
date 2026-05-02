from __future__ import annotations

import json
import os
from collections.abc import Awaitable

import httpx
from mcp.server.fastmcp import FastMCP

from marimo_mcp.client import MarimoClient
from marimo_mcp.discovery import _clear_cache, discover_notebooks, resolve_notebook
from marimo_mcp.tools.create import create_notebook_file

mcp = FastMCP("marimo-mcp")


def _token() -> str | None:
    return os.environ.get("MARIMO_TOKEN")


def _client(port: int, session_id: str) -> MarimoClient:
    return MarimoClient(port=port, session_id=session_id, token=_token())


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
        return "No running marimo notebooks found. Open a notebook in VS Code first."
    return json.dumps(
        [{"name": nb.name, "path": nb.path, "port": nb.port} for nb in notebooks],
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


@mcp.tool()
async def get_cells(notebook: str) -> str:
    """Get all cells with their IDs, code, and runtime state.

    Args:
        notebook: Path to the notebook file or port number (e.g. "analysis.py" or "2718").
    """
    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        client = _client(nb.port, nb.session_id)
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
        client = _client(nb.port, nb.session_id)
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
        client = _client(nb.port, nb.session_id)
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
        client = _client(nb.port, nb.session_id)
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
        client = _client(nb.port, nb.session_id)
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
    import asyncio

    async def _run() -> str:
        nb = await resolve_notebook(notebook, _token())
        client = _client(nb.port, nb.session_id)

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
        client = _client(nb.port, nb.session_id)
        await client.delete_cell(cell_id)
        return f"Deleted cell {cell_id}"

    return await _safe(_run())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

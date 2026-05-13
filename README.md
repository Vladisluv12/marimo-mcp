# marimo-mcp

A single MCP server that auto-discovers all running [marimo](https://marimo.io) notebooks
and exposes tools for reading, editing, and running cells — no `--mcp` flag required.

Works with two backends:

- **HTTP mode** — connects to marimo notebooks running via `marimo edit` (standard server)
- **VS Code mode** — connects to marimo notebooks open in VS Code via the companion bridge extension

---

## Architecture

```
Claude / MCP client
       │
       ▼
  marimo-mcp (Python MCP server)
       │
       ├─── HTTP backend ──────► marimo edit --no-token notebook.py
       │                         (port 2718 by default)
       │
       └─── VS Code backend ───► marimo-mcp-bridge (VS Code extension)
                                  │  port 42018
                                  ▼
                            vscode.commands.executeCommand('marimo.api', ...)
                                  │
                                  ▼
                          marimo VS Code extension
```

**Discovery** runs on every tool call (cached 5 s):
1. Scans running processes for `marimo` commands, extracts ports
2. For each port: fetches the HTML page to extract `Marimo-Server-Token`, then queries `/api/home/running_notebooks`
3. Checks if the bridge extension is running on port 42018 and appends any VS Code notebooks

**VS Code backend — how cell execution works:**

marimo's VS Code extension does not expose an HTTP server. The bridge extension (`marimo-mcp-bridge`) fills this gap — it runs a small HTTP server inside VS Code and forwards calls to `vscode.commands.executeCommand('marimo.api', ...)`.

Because VS Code notebooks don't expose cell outputs through the notebook API after execution, the bridge wraps executed code to redirect `stdout`/`stderr` into a JSON file in `/tmp`, which the MCP server polls until results appear (up to 15 s). This means `edit_and_run_cell` returns actual stdout/stderr output — just like a terminal. Rich outputs (plots, dataframes) are not available via VS Code mode; use the HTTP backend for those.

**VS Code backend — `get_deps` and `get_variables`:**

These tools use static analysis of the `.py` file via marimo's own AST engine. No kernel or bridge needed — just the file on disk. `get_variables` returns variable names and their kinds (variable, import, function, class); values are only available via the HTTP backend with a running session.

---

## Installation

### 1. Python MCP server

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo>
cd marimo-mcp
uv sync          # creates .venv and installs all dependencies
```

### 2. VS Code bridge extension (for VS Code notebooks)

```bash
cd marimo-mcp-bridge
npm install
npm run build    # produces dist/extension.js
```

Install in VS Code for development: open the `marimo-mcp-bridge` folder, press `F5` to launch an Extension Development Host. The bridge auto-starts when VS Code loads (`onStartupFinished` activation event).

For a permanent install, use **Developer: Install Extension from Location...** in the Command Palette and select the `marimo-mcp-bridge` folder.

---

## Configuration

### MCP settings

Add to `.vscode/mcp.json` or Claude Code's MCP config:

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uv",
      "args": ["run", "marimo-mcp"],
      "cwd": "/path/to/marimo-mcp",
      "env": {
        "MARIMO_TOKEN": "optional — only needed if marimo started with token auth"
      }
    }
  }
}
```

`uv run` automatically uses the `.venv` created by `uv sync`.

### Token authentication

By default marimo generates a random access token. Either:

- Start marimo with `--no-token` to disable authentication, **or**
- Set `MARIMO_TOKEN` to the token from the startup URL (`?access_token=...`)

---

## Tools

| Tool | HTTP | VS Code | Description |
|---|---|---|---|
| `list_notebooks` | ✓ | ✓ | List all discovered notebooks |
| `create_notebook` | ✓ | ✓ | Create a new `.py` notebook file |
| `get_cells` | ✓ | ✓ | List cells with IDs and code |
| `get_cell_outputs` | ✓ | — | Visual output and console streams |
| `get_errors` | ✓ | — | All errors grouped by cell |
| `get_variables` | ✓ (with values) | ✓ (names/kinds only) | Variables in the notebook |
| `get_deps` | ✓ | ✓ | Cell dependency graph |
| `add_cell` | ✓ | ✓ | Add a new cell (not executed); returns `cell_id` |
| `edit_and_run_cell` | ✓ | ✓ | Edit a cell and run it, returns stdout/stderr |
| `delete_cell` | ✓ | ✓ | Delete a cell |

`get_cell_outputs` and `get_errors` return an explicit error for VS Code notebooks. Use `edit_and_run_cell` with `print()` calls to inspect values.

### Current limitations

- **VS Code output is stdout/stderr only** — rich outputs (plots, dataframes, marimo UI elements) are not captured via the bridge. Use the HTTP backend (`marimo edit --no-token`) for full output access.

---

## Testing guide

### Test 1: HTTP backend (marimo running locally)

**Start a notebook:**

```bash
marimo edit --no-token --port 2718 /tmp/test_notebook.py
```

**Verify discovery:**

```bash
uv run python -c "
import asyncio
from marimo_mcp.discovery import discover_notebooks
async def main():
    nbs = await discover_notebooks()
    for nb in nbs:
        print(f'{nb.name}  port={nb.port}  via={\"vscode\" if nb.is_lsp else \"http\"}')
asyncio.run(main())
"
```

**Edit and run a cell:**

```python
import asyncio
from marimo_mcp.server import get_cells, edit_and_run_cell

async def main():
    cells = await get_cells('test_notebook.py')
    # get a cell_id from the output
    result = await edit_and_run_cell('test_notebook.py', 'CELL_ID', 'x = 6 * 7\nprint(x)')
    print(result)  # {"stdout": "42\n", ...}

asyncio.run(main())
```

---

### Test 2: VS Code bridge extension

**Verify bridge is running:**

```bash
curl -s http://127.0.0.1:42018/health
# {"status":"ok"}
```

**List open VS Code notebooks:**

```bash
curl -s http://127.0.0.1:42018/notebooks | python3 -m json.tool
```

**Full round-trip (edit + run + get output):**

```python
import asyncio
from marimo_mcp.server import get_cells, edit_and_run_cell

async def main():
    cells = await get_cells('goyda.py')  # VS Code notebook
    cell_id = ...  # from cells output
    result = await edit_and_run_cell('goyda.py', cell_id, 'print(6 * 7)')
    print(result)  # {"output": "42", "stdout": "42\n", "stderr": ""}

asyncio.run(main())
```

**Static analysis (no kernel needed):**

```python
import asyncio
from marimo_mcp.server import get_deps, get_variables

async def main():
    print(await get_deps('goyda.py'))
    print(await get_variables('goyda.py'))

asyncio.run(main())
```

---

### Test 3: Unit tests

```bash
uv run pytest tests/ -v
```

21 tests should pass, covering `MarimoClient`, `discovery` logic, and notebook creation.

---

## Troubleshooting

**No notebooks found, but marimo is running:**

- Run with `--no-token`, or set `MARIMO_TOKEN`
- Confirm the port is accessible: `curl http://localhost:2718/`

**Bridge not available (connection refused on port 42018):**

- Check the VS Code Output panel for "marimo-mcp-bridge" channel
- Make sure a `.py` marimo notebook is open — the `marimo.api` command is only available when the marimo extension is active

**`edit_and_run_cell` returns empty output or times out (VS Code):**

The cell execution output is captured via a temp file (`/tmp/marimo_mcp_{cell_id}.json`). If it stays empty:
1. Check `/debug` endpoint to confirm Python executable has marimo installed
2. Check VS Code Output → marimo for kernel startup errors
3. Default timeout is 15 s — increase it in `execute_and_get_output` if the kernel is slow

**Wrong Python executable (kernel fails to start):**

The bridge resolves Python in this order:
1. `.venv/bin/python` next to the notebook file
2. `.venv/bin/python` in any VS Code workspace folder
3. VS Code Python extension active environment
4. `python3` (system fallback)

Create a `.venv` with marimo in the workspace root:

```bash
python3 -m venv .venv
.venv/bin/pip install marimo
```

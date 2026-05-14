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

marimo's VS Code extension does not expose an HTTP server. The bridge extension (`marimo-mcp-bridge`) fills this gap — it runs a small HTTP server inside VS Code and forwards calls through VS Code's notebook execution pipeline (`notebook.cell.execute` → `executeHandler` → marimo LSP → kernel). This means `edit_and_run_cell` updates the cell visually in VS Code and returns actual stdout/stderr output.

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
bash install.sh  # compiles TypeScript, packages as VSIX, installs in VS Code
```

After installing, reload VS Code window (`Developer: Reload Window`).

For subsequent updates after code changes, just run `bash install.sh` again.

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
| `add_cell` | ✓ | ✓ | Add a new cell (not executed); `cell_type="markdown"` for markup |
| `edit_and_run_cell` | ✓ | ✓ | Edit a cell and run it, returns stdout/stderr |
| `delete_cell` | ✓ | ✓ | Delete a cell |

`get_cell_outputs` and `get_errors` return an explicit error for VS Code notebooks.
Use `edit_and_run_cell` with `print()` calls to inspect values.

### `add_cell` parameters

```
add_cell(notebook, code, after_cell_id=None, cell_type="code")
```

- `cell_type="code"` — standard Python cell (default)
- `cell_type="markdown"` — markdown cell; in VS Code uses native `NotebookCellKind.Markup`
  (renders immediately without execution); in HTTP mode wraps in `mo.md(...)`

### Current limitations

- **VS Code output is stdout/stderr only** — rich outputs (plots, dataframes, marimo UI elements)
  are not captured via the bridge. Use the HTTP backend (`marimo edit --no-token`) for full output access.

---

## Claude Code skill

A Claude Code skill for working with this MCP server is available at
`~/.claude/plugins/marketplaces/marimo-mcp/SKILL.md`. It's enabled automatically
when the `marimo-mcp@marimo-mcp` plugin is active in your Claude Code settings.

This skill is complementary to [`marimo-pair`](https://github.com/marimo-team/marimo-pair)
(which handles `marimo edit` HTTP mode). Use `marimo-mcp` when the notebook is open in VS Code.

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
    print(result)  # {"output": "42", "stdout": "42\n", ...}

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

---

### Test 3: Unit tests

```bash
uv run pytest tests/ -v
```

25 tests should pass, covering `MarimoClient`, `discovery` logic, and notebook creation.

---

## Troubleshooting

**No notebooks found, but marimo is running:**

- Run with `--no-token`, or set `MARIMO_TOKEN`
- Confirm the port is accessible: `curl http://localhost:2718/`

**Bridge not available (connection refused on port 42018):**

- Check the VS Code Output panel for "marimo-mcp-bridge" channel
- Make sure a `.py` marimo notebook is open — the `marimo.api` command is only available when the marimo extension is active

**Bridge needs reinstalling after code changes:**

```bash
cd marimo-mcp-bridge
bash install.sh
# Then: Developer: Reload Window in VS Code
```

**`edit_and_run_cell` returns empty output or times out (VS Code):**

The cell execution uses VS Code's notebook pipeline. If it times out (15s default):
1. Check VS Code Output → marimo for kernel startup errors
2. Make sure the notebook is open and visible (not just in the background)
3. Try running a cell manually first to warm up the kernel

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

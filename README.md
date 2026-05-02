# marimo-mcp

A single MCP server that auto-discovers all running [marimo](https://marimo.io) notebooks
and exposes tools for reading, editing, and running cells — no `--mcp` flag required.

## Run locally

From the project directory:

```bash
uv run marimo-mcp
```

## Configure in VS Code / Claude

Add to your MCP settings (`.vscode/mcp.json` or Claude Code settings):

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uv",
      "args": ["run", "marimo-mcp"],
      "cwd": "/path/to/marimo-mcp",
      "env": {
        "MARIMO_TOKEN": "your-token-if-needed"
      }
    }
  }
}
```

`MARIMO_TOKEN` нужен только если marimo запущен с токеном.
Проверить: `curl -X POST http://localhost:PORT/api/home/running_notebooks` — 200 = ок, 403 = нужен токен.

## Tools

| Tool | Description |
|---|---|
| `list_notebooks` | List all running notebooks |
| `get_cells` | Get all cells with IDs and code |
| `get_cell_outputs` | Get visual output and console streams |
| `get_errors` | Get all errors grouped by cell |
| `get_variables` | Get variable values and tables |
| `get_deps` | Get cell dependency graph |
| `edit_and_run_cell` | Edit cell code and run it, returns output |
| `delete_cell` | Delete a cell |
| `create_notebook` | Create a new notebook file |

## How it works

Discovery scans running processes for `marimo` commands, extracts ports, and verifies
them via `POST /api/home/running_notebooks`. Results are cached for 5 seconds.

Editing uses `POST /api/kernel/run` — a standard marimo HTTP endpoint that doesn't
require `--mcp` flag or agent mode.

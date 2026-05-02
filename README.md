# marimo-mcp

A single MCP server that auto-discovers all running [marimo](https://marimo.io) notebooks
and exposes tools for reading, editing, and running cells — no `--mcp` flag required.

## Install

```bash
pip install marimo-mcp
# or with uvx (no install needed):
uvx marimo-mcp
```

## Configure in VS Code / Claude

Add to your MCP settings:

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uvx",
      "args": ["marimo-mcp"],
      "env": {
        "MARIMO_TOKEN": "your-token-if-needed"
      }
    }
  }
}
```

No token needed if marimo is running locally with default settings.

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

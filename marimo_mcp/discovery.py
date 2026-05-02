from __future__ import annotations


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

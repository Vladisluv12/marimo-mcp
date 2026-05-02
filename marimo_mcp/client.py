from __future__ import annotations

import os

import httpx


class MarimoClient:
    def __init__(self, port: int, session_id: str, token: str | None = None) -> None:
        self.port = port
        self.session_id = session_id
        self._token = token or os.environ.get("MARIMO_TOKEN")
        self._base = f"http://localhost:{port}"

    def _headers(self) -> dict[str, str]:
        return {"Marimo-Session-Id": self.session_id}

    def _params(self) -> dict[str, str]:
        return {"token": self._token} if self._token else {}

    async def invoke_tool(self, tool_name: str, arguments: dict) -> dict:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/ai/invoke_tool",
                json={"toolName": tool_name, "arguments": arguments},
                headers=self._headers(),
                params=self._params(),
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def run_cells(self, cell_ids: list[str], codes: list[str]) -> None:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/kernel/run",
                json={"cellIds": cell_ids, "codes": codes},
                headers=self._headers(),
                params=self._params(),
                timeout=10.0,
            )
            resp.raise_for_status()

    async def delete_cell(self, cell_id: str) -> None:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/kernel/delete",
                json={"cellId": cell_id},
                headers=self._headers(),
                params=self._params(),
                timeout=10.0,
            )
            resp.raise_for_status()

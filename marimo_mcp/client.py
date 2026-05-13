from __future__ import annotations

import os
import random
import string

import httpx

_CELL_ID_ALPHABET = string.ascii_letters + string.digits


def generate_cell_id() -> str:
    return "".join(random.choices(_CELL_ID_ALPHABET, k=4))


class MarimoClient:
    def __init__(
        self,
        port: int,
        session_id: str,
        auth_token: str | None = None,
        server_token: str = "",
    ) -> None:
        self.port = port
        self.session_id = session_id
        self._auth_token = auth_token or os.environ.get("MARIMO_TOKEN")
        self._server_token = server_token
        self._base = f"http://localhost:{port}"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Marimo-Session-Id": self.session_id}
        if self._server_token:
            h["Marimo-Server-Token"] = self._server_token
        if self._auth_token:
            h["Authorization"] = f"Bearer {self._auth_token}"
        return h

    async def invoke_tool(self, tool_name: str, arguments: dict) -> dict:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/ai/invoke_tool",
                json={"toolName": tool_name, "arguments": arguments},
                headers=self._headers(),
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
                timeout=10.0,
            )
            resp.raise_for_status()

    async def delete_cell(self, cell_id: str, notebook_path: str) -> None:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/document/transaction",
                json={"changes": [{"type": "delete-cell", "cellId": cell_id}]},
                headers=self._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()

            runtime = await self.invoke_tool(
                "get_cell_runtime_data",
                {"sessionId": self.session_id, "cellIds": []},
            )
            cells = runtime.get("result", {}).get("data", [])
            resp2 = await http.post(
                f"{self._base}/api/kernel/save",
                json={
                    "cellIds": [c["cell_id"] for c in cells],
                    "codes": [c.get("code", "") for c in cells],
                    "names": ["" for _ in cells],
                    "configs": [{} for _ in cells],
                    "filename": notebook_path,
                },
                headers=self._headers(),
                timeout=10.0,
            )
            resp2.raise_for_status()

    async def create_cell(self, cell_id: str, code: str, before_cell_id: str | None) -> None:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._base}/api/document/transaction",
                json={"changes": [{"type": "create-cell", "cellId": cell_id, "code": code, "before": before_cell_id}]},
                headers=self._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()

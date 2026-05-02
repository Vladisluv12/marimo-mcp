import pytest
import respx
import httpx

from marimo_mcp.client import MarimoClient


@pytest.fixture
def client():
    return MarimoClient(port=2718, session_id="sess-abc", token=None)


@respx.mock
@pytest.mark.asyncio
async def test_invoke_tool_success(client):
    respx.post("http://localhost:2718/api/ai/invoke_tool").mock(
        return_value=httpx.Response(200, json={"status": "success", "result": {"cells": []}})
    )
    result = await client.invoke_tool("get_cell_outputs", {"sessionId": "sess-abc", "cellIds": []})
    assert result["status"] == "success"


@respx.mock
@pytest.mark.asyncio
async def test_invoke_tool_sends_session_header(client):
    route = respx.post("http://localhost:2718/api/ai/invoke_tool").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.invoke_tool("get_notebook_errors", {"sessionId": "sess-abc"})
    assert route.calls[0].request.headers["Marimo-Session-Id"] == "sess-abc"


@respx.mock
@pytest.mark.asyncio
async def test_invoke_tool_sends_tool_name_camel(client):
    route = respx.post("http://localhost:2718/api/ai/invoke_tool").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.invoke_tool("get_cell_outputs", {"sessionId": "s"})
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["toolName"] == "get_cell_outputs"


@respx.mock
@pytest.mark.asyncio
async def test_run_cells_success(client):
    respx.post("http://localhost:2718/api/kernel/run").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.run_cells(["cell-1"], ["x = 42"])


@respx.mock
@pytest.mark.asyncio
async def test_run_cells_sends_camel_keys(client):
    route = respx.post("http://localhost:2718/api/kernel/run").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.run_cells(["cell-1"], ["x = 42"])
    import json
    body = json.loads(route.calls[0].request.content)
    assert "cellIds" in body
    assert "codes" in body


@respx.mock
@pytest.mark.asyncio
async def test_delete_cell_success(client):
    respx.post("http://localhost:2718/api/kernel/delete").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.delete_cell("cell-1")


@respx.mock
@pytest.mark.asyncio
async def test_token_passed_as_query_param():
    c = MarimoClient(port=2718, session_id="s", token="mytoken")
    route = respx.post("http://localhost:2718/api/kernel/run").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await c.run_cells(["c"], ["pass"])
    assert "token=mytoken" in str(route.calls[0].request.url)

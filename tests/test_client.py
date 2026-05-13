import string

import pytest
import respx
import httpx

from marimo_mcp.client import MarimoClient, generate_cell_id


@pytest.fixture
def client():
    return MarimoClient(port=2718, session_id="sess-abc", auth_token=None)


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
    respx.post("http://localhost:2718/api/document/transaction").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    respx.post("http://localhost:2718/api/ai/invoke_tool").mock(
        return_value=httpx.Response(200, json={"result": {"data": [{"cell_id": "cell-2", "code": "x = 1"}]}})
    )
    respx.post("http://localhost:2718/api/kernel/save").mock(
        return_value=httpx.Response(200, text="ok")
    )
    await client.delete_cell("cell-1", "notebook.py")


@respx.mock
@pytest.mark.asyncio
async def test_auth_token_sent_as_bearer_header():
    c = MarimoClient(port=2718, session_id="s", auth_token="mytoken")
    route = respx.post("http://localhost:2718/api/kernel/run").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await c.run_cells(["c"], ["pass"])
    assert route.calls[0].request.headers.get("Authorization") == "Bearer mytoken"


def test_generate_cell_id_format():
    cid = generate_cell_id()
    assert len(cid) == 4
    assert all(c in (string.ascii_letters + string.digits) for c in cid)


def test_generate_cell_id_unique():
    ids = {generate_cell_id() for _ in range(100)}
    assert len(ids) > 90


@respx.mock
@pytest.mark.asyncio
async def test_create_cell_sends_transaction(client):
    import json
    route = respx.post("http://localhost:2718/api/document/transaction").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.create_cell("cccc", "z = 3", before_cell_id="bbbb")
    body = json.loads(route.calls[0].request.content)
    change = body["changes"][0]
    assert change["type"] == "create-cell"
    assert change["cellId"] == "cccc"
    assert change["code"] == "z = 3"
    assert change["before"] == "bbbb"


@respx.mock
@pytest.mark.asyncio
async def test_create_cell_before_none_appends(client):
    import json
    route = respx.post("http://localhost:2718/api/document/transaction").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.create_cell("dddd", "w = 0", before_cell_id=None)
    body = json.loads(route.calls[0].request.content)
    assert body["changes"][0]["before"] is None

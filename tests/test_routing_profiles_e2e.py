from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest
from helpers import make_post

from sparrow.mcp_server import handle_message
from sparrow.models import Model, Provider
from sparrow.proxy import serve
from sparrow.router import Pool

ROOT = Path(__file__).resolve().parents[1]
VIRTUAL_ROUTING_ALIASES = ("apex", "swift", "adaptive")


@pytest.fixture
def offline_pool(quota):
    post = make_post({})
    provider = Provider(
        id="offline",
        label="Offline",
        adapter="openai",
        base_url="https://offline.test/v1",
        auth="none",
        models=(Model("offline-small"), Model("offline-large")),
    )
    return Pool([provider], env={}, quota=quota, post=post), post


def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url)) as response:              
        return response.status, json.load(response)


def _post_json(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:              
        return response.status, json.load(response)


@pytest.mark.parametrize("alias", VIRTUAL_ROUTING_ALIASES)
def test_cli_subprocess_accepts_virtual_routing_alias_without_starting_pool(alias, tmp_path):
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, environment.get("PYTHONPATH")) if path
    )
    environment["SPARROW_DATA_DIR"] = str(tmp_path / "data")

    result = subprocess.run(
        [sys.executable, "-m", "sparrow", "ask", "--routing", alias, "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert alias in result.stdout


def test_proxy_model_listing_and_chat_accept_every_profile_offline(offline_pool):
    pool, post = offline_pool
    httpd = serve(pool, host="127.0.0.1", port=0, api_key="")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    try:
        status, models = _get_json(base + "/v1/models")
        assert status == 200
        model_ids = {row["id"] for row in models["data"]}
        assert set(VIRTUAL_ROUTING_ALIASES) <= model_ids

        for alias in VIRTUAL_ROUTING_ALIASES:
            status, body = _post_json(
                base + "/v1/chat/completions",
                {"model": alias, "messages": [{"role": "user", "content": "hello"}]},
            )
            assert status == 200
            assert body["choices"][0]["message"]["content"] == "ok"

        assert len(post.calls) == len(VIRTUAL_ROUTING_ALIASES)
        assert all(call["url"].startswith("https://offline.test/") for call in post.calls)
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("alias", VIRTUAL_ROUTING_ALIASES)
def test_mcp_route_explanation_accepts_profiles_without_network(alias, offline_pool):
    pool, post = offline_pool
    tools_response = handle_message(
        pool,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert tools_response is not None
    routing_enums = [
        tool["inputSchema"]["properties"]["routing"]["enum"]
        for tool in tools_response["result"]["tools"]
        if "routing" in tool["inputSchema"].get("properties", {})
    ]
    assert routing_enums
    assert all(set(VIRTUAL_ROUTING_ALIASES) <= set(values) for values in routing_enums)

    route_response = handle_message(
        pool,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "free_llm_route",
                "arguments": {"prompt": "Explain this small code sample", "routing": alias},
            },
        },
    )
    assert route_response is not None
    route_text = route_response["result"]["content"][0]["text"]
    assert f"routing mode: {alias}" in route_text
    assert "top candidates (in failover order)" in route_text
    assert "offline/" in route_text
    assert post.calls == []



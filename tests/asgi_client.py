"""Tiny in-process ASGI client for tests, with no extra dependencies."""

import asyncio
import json
from typing import Any

from app.main import app


async def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    query: str = "",
) -> tuple[int, dict[str, str], Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    request_headers = {"host": "127.0.0.1:8765", **(headers or {})}
    if body is not None:
        request_headers["content-type"] = "application/json"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": query.encode("ascii"),
        "headers": [(key.lower().encode("ascii"), value.encode("utf-8")) for key, value in request_headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765),
    }
    messages: list[dict[str, Any]] = []
    delivered = False
    hold_connection = asyncio.Event()

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await hold_connection.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=10)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        key.decode("latin1"): value.decode("latin1")
        for key, value in start.get("headers", [])
    }
    content = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    try:
        parsed: Any = json.loads(content) if content else None
    except json.JSONDecodeError:
        parsed = content.decode("utf-8", errors="replace")
    return start["status"], response_headers, parsed

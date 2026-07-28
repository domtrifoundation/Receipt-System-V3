"""MCP server for Agent Control (`v3-deepdive-55-agent-control-api.md` §4).

**On the transport choice, because it is a deliberate non-decision.** §11 logs "which MCP
SDK/library" as a genuinely open question. Rather than settle it by picking one here, this
implements the MCP wire protocol directly — JSON-RPC 2.0 over newline-delimited stdio, which
is what the protocol specifies — with no third-party dependency. That keeps the SDK choice
open for whoever makes it deliberately, and it means adopting an SDK later replaces this one
file rather than rippling outward.

This server is a **gRPC client** of `AgentControlService`, not a second implementation of
it. Every token check, scope check, rate limit, and audit write happens once, server-side,
so the MCP surface cannot drift from the CLI surface or quietly become more permissive.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

import grpc

from ..generated import agent_control_pb2 as pb
from ..generated import agent_control_pb2_grpc as pb_grpc
from ..service import DEFAULT_ADDRESS
from .tool_definitions import MCP_EXPOSED_TOOLS

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "resibo-agent-control", "version": "a01.00.00"}


class McpServer:
    def __init__(self, token: str, address: str = DEFAULT_ADDRESS) -> None:
        self._token = token
        self._channel = grpc.insecure_channel(address)
        self._stub = pb_grpc.AgentControlServiceStub(self._channel)

    def close(self) -> None:
        self._channel.close()

    # ------------------------------------------------------------ handlers
    def _initialize(self, _params: dict) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }

    def _tools_list(self, _params: dict) -> dict:
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": f"[{t.category.value}] {t.description}",
                    "inputSchema": t.parameters,
                }
                for t in MCP_EXPOSED_TOOLS
            ]
        }

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        reply = self._stub.ExecuteAgentAction(
            pb.AgentActionRequest(
                token=self._token, tool_name=name, arguments_json=json.dumps(args)
            )
        )
        if reply.ok:
            text = reply.payload_json
        else:
            # Surfaced as an MCP tool error rather than a protocol error: the call itself
            # succeeded, the tool declined. An agent needs to tell those apart.
            text = json.dumps({"error_code": reply.error_code, "error": reply.error_detail})
        return {
            "content": [{"type": "text", "text": text}],
            "isError": not reply.ok,
        }

    # ------------------------------------------------------------ dispatch
    def handle(self, request: dict) -> dict | None:
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params") or {}

        if method.startswith("notifications/"):
            return None  # notifications get no response, by spec

        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "tools/list":
                result = self._tools_list(params)
            elif method == "tools/call":
                result = self._tools_call(params)
            elif method == "ping":
                result = {}
            else:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
        except grpc.RpcError as e:  # pragma: no cover - transport failure path
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": f"agent control service unreachable: {e}"},
            }

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def run(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request: Any = json.loads(line)
            except json.JSONDecodeError:
                stdout.write(json.dumps({
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "parse error"},
                }) + "\n")
                stdout.flush()
                continue
            response = self.handle(request)
            if response is not None:
                stdout.write(json.dumps(response) + "\n")
                stdout.flush()


def main() -> int:  # pragma: no cover
    import argparse
    import os

    ap = argparse.ArgumentParser(prog="resibo-agent-mcp")
    ap.add_argument("--token", default=os.environ.get("RESIBO_AGENT_TOKEN", ""))
    ap.add_argument("--address", default=DEFAULT_ADDRESS)
    ns = ap.parse_args()
    if not ns.token:
        print("an agent token is required (--token or RESIBO_AGENT_TOKEN)", file=sys.stderr)
        return 2
    McpServer(ns.token, ns.address).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""`resibo-agent-cli` — the headless surface (`v3-deepdive-55-agent-control-api.md` §5).

For CI pipelines, scripted queries, and any automation where MCP's conversational
tool-calling shape is not the right fit. Same underlying gRPC calls, same token/scope/audit
discipline as the MCP path — a different transport for a different kind of caller, not a
second set of rules.

Usage matches the deep-dive's own examples:

    resibo-agent-cli --token $AGENT_TOKEN find-setting "email notifications"
    resibo-agent-cli --token $AGENT_TOKEN persistence-query --vendor "Denny's" --after 2026-01-01
    resibo-agent-cli --token $AGENT_TOKEN propose-setting-change smtp.enabled=false

Token issuance and revocation are here too, because a human operator scripting an install
needs them and the gRPC service already enforces that issuance is owner/staff-gated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import grpc

from ..generated import agent_control_pb2 as pb
from ..generated import agent_control_pb2_grpc as pb_grpc
from ..service import DEFAULT_ADDRESS


def _stub(address: str):
    return pb_grpc.AgentControlServiceStub(grpc.insecure_channel(address))


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _action(ns, tool: str, **args) -> int:
    reply = _stub(ns.address).ExecuteAgentAction(
        pb.AgentActionRequest(
            token=ns.token, tool_name=tool,
            arguments_json=json.dumps({k: v for k, v in args.items() if v is not None}),
        )
    )
    if reply.ok:
        _emit(json.loads(reply.payload_json))
        return 0
    _emit({"error_code": reply.error_code, "error": reply.error_detail,
           "tool_category": reply.tool_category})
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="resibo-agent-cli")
    ap.add_argument("--token", default=os.environ.get("RESIBO_AGENT_TOKEN", ""))
    ap.add_argument("--address", default=DEFAULT_ADDRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("find-setting", help="resolve a natural-language setting description")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)

    p = sub.add_parser("persistence-query", help="structured/full-text receipt search")
    p.add_argument("--vendor")
    p.add_argument("--after")
    p.add_argument("--before")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("propose-setting-change", help="stage a settings change for review")
    p.add_argument("assignment", help="key=value")

    p = sub.add_parser("run-status", help="status of one pipeline run")
    p.add_argument("run_id")

    sub.add_parser("system-health", help="Health API live diagnostic")
    sub.add_parser("dependency-status", help="tracked dependency currency")

    p = sub.add_parser("historian-narrative", help="what happened to one receipt")
    p.add_argument("receipt_id")

    p = sub.add_parser("tail-logs", help="recent log entries for a service")
    p.add_argument("service")
    p.add_argument("--level", default="INFO")
    p.add_argument("--limit", type=int, default=100)

    p = sub.add_parser("issue-token", help="issue an agent token (owner/staff only)")
    p.add_argument("--issued-by", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--role", default="staff", choices=["client", "staff"])
    p.add_argument("--scopes", default="read_only,dev_observability")
    p.add_argument("--expires-in", type=int, default=0, help="seconds; 0 means no expiry")

    p = sub.add_parser("revoke-token", help="revoke an agent token")
    p.add_argument("token_id")

    p = sub.add_parser("list-tokens", help="list issued agent tokens")
    p.add_argument("--include-inactive", action="store_true")

    return ap


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)

    # Token-management commands authenticate as the operator, not as an agent.
    if ns.cmd == "issue-token":
        reply = _stub(ns.address).IssueAgentToken(pb.IssueTokenRequest(
            issued_by=ns.issued_by, issued_to_label=ns.label, role=ns.role,
            scopes=[s.strip() for s in ns.scopes.split(",") if s.strip()],
            expires_in_seconds=ns.expires_in,
        ))
        if reply.error_code:
            _emit({"error_code": reply.error_code, "error": reply.error_detail})
            return 1
        _emit({
            "token_id": reply.token.token_id, "role": reply.token.role,
            "scopes": list(reply.token.scopes), "label": reply.token.issued_to_label,
            "plaintext_token": reply.plaintext_token,
            "note": "Store this now — only a SHA-256 hash is kept and it cannot be shown again.",
        })
        return 0

    if ns.cmd == "revoke-token":
        reply = _stub(ns.address).RevokeAgentToken(pb.RevokeTokenRequest(token_id=ns.token_id))
        if not reply.revoked:
            _emit({"error_code": reply.error_code, "error": reply.error_detail})
            return 1
        _emit({"revoked": True, "token_id": ns.token_id, "revoked_at": reply.revoked_at})
        return 0

    if ns.cmd == "list-tokens":
        reply = _stub(ns.address).ListAgentTokens(
            pb.ListTokensRequest(include_inactive=ns.include_inactive)
        )
        _emit([{
            "token_id": t.token_id, "label": t.issued_to_label, "role": t.role,
            "scopes": list(t.scopes), "active": t.active, "revoked_at": t.revoked_at,
        } for t in reply.tokens])
        return 0

    if not ns.token:
        print("an agent token is required (--token or RESIBO_AGENT_TOKEN)", file=sys.stderr)
        return 2

    if ns.cmd == "find-setting":
        return _action(ns, "find_setting", query=ns.query, limit=ns.limit)
    if ns.cmd == "persistence-query":
        return _action(ns, "persistence_query", vendor=ns.vendor, after=ns.after,
                       before=ns.before, limit=ns.limit)
    if ns.cmd == "propose-setting-change":
        if "=" not in ns.assignment:
            print("expected key=value", file=sys.stderr)
            return 2
        key, value = ns.assignment.split("=", 1)
        return _action(ns, "propose_setting_change", key=key, value=value)
    if ns.cmd == "run-status":
        return _action(ns, "get_run_status", run_id=ns.run_id)
    if ns.cmd == "system-health":
        return _action(ns, "get_system_health")
    if ns.cmd == "dependency-status":
        return _action(ns, "check_dependency_status")
    if ns.cmd == "historian-narrative":
        return _action(ns, "get_historian_narrative", receipt_id=ns.receipt_id)
    if ns.cmd == "tail-logs":
        return _action(ns, "tail_logs", service=ns.service, level=ns.level, limit=ns.limit)

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

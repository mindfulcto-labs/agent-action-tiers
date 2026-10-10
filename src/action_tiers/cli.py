"""Command line: run the demo, verify a log, summarise refusals."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .audit import AuditLog, read, verify
from .gate import Approval, Gate, Request
from .policy import Policy


def demo_approver(req: Request) -> Approval:
    """Stands in for a person. Approves refunds up to 100, declines the rest."""
    return Approval(granted=req.amount <= 100, by="duty-manager (simulated)")


DEMO_STEPS = [
    Request("run-001", "support-agent", "lookup_order", "customer_support"),
    Request("run-001", "support-agent", "update_delivery_address", "customer_support"),
    Request("run-001", "support-agent", "issue_refund", "customer_support", amount=80.0),
    Request("run-001", "support-agent", "issue_refund", "customer_support", amount=150.0),
    Request("run-001", "support-agent", "issue_refund", "customer_support", amount=500.0),
    Request("run-001", "support-agent", "lookup_order", "marketing"),
    Request("run-001", "support-agent", "delete_customer", "customer_support"),
    Request("run-002", "reporting-agent", "lookup_order", "reporting"),
    Request("run-002", "reporting-agent", "send_customer_email", "reporting"),
]


def cmd_demo(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if log_path.exists():
        log_path.unlink()
    gate = Gate(Policy.load(args.policy), AuditLog(log_path), approver=demo_approver)
    print(f"{'agent':<16} {'action':<24} {'purpose':<17} {'amount':>7}  result")
    for req in DEMO_STEPS:
        d = gate.check(req)
        result = "ALLOWED" if d.allowed else f"REFUSED ({d.reason})"
        amount = f"{req.amount:.0f}" if req.amount else "-"
        print(f"{req.agent:<16} {req.action:<24} {req.purpose:<17} {amount:>7}  {result}")
    ok, _ = verify(log_path)
    print(f"\nAudit log: {log_path} ({len(read(log_path))} records, chain {'intact' if ok else 'BROKEN'})")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ok, bad = verify(args.log)
    print("chain intact" if ok else f"chain broken at line {bad}")
    return 0 if ok else 1


def cmd_summary(args: argparse.Namespace) -> int:
    records = read(args.log)
    allowed = sum(1 for r in records if r["allowed"])
    print(f"{len(records)} decisions: {allowed} allowed, {len(records) - allowed} refused")
    for reason, n in Counter(r["reason"] for r in records if not r["allowed"]).most_common():
        print(f"  {n:>3}  {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="action-tiers", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the scripted demo")
    d.add_argument("--policy", default="examples/policy.toml")
    d.add_argument("--log", default="runs/demo.jsonl")
    d.set_defaults(func=cmd_demo)
    v = sub.add_parser("verify", help="check the hash chain of an audit log")
    v.add_argument("log")
    v.set_defaults(func=cmd_verify)
    s = sub.add_parser("summary", help="count decisions and refusal reasons")
    s.add_argument("log")
    s.set_defaults(func=cmd_summary)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

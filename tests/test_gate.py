import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from action_tiers import Approval, AuditLog, Gate, Policy, Request, Tier, verify
from action_tiers.cli import main

EXAMPLE = Path(__file__).parent.parent / "examples" / "policy.toml"
FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_gate(tmp_path, approve=True):
    approver = lambda r: Approval(approve, "tester")  # noqa: E731
    return Gate(Policy.load(EXAMPLE), AuditLog(tmp_path / "log.jsonl"), approver, clock=lambda: FIXED)


def req(action, purpose="customer_support", agent="support-agent", amount=0.0, run="r1"):
    return Request(run, agent, action, purpose, amount)


def test_read_is_allowed(tmp_path):
    d = make_gate(tmp_path).check(req("lookup_order"))
    assert d.allowed and d.reason == "ok" and d.tier == "read"


@pytest.mark.parametrize("request_, reason", [
    (req("delete_customer"), "unknown_action"),
    (req("lookup_order", agent="ghost"), "unknown_agent"),
    (req("lookup_order", purpose="marketing"), "purpose_not_granted_to_agent"),
    (req("send_customer_email", agent="reporting-agent", purpose="reporting"), "purpose_not_allowed_for_action"),
    (req("issue_refund", amount=500.0), "amount_above_action_limit"),
    (req("issue_refund", amount=0.0), "spend_amount_missing"),
])
def test_refusal_reasons(tmp_path, request_, reason):
    d = make_gate(tmp_path).check(request_)
    assert not d.allowed and d.reason == reason


def test_tier_ceiling(tmp_path):
    policy = Policy.from_dict({
        "actions": {"close_ticket": {"tier": "act", "purposes": ["ops"]}},
        "agents": {"reader": {"max_tier": "read", "purposes": ["ops"], "act_budget": 5}},
    })
    gate = Gate(policy, AuditLog(tmp_path / "log.jsonl"))
    d = gate.check(Request("r1", "reader", "close_ticket", "ops"))
    assert d.reason == "tier_above_agent_ceiling"


def test_act_budget_is_per_run(tmp_path):
    gate = make_gate(tmp_path)
    results = [gate.check(req("update_delivery_address")).allowed for _ in range(4)]
    assert results == [True, True, True, False]
    assert gate.check(req("update_delivery_address", run="r2")).allowed


def test_spend_budget_accumulates(tmp_path):
    gate = make_gate(tmp_path)
    assert gate.check(req("issue_refund", amount=200.0)).allowed
    d = gate.check(req("issue_refund", amount=100.0))
    assert d.reason == "spend_budget_exhausted"


def test_spend_needs_a_person(tmp_path):
    d = make_gate(tmp_path, approve=False).check(req("issue_refund", amount=50.0))
    assert d.reason == "approval_declined" and d.approver == "tester"


def test_human_not_asked_for_invalid_spend(tmp_path):
    asked = []
    gate = Gate(Policy.load(EXAMPLE), AuditLog(tmp_path / "l.jsonl"),
                approver=lambda r: asked.append(r) or Approval(True, "x"))
    gate.check(req("issue_refund", amount=999.0))
    assert asked == []


def test_default_approver_refuses_spend(tmp_path):
    gate = Gate(Policy.load(EXAMPLE), AuditLog(tmp_path / "l.jsonl"))
    assert gate.check(req("issue_refund", amount=10.0)).reason == "approval_declined"


def test_every_decision_is_logged(tmp_path):
    gate = make_gate(tmp_path)
    gate.check(req("lookup_order"))
    gate.check(req("delete_customer"))
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    records = [json.loads(x) for x in lines]
    assert [r["allowed"] for r in records] == [True, False]
    assert records[1]["reason"] == "unknown_action"
    assert verify(tmp_path / "log.jsonl") == (True, None)


def test_tampering_is_detected(tmp_path):
    gate = make_gate(tmp_path)
    for _ in range(3):
        gate.check(req("lookup_order"))
    path = tmp_path / "log.jsonl"
    lines = path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["allowed"] = False
    lines[1] = json.dumps(rec, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    assert verify(path) == (False, 2)


def test_deleted_line_is_detected(tmp_path):
    gate = make_gate(tmp_path)
    for _ in range(3):
        gate.check(req("lookup_order"))
    path = tmp_path / "log.jsonl"
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n")
    assert verify(path) == (False, 2)


def test_log_resumes_chain(tmp_path):
    make_gate(tmp_path).check(req("lookup_order"))
    make_gate(tmp_path).check(req("lookup_order"))
    assert verify(tmp_path / "log.jsonl") == (True, None)


def test_policy_rejects_spend_without_cap():
    with pytest.raises(ValueError):
        Policy.from_dict({"actions": {"pay": {"tier": "spend"}}})


def test_tier_order():
    assert Tier.READ < Tier.ACT < Tier.SPEND
    with pytest.raises(ValueError):
        Tier.parse("delete")


def test_demo_runs(tmp_path, capsys):
    log = tmp_path / "demo.jsonl"
    assert main(["demo", "--policy", str(EXAMPLE), "--log", str(log)]) == 0
    out = capsys.readouterr().out
    assert "REFUSED (approval_declined)" in out and "chain intact" in out
    assert main(["verify", str(log)]) == 0
    assert main(["summary", str(log)]) == 0

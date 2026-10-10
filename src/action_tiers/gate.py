"""The gate. Every agent action passes through `Gate.check` before it runs.

The gate answers four questions for every request:
who is asking, for what purpose, at which tier, and how much budget is left.
A refusal is a normal result. It is logged with a reason code, like an approval.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .audit import AuditLog
from .policy import Policy, Tier


@dataclass(frozen=True)
class Request:
    run_id: str
    agent: str
    action: str
    purpose: str
    amount: float = 0.0  # spend tier only


@dataclass(frozen=True)
class Approval:
    granted: bool
    by: str  # who approved or declined; a person, not the agent


@dataclass
class Decision:
    allowed: bool
    reason: str  # stable reason code, e.g. "ok", "purpose_not_allowed"
    tier: str | None
    checks: list[tuple[str, bool]] = field(default_factory=list)
    approver: str | None = None


Approver = Callable[[Request], Approval]


def no_approver(_: Request) -> Approval:
    """Default: nobody is available to approve, so spend is always refused."""
    return Approval(granted=False, by="none")


class Gate:
    def __init__(
        self,
        policy: Policy,
        log: AuditLog,
        approver: Approver = no_approver,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.policy = policy
        self.log = log
        self.approver = approver
        self.clock = clock
        self._acts_used: dict[str, int] = defaultdict(int)
        self._spent: dict[str, float] = defaultdict(float)

    def check(self, req: Request) -> Decision:
        decision = self._decide(req)
        if decision.allowed:
            tier = Tier.parse(decision.tier)
            if tier is Tier.ACT:
                self._acts_used[req.run_id] += 1
            elif tier is Tier.SPEND:
                self._spent[req.run_id] += req.amount
        self.log.append({
            "ts": self.clock().isoformat(),
            "run_id": req.run_id,
            "agent": req.agent,
            "action": req.action,
            "purpose": req.purpose,
            "amount": req.amount,
            "tier": decision.tier,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "checks": [{"check": name, "passed": ok} for name, ok in decision.checks],
            "approver": decision.approver,
        })
        return decision

    def _decide(self, req: Request) -> Decision:
        checks: list[tuple[str, bool]] = []

        def refuse(check: str, tier: Tier | None = None) -> Decision:
            checks.append((check, False))
            return Decision(False, check, tier.name.lower() if tier else None, checks)

        agent = self.policy.agents.get(req.agent)
        if agent is None:
            return refuse("unknown_agent")
        checks.append(("known_agent", True))

        action = self.policy.actions.get(req.action)
        if action is None:
            return refuse("unknown_action")
        checks.append(("known_action", True))
        tier = action.tier

        if req.purpose not in agent.purposes:
            return refuse("purpose_not_granted_to_agent", tier)
        if req.purpose not in action.purposes:
            return refuse("purpose_not_allowed_for_action", tier)
        checks.append(("purpose", True))

        if tier > agent.max_tier:
            return refuse("tier_above_agent_ceiling", tier)
        checks.append(("tier_within_ceiling", True))

        if tier is Tier.ACT:
            if self._acts_used[req.run_id] >= agent.act_budget:
                return refuse("act_budget_exhausted", tier)
            checks.append(("act_budget", True))

        approver = None
        if tier is Tier.SPEND:
            if req.amount <= 0:
                return refuse("spend_amount_missing", tier)
            if req.amount > action.max_amount:
                return refuse("amount_above_action_limit", tier)
            if self._spent[req.run_id] + req.amount > agent.spend_budget:
                return refuse("spend_budget_exhausted", tier)
            checks.append(("spend_limits", True))
            # A person is asked only after every automatic check has passed.
            approval = self.approver(req)
            approver = approval.by
            if not approval.granted:
                d = refuse("approval_declined", tier)
                d.approver = approver
                return d
            checks.append(("human_approval", True))

        return Decision(True, "ok", tier.name.lower(), checks, approver)

# agent-action-tiers

Read, act, spend: three risk tiers for AI agent actions, a policy gate that checks every call, and an audit log that shows if anyone has edited it.

Under 400 lines of Python. No dependencies. Runs offline. No model or API key needed.

## The idea

Most agents get one permission: access to a tool. If an agent can read a customer table, it can often change it too. Nobody decided that on purpose. It came with the tool.

This repo sorts every agent action into one of three tiers, and each tier gets a different control:

| Tier | Examples | Control |
|---|---|---|
| **read** | look up, search, summarise | Runs freely. Every call is logged. |
| **act** | change a record, send a message, open a ticket | A budget of calls per run. |
| **spend** | move money, commit stock, sign anything | Hard limits per call and per run, then a person approves every time. |

Before any action runs, the gate asks four questions. Who is asking? For what purpose? At which tier? How much budget is left?

A refusal is a normal result. It gets a reason code and goes in the same log as the approvals. That log is the evidence an auditor will ask for.

## Quickstart

Needs Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mindfulcto-labs/agent-action-tiers
cd agent-action-tiers
uv sync
uv run action-tiers demo
```

Output:

```
agent            action                   purpose            amount  result
support-agent    lookup_order             customer_support        -  ALLOWED
support-agent    update_delivery_address  customer_support        -  ALLOWED
support-agent    issue_refund             customer_support       80  ALLOWED
support-agent    issue_refund             customer_support      150  REFUSED (approval_declined)
support-agent    issue_refund             customer_support      500  REFUSED (amount_above_action_limit)
support-agent    lookup_order             marketing               -  REFUSED (purpose_not_granted_to_agent)
support-agent    delete_customer          customer_support        -  REFUSED (unknown_action)
reporting-agent  lookup_order             reporting               -  ALLOWED
reporting-agent  send_customer_email      reporting               -  REFUSED (purpose_not_allowed_for_action)

Audit log: runs/demo.jsonl (9 records, chain intact)
```

Then:

```bash
uv run action-tiers summary runs/demo.jsonl   # decisions and refusal reasons
uv run action-tiers verify runs/demo.jsonl    # check nobody edited the log
uv run pytest                                 # the tests
```

Note the 500 refund. It is refused before a person is asked. People should only see requests that already passed every automatic check, or they learn to click approve without reading.

## The policy file

Policy is a TOML file under version control, so a change to what an agent may do is a reviewed change. See [`examples/policy.toml`](examples/policy.toml).

```toml
[actions.issue_refund]
tier = "spend"
purposes = ["customer_support"]
max_amount = 200.0

[agents.support-agent]
max_tier = "spend"
purposes = ["customer_support"]
act_budget = 3
spend_budget = 250.0
```

A spend action without `max_amount` is rejected when the policy loads.

## Using it in your own agent

```python
from action_tiers import AuditLog, Gate, Policy, Request, Approval

gate = Gate(
    Policy.load("policy.toml"),
    AuditLog("runs/agent.jsonl"),
    approver=lambda req: ask_a_person(req),  # returns Approval(granted, by)
)

decision = gate.check(Request("run-42", "support-agent", "issue_refund", "customer_support", amount=60))
if decision.allowed:
    issue_refund(...)
else:
    tell_the_agent(decision.reason)  # the agent sees why, and can try another route
```

Call `gate.check` in the one place where your agent framework runs tools, so no tool call can skip it.

## The checks, in order

1. `unknown_agent`: the agent is not in the policy.
2. `unknown_action`: the action is not in the policy.
3. `purpose_not_granted_to_agent`, `purpose_not_allowed_for_action`: purpose limitation, both ways.
4. `tier_above_agent_ceiling`: a read-only agent asked to act or spend.
5. `act_budget_exhausted`: too many act calls in this run.
6. `spend_amount_missing`, `amount_above_action_limit`, `spend_budget_exhausted`: hard spend limits.
7. `approval_declined`: a person said no. With no approver set, spend is always refused.

## The audit log

One JSON line per decision. Each line holds the SHA-256 hash of the line before it. If someone edits, deletes or reorders a line, `verify` names the first line that no longer fits. This makes tampering visible. It does not stop it, so in production also ship the log somewhere the agent cannot write to.

## What this is not

- Not a product, and not a framework to run in production as it is.
- Not tied to any agent framework. It is the check, not the agent.
- Not compliance on its own. A log like this helps you answer record-keeping and human-oversight questions (for example EU AI Act Articles 12 and 14, ISO/IEC 42001 event logging). It does not make a system compliant.

Personal work, built in my own time. Not affiliated with any employer. The example domain is fictional.

## Licence

Apache 2.0. See [LICENSE](LICENSE).

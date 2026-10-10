"""Tiers, actions, agents, and the policy file that ties them together."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Tier(IntEnum):
    """Three risk tiers. Higher number means more risk."""

    READ = 1   # look up, search, summarise
    ACT = 2    # change a record, send a message, open a ticket
    SPEND = 3  # move money, commit stock, sign anything

    @classmethod
    def parse(cls, value: str) -> "Tier":
        try:
            return cls[value.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown tier {value!r}; use read, act or spend") from None


@dataclass(frozen=True)
class Action:
    name: str
    tier: Tier
    purposes: frozenset[str]
    max_amount: float | None = None  # spend tier only: cap for a single call


@dataclass(frozen=True)
class Agent:
    name: str
    max_tier: Tier
    purposes: frozenset[str]
    act_budget: int = 0        # act-tier calls allowed per run
    spend_budget: float = 0.0  # total amount allowed per run


@dataclass(frozen=True)
class Policy:
    actions: dict[str, Action] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Policy":
        actions = {}
        for name, a in data.get("actions", {}).items():
            tier = Tier.parse(a["tier"])
            max_amount = a.get("max_amount")
            if tier is Tier.SPEND and max_amount is None:
                raise ValueError(f"spend action {name!r} must set max_amount")
            actions[name] = Action(
                name=name,
                tier=tier,
                purposes=frozenset(a.get("purposes", [])),
                max_amount=float(max_amount) if max_amount is not None else None,
            )
        agents = {}
        for name, g in data.get("agents", {}).items():
            agents[name] = Agent(
                name=name,
                max_tier=Tier.parse(g["max_tier"]),
                purposes=frozenset(g.get("purposes", [])),
                act_budget=int(g.get("act_budget", 0)),
                spend_budget=float(g.get("spend_budget", 0.0)),
            )
        return cls(actions=actions, agents=agents)

    @classmethod
    def load(cls, path: str | Path) -> "Policy":
        with open(path, "rb") as fh:
            return cls.from_dict(tomllib.load(fh))

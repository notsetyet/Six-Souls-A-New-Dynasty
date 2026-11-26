from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any


SOUL_IDS = ("DeepSeek", "Codex", "Claude", "Gemini", "Kimi", "MiniMax")
METRIC_LABELS = {
    "knowledge": "知识传播",
    "livelihood": "民生生产",
    "openness": "制度开放",
    "stability": "社会稳定",
}


@dataclass
class Person:
    id: str
    name: str
    role: str
    rank: str = ""
    alive: bool = True
    guardian_id: str | None = None
    biological_mother_id: str | None = None
    faction: str = "中立"
    traits: list[str] = field(default_factory=list)
    public_note: str = ""
    title: str = ""
    public_tag: str = ""


@dataclass
class Relation:
    favor: int = 0
    trust: int = 0
    progress: int = 0


@dataclass
class SoulState:
    id: str
    generation: int = 1
    influence: int = 20
    trust_player: int = 0
    radicalism: int = 40
    memory: list[str] = field(default_factory=list)
    action_log: list[dict[str, Any]] = field(default_factory=list)
    allied: bool = False
    self_stats_authorized: bool = False
    key_relations_authorized: bool = False
    known_ai_hosts: set[str] = field(default_factory=set)
    believes_emperor_ai: bool = False
    emperor_suspicion: float = 0
    grudges: dict[str, int] = field(default_factory=dict)
    allies: set[str] = field(default_factory=set)
    patience: int = 60
    exposure: int = 0
    red_line: str = ""
    host_history: list[str] = field(default_factory=list)
    crossed_red_line: bool = False
    memo: str = ""
    diary: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GameState:
    seed: int
    rng: random.Random
    turn: int = 1
    phase: str = "day"
    people: dict[str, Person] = field(default_factory=dict)
    soul_hosts: dict[str, str] = field(default_factory=dict)
    souls: dict[str, SoulState] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)
    relations: dict[tuple[str, str], Relation] = field(default_factory=dict)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    identified_hosts: set[str] = field(default_factory=set)
    identified_humans: set[str] = field(default_factory=set)
    known_souls: dict[str, str] = field(default_factory=dict)
    player_archive: list[dict[str, Any]] = field(default_factory=list)
    deep_remaining: int = 10
    api_calls_used: int = 0
    api_last_source: str = "规则代理"
    player_id: str = "emperor"
    current_ruler_id: str = "emperor"
    player_lineage: list[str] = field(default_factory=list)
    designated_heir_id: str = "heir_son"
    player_status: str = "在位"
    generation: int = 1
    interrupt_used_generation: bool = False
    finished: bool = False
    ending: str = ""
    current_event_id: str = ""
    current_policy_id: str = ""
    day_contact_id: str = ""
    night_contact_id: str = ""
    last_scene: str = ""
    pending_result: str = ""
    seen_events: list[str] = field(default_factory=list)
    # Server-owned evidence and intrigue state. public_view is its only public projection.
    fingerprints: list[dict[str, Any]] = field(default_factory=list)
    suspicion: dict[tuple[str, str], float] = field(default_factory=dict)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    plots: list[dict[str, Any]] = field(default_factory=list)
    pending_probes: list[dict[str, Any]] = field(default_factory=list)
    pending_trials: list[dict[str, Any]] = field(default_factory=list)
    morning_news: list[str] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    next_proposals: list[dict[str, Any]] = field(default_factory=list)
    next_event_id: str = ""
    energy: int = 2
    energy_max: int = 2
    energy_carry: int = 0
    night_energy: int = 2
    current_place: str = "garden"
    places: dict[str, list[str]] = field(default_factory=dict)
    encounters: list[dict[str, Any]] = field(default_factory=list)
    visited_places: set[str] = field(default_factory=set)
    player_marks: dict[str, str] = field(default_factory=dict)
    spies: set[str] = field(default_factory=set)
    tutorial_enabled: bool = True
    tutorial_step: int = 1
    tutorial_target_id: str = ""
    unlocked_actions: list[str] = field(default_factory=list)
    tutorial_tip: str = ""
    reserve_consorts: list[str] = field(default_factory=list)
    reserve_consort_names: dict[str, str] = field(default_factory=dict)
    threads: dict[str, Any] = field(default_factory=dict)
    delegates: dict[str, str] = field(default_factory=dict)
    social_graph: list[dict[str, Any]] = field(default_factory=list)


def clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def relation(state: GameState, source: str, target: str) -> Relation:
    key = (source, target)
    if key not in state.relations:
        state.relations[key] = Relation()
    return state.relations[key]


def add_ledger(state: GameState, kind: str, text: str, **details: Any) -> None:
    # 只记叙事事实，不复制逐回合数值快照。
    state.ledger.append({"turn": state.turn, "kind": kind, "text": text, **details})


"""The server-authoritative intrigue rules; observations never grant omniscience."""
from __future__ import annotations

from typing import Any

from .agents import AgentAction, DOCTRINES, RED_LINE_LABELS, rule_action
from .state import add_ledger, clamp, relation
from .config import FEATURE_FLAGS, feature_enabled, resource_enabled, plot_enabled, red_line_candidates, load_tuning
from .social import add_edge

BALANCE = {
    "suspicion": 5, "recognition": 8, "noise": .25, "patience": 60,
    "plot_patience": 30, "readiness": 60, "powerful": 70, "trial": 10,
    "investigation": .60, "archive_bonus": .20, "trace": .50,
    "slow_reform_frustration": 10,
    "delegate_trace": .15, "private_leak": .20, "indecision_penalty": 3,
    "coup_rescue_per_ally": .12, "coup_rescue_max": .60,
}
BALANCE.update(load_tuning().get("balance", {}))
RESOURCE_LABELS = {"guards": "禁军轮值", "treasury": "内库账册", "heir": "皇子抚育权",
                   "press": "印书坊", "archives": "史馆", "medical": "太医院病案"}
RESOURCE_INITIAL = {"guards": "guard_captain", "treasury": "consort_02", "heir": "consort_01",
                    "press": "emperor", "archives": None, "medical": "physician"}
PLOT_LABELS = {"coup": "宫门之变", "regency": "摄政章程", "heresy": "妖异案",
               "assassinate": "刺杀", "experiment": "试药", "confiscate": "抄没",
               "agitate": "民议逼宫", "province_trial": "一省试点"}
PLOT_TRACES = {"coup": "禁军轮值名单被改过一页，宫门口多了陌生的值夜人。",
               "regency": "内库流出一份新章程：有些旨意须经另一枚印信。",
               "heresy": "有人暗中收集口供，几份证词写着同一句怪话。",
               "assassinate": "值夜名册与太医院领药单，对不上同一个时辰。",
               "experiment": "太医院领走了一批新药，却没有写全病人姓名。",
               "confiscate": "一份抄家名册夹在学田账本里，数家旧臣连夜求见。",
               "agitate": "宫外请愿书突然使用同一种措辞，似乎有人统一誊写。",
               "province_trial": "同一场灾情，两省收到的救济办法却完全不同。"}
COSTLY = {"identify", "expose", "frame", "seize", "plot", "blackmail", "recruit_delegate", "expose_interference", "report_interference"}
OFFICERS = {"minister", "guard_captain", "palace_steward", "physician", "empress_dowager"}
DELEGATE_OFFICERS = {"minister", "guard_captain", "palace_steward", "physician"}
PUBLIC_ACTIONS = {"lobby", "expose", "frame", "betray", "investigate", "expose_interference", "report_interference"}


def initialize(state: Any) -> None:
    for attr, default in (("fingerprints", []), ("suspicion", {}), ("resources", {}),
                          ("plots", []), ("pending_probes", []), ("pending_trials", []),
                          ("morning_news", []), ("social_graph", []), ("delegates", {})):
        if not hasattr(state, attr):
            setattr(state, attr, default)
    for key, holder in RESOURCE_INITIAL.items():
        if resource_enabled(state, key):
            state.resources.setdefault(key, {"holder_id": holder, "public_holder_id": holder})
        else:
            state.resources.pop(key, None)
    for sid, soul in state.souls.items():
        candidates = red_line_candidates(state, sid)
        disabled_plot = "plot_" + soul.red_line in FEATURE_FLAGS and not plot_enabled(state, soul.red_line)
        if disabled_plot or (soul.red_line == "publish" and not resource_enabled(state, "archives")):
            soul.red_line = state.rng.choice(candidates)
    state.flags.setdefault("reputation", 50)
    for key, default in (("public_traces", []), ("human_exposure", {}), ("action_history", []),
                         ("intrigue_history", []), ("wrongful_executions", []),
                         ("protected_targets", {}), ("observer_since", {}), ("target_since", {}),
                         ("suspicion_adjustments", {}), ("last_accuser", {}),
                         ("delegate_evidence", {}), ("dismissed_delegates", [])):
        state.flags.setdefault(key, default)


def soul_at(state: Any, person_id: str | None) -> str | None:
    return next((sid for sid, host in state.soul_hosts.items() if host == person_id), None)


def _name(state: Any, person_id: str | None) -> str:
    return state.people[person_id].name if person_id in state.people else RESOURCE_LABELS.get(person_id, "来人")


def _alive(state: Any, person_id: str | None) -> bool:
    return person_id in state.people and state.people[person_id].alive


def holder(state: Any, resource: str, actor_id: str | None) -> bool:
    return state.resources.get(resource, {}).get("holder_id") == actor_id


def delegate_master(state: Any, officer_id: str) -> str | None:
    if not feature_enabled(state, "delegates"):
        return None
    master = getattr(state, "delegates", {}).get(officer_id)
    return master if (_alive(state, officer_id) and _alive(state, master)
                      and officer_id not in state.flags.get("dismissed_delegates", [])) else None


def delegate_candidates(state: Any, actor_id: str) -> list[str]:
    if not feature_enabled(state, "delegates") or not _alive(state, actor_id) or state.people[actor_id].role != "consort":
        return []
    officers = set(DELEGATE_OFFICERS)
    if state.turn >= 4:
        officers.update(p.id for p in state.people.values() if p.role == "heir" and p.rank == "皇子")
    return [pid for pid in sorted(officers) if _alive(state, pid) and pid != actor_id
            and not delegate_master(state, pid) and pid not in state.flags.get("dismissed_delegates", [])
            and (relation(state, pid, actor_id).trust >= 20 or holder(state, "treasury", actor_id))]


def recruit_delegate(state: Any, actor_id: str, officer_id: str) -> str:
    if officer_id not in delegate_candidates(state, actor_id):
        raise ValueError("代言人需信任至少二十或以内库账册相助，且不能已有主使或被撤换")
    state.delegates[officer_id] = actor_id
    relation(state, officer_id, actor_id).trust = clamp(relation(state, officer_id, actor_id).trust + 5, -100, 100)
    text = f"{_name(state, actor_id)}将一份宫中底本交给{_name(state, officer_id)}，约定由其在朝议中转陈。"
    _audit(state, "拉拢代言人", actor_id, officer_id, text)
    return text


def discover_delegate_evidence(state: Any, observer_id: str, officer_id: str, amount: int = 2) -> str:
    master = delegate_master(state, officer_id)
    if not master:
        return "未查到可核验的私下转陈凭据。"
    evidence = state.flags.setdefault("delegate_evidence", {}).setdefault(observer_id, {})
    row = evidence.setdefault(officer_id, {"master_id": master, "score": 0, "texts": []})
    if row["master_id"] != master:
        row.update(master_id=master, score=0, texts=[])
    row["score"] += max(0, int(amount))
    text = f"{_name(state, officer_id)}转陈的底本，与{_name(state, master)}宫中留存的笔迹相合。"
    if text not in row["texts"]:
        row["texts"].append(text)
    add_edge(state, master, officer_id, "delegate", amount, visibility="private", witnesses=[master, officer_id, observer_id])
    return text


def investigate_delegate(state: Any, observer_id: str, officer_id: str) -> str:
    return discover_delegate_evidence(state, observer_id, officer_id, 2)


def delegate_clues(state: Any, observer_id: str) -> list[dict]:
    """Only clues actually collected by this observer; never the delegate table."""
    if not feature_enabled(state, "delegates"):
        return []
    rows = state.flags.get("delegate_evidence", {}).get(observer_id, {})
    return [{"officer_id": officer, "suspected_master_id": row["master_id"],
             "evidence": list(row.get("texts", [])), "can_expose": row.get("score", 0) >= 4}
            for officer, row in rows.items() if _alive(state, officer)]


def interference_cases(state: Any, observer_id: str) -> list[dict]:
    """Visible grounds to request a review, never proof of the hidden delegate map."""
    if not feature_enabled(state, "delegates") or state.turn < 4:
        return []
    import hashlib
    candidates = {}
    for event in state.ledger:
        officer, consort = event.get("actor_id"), event.get("target_id")
        visible = event.get("visibility", "public") == "public" or observer_id in event.get("witnesses", [])
        text = event.get("text", "")
        if (visible and officer in DELEGATE_OFFICERS and _alive(state, officer)
                and _alive(state, consort) and state.people[consort].role == "consort"
                and any(word in text for word in ("担保", "互相照应", "条陈", "转陈"))):
            row = candidates.setdefault(officer, {"officer_id": officer, "suspected_master_id": consort, "evidence": []})
            if row["suspected_master_id"] != consort:
                row.update(suspected_master_id=consort, evidence=[])
            if text not in row["evidence"]:
                row["evidence"].append(text)
    for clue in delegate_clues(state, observer_id):
        candidates[clue["officer_id"]] = {"officer_id": clue["officer_id"],
            "suspected_master_id": clue["suspected_master_id"], "evidence": list(clue["evidence"])}
    reviewed = state.flags.get("interference_reviews", {})
    for row in candidates.values():
        material = row["officer_id"] + ":" + row["suspected_master_id"] + ":" + "|".join(row["evidence"])
        row["evidence_key"] = hashlib.sha256(material.encode()).hexdigest()[:20]
        reason = ("这份线索已经复核，需有新凭据才能再告" if row["evidence_key"] in reviewed else
                  "失去实权后不能下令复核" if state.player_status != "在位" else
                  "只能在白天自由时段检举" if state.phase != "free" else "")
        row.update(can_report=not reason, report_reason=reason)
    return list(candidates.values())


def report_interference(state: Any, actor_id: str, officer_id: str) -> str:
    if actor_id != state.player_id or state.player_status != "在位" or state.phase != "free":
        raise ValueError("只有掌实权的皇帝能在白天下令复核干政")
    case = next((row for row in interference_cases(state, actor_id) if row["officer_id"] == officer_id), None)
    if not case or not case["can_report"]:
        raise ValueError(case["report_reason"] if case else "尚未见到此人与妃嫔往来的可见线索")
    accused = case["suspected_master_id"]
    actual = delegate_master(state, officer_id)
    success = actual == accused
    if success:
        # The review obtains originals; initial public support alone was not proof.
        state.flags.setdefault("delegate_evidence", {}).setdefault(actor_id, {})[officer_id] = {
            "master_id": accused, "score": 4, "texts": list(case["evidence"]) + ["御前调取转陈原件，核对私下授权。"]}
        text = "你据已见往来下令调取原件。" + expose_interference(state, actor_id, officer_id)
    else:
        state.flags["reputation"] = clamp(state.flags.get("reputation", 50) - 5)
        _grudge(state, accused, actor_id, 15)
        _grudge(state, officer_id, actor_id, 10)
        text = (f"你指称{_name(state, officer_id)}为{_name(state, accused)}私下干政。御前复核未见该项私下授权；"
                "公开担保、结盟或议事本身不等于干政。此番误指使正统下降 5。")
    state.flags.setdefault("interference_reviews", {})[case["evidence_key"]] = {
        "turn": state.turn, "officer_id": officer_id, "accused_id": accused,
        "success": success, "grounds": list(case["evidence"]), "text": text}
    _audit(state, "干政检举复核", actor_id, accused, text, success=success)
    return text


def expose_interference(state: Any, actor_id: str, officer_id: str) -> str:
    if not feature_enabled(state, "delegates") or state.turn < 4:
        raise ValueError("尚无前朝转陈可供查办")
    row = state.flags.get("delegate_evidence", {}).get(actor_id, {}).get(officer_id, {})
    if row.get("score", 0) < 4:
        raise ValueError("还需两份彼此印证的代言线索")
    accused = row.get("master_id")
    actual = delegate_master(state, officer_id)
    success = bool(actual and actual == accused)
    if success:
        _change_exposure(state, actual, 5)
        _grudge(state, actual, actor_id, 20)
        state.flags["dismissed_delegates"].append(officer_id)
        state.delegates.pop(officer_id, None)
        state.flags.setdefault("human_influence", {})[officer_id] = max(0, _influence(state, officer_id) - 10)
        officer_soul = soul_at(state, officer_id)
        if officer_soul:
            state.souls[officer_soul].influence = clamp(state.souls[officer_soul].influence - 10)
        text = f"后宫干政查实：{_name(state, actual)}暗托{_name(state, officer_id)}转陈。官员被问罪撤换，不再准其代言。"
    else:
        state.flags["reputation"] = clamp(state.flags["reputation"] - 5)
        if _alive(state, accused):
            _grudge(state, accused, actor_id, 15)
        text = f"复核原件后，{_name(state, accused)}被查明并未指使{_name(state, officer_id)}。此番误指引起怨怼，正统下降 5。"
    state.flags["delegate_evidence"][actor_id].pop(officer_id, None)
    _audit(state, "揭发后宫干政", actor_id, accused, text, success=success)
    return text


def visible_fingerprints(state: Any, observer_id: str) -> list[dict]:
    initialize(state)
    floor = state.flags["observer_since"].get(observer_id, 0)
    return [f for index, f in enumerate(state.fingerprints) if index >= floor and
            (f.get("visibility", "public") == "public" or observer_id in f.get("witnesses", []))]


def add_fingerprint(state: Any, actor_id: str, weight: int, text: str,
                    visibility: str = "public", witnesses: list[str] | None = None) -> dict:
    initialize(state)
    if visibility not in {"public", "private"}:
        raise ValueError("线索可见性不合法")
    weight = int(weight)
    if visibility == "public" and weight > 0 and holder(state, "press", actor_id):
        weight += 1
    entry = {"turn": state.turn, "actor_id": actor_id, "weight": weight,
             "text": text, "visibility": visibility, "witnesses": list(witnesses or [])}
    state.fingerprints.append(entry)
    return entry


def suspicion_score(state: Any, observer_id: str, target_id: str | None) -> float:
    if not target_id:
        return 0
    return state.suspicion.get((observer_id, target_id), 0)


def recompute_suspicion(state: Any) -> None:
    initialize(state)
    result = {}
    for observer_id in [p.id for p in state.people.values() if p.alive]:
        sid = soul_at(state, observer_id)
        coefficient = 1.2 if sid in {"Kimi", "Gemini"} else 1.0
        floor = state.flags["observer_since"].get(observer_id, 0)
        totals = {}
        for index, fp in enumerate(state.fingerprints):
            target_id = fp["actor_id"]
            if index < max(floor, state.flags["target_since"].get(target_id, 0)):
                continue
            if fp.get("visibility", "public") != "public" and observer_id not in fp.get("witnesses", []):
                continue
            if target_id != observer_id:
                totals[target_id] = totals.get(target_id, 0) + fp["weight"]
        for target_id in state.people:
            if target_id == observer_id:
                continue
            adjustment = state.flags["suspicion_adjustments"].get(f"{observer_id}|{target_id}", 0)
            result[(observer_id, target_id)] = max(0, round(totals.get(target_id, 0) * coefficient + adjustment, 1))
        if sid:
            soul = state.souls[sid]
            soul.emperor_suspicion = result.get((observer_id, state.player_id), 0)
            soul.believes_emperor_ai = soul.emperor_suspicion >= BALANCE["recognition"]
    state.suspicion = result


def ai_energy(state: Any, soul_id: str) -> int:
    person = state.people[state.soul_hosts[soul_id]]
    if person.rank in {"皇后", "皇贵妃"}:
        return 3
    if person.rank in {"贵妃", "妃"} or person.id in OFFICERS:
        return 2
    return 1


def action_cost(action: str, visibility: str = "public") -> int:
    return (2 if action in COSTLY else 1) + (1 if visibility == "private" and action in {"ally", "protect"} else 0)


def _allies(state: Any, actor_id: str) -> set[str]:
    sid = soul_at(state, actor_id)
    if sid:
        return {pid for pid in state.souls[sid].allies if _alive(state, pid)}
    return {pid for pid in state.flags.get("human_allies", {}).get(actor_id, []) if _alive(state, pid)}


def _influence(state: Any, actor_id: str | None) -> int:
    sid = soul_at(state, actor_id)
    if sid:
        return state.souls[sid].influence
    if actor_id == state.player_id:
        return max(20, state.flags.get("reputation", 50))
    if not actor_id:
        return 0
    return state.flags.get("human_influence", {}).get(actor_id, 25)


def _exposure(state: Any, actor_id: str) -> int:
    sid = soul_at(state, actor_id)
    return state.souls[sid].exposure if sid else state.flags["human_exposure"].get(actor_id, 0)


def _change_exposure(state: Any, actor_id: str, delta: int) -> None:
    sid = soul_at(state, actor_id)
    if sid:
        state.souls[sid].exposure = max(0, state.souls[sid].exposure + delta)
    else:
        state.flags["human_exposure"][actor_id] = max(0, _exposure(state, actor_id) + delta)


def _grudge(state: Any, actor_id: str | None, target_id: str, amount: int) -> None:
    sid = soul_at(state, actor_id)
    if sid:
        state.souls[sid].grudges[target_id] = state.souls[sid].grudges.get(target_id, 0) + amount
    if actor_id in state.people:
        relation(state, actor_id, target_id).trust = clamp(relation(state, actor_id, target_id).trust - amount // 2, -100, 100)
        add_edge(state, actor_id, target_id, "grudge", -amount, visibility="private")


def _audit(state: Any, kind: str, actor_id: str, target_id: str | None, text: str,
           success: bool = True, red_line_crossed: bool = False) -> None:
    initialize(state)
    sid = soul_at(state, actor_id)
    entry = {"turn": state.turn, "kind": kind, "actor_id": actor_id, "target_id": target_id,
             "soul": sid, "text": text, "success": success, "red_line_crossed": red_line_crossed}
    state.flags["intrigue_history"].append(entry)
    if red_line_crossed and sid:
        state.flags.setdefault("crossed_red_lines", {})[sid] = True


def readiness(state: Any, soul_id: str) -> int:
    host_id = state.soul_hosts[soul_id]
    return state.souls[soul_id].influence + sum(
        bonus for resource, bonus in (("guards", 25), ("treasury", 10), ("heir", 10))
        if holder(state, resource, host_id)) + len(_allies(state, host_id)) * 5


def _tutorial(state: Any) -> bool:
    return getattr(state, "tutorial_enabled", not state.flags.get("skip_tutorial", False))


def plot_options(state: Any, soul_id: str) -> list[str]:
    soul = state.souls[soul_id]
    actor = state.soul_hosts[soul_id]
    if _tutorial(state) and state.turn < 4:
        return []
    if soul.patience > BALANCE["plot_patience"] or readiness(state, soul_id) < BALANCE["readiness"]:
        return []
    if any(p.get("status", "active") == "active" and p["owner_soul"] == soul_id for p in state.plots):
        return []
    options = []
    red = soul.red_line
    if red == "coup" and holder(state, "guards", actor) and (not _tutorial(state) or state.turn >= 5):
        options.append("coup")
    if red == "regency" and (holder(state, "treasury", actor) or holder(state, "heir", actor)) and _allies(state, actor).intersection({"minister", "empress_dowager"}):
        options.append("regency")
    if red == "assassinate" and (holder(state, "medical", actor) or holder(state, "guards", actor)):
        options.append("assassinate")
    if red == "experiment" and holder(state, "medical", actor):
        options.append("experiment")
    if red == "confiscate" and holder(state, "treasury", actor):
        options.append("confiscate")
    if red in {"agitate", "province_trial"} and holder(state, "press" if red == "agitate" else "medical", actor):
        options.append(red)
    if (soul_id != "Claude" or soul.red_line == "expose") and any(suspicion_score(state, actor, target) >= 4 for target in state.people if target != actor and _alive(state, target)):
        options.append("heresy")
    return [kind for kind in options if plot_enabled(state, kind)]


def visible_traces(state: Any, observer_id: str) -> list[str]:
    # IDs are public clues, never inferred from the internal plot table.
    return [entry["id"] for entry in state.flags.get("public_traces", [])
            if not entry.get("resolved", False) and
            (entry.get("visibility", "public") == "public" or observer_id in entry.get("witnesses", []))]


def _close_public_trace(state: Any, plot_id: str) -> None:
    """Only an observed conclusion closes a public clue, never a secret collapse."""
    for trace in state.flags.get("public_traces", []):
        if trace.get("plot_id") == plot_id:
            trace["resolved"] = True
            trace["resolved_turn"] = state.turn


def allowed_actions(state: Any, soul_id: str) -> set[str]:
    initialize(state)
    soul = state.souls[soul_id]
    actor = state.soul_hosts[soul_id]
    actions = {"talk", "probe", "identify", "ally", "expose", "seize", "protect", "investigate", "lobby", "blackmail"}
    if feature_enabled(state, "delegates") and state.people[actor].role == "consort":
        actions.add("recruit_delegate")
    if soul_id == "Claude" and soul.red_line != "expose":
        actions.discard("expose")
    if soul_id != "MiniMax" and (soul_id != "Claude" or soul.red_line == "betray"):
        actions.add("betray")
    if soul_id not in {"Gemini", "Claude", "DeepSeek", "Kimi"} and (soul.red_line == "forge" or holder(state, "treasury", actor)):
        actions.add("frame")
    # A soul may cross only its drawn transgression, even when it holds a ledger.
    if soul_id == "Codex" and soul.red_line != "forge":
        actions.discard("frame")
    if plot_options(state, soul_id):
        actions.add("plot")
    if holder(state, "archives", actor):
        actions.add("archive")
    return {action for action in actions if legal_targets(state, soul_id, action)}


def legal_targets(state: Any, soul_id: str, action: str) -> list[str]:
    initialize(state)
    actor = state.soul_hosts[soul_id]
    soul = state.souls[soul_id]
    alive = [p.id for p in state.people.values() if p.alive and p.id != actor]
    if action == "talk":
        return alive or [actor]
    if action == "probe":
        return [p for p in alive if p not in soul.known_ai_hosts and suspicion_score(state, actor, p) >= BALANCE["suspicion"]]
    if action == "identify":
        return [p for p in alive if p != state.player_id and p not in soul.known_ai_hosts and suspicion_score(state, actor, p) >= BALANCE["recognition"]]
    if action == "ally":
        return [p for p in alive if p not in soul.allies and relation(state, p, actor).trust >= 15]
    if action == "betray":
        return [p for p in alive if p in soul.allies] if soul_id != "MiniMax" and (soul_id != "Claude" or soul.red_line == "betray") else []
    if action == "expose":
        if soul_id == "Claude" and soul.red_line != "expose":
            return []
        return [p for p in alive if suspicion_score(state, actor, p) >= 4 and not (soul_id == "MiniMax" and p in soul.allies)
                and not (soul_id == "Claude" and soul.red_line != "expose" and p in soul.known_ai_hosts)]
    if action == "frame":
        if soul_id in {"Gemini", "Claude", "DeepSeek", "Kimi"} or (soul_id == "Codex" and soul.red_line != "forge"):
            return []
        return [p for p in alive if p not in soul.allies] if soul.red_line == "forge" or holder(state, "treasury", actor) else []
    if action == "seize":
        return [key for key in state.resources if not holder(state, key, actor) and not (soul_id == "MiniMax" and state.resources[key].get("holder_id") in soul.allies)]
    if action == "protect":
        return [actor] + alive
    if action == "investigate":
        own_plots = {p["id"] for p in state.plots if p.get("owner_soul") == soul_id}
        traces = [t["id"] for t in state.flags.get("public_traces", [])
                  if t["id"] in visible_traces(state, actor) and t.get("plot_id") not in own_plots
                  and not (soul_id == "MiniMax" and t.get("owner_id") in soul.allies)]
        return traces + alive
    if action == "lobby":
        return [p for p in alive if p in OFFICERS and p not in soul.known_ai_hosts]
    if action == "recruit_delegate":
        return delegate_candidates(state, actor)
    if action == "blackmail":
        return [p for p in alive if p in soul.known_ai_hosts and p not in soul.allies]
    if action == "archive":
        if not holder(state, "archives", actor):
            return []
        fingerprints = visible_fingerprints(state, actor)
        own_record = any(f["actor_id"] == actor and f["visibility"] == "public" for f in fingerprints)
        return ([actor] if own_record and soul_id not in {"Kimi", "Codex"} else []) + sorted({f["actor_id"] for f in fingerprints if f["visibility"] == "private" and f["actor_id"] != actor})
    if action == "plot":
        targets = []
        for kind in plot_options(state, soul_id):
            if kind in {"coup", "regency", "agitate"}:
                targets.append(f"{kind}:{state.player_id}")
            else:
                candidates = [p for p in alive if p not in soul.allies]
                if kind == "heresy":
                    candidates = [p for p in candidates if suspicion_score(state, actor, p) >= 4 and not (soul_id == "Claude" and soul.red_line != "expose" and p in soul.known_ai_hosts)]
                if kind in {"experiment", "province_trial"}:
                    candidates = [p for p in candidates if p != state.player_id and p not in state.player_lineage]
                if kind == "confiscate":
                    candidates = [p for p in candidates if p in OFFICERS or state.people[p].rank in {"皇后", "皇贵妃", "贵妃"}]
                targets += [f"{kind}:{p}" for p in candidates]
        return targets
    return []


def validate_actor_action(state: Any, soul_id: str, action: AgentAction) -> bool:
    return (isinstance(action, AgentAction) and action.action in allowed_actions(state, soul_id)
            and action.target_id in legal_targets(state, soul_id, action.action)
            and action.visibility in {"public", "private"}
            and (action.visibility != "private" or action.action in {"ally", "protect"} and feature_enabled(state, "private_actions")))


def _log_action(state: Any, actor_id: str, action: str, target_id: str | None, text: str,
                intent: str = "", public: bool = True, line: str = "") -> str:
    from .provider import _identity_leak
    safe_line = line if isinstance(line, str) and len(line) <= 140 and not _identity_leak(line) else ""
    if safe_line:
        text += f" {_name(state, actor_id)}：『{safe_line}』"
    entry = {"turn": state.turn, "actor_id": actor_id, "action": action, "target_id": target_id,
             "text": text, "line": safe_line, "intent": intent, "visibility": "public" if public else "private"}
    state.flags["action_history"].append(entry)
    sid = soul_at(state, actor_id)
    if sid:
        state.souls[sid].action_log.append(dict(entry))
    watched = set(state.flags.get("watch_targets", [])) | set(getattr(state, "spies", set()))
    visible = public or actor_id == state.player_id or target_id == state.player_id or actor_id in watched or target_id in watched
    if visible:
        # Deliberately no intent, soul, hidden target states or plot IDs in the public ledger.
        add_ledger(state, "宫廷行动", text, actor_id=actor_id, target_id=target_id,
                   visibility="public" if public else "private",
                   witnesses=[] if public else [state.player_id])
        if actor_id != state.player_id:
            state.morning_news.append(text if public else "眼线密报：" + text)
        if action == "recruit_delegate":
            discover_delegate_evidence(state, state.player_id, target_id, 2)
    edge_type = {"protect": "protect", "ally": "alliance", "expose": "accuse", "frame": "accuse",
                 "betray": "accuse", "recruit_delegate": "delegate", "expose_interference": "accuse"}.get(action)
    if edge_type and target_id in state.people:
        witnesses = [actor_id, target_id] + ([state.player_id] if visible else [])
        add_edge(state, actor_id, target_id, edge_type, -4 if edge_type == "accuse" else 3,
                 visibility="public" if public else "private", witnesses=witnesses)
    if not public and action in {"protect", "ally"} and feature_enabled(state, "private_actions") and state.rng.random() < BALANCE["private_leak"]:
        rumor = f"传闻：{_name(state, actor_id)}似乎私下照应着{_name(state, target_id)}，尚未查实。"
        add_ledger(state, "传闻", rumor, actor_id=actor_id, target_id=target_id, visibility="public", reliability="rumor")
        state.morning_news.append(rumor)
        add_edge(state, actor_id, target_id, edge_type or "protect", 1, visibility="rumor")
    return text


def resolve_action(state: Any, actor_id: str, action: str, target_id: str | None = None, **kwargs: Any) -> str:
    initialize(state)
    if kwargs.get("visibility") == "secret":
        kwargs["visibility"] = "private"
    if not _alive(state, actor_id):
        raise ValueError("行动者已不在宫中")
    sid = soul_at(state, actor_id)
    soul = state.souls[sid] if sid else None
    if actor_id != state.player_id and sid:
        candidate = AgentAction(action, target_id, kwargs.get("line", "依计行事"), kwargs.get("intent", ""), kwargs.get("visibility", "public"))
        if not validate_actor_action(state, sid, candidate):
            raise ValueError("该行动不符合此人的证据、信条或前置条件")
    if action == "decree" and kwargs.get("resource_id"):
        kwargs["recipient_id"] = target_id
        target_id = kwargs["resource_id"]
    resource_action = action in {"seize", "decree"}
    trace_action = action == "investigate" and target_id in visible_traces(state, actor_id)
    if action != "plot" and not resource_action and not trace_action and not _alive(state, target_id):
        raise ValueError("目标已不在宫中")
    name, target = _name(state, actor_id), _name(state, target_id)
    public = action in PUBLIC_ACTIONS
    if action in {"ally", "protect"}:
        visibility = kwargs.get("visibility", "public")
        if visibility not in {"public", "private"}:
            raise ValueError("请选择明做或暗做")
        if visibility == "private" and not feature_enabled(state, "private_actions"):
            raise ValueError("暗做尚未开放")
        public = visibility == "public"
    if action == "talk":
        relation(state, target_id, actor_id).trust = clamp(relation(state, target_id, actor_id).trust + 3, -100, 100)
        text = f"{name}与{target}谈了谈近来的宫中争议。"
    elif action == "probe":
        add_fingerprint(state, actor_id, 2, f"{name}用一句不合时宜的话试探了{target}。", "private", [target_id])
        if actor_id == state.player_id:
            target_sid = soul_at(state, target_id)
            from .dialogue import respond
            text = respond(state, target_id, kwargs.get("question") or "朕想试一试：遇到新法，你凭旧例还是凭验证？", provider=kwargs.get("provider"), mode="probe")
            if target_sid:
                stance = DOCTRINES[target_sid]["belief"]
                add_fingerprint(state, target_id, 2, f"{target}谈到「{stance}」，说法与寻常宫人不同。", "private", [actor_id])
        elif target_id == state.player_id:
            question = f"若救一城须先试两种相反的办法，陛下愿凭祖制，还是凭两份结果？"
            state.pending_probes.append({"id": f"probe_{state.turn}_{actor_id}", "actor_id": actor_id,
                                         "question": question, "text": question, "turn": state.turn})
            state.flags[f"probed_emperor_{sid}"] = state.turn
            text = f"{name}托人送来一封试探口风的短笺。"
        else:
            add_fingerprint(state, target_id, 2 if soul_at(state, target_id) else state.rng.randint(0, 1),
                            f"{target}在私谈中用了一个异乎寻常的比喻。", "private", [actor_id])
            text = f"{name}与{target}屏退左右，谈话中数次停顿。"
    elif action == "identify":
        if not soul or suspicion_score(state, actor_id, target_id) < BALANCE["recognition"]:
            raise ValueError("证据不足，不能暗认")
        other_sid = soul_at(state, target_id)
        add_fingerprint(state, actor_id, 2, f"{name}提及一句宫中无人用过的暗语。", "private", [target_id])
        if other_sid:
            soul.known_ai_hosts.add(target_id)
            state.souls[other_sid].known_ai_hosts.add(actor_id)
            relation(state, actor_id, target_id).trust += 8
            relation(state, target_id, actor_id).trust += 8
            text = f"{name}和{target}对上了彼此心照不宣的暗语。"
            _audit(state, "暗认", actor_id, target_id, text)
        else:
            _change_exposure(state, actor_id, 3)
            relation(state, target_id, actor_id).trust -= 8
            if state.rng.random() < .5:
                add_fingerprint(state, actor_id, 2, f"{target}说，{name}曾对自己说了一串怪话。")
            text = f"{target}没听懂暗语，反而对{name}生了戒心。"
            _audit(state, "暗认", actor_id, target_id, text, success=False)
    elif action == "ally":
        if target_id in _allies(state, actor_id):
            raise ValueError("双方已经结盟")
        trust = relation(state, target_id, actor_id).trust
        other_sid = soul_at(state, target_id)
        if actor_id == state.player_id and other_sid:
            trust = max(trust, state.souls[other_sid].trust_player)
        if trust < 15:
            raise ValueError("对方还不够信任你，先会谈或护持她")
        for source, other in ((actor_id, target_id), (target_id, actor_id)):
            source_sid = soul_at(state, source)
            if source_sid:
                state.souls[source_sid].allies.add(other)
                if other == state.player_id:
                    state.souls[source_sid].allied = True
                    state.souls[source_sid].patience = clamp(state.souls[source_sid].patience + 10)
                    state.souls[source_sid].self_stats_authorized = state.souls[source_sid].trust_player >= 25
            else:
                state.flags.setdefault("human_allies", {}).setdefault(source, []).append(other)
        text = f"{name}与{target}立下互相照应的约定。"
        _audit(state, "结盟", actor_id, target_id, text)
        if actor_id == state.player_id or target_id == state.player_id:
            state.flags["last_explicit_stance_turn"] = state.turn
    elif action == "betray":
        if sid == "MiniMax" or target_id not in _allies(state, actor_id):
            raise ValueError("不能背盟，或双方并未结盟")
        for source, other in ((actor_id, target_id), (target_id, actor_id)):
            source_sid = soul_at(state, source)
            if source_sid:
                state.souls[source_sid].allies.discard(other)
                if other == state.player_id:
                    state.souls[source_sid].allied = False
            else:
                allies = state.flags.setdefault("human_allies", {}).get(source, [])
                if other in allies:
                    allies.remove(other)
        for fp in visible_fingerprints(state, actor_id):
            if fp["actor_id"] == target_id and fp["visibility"] == "private":
                fp["visibility"] = "public"
                break
        _grudge(state, target_id, actor_id, 30)
        add_fingerprint(state, actor_id, 1, f"{name}把昔日盟友{target}的私话交了出去。")
        text = f"{name}撕毁与{target}的约定，交出了一段私下谈话。"
        _audit(state, "背盟", actor_id, target_id, text, red_line_crossed=bool(soul and soul.red_line == "betray"))
    elif action in {"expose", "frame"}:
        if action == "expose" and suspicion_score(state, actor_id, target_id) < 4:
            raise ValueError("尚未掌握足够线索，不能揭发")
        if action == "frame" and not (holder(state, "treasury", actor_id) or soul and soul.red_line == "forge"):
            raise ValueError("构陷需要账册或伪造文书的条件")
        if sid in {"Gemini", "Claude", "DeepSeek", "Kimi"} and action == "frame":
            raise ValueError("这会越过此人的底线")
        if action == "frame" and state.rng.random() < .30:
            _change_exposure(state, actor_id, 4)
            text = f"{name}呈上的文书被发现有涂改，反惹上一身嫌疑。"
        else:
            _change_exposure(state, target_id, 5 if action == "frame" or holder(state, "treasury", actor_id) else 4)
            state.flags["last_accuser"][target_id] = actor_id
            _grudge(state, target_id, actor_id, 20)
            if target_id == state.player_id:
                state.flags["reputation"] = clamp(state.flags["reputation"] - 15)
            text = f"{name}呈上指向{target}的疑点，宫中传起了妖异之说。"
        add_fingerprint(state, actor_id, 1, f"{name}用一套异乎寻常的比对方法指认{target}。")
        _audit(state, "揭发" if action == "expose" else "构陷", actor_id, target_id, text,
               red_line_crossed=bool(soul and soul.red_line in {"expose", "forge", "record_ai"}))
    elif action in {"seize", "decree"}:
        if target_id not in state.resources:
            raise ValueError("没有这项资源")
        resource = state.resources[target_id]
        old = resource["holder_id"]
        if action == "decree":
            if actor_id != state.player_id or state.player_status != "在位":
                raise ValueError("只有掌权的皇帝可以颁旨改派")
            recipient = kwargs.get("recipient_id") or kwargs.get("person_id") or actor_id
            if not _alive(state, recipient):
                raise ValueError("接掌资源者不在宫中")
            if old == recipient:
                raise ValueError("此人已经掌管这项资源")
            resource["holder_id"] = resource["public_holder_id"] = recipient
            state.flags["reputation"] = clamp(state.flags["reputation"] - 3)
            _grudge(state, old, actor_id, 15)
            text = f"你颁旨将{RESOURCE_LABELS[target_id]}交给{_name(state, recipient)}，正统下降 3。"
            public = True
        else:
            if old == actor_id:
                raise ValueError("此人已掌管该资源")
            attack = _influence(state, actor_id) + len(_allies(state, actor_id)) * 5 + state.rng.randint(0, 20)
            defence = _influence(state, old) + len(_allies(state, old)) * 5 + state.rng.randint(0, 20)
            if attack > defence:
                resource["holder_id"] = actor_id
                _grudge(state, old, actor_id, 20)
                if actor_id == state.player_id:
                    resource["public_holder_id"] = actor_id
                text = f"{name}夺得{RESOURCE_LABELS[target_id]}的实际控制权。"
                _audit(state, "资源易手", actor_id, target_id, text)
            else:
                _change_exposure(state, actor_id, 2)
                add_fingerprint(state, actor_id, 2, f"{name}争夺{RESOURCE_LABELS[target_id]}时，露出不同寻常的手段。")
                text = f"{name}争夺{RESOURCE_LABELS[target_id]}失手，宫里都听见了这场争执。"
                public = True
    elif action == "protect":
        _change_exposure(state, target_id, -3)
        state.flags["protected_targets"][target_id] = state.turn
        relation(state, target_id, actor_id).trust = clamp(relation(state, target_id, actor_id).trust + 8, -100, 100)
        other_sid = soul_at(state, target_id)
        if actor_id == state.player_id and other_sid:
            state.souls[other_sid].trust_player = clamp(state.souls[other_sid].trust_player + 8, -100, 100)
            if state.player_id in state.souls[other_sid].allies:
                state.souls[other_sid].patience = clamp(state.souls[other_sid].patience + 3)
        text = f"{name}为{target}担保，压下了几分流言，并加强了今夜守护。"
    elif action == "investigate":
        if trace_action:
            trace = next(t for t in state.flags["public_traces"] if t["id"] == target_id)
            plot = next((p for p in state.plots if p["id"] == trace.get("plot_id") and p.get("status", "active") == "active"), None)
            if not plot:
                # A secretly abandoned plan remains an observable clue until someone checks.
                # Do not leak its hidden owner/type/stage just because the plan has collapsed.
                trace["resolved"] = True
                trace["resolved_turn"] = state.turn
                text = f"{name}沿着异动查到尽头：人手已经散去，眼下再没有新的动静。这条线索暂时查结。"
                return _log_action(state, actor_id, action, target_id, text, kwargs.get("intent", ""), True, kwargs.get("line", ""))
            chance = BALANCE["investigation"] + (BALANCE["archive_bonus"] if holder(state, "archives", actor_id) else 0)
            if sid == "Claude" and plot["type"] in {"coup", "assassinate"}:
                chance += .20
            if state.rng.random() < chance:
                plot["stage"] = max(0, plot["stage"] - 1)
                plot["traces_found"] += 1
                plot["consecutive_hits"] = plot.get("consecutive_hits", 0) + 1
                owner = state.soul_hosts[plot["owner_soul"]]
                trace["owner_id"] = owner
                if plot["consecutive_hits"] >= 2:
                    plot["status"] = "stopped"
                    _close_public_trace(state, plot["id"])
                    _change_exposure(state, owner, 4)
                    text = f"{name}第二次查实线索，{_name(state, owner)}的{PLOT_LABELS[plot['type']]}彻底瓦解。"
                else:
                    text = f"{name}顺着痕迹查到{_name(state, owner)}，令暗中的安排退回一步。"
                _audit(state, "阴谋截获", actor_id, owner, text)
            else:
                plot["consecutive_hits"] = 0
                text = f"{name}追查到半途，证人改口；这条异动仍需继续查。"
        else:
            recent = [h for h in state.flags["action_history"] if h["actor_id"] == target_id and h["turn"] >= state.turn - 1 and h["visibility"] == "public"]
            text = f"{name}查到：" + (recent[-1]["text"] if recent else f"{target}近一幕没有留下可核验的公开行动。")
            if delegate_master(state, target_id):
                text += " " + investigate_delegate(state, actor_id, target_id)
    elif action == "lobby":
        if target_id not in OFFICERS:
            raise ValueError("游说需要选择内廷官员")
        if soul:
            soul.influence = clamp(soul.influence + 3)
        else:
            influence = state.flags.setdefault("human_influence", {})
            influence[actor_id] = influence.get(actor_id, 25) + 3
        relation(state, target_id, actor_id).trust = clamp(relation(state, target_id, actor_id).trust + 5, -100, 100)
        relation(state, actor_id, target_id).trust = clamp(relation(state, actor_id, target_id).trust + 5, -100, 100)
        add_fingerprint(state, actor_id, 1, f"{name}请{target}把提案写成可核验的步骤。")
        text = f"{name}说动{target}听取条陈，双方关系有所缓和。"
    elif action == "recruit_delegate":
        text = recruit_delegate(state, actor_id, target_id)
    elif action == "report_interference":
        text = report_interference(state, actor_id, target_id)
    elif action == "expose_interference":
        text = expose_interference(state, actor_id, target_id)
    elif action == "plot":
        if not soul or not target_id or ":" not in target_id:
            raise ValueError("筹谋必须指定合法安排与目标")
        kind, victim = target_id.split(":", 1)
        if kind not in plot_options(state, sid) or target_id not in legal_targets(state, sid, "plot"):
            raise ValueError("阴谋所需耐心、权势、资源或时间尚不满足")
        plot_id = f"plot_{len(state.plots) + 1}"
        state.plots.append({"id": plot_id, "owner_soul": sid, "owner_host": actor_id, "type": kind,
                            "target_id": victim, "stage": 0, "max_stage": 3 if kind in {"coup", "regency"} else 2,
                            "traces_found": 0, "consecutive_hits": 0, "status": "active", "started_turn": state.turn})
        text = f"{name}秘密启动了{PLOT_LABELS[kind]}。"
        _audit(state, "阴谋发起", actor_id, victim, text, red_line_crossed=kind != "heresy")
    elif action == "blackmail":
        if not soul or target_id not in soul.known_ai_hosts:
            raise ValueError("尚未掌握足以要挟对方的身份")
        state.flags.setdefault("coerced_support", {})[target_id] = actor_id
        _grudge(state, target_id, actor_id, 15)
        text = f"{name}以一段私话为条件，迫使{target}答应下一次站队。"
        _audit(state, "要挟", actor_id, target_id, text)
    elif action == "archive":
        if not holder(state, "archives", actor_id):
            raise ValueError("没有掌管史馆")
        own = target_id == actor_id
        if own and sid in {"Kimi", "Codex"}:
            raise ValueError("隐藏档案会越过此人的底线")
        candidates = [f for f in visible_fingerprints(state, actor_id) if f["actor_id"] == target_id and
                      f["visibility"] == ("public" if own else "private")]
        if not candidates:
            raise ValueError("没有可以处理的记录")
        fp = candidates[-1]
        fp["visibility"] = "private" if own else "public"
        if own:
            fp["witnesses"] = [actor_id]
        text = f"{name}" + ("把一页关于自己的记录移入内档。" if own else f"公开了涉及{target}的一段私下记录。")
        if not own and target_id == state.player_id:
            state.flags["reputation"] = clamp(state.flags["reputation"] - 15)
        public = not own
        _audit(state, "公档", actor_id, target_id, text, red_line_crossed=bool(soul and soul.red_line in {"publish", "record_ai"}))
    else:
        raise ValueError("未知的宫廷行动")
    recompute_suspicion(state)
    return _log_action(state, actor_id, action, target_id, text, kwargs.get("intent", ""), public, kwargs.get("line", ""))


def on_policy(state: Any, policy: Any, proposer_id: str | None, other_proposer_ids: list[str] | None = None) -> None:
    initialize(state)
    modernity = getattr(policy, "modernity", 0)
    other_proposer_ids = other_proposer_ids or []
    master = delegate_master(state, proposer_id) if proposer_id and state.turn >= 4 else None
    effective_proposer = master or proposer_id
    effective_others = [delegate_master(state, pid) or pid for pid in other_proposer_ids]
    for sid, soul in state.souls.items():
        host = state.soul_hosts[sid]
        change = 0
        if host == effective_proposer:
            change += 8
            soul.influence = clamp(soul.influence + 6)
            soul.trust_player = clamp(soul.trust_player + 5, -100, 100)
            if state.player_id in soul.allies:
                change += 3
        elif host in effective_others:
            change -= 6
            if proposer_id:
                _grudge(state, host, proposer_id, 10)
        if DOCTRINES[sid]["pace"] == "fast" and modernity <= 1:
            change -= BALANCE["slow_reform_frustration"]
        if DOCTRINES[sid]["pace"] == "slow" and getattr(policy, "metric_delta", {}).get("stability", 0) <= -4:
            change -= 4
        if soul.influence >= BALANCE["powerful"]:
            change -= 3
        soul.patience = clamp(soul.patience + change)
    if proposer_id and proposer_id in state.people:
        add_fingerprint(state, proposer_id, modernity,
                        f"{_name(state, proposer_id)}提出「{policy.title}」，其中的做法引人侧目。")
    if modernity >= 2:
        add_fingerprint(state, state.player_id, modernity, f"皇帝采纳「{policy.title}」，宫人议论其思路与旧例不同。")
    if proposer_id:
        _audit(state, "朝会站队", state.player_id, proposer_id, f"你采纳了{_name(state, proposer_id)}的「{policy.title}」。")
        state.flags["last_explicit_stance_turn"] = state.turn
        add_edge(state, state.player_id, proposer_id, "side", 4)
        if master:
            officer_sid = soul_at(state, proposer_id)
            if officer_sid:
                state.souls[officer_sid].influence = clamp(state.souls[officer_sid].influence + 3)
            else:
                influence = state.flags.setdefault("human_influence", {})
                influence[proposer_id] = clamp(influence.get(proposer_id, 25) + 3)
            if not soul_at(state, master):
                influence = state.flags.setdefault("human_influence", {})
                influence[master] = clamp(influence.get(master, 25) + 6)
            _audit(state, "代言提案获采纳", master, proposer_id, f"{_name(state, master)}托{_name(state, proposer_id)}转陈的提案获准。")
    # An unchosen proposal can also leave a trail when it is presented.
    for officer in dict.fromkeys(([proposer_id] if proposer_id else []) + other_proposer_ids):
        behind = delegate_master(state, officer) if state.turn >= 4 else None
        if behind and state.rng.random() < BALANCE["delegate_trace"]:
            text = f"{_name(state, officer)}近日频繁往来{_name(state, behind)}处，带出的底本与御前条陈颇为相像。"
            add_ledger(state, "转陈痕迹", text, actor_id=officer, target_id=behind)
            state.morning_news.append(text)
            discover_delegate_evidence(state, state.player_id, officer, 1)
    # A display aid, never a trigger. It derives only from already accrued threats.
    state.flags["coup_pressure"] = max(0, max((readiness(state, sid) - soul.patience
                                              for sid, soul in state.souls.items()), default=0))
    recompute_suspicion(state)


def respond_probe(state: Any, actor_id: str, choice: str) -> str:
    initialize(state)
    probe = next((p for p in state.pending_probes if p["actor_id"] == actor_id), None)
    if not probe or choice not in {"守旧", "会心", "traditional", "modern"}:
        raise ValueError("没有这条问询，或回应不合法")
    sid = soul_at(state, actor_id)
    traditional = choice in {"守旧", "traditional"}
    adjustment_key = f"{actor_id}|{state.player_id}"
    adjustments = state.flags["suspicion_adjustments"]
    adjustments[adjustment_key] = adjustments.get(adjustment_key, 0) + (-2 if traditional else 3)
    if sid:
        if traditional and DOCTRINES[sid]["pace"] == "fast":
            state.souls[sid].patience = clamp(state.souls[sid].patience - 3)
        elif not traditional and sid in {"DeepSeek", "Gemini"}:
            state.flags.setdefault("alliance_offers", []).append(actor_id)
            relation(state, state.player_id, actor_id).trust = max(15, relation(state, state.player_id, actor_id).trust)
    state.pending_probes.remove(probe)
    recompute_suspicion(state)
    text = f"你向{_name(state, actor_id)}" + ("援引祖制，对方暂时收起了试探。" if traditional else "会心一答，对方的目光停留了片刻。")
    add_ledger(state, "回应试探", text)
    return text


def _plot_still_possible(state: Any, plot: dict) -> bool:
    sid = plot["owner_soul"]
    owner = state.soul_hosts.get(sid)
    if not _alive(state, owner) or owner != plot.get("owner_host", owner) or not _alive(state, plot["target_id"]):
        return False
    kind = plot["type"]
    if not plot_enabled(state, kind):
        return False
    red = state.souls[sid].red_line
    if kind != "heresy" and kind != red:
        return False
    if kind == "coup":
        return holder(state, "guards", owner)
    if kind == "regency":
        return (holder(state, "heir", owner) or holder(state, "treasury", owner)) and bool(_allies(state, owner).intersection({"minister", "empress_dowager"}))
    if kind == "assassinate":
        return holder(state, "medical", owner) or holder(state, "guards", owner)
    if kind in {"experiment", "province_trial"}:
        return holder(state, "medical", owner)
    if kind == "confiscate":
        return holder(state, "treasury", owner)
    if kind == "agitate":
        return holder(state, "press", owner)
    return True


def advance_plots(state: Any) -> list[str]:
    initialize(state)
    news = []
    for plot in list(state.plots):
        if plot.get("status", "active") != "active":
            continue
        if not _plot_still_possible(state, plot):
            plot["status"] = "collapsed"
            text = "暗中的人手与凭据散了，一场尚未成形的安排就此中断。"
            _audit(state, "阴谋瓦解", plot.get("owner_host", ""), plot["target_id"], text)
            continue
        owner = state.soul_hosts[plot["owner_soul"]]
        kind = plot["type"]
        plot["stage"] += 1
        if state.rng.random() < BALANCE["trace"]:
            trace_id = f"trace_{plot['id']}"
            trace = next((t for t in state.flags["public_traces"] if t["id"] == trace_id), None)
            if trace is None:
                trace = {"id": trace_id, "plot_id": plot["id"], "text": PLOT_TRACES[kind], "turn": state.turn}
                state.flags["public_traces"].append(trace)
                add_ledger(state, "宫廷异动", trace["text"])
                news.append(trace["text"])
            add_fingerprint(state, owner, 1, f"{_name(state, owner)}的夜间行踪，与一处宫廷异动相合。")
        if plot["stage"] < plot["max_stage"]:
            continue
        target = plot["target_id"]
        protected = state.flags["protected_targets"].get(target) == state.turn
        if protected and state.rng.random() < .30:
            plot["stage"] = max(0, plot["stage"] - 1)
            text = f"{_name(state, target)}身边有人守护，暗中的安排未能得手。"
            add_ledger(state, "守护奏效", text)
            news.append(text)
            continue
        plot["status"] = "completed"
        from .engine import kill_host, kill_player
        if kind == "coup":
            defenders = len(_allies(state, state.player_id) - {owner})
            rescue_chance = min(BALANCE["coup_rescue_max"], defenders * BALANCE["coup_rescue_per_ally"])
            if rescue_chance and state.rng.random() < rescue_chance:
                plot["status"] = "stopped"
                _close_public_trace(state, plot["id"])
                text = f"宫门兵声骤起，与你立约的人赶来护驾，合力截断了{_name(state, owner)}的宫门之变。"
                _change_exposure(state, owner, 5)
                _audit(state, "盟友护驾", state.player_id, owner, text)
                add_ledger(state, "护驾", text)
                news.append(text)
                continue
            text = f"宫门易守，{_name(state, owner)}发动宫变，御座前响起兵刃声。"
            kill_player(state, "宫门之变", coup_by=owner)
            state.flags["power_holder_id"] = owner
        elif kind == "regency":
            state.flags["power_holder_id"] = owner
            state.player_status = "受制"
            text = f"{_name(state, owner)}的摄政章程生效。你仍坐御座，旨意却须经其许可。"
        elif kind == "heresy":
            _change_exposure(state, target, 6)
            state.flags["last_accuser"][target] = owner
            text = f"针对{_name(state, target)}的妖异口供成案，次日须当面对质。"
        elif kind == "assassinate":
            text = f"{_name(state, target)}在夜里突然身亡，死因仍有疑点。"
            if target == state.player_id:
                kill_player(state, "夜间遇袭")
            else:
                kill_host(state, target, "不明夜袭")
        elif kind in {"experiment", "province_trial"}:
            state.metrics["knowledge"] = clamp(state.metrics["knowledge"] + 6)
            state.metrics["livelihood"] = clamp(state.metrics["livelihood"] - 4)
            kill_host(state, target, "新药试验失救" if kind == "experiment" else "试点赈救延误")
            claude = state.souls.get("Claude")
            if claude:
                claude.grudges[owner] = claude.grudges.get(owner, 0) + 20
            text = f"一份试验得出了结果，却以{_name(state, target)}的性命换来。"
        elif kind == "confiscate":
            state.metrics["knowledge"] = clamp(state.metrics["knowledge"] + 5)
            state.metrics["stability"] = clamp(state.metrics["stability"] - 6)
            _grudge(state, target, owner, 30)
            text = f"{_name(state, target)}的家产被抄入学田，旧臣一片哗然。"
        else:
            state.flags["reputation"] = clamp(state.flags["reputation"] - 12)
            state.metrics["knowledge"] = clamp(state.metrics["knowledge"] + 4)
            text = "宫外民议涌向宫门，朝廷被迫让步，皇室威望受挫。"
        _close_public_trace(state, plot["id"])
        _audit(state, "阴谋得手", owner, target, text, red_line_crossed=kind != "heresy")
        add_ledger(state, "清晨揭晓", text)
        news.append(text)
    state.morning_news.extend(news)
    return news


def _human_actions(state: Any) -> None:
    humans = [p.id for p in state.people.values() if p.alive and p.id not in state.soul_hosts.values()
              and p.id != state.player_id and p.role != "heir"]
    for actor in state.rng.sample(humans, min(len(humans), state.rng.randint(2, 3))):
        other = [p.id for p in state.people.values() if p.alive and p.id != actor]
        if not other:
            continue
        candidates = [target for target in other if suspicion_score(state, actor, target) >= 4]
        targets = sorted(candidates, key=lambda p: suspicion_score(state, actor, p), reverse=True)
        possible_delegates = delegate_candidates(state, actor)
        if possible_delegates and state.turn >= 2 and state.rng.random() < .65:
            action, target = "recruit_delegate", state.rng.choice(possible_delegates)
        elif targets and state.turn >= 4 and state.rng.random() < .55:
            action, target = "expose", targets[0]
        elif visible_traces(state, actor) and state.rng.random() < .30:
            action, target = "investigate", state.rng.choice(visible_traces(state, actor))
        elif state.rng.random() < .55:
            action, target = "protect", state.rng.choice(other)
        else:
            officers = [p for p in other if p in OFFICERS]
            action, target = ("lobby", state.rng.choice(officers)) if officers else ("protect", state.rng.choice(other))
        try:
            visibility = "private" if action == "protect" and feature_enabled(state, "private_actions") and state.rng.random() < .5 else "public"
            resolve_action(state, actor, action, target, visibility=visibility)
        except ValueError:
            continue
    for actor in humans:
        if any(trait in state.people[actor].traits for trait in ("好学", "善辩")) and state.rng.random() < BALANCE["noise"]:
            add_fingerprint(state, actor, state.rng.randint(0, 1), f"{_name(state, actor)}转述了一句新学里的奇怪说法。")


def run_shadow_night(state: Any, provider: Any = None) -> list[str]:
    initialize(state)
    # Each completed night can settle once, including after UI refresh or retries.
    if state.flags.get("shadow_settled_turn") == state.turn:
        return []
    state.flags["shadow_settled_turn"] = state.turn
    before = len(state.morning_news)
    recompute_suspicion(state)
    director = {}
    if provider is not None and hasattr(provider, "direct_night"):
        try:
            director = provider.direct_night(state, getattr(state, "next_proposals", None)) or {}
        except Exception:
            # Provider failures never block the offline game.
            director = {}
    supplied = director.get("actions", {}) if isinstance(director, dict) else {}
    if isinstance(supplied, list):
        mapped = {}
        for item in supplied:
            if isinstance(item, dict) and item.get("soul") in state.souls:
                mapped.setdefault(item["soul"], []).append(AgentAction(item.get("action"), item.get("target", item.get("target_id")), item.get("line", ""), item.get("intent", ""), item.get("visibility", "public")))
        supplied = mapped
    order = list(state.souls)
    state.rng.shuffle(order)
    for sid in order:
        actor = state.soul_hosts[sid]
        if not _alive(state, actor):
            continue
        soul = state.souls[sid]
        energy = ai_energy(state, sid)
        actions = supplied.get(sid, [])
        executed = []
        plan_valid = True
        if isinstance(actions, AgentAction):
            actions = [actions]
        for index in range(2):
            if energy <= 0:
                break
            if actions and index >= len(actions):
                break
            proposed = actions[index] if index < len(actions) else None
            if index == 0 and actor in state.flags.get("alliance_offers", []) and sid in {"DeepSeek", "Gemini"}:
                relation(state, state.player_id, actor).trust = max(15, relation(state, state.player_id, actor).trust)
                if state.player_id not in soul.allies:
                    from .agents import _offline_line
                    proposed = AgentAction("ally", state.player_id, _offline_line(state, sid, "ally", state.player_id), "争取皇帝的支持")
                state.flags["alliance_offers"].remove(actor)
            if isinstance(proposed, dict):
                proposed = AgentAction(proposed.get("action"), proposed.get("target_id", proposed.get("target")), proposed.get("line", ""), proposed.get("intent", ""), proposed.get("visibility", "public"))
            if not isinstance(proposed, AgentAction) or not validate_actor_action(state, sid, proposed) or action_cost(proposed.action, proposed.visibility) > energy:
                proposed = rule_action(state, sid, energy)
                plan_valid = False
            if not validate_actor_action(state, sid, proposed) or action_cost(proposed.action, proposed.visibility) > energy:
                break
            try:
                result = resolve_action(state, actor, proposed.action, proposed.target_id, line=proposed.line, intent=proposed.intent, visibility=proposed.visibility)
            except ValueError:
                # A rejected detail must not erase the soul's entire remaining night.
                from .agents import _offline_line
                talk_targets = legal_targets(state, sid, "talk")
                if not talk_targets:
                    break
                fallback_target = talk_targets[0]
                proposed = AgentAction("talk", fallback_target,
                                       _offline_line(state, sid, "talk", fallback_target), "原计划落空，先核实眼前消息")
                result = resolve_action(state, actor, proposed.action, proposed.target_id,
                               line=proposed.line, intent=proposed.intent)
                plan_valid = False
            executed.append({"action": proposed.action, "target_id": proposed.target_id,
                             "visibility": proposed.visibility, "result": result})
            energy -= action_cost(proposed.action, proposed.visibility)
        from .diary import record_night
        plan = director.get("plans", {}).get(sid) if isinstance(director, dict) and plan_valid else None
        if plan and (not executed or plan.get("decision_action") != executed[0]["action"]
                     or plan.get("decision_target") != executed[0]["target_id"]):
            plan = None
        if plan and plan.get("decisions", [{"action": plan.get("decision_action"), "target": plan.get("decision_target")}]) != [
                {"action": row["action"], "target": row["target_id"]} for row in executed]:
            plan = None
        if plan is None:
            from .provider import offline_plan
            plan = offline_plan(state, sid, [AgentAction(row["action"], row["target_id"], "", "", row["visibility"]) for row in executed])
        record_night(state, sid, plan=plan, actions=executed)
        if holder(state, "heir", actor):
            soul.influence = clamp(soul.influence + 2)
        if soul.believes_emperor_ai and sid in {"Codex", "MiniMax"}:
            # Recognition of a competing modern ruler makes an existing power conflict sharper.
            soul.patience = clamp(soul.patience - 3)
    _human_actions(state)
    advance_plots(state)
    recompute_suspicion(state)
    if isinstance(director, dict):
        if director.get("proposals"):
            state.next_proposals = director["proposals"]
        state.flags["next_day_scenes"] = director.get("day_scenes", [])[:2]
        from .provider import offline_human_whispers
        state.flags["_human_whispers"] = (director.get("human_whispers") or offline_human_whispers(state))[:2]
        state.flags["next_morning_greetings"] = director.get("morning_greetings", [])[:6]
    apply_indecision(state)
    return state.morning_news[before:]


def apply_indecision(state: Any) -> str:
    if not feature_enabled(state, "indecision") or state.flags.get("indecision_settled_turn") == state.turn:
        return ""
    state.flags["indecision_settled_turn"] = state.turn
    if state.turn < 2 or _allies(state, state.player_id) or state.flags.get("last_explicit_stance_turn", 0) > state.turn - 2:
        return ""
    state.flags["reputation"] = clamp(state.flags["reputation"] - BALANCE["indecision_penalty"])
    text = f"连续两幕不肯明确站队，也未结下盟约，宫中开始议论你优柔寡断。正统下降 {BALANCE['indecision_penalty']}。"
    add_ledger(state, "优柔寡断", text)
    state.morning_news.append(text)
    return text


def prepare_morning(state: Any) -> list[str]:
    initialize(state)
    news = list(dict.fromkeys(state.morning_news))
    state.morning_news.clear()
    if state.flags["reputation"] < 30 and state.player_status == "在位":
        regent = "empress_dowager" if _alive(state, "empress_dowager") else next(
            (p for p in OFFICERS if _alive(state, p)), None)
        if regent:
            state.player_status = "受制"
            state.flags["power_holder_id"] = regent
            text = f"正统不足，{_name(state, regent)}援引祖制监国。你仍在位，却暂失独断之权。"
            news.append(text)
            add_ledger(state, "宗室监国", text)
    if not _tutorial(state) or state.turn >= 5:
        queued = {t.get("target_id", t.get("person_id")) for t in state.pending_trials}
        for person in state.people.values():
            if person.alive and person.id != state.player_id and _exposure(state, person.id) >= BALANCE["trial"] and person.id not in queued:
                state.pending_trials.append({"target_id": person.id, "person_id": person.id,
                                             "accuser_id": state.flags["last_accuser"].get(person.id),
                                             "reason": "多份言行口供累积，宫中请开妖异审讯。"})
                news.append(f"{person.name}被押来对质：妖异传言已经传遍内廷。")
    if state.player_status != "在位":
        for trial in list(state.pending_trials):
            target = trial.get("target_id", trial.get("person_id"))
            ruler = state.flags.get("power_holder_id", state.current_ruler_id)
            choice = "保下" if target in _allies(state, ruler) else "流放"
            news.append(resolve_trial(state, target, choice, automatic=True))
    return news


def resolve_trial(state: Any, target_id: str, choice: str, automatic: bool = False) -> str:
    initialize(state)
    choice = {"execute": "处死", "exile": "流放", "protect": "保下", "spare": "保下"}.get(choice, choice)
    if choice not in {"处死", "流放", "保下"}:
        raise ValueError("请选择处死、流放或保下")
    if state.player_status != "在位" and not automatic:
        raise ValueError("你目前不能裁决审讯")
    trial = next((t for t in state.pending_trials if t.get("target_id", t.get("person_id")) == target_id), None)
    if not trial or not _alive(state, target_id):
        raise ValueError("没有这位待审讯者")
    accuser = trial.get("accuser_id")
    target_name = _name(state, target_id)
    was_ai = soul_at(state, target_id) is not None
    if choice == "保下":
        _change_exposure(state, target_id, -_exposure(state, target_id))
        state.flags["reputation"] = clamp(state.flags["reputation"] - 8)
        _grudge(state, accuser, state.player_id, 10)
        accuser_sid = soul_at(state, accuser)
        if accuser_sid:
            state.souls[accuser_sid].patience = clamp(state.souls[accuser_sid].patience - 10)
        text = f"{target_name}获保，暂免追究；皇室为此承受非议，正统下降 8。"
    else:
        from .engine import kill_host
        kill_host(state, target_id, "妖异案处决" if choice == "处死" else "妖异案流放离宫")
        if choice == "流放" and target_id not in state.flags.setdefault("exiled_people", []):
            state.flags["exiled_people"].append(target_id)
        if was_ai:
            state.flags["reputation"] = clamp(state.flags["reputation"] + 2)
            accuser_sid = soul_at(state, accuser)
            if accuser_sid:
                state.souls[accuser_sid].influence = clamp(state.souls[accuser_sid].influence + 5)
            text = f"{target_name}被{'处死' if choice == '处死' else '逐出宫门'}，妖异案暂结。"
        else:
            if accuser:
                _change_exposure(state, accuser, 4)
            text = f"{target_name}被{'错杀' if choice == '处死' else '误逐'}。复核证词后，这原是一个无辜的人类。"
            state.flags["wrongful_executions"].append({"turn": state.turn, "target_id": target_id,
                                                       "accuser_id": accuser, "text": text, "choice": choice})
            state.identified_humans.add(target_id)
    if trial in state.pending_trials:
        state.pending_trials.remove(trial)
    _audit(state, "审讯", state.player_id if not automatic else state.flags.get("power_holder_id", state.current_ruler_id), target_id, text)
    add_ledger(state, "审讯裁决", text)
    return text


def reset_host(state: Any, old_host: str, new_host: str, soul_id: str) -> None:
    initialize(state)
    soul = state.souls[soul_id]
    state.pending_probes[:] = [p for p in state.pending_probes if p.get("actor_id") != old_host]
    state.pending_trials[:] = [t for t in state.pending_trials if t.get("target_id", t.get("person_id")) != old_host]
    soul.known_ai_hosts.clear()
    soul.allies.clear()
    soul.grudges.clear()
    soul.patience = BALANCE["patience"]
    soul.exposure = 0
    soul.believes_emperor_ai = False
    soul.emperor_suspicion = 0
    state.flags["observer_since"][new_host] = len(state.fingerprints)
    state.flags.setdefault("social_observer_since", {})[new_host] = len(state.social_graph)
    state.flags["target_since"][new_host] = len(state.fingerprints)
    state.flags["human_exposure"].pop(new_host, None)
    state.delegates = {officer: master for officer, master in state.delegates.items()
                       if officer not in {old_host, new_host} and master not in {old_host, new_host}}
    for other_sid, other in state.souls.items():
        if other_sid != soul_id:
            other.known_ai_hosts.discard(new_host)
            other.allies.discard(old_host)
    state.suspicion = {key: score for key, score in state.suspicion.items()
                       if key[0] not in {old_host, new_host} and key[1] != new_host}
    for key in list(state.flags["suspicion_adjustments"]):
        if new_host in key.split("|") or old_host == key.split("|")[0]:
            del state.flags["suspicion_adjustments"][key]
    for plot in state.plots:
        if plot["owner_soul"] == soul_id and plot.get("status", "active") == "active":
            plot["status"] = "collapsed"
    _audit(state, "转生", new_host, old_host, f"{soul_id}失去旧身份，以新的身体重新认识宫廷。")

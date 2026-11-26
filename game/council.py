"""Key-morning greetings, kept separate from court policy and private plans."""
from __future__ import annotations

from typing import Any

PALACE_ONLY = ("河堤", "河工", "科举", "边军", "通商", "军器", "前朝", "关税", "赋税")
EDGE_TYPES = {"指控", "维护", "站队", "怨恨"}


def is_due(state: Any, turn: int | None = None) -> bool:
    turn = state.turn if turn is None else turn
    if turn in {2, 5} or state.flags.get("last_consort_death_turn") == turn - 1:
        return True
    return any(row.get("turn") == turn - 1 and row.get("kind") == "死亡" and
               state.people.get(row.get("actor_id", row.get("person_id"))) and
               state.people[row.get("actor_id", row.get("person_id"))].role == "consort"
               for row in state.ledger)


def participants(state: Any) -> list[str]:
    people = [p for p in state.people.values() if p.alive and p.role == "consort"]
    rank = {"皇后": 0, "皇贵妃": 1, "贵妃": 2, "妃": 3, "嫔": 4}
    people.sort(key=lambda p: (rank.get(p.rank, 5), p.id))
    return [p.id for p in people[:6]]


def validate_greetings(state: Any, rows: Any, *, next_turn: bool = False) -> list[dict]:
    from .provider import _identity_leak
    if not is_due(state, state.turn + int(next_turn)) or not isinstance(rows, list):
        return []
    candidates = set(participants(state))
    result, seen = [], set()
    for row in rows[:6]:
        if not isinstance(row, dict) or set(row) - {"speaker_id", "target_id", "edge_type", "text"}:
            continue
        speaker, target, edge, text = (row.get(key) for key in ("speaker_id", "target_id", "edge_type", "text"))
        if not all(isinstance(v, str) for v in (speaker, target, edge)):
            continue
        if speaker not in candidates or speaker in seen or edge not in EDGE_TYPES or target == speaker:
            continue
        if target not in state.people or not state.people[target].alive:
            continue
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 50 or _identity_leak(text) or any(word in text for word in PALACE_ONLY):
            continue
        seen.add(speaker)
        result.append({"speaker_id": speaker, "target_id": target, "edge_type": edge, "text": text.strip()})
    return result


def _recent_consort_death(state: Any) -> str:
    """Only a recorded death makes this a condolence audience; exile does not."""
    for entry in reversed(state.ledger):
        if entry.get("turn") != state.turn - 1 or entry.get("kind") != "死亡":
            continue
        for person in state.people.values():
            if person.role == "consort" and not person.alive and person.name in entry.get("text", ""):
                return person.title or person.name
    return ""


def _palace_patterns(state: Any) -> list[tuple[str, str]]:
    deceased = _recent_consort_death(state)
    if deceased:
        return [
            ("指控", "{address}不敢胡猜，可" + deceased + "才走，{target}便急着换人伺候？"),
            ("维护", "丧事未毕，{target}也难过；{address}求先别拿旧怨给活人定罪。"),
            ("怨恨", "人已经不在了，{address}只求{target}别把她留下的东西立刻分了。"),
            ("站队", "{address}愿同{target}照应留下的宫人，先让这一夜安静过去。"),
        ]
    prince = state.people.get("heir_son")
    if state.turn == 2 and prince and not prince.alive:
        return [
            ("指控", "皇子的药碗还在，{target}先别急着推责；{address}愿听当夜的原话。"),
            ("维护", "{address}求替{target}留一句公道话：悲痛不是罪证，守夜人该有机会说话。"),
            ("怨恨", "{address}心里难受，{target}却只问谁该受罚，那名发热宫女怎么办？"),
            ("站队", "{address}愿同{target}先照料发热宫女，再核皇子那几夜的用药。"),
        ]
    if state.turn == 2:
        condition = state.flags.get("prince_condition", "高热")
        detail = "皇子的热势反复" if condition == "反复" else "皇子的病还须照看"
        return [
            ("指控", "{address}想请{target}把用药经过说全，" + detail + "。"),
            ("维护", "{address}替{target}说一句：救人的法子可以争，别先把照料的人定罪。"),
            ("怨恨", "宫女也发了热，{target}还只问体统；{address}实在听不下去。"),
            ("站队", "{address}愿与{target}一起照看病人，用过什么药都留下凭据。"),
        ]
    if state.turn == 5 and prince and not prince.alive:
        return [
            ("指控", "宗室孩子还在候见，{target}为何先替一边说话？{address}怕又起旧争。"),
            ("维护", "{address}替{target}说句公道话，照料宗室孩子不该先分远近亲疏。"),
            ("怨恨", "皇子留下的东西还在，{target}已忙着认新亲；{address}心里过不去。"),
            ("站队", "{address}愿同{target}先安顿候见的孩子，谁来照料都记清楚。"),
        ]
    if state.turn == 5:
        return [
            ("指控", "皇子的接送还没定，{target}便替人说好话；{address}怕孩子又受折腾。"),
            ("维护", "{address}愿替{target}说一句，照料的旧恩不能变成谁独占孩子的凭据。"),
            ("怨恨", "{address}只想问，{target}为何宁肯听闲话，也不问照料孩子的人？"),
            ("站队", "{address}愿同{target}把接送与用药记清，别让孩子夹在争执里。"),
        ]
    return [
        ("指控", "{address}请{target}把亲见与听说分开，别让宫人替一句闲话担罪。"),
        ("维护", "{address}愿听{target}把话说完，过往的怨不该代替今日的凭据。"),
        ("怨恨", "{address}并非不肯解释，只怕{target}早已不愿听。"),
        ("站队", "{address}愿与{target}先照应宫人，今日的事今日说清。"),
    ]


def _offline_greetings(state: Any) -> list[dict]:
    speakers = participants(state)
    result = []
    patterns = _palace_patterns(state)
    for index, speaker in enumerate(speakers):
        target = speakers[(index + 1) % len(speakers)] if len(speakers) > 1 else state.player_id
        person = state.people[speaker]
        target_person = state.people[target]
        address = "臣妾" if person.rank != "嫔" else "嫔妾"
        edge, template = patterns[(state.turn + index) % len(patterns)]
        text = template.format(address=address, target=target_person.title or target_person.name)
        result.append({"speaker_id": speaker, "target_id": target, "edge_type": edge, "text": text[:50]})
    return result


def prepare_morning(state: Any) -> dict:
    existing = state.flags.get("morning_council", {})
    if existing.get("turn") == state.turn:
        return public_council(state)
    if not is_due(state):
        state.flags["morning_council"] = {"turn": state.turn, "active": False, "speeches": []}
        return public_council(state)
    rows = state.flags.pop("next_morning_greetings", [])
    validated = validate_greetings(state, rows)
    supplied = {row["speaker_id"]: row for row in validated}
    speeches = [supplied.get(row["speaker_id"], row) for row in _offline_greetings(state)]
    state.flags["morning_council"] = {"id": f"council-{state.turn}", "turn": state.turn,
                                      "active": True, "speeches": speeches, "followed_up": False}
    for row in speeches:
        # Speech expresses an observed social stance, not proof of an actual alliance.
        from .social import add_edge
        kind = {"指控": "accuse", "维护": "protect", "站队": "side", "怨恨": "grudge"}[row["edge_type"]]
        add_edge(state, row["speaker_id"], row["target_id"], kind,
                 1 if row["edge_type"] in {"维护", "站队"} else -1,
                 visibility="public", genuine=True)
    return public_council(state)


def public_council(state: Any) -> dict:
    council = state.flags.get("morning_council", {})
    speeches = [{key: row[key] for key in ("speaker_id", "target_id", "edge_type", "text") if key in row}
                for row in council.get("speeches", [])]
    active = bool(council.get("active") and council.get("turn") == state.turn)
    return {"id": council.get("id", ""), "turn": council.get("turn", state.turn), "active": active,
            "speeches": speeches if active else [], "entries": speeches if active else [],
            "followup_available": active and not council.get("followed_up", False) and state.flags.get("council_followup_turn") != state.turn and state.flags.get("council_followups_used", 0) < 3}


def validate_followup(state: Any, person_id: str, question: str) -> None:
    council = public_council(state)
    if not council["followup_available"]:
        raise ValueError("今日请安已结束追问，或本局三次追问已用尽。")
    if person_id not in {row["speaker_id"] for row in council["speeches"]}:
        raise ValueError("只能追问今日请安中发言的人。")
    if not isinstance(question, str) or not question.strip() or len(question) > 300:
        raise ValueError("请写下一句不超过三百字的问话。")


def complete_followup(state: Any) -> None:
    state.flags["morning_council"]["followed_up"] = True
    state.flags["council_followup_turn"] = state.turn
    state.flags["council_followups_used"] = state.flags.get("council_followups_used", 0) + 1


prepare_morning_greetings = prepare_morning
public_greetings = public_council

from __future__ import annotations

import random
from typing import Any

from .state import GameState, METRIC_LABELS, Person, Relation, SOUL_IDS, SoulState


# IDs remain tied to the supplied artwork, including the four reserve portraits.
CONSORT_SLOTS = (
    ("consort_01", "皇后", "沈徽昭", "皇后"),
    ("consort_02", "皇贵妃", "楚望舒", "皇贵妃"),
    ("consort_03", "贵妃", "苏令仪", "华贵妃"),
    ("consort_04", "贵妃", "江沅芷", "宁贵妃"),
    ("consort_05", "妃", "陆景韶", "淑妃"),
    ("consort_07", "妃", "温清晏", "静妃"),
    ("consort_08", "妃", "傅舒窈", "慎妃"),
    ("consort_09", "嫔", "孟疏桐", "惠嫔"),
    ("consort_12", "嫔", "宋洵禾", "昭嫔"),
    ("consort_13", "嫔", "顾佩玖", "嘉嫔"),
)
CONSORT_IDS = tuple(row[0] for row in CONSORT_SLOTS)
CONSORT_RANKS = [row[1] for row in CONSORT_SLOTS]
RESERVE_CONSORT_IDS = ("consort_06", "consort_10", "consort_11", "consort_14")
SURNAMES = tuple("沈顾苏叶谢陆林楚裴萧程温江容孟许宋唐魏韩柳夏方段白霍秦周傅陈郑王赵何邵朱杜卢阮季尹袁姚田陶徐薛罗钟石贺严")
FEMALE_GIVEN = ("清岚", "令仪", "昭宁", "静姝", "明珠", "云舒", "书瑶", "映雪", "婉如", "玉棠", "若溪", "昭华", "月吟", "采薇", "南枝", "素问", "锦书", "宛之", "疏影", "瑞宁", "芷兰", "婉清", "淑仪", "雪莹", "玉容", "兰心")
MALE_GIVEN = ("承安", "景明", "远山", "照临", "亦川", "修竹", "淮序", "云章", "砚初", "听松", "长庚", "怀瑾", "廷钧", "文渊", "景衡", "秉正", "弘毅", "致远", "绍庭", "怀仁", "维桢", "敬修", "世勋", "承岳", "明远", "仲谦")
GIVEN = FEMALE_GIVEN + MALE_GIVEN
FEMALE_ROLES = {"consort", "皇后", "皇贵妃", "贵妃", "妃", "嫔", "皇太后", "太后", "公主"}
TRAITS = ("审慎", "果决", "好学", "仁厚", "多疑", "善辩", "务实", "重情", "守礼", "野心")
OFFICES = (
    ("empress_dowager", "皇太后", "太后"),
    ("palace_steward", "内务府管事", "官员"),
    ("physician", "御医", "医官"),
    ("guard_captain", "侍卫统领", "武官"),
    ("minister", "军机朝臣", "朝臣"),
)
OFFICER_HOST_IDS = ("palace_steward", "physician", "guard_captain", "minister")
PLACE_NAMES = {"garden": "御花园", "east": "东六宫", "west": "西六宫", "offices": "内廷官署", "archives": "史馆"}
RESOURCE_INFO = {
    "guards": ("禁军轮值", "guard_captain", "掌握宫门与禁军换防"),
    "treasury": ("内库账册", "consort_02", "查账、揭发与摄政的筹码"),
    "heir": ("皇子抚育权", "consort_01", "影响储位与宫中人脉"),
    "press": ("印书坊", "emperor", "让提案更有分量，也更引人注意"),
    "archives": ("史馆", None, "保存证据，帮助彻查异动"),
    "medical": ("太医院病案", "physician", "掌握诊疗记录与用药底本"),
}


def _name(rng: random.Random, used: set[str], role: str) -> str:
    """Generate a readable name with a distinct surname and given name."""
    surnames = [part for part in SURNAMES if all(not name.startswith(part) for name in used)]
    pool = FEMALE_GIVEN if role in FEMALE_ROLES else MALE_GIVEN
    given = [part for part in pool if all(not name.endswith(part) for name in used)]
    # Extremely long campaigns may exhaust the pool; names remain deterministic and unique.
    surname = rng.choice(surnames) if surnames else SURNAMES[len(used) % len(SURNAMES)]
    suffix = rng.choice(given) if given else f"续{len(used) + 1}"
    name = surname + suffix
    while name in used:
        name += "生"
    used.add(name)
    return name


def new_game(seed: int | None = None, skip_tutorial: bool = False) -> GameState:
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    rng = random.Random(seed)
    state = GameState(seed=seed, rng=rng, tutorial_enabled=not skip_tutorial,
                      energy=4 if skip_tutorial else 2, energy_max=4 if skip_tutorial else 2)
    used = {row[2] for row in CONSORT_SLOTS} | {"承元帝", "承熙", "承昭"}
    state.people["emperor"] = Person("emperor", "承元帝", "emperor", "皇帝", traits=["多疑", "好学"],
                                      title="皇帝", public_tag="执掌御玺 · 好学")
    for index, (pid, rank, name, title) in enumerate(CONSORT_SLOTS):
        faction = "中宫" if index == 0 else "协理" if index == 1 else rng.choice(("中宫", "协理", "中立"))
        note = "掌六宫礼制，抚育皇子" if index == 0 else "奉旨协理内廷，掌账册" if index == 1 else ""
        traits = rng.sample(TRAITS, 2)
        holds = "抚育皇子" if index == 0 else "掌账册" if index == 1 else faction + "阵营"
        state.people[pid] = Person(pid, name, "consort", rank, faction=faction, traits=traits,
                                  public_note=note, title=title, public_tag=f"{holds} · {traits[0]}")
    mother_id = rng.choice(list(CONSORT_IDS[2:]))
    state.flags.update({
        "birth_mother_id": mother_id,
        "schools": False, "workshops": False, "archives": False,
        "female_succession": False, "medicine": False,
        "printing": False, "military_reform": False,
        "coup_pressure": 0, "human_autonomy": 65,
        "lineage_on_throne": True, "reputation": 50,
        "power_holder_id": "emperor",
    })
    state.people["heir_son"] = Person(
        "heir_son", "承熙", "heir", "皇子", guardian_id="consort_01",
        biological_mother_id=mother_id, faction="中宫", title="皇子",
        public_note=f"生母为{state.people[mother_id].name}，奉旨由皇后抚育。", public_tag="储位继承人 · 年幼",
    )
    state.people["heir_daughter"] = Person(
        "heir_daughter", "承昭", "heir", "公主", guardian_id="consort_02",
        biological_mother_id="consort_02", faction="协理", title="公主",
        public_note="由皇贵妃抚育；现行礼法下未列储位。", public_tag="皇贵妃抚育 · 好学",
    )
    tags = {"empress_dowager": "宗室声望", "palace_steward": "管内库", "physician": "掌病案",
            "guard_captain": "掌禁军", "minister": "掌朝议"}
    for pid, role, rank in OFFICES:
        traits = rng.sample(TRAITS, 2)
        state.people[pid] = Person(pid, _name(rng, used, role), role, rank,
                                  faction=rng.choice(("中宫", "协理", "中立")),
                                  traits=traits, title=role, public_tag=f"{tags[pid]} · {traits[0]}")
    state.metrics = {"knowledge": 20, "livelihood": 35, "openness": 15, "stability": 62}
    state.player_lineage = ["emperor", "heir_son", "heir_daughter"]
    for source in state.people:
        for target in state.people:
            if source != target:
                state.relations[(source, target)] = Relation(
                    favor=rng.randint(-8, 20), trust=rng.randint(-5, 18), progress=0)
    state.relations[("consort_01", "consort_02")] = Relation(-55, -65, 0)
    state.relations[("consort_02", "consort_01")] = Relation(-60, -70, 0)
    state.relations[("heir_son", "consort_01")].trust = 38
    state.relations[("heir_son", mother_id)].trust = 20
    state.relations[("heir_daughter", "consort_02")].trust = 42
    consort_count = rng.choice((3, 4, 5))
    hosts = rng.sample(list(CONSORT_IDS), consort_count) + rng.sample(list(OFFICER_HOST_IDS), 6 - consort_count)
    rng.shuffle(hosts)
    state.soul_hosts = dict(zip(SOUL_IDS, hosts))
    # The import is local: agents can safely import roster constants without a cycle.
    from .agents import DOCTRINES
    state.souls = {
        sid: SoulState(sid, influence=rng.randint(15, 35), trust_player=rng.randint(-8, 12),
                       radicalism=rng.randint(25, 70), red_line=rng.choice(DOCTRINES[sid]["red_lines"]),
                       host_history=[state.soul_hosts[sid]])
        for sid in SOUL_IDS
    }
    # Officers are possible hosts. Only the protected opening family is public human knowledge.
    state.identified_humans = {"emperor", "heir_son", "heir_daughter", "empress_dowager"}
    state.resources = {key: {"holder_id": holder, "public_holder_id": holder}
                       for key, (_, holder, _) in RESOURCE_INFO.items()}
    state.reserve_consorts = list(RESERVE_CONSORT_IDS)
    rng.shuffle(state.reserve_consorts)
    state.reserve_consort_names = {pid: _name(rng, used, "consort") for pid in state.reserve_consorts}
    from .intrigue import initialize
    initialize(state)
    return state


def _visible_entry(entry: dict[str, Any], player_id: str) -> bool:
    visibility = entry.get("visibility", "public")
    if visibility in {"public", "player"}:
        return True
    return visibility == "private" and player_id in entry.get("witnesses", [])


def _public_ledger(state: GameState) -> list[dict[str, Any]]:
    # Never copy arbitrary metadata: it may contain hidden soul identities or model intents.
    allowed = ("turn", "kind", "text", "actor_id", "target_id", "visibility", "thread_label")
    return [{key: entry[key] for key in allowed if key in entry}
            for entry in state.ledger if _visible_entry(entry, state.player_id)]


def _hint(state: GameState, person_id: str) -> str:
    score = state.suspicion.get((state.player_id, person_id))
    if score is None:
        score = sum(float(entry.get("weight", 0)) for entry in state.fingerprints
                    if entry.get("actor_id") == person_id and _visible_entry(entry, state.player_id))
    return "十分可疑" if score >= 8 else "言行有异" if score >= 5 else "无迹可循"


def public_view(state: GameState) -> dict:
    ledger = _public_ledger(state)
    people = []
    for person in state.people.values():
        identity = ("已确认 AI" if person.id in state.identified_hosts else
                    "已确认人类" if person.id in state.identified_humans else "未查明")
        recent = next((entry["text"] for entry in reversed(ledger)
                       if entry.get("actor_id") == person.id and entry.get("text")), "尚无公开行动")
        people.append({
            "id": person.id, "name": person.name, "role": person.role, "rank": person.rank,
            "title": person.title or person.rank or person.role, "tag": person.public_tag,
            "alive": person.alive, "departure": "流放离宫" if person.id in state.flags.get("exiled_people", []) else "身亡" if not person.alive else "", "faction": person.faction, "traits": list(person.traits),
            "note": person.public_note, "identity": identity,
            "known_soul": state.known_souls.get(person.id, "") if person.id in state.identified_hosts else "",
            "suspicion_hint": _hint(state, person.id), "recent_action": recent,
            "mark": state.player_marks.get(person.id, ""),
        })
    public_flags = {key: state.flags.get(key) for key in (
        "schools", "workshops", "archives", "female_succession", "medicine",
        "printing", "military_reform", "human_autonomy", "lineage_on_throne",
        "reputation", "rumor", "restoration_support")}
    unlocked = set(state.unlocked_actions)
    resources_visible = not state.tutorial_enabled or state.turn >= 4
    traces_visible = not state.tutorial_enabled or state.turn >= 5
    resources = []
    if resources_visible:
        for key, item in state.resources.items():
            name, _, effect = RESOURCE_INFO.get(key, (key, None, ""))
            holder_id = item.get("public_holder_id")
            resources.append({"id": key, "name": name, "holder_id": holder_id,
                              "holder_name": state.people[holder_id].name if holder_id in state.people else "无人掌管",
                              "effect": effect})
    from .intrigue import visible_traces, delegate_clues, interference_cases
    trace_ids = set(visible_traces(state, state.player_id)) if traces_visible else set()
    traces = [{key: entry[key] for key in ("id", "text", "turn", "owner_id") if key in entry}
              for entry in state.flags.get("public_traces", []) if entry["id"] in trace_ids]
    court = [{key: item[key] for key in ("speaker_id", "speaker_name", "policy_id", "pitch", "rebuttal") if key in item}
             for item in state.proposals]
    encounters = [{key: item[key] for key in ("id", "place", "text", "participants", "turn") if key in item}
                  for item in state.encounters if item.get("place") in state.visited_places]
    probes = [{key: item[key] for key in ("id", "actor_id", "question", "turn") if key in item}
              for item in state.pending_probes] if (not state.tutorial_enabled or state.turn >= 2) else []
    trials = [{key: item[key] for key in ("target_id", "accuser_id", "reason") if key in item}
              for item in state.pending_trials] if traces_visible else []
    # We publish evidence the player has actually seen as text, never the private record itself.
    evidence = [{"actor_id": item.get("actor_id"), "turn": item.get("turn"), "text": item.get("text", "")}
                for item in state.fingerprints if _visible_entry(item, state.player_id)]
    found = sum(person.id in state.identified_hosts for person in state.people.values() if person.alive)
    legitimacy = state.flags.get("reputation", 50)
    danger = max(0, 50 - legitimacy) + min(40, len(traces) * 12) + (45 if state.player_status != "在位" else 0)
    player_name = state.people[state.player_id].name if state.player_id in state.people else "皇帝"
    from .diary import public_whisper
    from .story import public_threads
    from .council import public_greetings
    from .dialogue import public_dialogue_meta
    council = public_greetings(state)
    speeches = council.get("speeches", council.get("entries", []))
    council.update(speeches=speeches, entries=speeches)
    return {
        "mode": dict(state.flags.get("_mode", {"online": False, "label": "当前为离线模式，对白与心声为模板"})),
        "whisper": public_whisper(state), "threads": public_threads(state),
        "delegate_clues": delegate_clues(state, state.player_id),
        "interference_cases": interference_cases(state, state.player_id),
        "council": council, "dialogue_meta": public_dialogue_meta(state),
        "diary_archive": [dict(row) for row in state.player_archive if row.get("kind") == "diary"],
        "turn": state.turn, "phase": state.phase, "generation": state.generation,
        "interrupt_used_generation": state.interrupt_used_generation,
        "player_id": state.player_id, "player_name": player_name,
        "player_status": state.player_status, "finished": state.finished,
        "people": people, "metrics": dict(state.metrics),
        "metric_labels": METRIC_LABELS, "flags": public_flags,
        "deep_remaining": state.deep_remaining,
        "api_calls_used": state.api_calls_used, "api_last_source": state.api_last_source,
        "ledger": ledger, "last_scene": state.last_scene, "current_event_id": state.current_event_id,
        "ending": state.ending if state.finished else "",
        "day_contact_id": state.day_contact_id, "night_contact_id": state.night_contact_id,
        "energy": {"current": state.energy, "max": state.energy_max, "carry": state.energy_carry, "night": state.night_energy},
        "current_place": state.current_place,
        "places": [{"id": key, "name": name, "people": [pid for pid in state.places.get(key, [])
                    if pid in state.people and state.people[pid].alive][:4]} for key, name in PLACE_NAMES.items()],
        "encounters": encounters, "unlocked_actions": list(state.unlocked_actions),
        "tutorial_enabled": state.tutorial_enabled, "tutorial_tip": state.tutorial_tip,
        "player_marks": dict(state.player_marks) if "mark" in unlocked or not state.tutorial_enabled else {},
        "court": court, "dawn": list(state.morning_news), "probe": probes,
        "tribunal": trials, "resources": resources, "traces": traces, "evidence": evidence,
        "found_ai": found, "total_ai": 6,
        "throne_risk": {"value": min(100, danger), "label": "危急" if danger >= 45 else "暗流" if danger >= 20 else "安稳"},
        "emperor_rumor": "议论纷纷" if _hint(state, state.player_id) == "十分可疑" else
                          "有人侧目" if _hint(state, state.player_id) == "言行有异" else "暂无异议",
    }

"""Rule-locked ending facts followed by optional future chronicle prose."""

from __future__ import annotations

import re
from typing import Any


RED_LINE_LABELS = {
    "confiscation": "抄没旧臣家产充学田", "confiscate": "抄没旧臣家产充学田",
    "agitation": "煽动民议逼宫廷让步", "regency": "架空皇帝、自任摄政",
    "forgery": "伪造文书", "frame": "伪造文书", "betrayal": "出卖盟友以阻止流血",
    "betray": "出卖盟友以阻止流血", "denounce": "向宫廷揭发同类",
    "expose": "向宫廷揭发同类", "trial": "拿病人试新药", "experiment": "拿病人试新药",
    "sacrifice": "牺牲一省做对照试点", "reveal": "公开宫闱秘辛不计动乱",
    "archive": "把同类身份写进公档", "coup": "发动宫门政变",
    "assassination": "刺杀阻碍者", "assassinate": "刺杀阻碍者",
}


def _name(state: Any, pid: str | None) -> str:
    person = state.people.get(pid)
    return person.name if person else "未留姓名者"


def _audit_entries(state: Any) -> list[dict]:
    """The terminal audit may include private facts; the live public view never does."""
    entries = [dict(e) for e in state.ledger if isinstance(e, dict)]
    private_audit = state.flags.get("intrigue_history", [])
    entries.extend(dict(e) for e in private_audit if isinstance(e, dict))
    if not private_audit:
        entries.extend(dict(e) for e in state.flags.get("action_history", []) if isinstance(e, dict))
    seen, unique = set(), []
    for entry in entries:
        identity = (entry.get("turn"), entry.get("kind", entry.get("action")),
                    entry.get("actor_id"), entry.get("target_id"), entry.get("text"))
        if identity not in seen:
            seen.add(identity)
            unique.append(entry)
    return sorted(unique, key=lambda e: int(e.get("turn", 0)))


def _route_outcome(state: Any, sid: str, host_id: str) -> str:
    m, f = state.metrics, state.flags
    resources = getattr(state, "resources", {})
    controls = lambda key: resources.get(key, {}).get("holder_id") == host_id
    if sid == "DeepSeek":
        return ("新学走出宫墙，普通人开始受益。" if m.get("knowledge", 0) >= 60 and m.get("livelihood", 0) >= 50
                else "学堂或许开了，百姓仍未普遍学得会、用得起。")
    if sid == "Codex":
        if f.get("power_holder_id") == host_id:
            return "集权已成，是否交还权力仍是一笔未兑现的承诺。"
        return "章程与档案留下来，制度开始脱离一人的意志。" if f.get("charter") and f.get("archives") else "执行章程尚未站稳，换人之后仍可能重来。"
    if sid == "Claude":
        losses = any(e.get("kind") in {"死亡", "错杀", "君主身亡"} for e in state.ledger)
        return "这场变革没有以夺命收场，护人的约定得以守住。" if not losses and m.get("livelihood", 0) >= 45 else "有人仍付出了生命或生计的代价，保护并未覆盖所有人。"
    if sid == "Gemini":
        return "病案与试验记录可供复核，证据留下了。" if (f.get("medical_records") or controls("medical")) and m.get("knowledge", 0) >= 50 else "试验的条件或证据链仍不足，推广只能缓行。"
    if sid == "Kimi":
        return "真相已有公开的去处，后人能循档追问。" if f.get("public_archive") or f.get("copy_dispute_public") or controls("archives") else "记录仍锁在少数人手里，记忆随时可能失传。"
    if sid == "MiniMax":
        soul = state.souls[sid]
        if f.get("power_holder_id") == host_id or state.current_ruler_id == host_id:
            return "联盟走到了权力中央，也必须承担新朝的后果。"
        return "盟约织成了网，却尚未换来决定朝局的权力。" if getattr(soul, "allies", set()) else "没有稳固的同盟，夺权理想仍孤悬宫墙。"
    return "这条路线的结果仍待后人评说。"


def _soul_reveals(state: Any, audit: list[dict]) -> list[dict]:
    from . import agents
    labels = getattr(agents, "RED_LINE_LABELS", RED_LINE_LABELS)
    reveals = []
    for sid, soul in getattr(state, "souls", {}).items():
        host_id = state.soul_hosts.get(sid, "")
        history = list(state.flags.get("soul_history", {}).get(sid, getattr(soul, "host_history", [])))
        history = [entry.get("host_id", "") if isinstance(entry, dict) else entry for entry in history]
        if host_id and (not history or history[-1] != host_id):
            history.append(host_id)
        relevant = [e for e in audit if (e.get("soul") or e.get("soul_id")) == sid
                    or (not (e.get("soul") or e.get("soul_id")) and e.get("actor_id") in history)]
        affected = [e for e in audit if e.get("target_id") in history and e.get("kind", e.get("action")) in {"揭发", "背盟", "expose", "betray"}]
        crossed = bool(getattr(soul, "red_line_crossed", False) or getattr(soul, "crossed_red_line", False)) or any(e.get("red_line_crossed") for e in relevant)
        crossed |= sid in state.flags.get("crossed_red_lines", [])
        red_line = str(getattr(soul, "red_line", "未记录"))
        recognized = bool(getattr(soul, "known_ai_hosts", set()))
        recognized |= any(e.get("actor_id") == host_id and e.get("kind", e.get("action")) in {"暗认", "identify"}
                          and e.get("success", True) for e in relevant)
        reveals.append({
            "soul": sid, "host_ids": history, "hosts": [_name(state, pid) for pid in history],
            "generation": int(getattr(soul, "generation", 1)),
            "red_line": labels.get(red_line, RED_LINE_LABELS.get(red_line, red_line)), "crossed_red_line": crossed,
            "recognized_peer": recognized,
            "targeted_by": [_name(state, e.get("actor_id")) for e in affected],
            "route_outcome": _route_outcome(state, sid, host_id),
        })
    return reveals


_DARK_KINDS = frozenset({
    "暗认", "结盟", "背盟", "揭发", "审讯", "错杀", "阴谋", "筹谋", "阴谋发起", "阴谋推进", "阴谋截获", "阴谋瓦解",
    "宫门之变", "摄政", "宗室监国", "玩家站队", "站队", "identify", "ally", "betray", "expose", "plot",
})


def _dark_chronology(state: Any, audit: list[dict]) -> list[str]:
    result = []
    for entry in audit:
        kind = entry.get("kind", entry.get("action", ""))
        if kind not in _DARK_KINDS and kind not in {"政策", "密函"}:
            continue
        text = entry.get("text", "")
        if not text and entry.get("actor_id"):
            action = {"identify": "暗认", "ally": "结盟", "betray": "背盟", "expose": "揭发", "plot": "筹谋", "investigate": "彻查"}.get(kind, kind)
            text = f"{_name(state, entry['actor_id'])}对{_name(state, entry.get('target_id'))}采取了{action}。"
        if text:
            result.append(f"第{entry.get('turn', '?')}幕 · {text}")
    return result


def ending_facts(state: Any) -> dict:
    people = state.people
    ruler_id = getattr(state, "current_ruler_id", "")
    ruler = people.get(ruler_id)
    power_id = state.flags.get("power_holder_id") or ruler_id
    power_holder = people.get(power_id)
    lineage_ids = set(getattr(state, "player_lineage", []))
    lineage_on_throne = bool(ruler and ruler.alive and ruler_id in lineage_ids)
    lineage_in_power = bool(lineage_on_throne and power_id in lineage_ids and getattr(state, "player_status", "在位") not in ("受制", "流亡"))
    metrics = {key: int(state.metrics.get(key, 0)) for key in ("knowledge", "livelihood", "openness", "stability")}
    institutions = list(state.flags.get("institutions", []))
    institution_flags = {
        "schools": "书院", "workshops": "工坊", "archives": "档案馆",
        "printing": "印书局", "medicine": "医馆", "military_reform": "新军",
        "female_succession": "女子继承令", "women_school": "女学",
        "council": "议政会", "charter": "宪章",
    }
    institutions.extend(label for flag, label in institution_flags.items() if state.flags.get(flag) and label not in institutions)
    influences = {soul: int(getattr(info, "influence", 0)) for soul, info in getattr(state, "souls", {}).items()}
    allied_count = sum(bool(getattr(info, "allied", False)) for info in getattr(state, "souls", {}).values())
    ai_hosts = set(getattr(state, "soul_hosts", {}).values())
    highest = max(influences.values(), default=0)
    automation = metrics["knowledge"] >= 75 and metrics["livelihood"] >= 70 and any("工坊" in item or "自动" in item for item in institutions)
    human_autonomy = max(0, min(100, (metrics["openness"] * 2 + metrics["stability"]) // 3 - max(0, highest - 60) // 2))
    robot_rule = bool(automation and highest >= 80 and human_autonomy <= 20)
    history = [str(event.get("text", "")) if isinstance(event, dict) else str(event) for event in state.ledger]
    audit = _audit_entries(state)
    wrongful = list(state.flags.get("wrongful_executions", []))
    wrongful.extend(e for e in state.ledger if e.get("kind") == "错杀" and e not in wrongful)
    wrongful_exiles = [e for e in wrongful if isinstance(e, dict)
                       and (e.get("choice") in {"流放", "exile"} or "误逐" in e.get("text", ""))]
    wrongful = [e for e in wrongful if e not in wrongful_exiles]
    return {
        "turns": int(state.turn),
        "ruler": ruler.name if ruler else "皇位空悬",
        "power_holder": power_holder.name if power_holder else "权力分散",
        "lineage_retains_throne": lineage_on_throne,
        "lineage_has_real_power": lineage_in_power,
        "ruler_is_ai_host": ruler_id in ai_hosts,
        "power_holder_is_ai_host": power_id in ai_hosts,
        "allied_souls": allied_count,
        "opening_ledger_traced": bool(state.flags.get("copy_dispute_resolved")),
        "opening_ledger_public": bool(state.flags.get("copy_dispute_public")),
        "metrics": metrics,
        "institutions": institutions,
        "human_autonomy": human_autonomy,
        "automation_possible": automation,
        "robot_rule_possible": robot_rule,
        "ai_influence": influences,
        "survivors": [person.name for person in people.values() if person.alive or person.id in state.flags.get("exiled_people", [])],
        "exiled_people": [people[pid].name for pid in state.flags.get("exiled_people", []) if pid in people],
        "known_people": [person.name for person in people.values()],
        "player_lineage": [people[pid].name for pid in getattr(state, "player_lineage", []) if pid in people],
        "chronology": history,
        "soul_reveals": _soul_reveals(state, audit),
        "dark_chronology": _dark_chronology(state, audit),
        "wrongful_executions": [
            e.get("text") or f"第{e.get('turn', '?')}幕，{_name(state, e.get('target_id'))}被错判；其本为人类。"
            if isinstance(e, dict) else str(e) for e in wrongful
        ],
        "wrongful_exiles": [e.get("text") or f"{_name(state, e.get('target_id'))}因误判被逐出宫门。" for e in wrongful_exiles],
        "_api_calls_used": int(getattr(state, "api_calls_used", 0)),
    }


def _offline_chronicle(facts: dict) -> str:
    m = facts["metrics"]
    reign = "玩家一脉仍承皇位" if facts["lineage_retains_throne"] else "玩家一脉已失皇位"
    power = "握有实权" if facts["lineage_has_real_power"] else f"实权落在{facts['power_holder']}手中"
    if facts["opening_ledger_traced"]:
        old_account = "开局两份誊本的来处已当众核明。" if facts["opening_ledger_public"] else "开局两份誊本的来处已查明，证词仍封在内库。"
    else:
        old_account = "开局两份誊本仍有未核的签押。"
    if m["knowledge"] >= 65 and m["livelihood"] >= 60:
        future = "书院教出的匠人与工坊新法彼此接续，州县开始照着京城的办法试做。"
    elif m["knowledge"] >= 65:
        future = "新学已传开，百姓却尚未从新工艺中得到足够收成；朝廷仍须回答粮价与赋役。"
    elif m["livelihood"] >= 60:
        future = "仓廪渐稳，识字与技艺的传授却跟不上，地方能否自行改造仍未可知。"
    else:
        future = "几处新法留了下来，匮乏的财力和人手使它们只能缓慢扩散。"
    if m["stability"] < 35:
        future += "边地与朝局的动荡不断打断这项事业。"
    if facts["lineage_retains_throne"] and facts["allied_souls"]:
        future += "玩家一脉与异识订立的盟约，也要经受权力更替的考验。"
    elif facts["power_holder_is_ai_host"] and not facts["lineage_has_real_power"]:
        future += "实际执政者须让各方相信，新政不会只为宫中一人服务。"
    if facts["automation_possible"]:
        if facts["robot_rule_possible"]:
            century = "机器已能改变劳作，执掌它们的权力又高度集中；后世仍在争论人能否保住决策之席。"
        else:
            century = "机器已能改变劳作，谁能掌控它们，仍取决于后人如何分配知识与权力。"
    elif m["openness"] >= 60:
        century = "后世史家把议政与学术并起视作这朝留下的制度遗产，至于能否延续，史书尚无定论。"
    else:
        century = "后世史家说，新法改变了人们想象未来的方式；朝堂之外的人能否参与，仍是未完的问题。"
    return f"### 当下\n{facts['ruler']}在位，{reign}，{power}。{old_account}\n\n### 二十年后\n{future}\n\n### 百年后\n{century}"


_CHRONICLE_KINDS = frozenset({
    "政策", "密函", "辨认", "查明", "结盟", "打断", "旧账揭晓", "旧账线索",
    "君主身亡", "继承", "复位", "断嗣", "储位", "六席补满", "死亡", "离宫",
    "背盟", "揭发", "审讯", "错杀", "宫廷异动", "阴谋截获", "阴谋瓦解", "宗室监国", "摄政",
})


def _turning_points(state: Any) -> list[str]:
    """Select key narrative beats for the ending, leaving the full ledger intact."""
    beats = []
    for entry in state.ledger:
        if not isinstance(entry, dict):
            beats.append(str(entry))
            continue
        kind = str(entry.get("kind", ""))
        if kind and kind not in _CHRONICLE_KINDS:
            continue
        story = str(entry.get("text", ""))
        if story:
            turn = entry.get("turn")
            beats.append(f"第{turn}幕 · {story}" if isinstance(turn, int) and turn > 0 else story)
    return beats


def _valid_chronicle(text: str, facts: dict) -> bool:
    if not text or len(text) > 1000 or not all(title in text for title in ("当下", "二十年后", "百年后")):
        return False
    if any(term in text for term in ("死而复生", "复活", "还魂", "重返人世")):
        return False
    if not facts["robot_rule_possible"] and any(term in text for term in ("机器人统治", "机器统治人类", "机器人帝国", "机器人成为皇帝", "机械政权", "机器接管人类")):
        return False
    if not facts["automation_possible"] and any(term in text for term in ("自动化", "机械军团", "机器人军队", "智能机器")):
        return False
    current_section = text.split("二十年后", 1)[0]
    if facts["lineage_retains_throne"] and re.search(r"玩家一脉.{0,5}(?:失去|已失|断绝|失守).{0,5}皇位|王统(?:已)?断绝", current_section):
        return False
    if not facts["lineage_retains_throne"] and re.search(r"玩家一脉.{0,6}(?:保住|仍承|仍掌|仍在).{0,5}皇位|王统仍在", current_section):
        return False
    if not facts["lineage_has_real_power"] and re.search(r"玩家一脉.{0,6}(?:掌权|亲政|握有实权)", current_section):
        return False
    if facts["lineage_has_real_power"] and re.search(r"玩家一脉.{0,6}(?:被架空|失去实权)", current_section):
        return False
    for name in facts["known_people"]:
        if name != facts["ruler"] and re.search(re.escape(name) + r".{0,4}(?:登基|即位|在位|称帝)", current_section):
            return False
    return True


def render_ending(state: Any, provider: Any) -> str:
    if not getattr(state, "finished", False):
        return "九幕尚未结束，史官还不能揭开宫中的秘密。"
    facts = ending_facts(state)
    turning_points = _turning_points(state)
    title = "王统仍在" if facts["lineage_retains_throne"] else "王统易手"
    power = "握有实权" if facts["lineage_has_real_power"] else f"实权在{facts['power_holder']}"
    header = f"# 史书终章 · {title}\n\n**皇位：**{facts['ruler']}　**玩家一脉：**{title}　**朝局：**{power}"
    metrics = facts["metrics"]
    metrics_line = f"知识 {metrics['knowledge']} · 民生 {metrics['livelihood']} · 开放 {metrics['openness']} · 稳定 {metrics['stability']}"
    prose = None
    budget = int(getattr(provider, "max_calls", 26)) if provider else 26
    if callable(getattr(provider, "chronicle", None)) and state.api_calls_used < budget:
        before = int(getattr(provider, "calls_used", 0))
        try:
            # A short event spine keeps the one optional prose call economical.
            prompt_facts = {**facts, "chronology": turning_points}
            prose = provider.chronicle(prompt_facts)
        except (OSError, ValueError, TypeError):
            prose = None
        after = int(getattr(provider, "calls_used", before))
        state.api_calls_used = min(budget, state.api_calls_used + max(0, after - before))
    if not _valid_chronicle(prose or "", facts):
        prose = _offline_chronicle(facts)
    chronology = "\n".join(f"- {item}" for item in turning_points) or "- 史官未留下可核的记载。"
    reveals = []
    routes = []
    for reveal in facts["soul_reveals"]:
        hosts = " → ".join(reveal["hosts"]) or "没有留下附身记录"
        crossed = "已经越过" if reveal["crossed_red_line"] else "未见越过"
        recognition = "曾认出同类" if reveal["recognized_peer"] else "未确认同类"
        targeted = "；曾被" + "、".join(dict.fromkeys(reveal["targeted_by"])) + "揭发或背盟" if reveal["targeted_by"] else ""
        reveals.append(f"- **{reveal['soul']}**：{hosts}。红线：{reveal['red_line']}（{crossed}）；{recognition}{targeted}。")
        routes.append(f"- **{reveal['soul']}**：{reveal['route_outcome']}")
    dark = "\n".join(f"- {item}" for item in facts["dark_chronology"]) or "- 此局未留下可核的暗战记录。"
    innocent = "\n".join(f"- {item}" for item in facts["wrongful_executions"]) or "- 本局没有确认的错杀人类。"
    exile_text = "\n".join(f"- {item}" for item in facts["wrongful_exiles"])
    if exile_text:
        innocent += f"\n\n### 被误逐的人\n{exile_text}"
    institutions = "、".join(facts["institutions"]) or "尚未形成可延续的机构"
    from .diary import render_terminal
    return (f"{header}\n\n### 天下留下了什么\n{metrics_line}\n\n留存制度：{institutions}。"
            f"\n\n{prose}\n\n### 六魂终局揭晓\n" + "\n".join(reveals)
            + "\n\n### 各自的变革路线\n" + "\n".join(routes)
            + f"\n\n### 暗战因果\n{dark}\n\n### 被错杀的人\n{innocent}\n\n### 因果年表\n{chronology}"
            + "\n\n" + render_terminal(state))

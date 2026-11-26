"""Rule-owned fictional plans, trust gates and anonymous overheard dialogue.

These are authored character plans, never model-internal chain of thought.
Only public_report / public_whisper may cross the browser boundary.
"""
from __future__ import annotations

import copy
import re
from typing import Any
from .state import add_ledger
from .roster import PLACE_NAMES, RESOURCE_INFO

DESCRIPTION = "这是她做决定时写下的盘算，由模型生成并经规则校验。"
OFFLINE_DESCRIPTION = "这是角色盘算的规则模板；未获得通过校验的模型盘算。"
_ACTIONS = {"talk": "先听一听旁人的口风", "probe": "探一探话里的破绽", "ally": "争取一个能相互照应的人", "protect": "替人留下余地", "expose": "把疑点摆到众人面前", "betray": "重新衡量盟约", "seize": "握住办事的凭据", "plot": "为下一步留好退路", "lobby": "争取办事的人", "recruit_delegate": "让可信的人替我说话", "investigate": "核实传言", "spy": "留意暗处的动静"}


def tier(soul: Any) -> int:
    return 3 if soul.allied or soul.trust_player >= 50 else 2 if soul.trust_player >= 30 else 1 if soul.trust_player >= 15 else 0


def refresh_access(state: Any, soul_id: str) -> None:
    soul = state.souls[soul_id]
    level = tier(soul)
    for page in soul.diary:
        page["unlocked_tier"] = max(page.get("unlocked_tier", 0), level)
        if soul.allied:
            page["decision_opened"] = True


def record_night(state: Any, soul_id: str, plan: dict | None = None, actions: list | None = None, **kwargs: Any) -> None:
    """Record once, after rules have settled the character's actual actions."""
    soul = state.souls[soul_id]
    host = state.soul_hosts[soul_id]
    if soul.diary and soul.diary[-1]["turn"] == state.turn and soul.diary[-1]["generation"] == soul.generation:
        refresh_access(state, soul_id)
        return
    actions = actions or kwargs.get("executed_actions") or []
    actual = []
    for action in actions:
        row = action if isinstance(action, dict) else vars(action)
        actual.append({k: row.get(k) for k in ("action", "target_id", "visibility", "result")})
    last = actual[-1] if actual else {}
    verb = _ACTIONS.get(last.get("action"), "先把局势看清")
    target = state.people.get(last.get("target_id"))
    observed = "今日御前已作裁决，宫中仍有人各持己见。"
    from .provider import _public_records
    public = _public_records(state, 1)
    if public:
        observed = public[-1][:50]
    judgement = "嘴上应承的人未必肯担风险，我还得看他们怎样做。"
    decision = verb + (f"，与{target.name}有关。" if target else "。")
    reason = (plan or {}).get("reasoning", {})
    if not isinstance(reason, dict):
        reason = {}
    # Provider owns validation; no unchecked arbitrary fields enter the page.
    source = "model" if plan and plan.get("source") == "model" else "template"
    memo = str((plan or {}).get("memo") or f"{verb}。" + (str(last.get("result") or "今夜尚未看出结果。")))[:150]
    soul.memo = memo
    against = any(a.get("target_id") == state.player_id and a.get("action") in {"probe", "plot", "expose", "betray", "frame", "spy"} for a in actual)
    # Plots may target a plot kind rather than a person; these threaten the ruler.
    against |= any(a.get("action") == "plot" and (str(a.get("target_id", "")).split(":", 1)[0] in {"coup", "regency", "heresy", "assassinate"} and (":" not in str(a.get("target_id", "")) or str(a.get("target_id", "")).split(":", 1)[1] == state.player_id)) for a in actual)
    page = {
        "turn": state.turn, "generation": soul.generation, "host_id": host,
        "observed": str(reason.get("observed") or observed)[:50],
        "judgement": str(reason.get("judgement") or judgement)[:50],
        "decision": str(reason.get("decision") or decision)[:50], "memo": memo,
        "monologue": str((plan or {}).get("monologue") or f"{judgement}{verb}，总不能只凭谁的一句话。")[:80],
        "staged_monologue": str((plan or {}).get("staged_monologue") or "我只盼这阵风波快过去。旁人争的那些事，与我有什么相干？")[:80],
        "actions": actual, "source": source, "against_emperor": against,
        "action_source": "model" if (plan or {}).get("action_source") == "model" else source,
        "fallback_reason": str((plan or {}).get("fallback_reason", "")),
        "unlocked_tier": tier(soul), "decision_opened": bool(soul.allied),
    }
    soul.diary.append(page)
    refresh_access(state, soul_id)


def public_report(state: Any, person_id: str, *, archive: bool = False) -> dict:
    sid = next((sid for sid, pid in state.soul_hosts.items() if pid == person_id), None)
    if sid is None or person_id not in state.identified_hosts or not state.people[person_id].alive:
        return {"error": "需先辨认此人，才能查阅这一世的日记。"}
    soul = state.souls[sid]
    pages = []
    for page in soul.diary:
        unlocked = page.get("unlocked_tier", 0)
        row = {k: page[k] for k in ("turn", "generation", "source")}
        row["unlocked_tier"] = unlocked
        locked = bool(page.get("against_emperor") and not (page.get("decision_opened") or soul.allied))
        row.update(decision_locked=locked, decision_requires_alliance=locked)
        if unlocked >= 1:
            row["observed"] = page["observed"]
        if unlocked >= 2:
            row["judgement"] = page["judgement"]
        if unlocked >= 3:
            if not locked:
                row["decision"] = page["decision"]
            # A memo may repeat a hostile decision; gate it with that decision.
            if not locked:
                row["memo"] = page["memo"]
        pages.append(row)
        if archive and any(k in row for k in ("observed", "judgement", "decision", "memo")):
            key = (person_id, page["generation"], page["turn"])
            entry = next((e for e in state.player_archive if (e.get("host_id"), e.get("generation"), e.get("turn")) == key and e.get("kind") == "diary"), None)
            item = {"kind": "diary", "host_id": person_id, "host_name": state.people[person_id].name, **copy.deepcopy(row)}
            item["text"] = "；".join(row[k] for k in ("observed", "judgement", "decision", "memo") if k in row)
            if entry is None:
                state.player_archive.append(item)
            else:
                entry.update(item)
    source = "model" if any(p["source"] == "model" for p in pages) else "template"
    person = state.people[person_id]
    return {"person_id": person_id, "name": person.name, "host_name": person.name, "role": person.title,
            "recognized": True, "tier": tier(soul), "current_tier": tier(soul), "source": source,
            "description": DESCRIPTION if source == "model" else OFFLINE_DESCRIPTION,
            "requirements": {"1": 15, "2": 30, "3": 50}, "pages": pages}


def reset_life(state: Any, soul_id: str) -> None:
    soul = state.souls[soul_id]
    state.flags.setdefault("_diary_history", {}).setdefault(soul_id, []).extend(copy.deepcopy(soul.diary))
    soul.diary.clear()
    soul.memo = ""


def terminal_diaries(state: Any) -> list[dict]:
    if not state.finished:
        return []
    result = []
    for sid, soul in state.souls.items():
        pages = list(state.flags.get("_diary_history", {}).get(sid, [])) + list(getattr(soul, "diary", []))
        result.append({"soul": sid, "pages": copy.deepcopy(pages)})
    return result


def render_terminal(state: Any) -> str:
    if not state.finished:
        return ""
    lines = ["### 六魂逐夜盘算", "以下为角色作决定时写下的盘算及规则结算结果；离线页来自模板。"]
    for entry in terminal_diaries(state):
        lines.append(f"#### {entry['soul']}")
        for page in entry["pages"]:
            host = state.people.get(page["host_id"])
            label = host.name if host else "旧日宿主"
            lines.append(f"**第 {page['turn']} 幕 · {label} · 第 {page['generation']} 世**")
            for key, title in (("observed", "看到"), ("judgement", "判断"), ("decision", "决定"), ("memo", "备忘")):
                lines.append(f"- {title}：{page[key]}")
            for act in page.get("actions", []):
                if act.get("result"):
                    lines.append(f"- 结果：{act['result']}")
    return "\n\n".join(lines)


def redact_whisper(state: Any, person_id: str, text: str) -> str:
    person = state.people[person_id]
    terms = {person.name, person.title, person.rank, person.role if person.role != "consort" else "妃嫔"}
    terms.update(PLACE_NAMES.values())
    terms.update(("景仁宫", "翊坤宫", "永寿宫", "慈宁宫", "寿康宫", "养心殿", "钟粹宫", "承乾宫"))
    terms.update(RESOURCE_INFO[key][0] for key, value in state.resources.items() if value.get("holder_id") == person_id and key in RESOURCE_INFO)
    for term in sorted((t for t in terms if t), key=len, reverse=True):
        text = text.replace(term, "我" if term == person.name else "那边")
    # Strip specific target and timing from plans, retaining a direction only.
    text = re.sub(r"第[一二三四五六七八九十\d]+[幕夜日天]|今晚|今夜|明晚|明夜|明日|后天|三更|子时|寅时", "日后", text)
    for other in sorted(state.people.values(), key=lambda p: len(p.name), reverse=True):
        text = text.replace(other.name, "那个人")
    titles = {p.title for p in state.people.values()} | {p.rank for p in state.people.values()}
    titles.update(("皇帝", "陛下", "太后", "皇子", "公主", "御医", "侍卫统领", "军机朝臣", "内务府管事"))
    for title in sorted((t for t in titles if t), key=len, reverse=True):
        text = text.replace(title, "那边")
    # A quoted plan must not give away its concrete victim through an office title.
    clauses = re.split(r"([。；])", text)
    for index in range(0, len(clauses), 2):
        clause = clauses[index]
        if re.search(r"杀死|刺杀|处死|退位|废黜|架空|除掉", clause):
            clauses[index] = "权柄的归属还得再看，我总要留一条退路"
        elif "那边" in clause and re.search(r"夺|揭发|试探|拉拢|结盟|逼", clause):
            clauses[index] = "办这件事，总得先分清谁肯担责"
    text = "".join(clauses)
    text = re.sub(r"DeepSeek|Codex|Claude|Gemini|Kimi|MiniMax|OpenAI|Anthropic|Google|阿里|深度求索", "异乡", text, flags=re.I)
    return text[:100]


def _human_whisper(state: Any, pid: str) -> tuple[str, str]:
    # Provider output is private; the safe projection never returns this id.
    rows = state.flags.get("_human_whispers", state.flags.get("human_whispers", []))
    if isinstance(rows, dict):
        rows = [{"speaker_id": key, "text": value} for key, value in rows.items()]
    for row in rows:
        if isinstance(row, dict) and row.get("speaker_id", row.get("person_id")) == pid:
            return str(row.get("text", row.get("monologue", "")))[:80], "model" if row.get("source") == "model" else "template"
    options = (
        "给他作保那日，我也是怕把家人牵进来。如今倒说我早有谋算，叫我往哪里辩？",
        "她替我挡过一次，我不能全忘了。可要我拿一家人的前程去还，我也得想一想。",
        "一页薄纸，比多少人的命都值钱。我若再做老好人，只怕连退路都没有了。",
        "我不过是想让孩子安稳长大，他们却一开口就要我选一边。",
        "有人争名，有人争利，我争的不过是不再任人摆布。",
        "当面答应容易，真到了担责的时候，谁还记得今日的好话？",
    )
    return state.rng.choice(options), "template"


def eavesdrop(state: Any) -> str:
    from .intrigue import add_fingerprint, recompute_suspicion, suspicion_score
    place = state.current_place
    usage = state.flags.setdefault("_eavesdrop_usage", {})
    if usage.get("turn") != state.turn:
        usage.clear()
        usage.update(turn=state.turn, places=[], speakers=[])
    if place in usage["places"]:
        raise ValueError("今日已在此处偷听，换个地方再寻线索。")
    people = [pid for pid in state.places.get(place, []) if pid not in usage["speakers"] and state.people[pid].alive]
    if not people:
        raise ValueError("此处已没有新的低语，先换一个地点。")
    hosts = set(state.soul_hosts.values())
    ai = [pid for pid in people if pid in hosts]
    humans = [pid for pid in people if pid not in hosts]
    tutorial = bool(state.tutorial_enabled and state.turn == 2 and not state.flags.get("_tutorial_whisper_done"))
    if tutorial and ai:
        pid = state.rng.choice(ai)
    elif humans and (not ai or state.rng.random() < .12):
        pid = state.rng.choice(humans)
    else:
        pid = state.rng.choice(ai or people)
    usage["places"].append(place)
    usage["speakers"].append(pid)
    roll = state.rng.random()
    quality = "clear" if tutorial or roll < .4 else "fragment" if roll < .8 else "voice"
    sid = next((sid for sid, host in state.soul_hosts.items() if host == pid), None)
    staged = False
    if sid:
        soul = state.souls[sid]
        page = next((p for p in reversed(soul.diary) if p["turn"] < state.turn), None)
        suspicious = max(soul.emperor_suspicion, suspicion_score(state, pid, state.player_id)) >= 5
        watched = pid in state.flags.get("_ever_spied", [])
        staged = bool((suspicious or watched) and state.rng.random() < .3)
        text = (page or {}).get("staged_monologue" if staged else "monologue") or ("我只求安稳，别的都不想沾。" if staged else "这里的话处处留着半句。我得看清谁肯担责，再决定要不要把法子交出去。")
        source = (page or {}).get("source", "template")
    else:
        text, source = _human_whisper(state, pid)
    text = redact_whisper(state, pid, text)
    emotion = state.rng.choice(("焦虑", "犹豫", "压着得意", "戒备"))
    if quality == "fragment":
        text = "……" + text[:max(5, len(text)//2)] + "……（声音忽然压低）"
    elif quality == "voice":
        text = f"只听见一阵低语，透着{emotion}，具体的话没有听清。"
    state.flags["_last_whisper"] = {"id": f"whisper-{state.turn}-{place}", "quality": quality, "text": text, "emotion": emotion, "source": source, "place_id": place}
    # Private instrumentation, not sent to players or player agents.
    state.flags.setdefault("_whisper_audit", []).append({"turn": state.turn, "speaker_id": pid, "human": not bool(sid), "staged": staged, "quality": quality})
    clues = []
    private = [f for f in state.fingerprints if f.get("actor_id") in people and f.get("visibility") == "private" and state.player_id not in f.get("witnesses", [])]
    if private:
        found = state.rng.choice(private)
        found.setdefault("witnesses", []).append(state.player_id)
        clues.append(found["text"])
    else:
        clues += [f["text"] for f in state.fingerprints if f.get("actor_id") in people and f.get("visibility") == "public"][-2:]
    if not tutorial and state.rng.random() < .3:
        state.flags["rumor"] = state.flags.get("rumor", 0) + 1
        add_fingerprint(state, state.player_id, 1, "有人发现皇帝在廊后偷听。")
        clues.append("脚步声惊动了宫人，关于你的闲话传开了。")
    if tutorial:
        state.flags["_tutorial_whisper_done"] = True
    # This clue is about a visible visitor, never identifies the anonymous voice.
    from .intrigue import discover_delegate_evidence
    for officer in people:
        if officer in state.delegates:
            evidence = discover_delegate_evidence(state, state.player_id, officer, amount=2)
            if isinstance(evidence, str) and evidence:
                clues.append(evidence)
            break
    recompute_suspicion(state)
    body = "屏风后有人低声说：" + text
    add_ledger(state, "偷听低语", body, visibility="private", witnesses=[state.player_id])
    return body + ("\n" + "；".join(clues) if clues else "")


def public_whisper(state: Any) -> dict | None:
    row = state.flags.get("_last_whisper")
    return {k: row[k] for k in ("id", "quality", "text", "emotion", "source", "place_id") if k in row} if row else None

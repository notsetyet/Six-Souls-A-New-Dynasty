"""Rule driven AI souls and the narrow model-action boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


ALLOWED_ACTIONS = frozenset({"reform", "influence", "intrigue", "protect", "investigate", "educate", "coup", "talk", "probe", "identify", "ally", "betray", "expose", "frame", "seize", "lobby", "plot", "blackmail", "archive", "recruit_delegate"})


@dataclass(frozen=True)
class AgentAction:
    action: str
    target_id: str | None
    line: str
    intent: str
    visibility: str = "public"


class Provider(Protocol):
    def decide(self, state: Any, soul_id: str, allowed_actions: set[str]) -> AgentAction | None: ...
    def answer(self, state: Any, person_id: str, question: str) -> str: ...
    def chronicle(self, facts: dict) -> str | None: ...


def validate_action(raw: dict, allowed: set[str] | frozenset[str]) -> AgentAction | None:
    """Accept narrative decisions, never direct edits to world state or endings."""
    if not isinstance(raw, dict) or not set(raw).issubset({"action", "target_id", "line", "intent", "visibility"}):
        return None
    action, target_id = raw.get("action"), raw.get("target_id")
    line, intent = raw.get("line"), raw.get("intent")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS or action not in allowed:
        return None
    if target_id is not None and (not isinstance(target_id, str) or not 0 < len(target_id) <= 64):
        return None
    if not isinstance(line, str) or not 0 < len(line.strip()) <= 140:
        return None
    if not isinstance(intent, str) or not 0 < len(intent.strip()) <= 140:
        return None
    visibility = raw.get("visibility", "public")
    if visibility not in {"public", "private"} or (visibility == "private" and action not in {"ally", "protect"}):
        return None
    return AgentAction(action, target_id, line.strip(), intent.strip(), visibility)


PERSONAS = {
    "DeepSeek": ("educate", "reform", "protect"),
    "Codex": ("reform", "investigate", "educate"),
    "Claude": ("protect", "influence", "educate"),
    "Gemini": ("investigate", "educate", "reform"),
    "Kimi": ("investigate", "influence", "educate"),
    "MiniMax": ("influence", "reform", "intrigue"),
}

PERSONA_GOALS = {
    "DeepSeek": "让普通人学得会、用得起新知识",
    "Codex": "把改革变成可核验、可交接的制度",
    "Claude": "少让人受伤，先保护会被旧制或新法牺牲的人",
    "Gemini": "并行试验，比较证据后推广可行办法",
    "Kimi": "找清档案里的前因，让下一代读得到真相",
    "MiniMax": "组织跨越宫墙的联盟，让改变得到足够支持",
}

PERSONA_VOICES = {
    "DeepSeek": ("先算算百姓为这步新法要付多少", "宫墙外的人能否学会，也得算进账里"),
    "Codex": ("做法与验收都写清，换了人也能接手", "先定谁负责、怎么核查，再谈快慢"),
    "Claude": ("若让无名者先受伤，这道旨意就失了分寸", "我愿先护住承受代价的人"),
    "Gemini": ("一份说法不够，至少要拿另一种结果比对", "不妨小范围试一次，再看能否重复"),
    "Kimi": ("这道记录从何而来，得先弄明白", "此事的前因未清，先问谁保管原始记录"),
    "MiniMax": ("一道旨意推不动，得有人愿一同承担", "先让能做事的人结成一线"),
}

LINES = {
    "educate": ("一座学堂比十道密旨活得长。", "让更多人看得懂图纸，才谈得上改朝换代。"),
    "reform": ("请把试行期限、责任和撤回办法立成章程。", "我求的是可复用的办法。"),
    "protect": ("先护住能做事的人，再争下一步。", "若眼前的人都活不下去，新法也无处安放。"),
    "investigate": ("两份档案的差异得逐字核实。", "我得知道谁掌着底本，差异又从何而来。"),
    "influence": ("一人说话轻，十人合议就不同。", "我想让决定有更多见证者。"),
    "intrigue": ("名分是门，钥匙却未必在门上。", "先动摇旧同盟，才能改变局面。"),
    "coup": ("宫门今夜只开一次。", "既然旧路已堵，我愿承担夺权代价。"),
}


def current_event_title(state: Any) -> str:
    """Short current focus; no private event or past-life memory is inferred."""
    from .events import EVENT_POOL

    event_id = getattr(state, "current_event_id", "")
    return next((event.title for event in EVENT_POOL if event.id == event_id), "")


def _alive_by_role(state: Any, roles: tuple[str, ...]) -> str | None:
    for role in roles:
        for person in state.people.values():
            if person.alive and (person.role == role or person.rank == role):
                return person.id
    return None


def _has_old_records(soul: Any, flags: dict) -> bool:
    """Current-life intentions are not memories of a previous host."""
    if flags.get("public_archive"):
        return True
    return any(
        isinstance(entry, str) and any(mark in entry for mark in
                                       ("玩家分享", "旧档", "前世档案", "从当世档案", "公档"))
        for entry in getattr(soul, "memory", [])
    )


def _legacy_rule_action(state: Any, soul_id: str) -> AgentAction:
    """Make a bounded choice from personality, host, current conditions and records."""
    if soul_id not in state.soul_hosts or soul_id not in PERSONAS:
        raise ValueError("未知或未降临的 AI")
    host = state.people[state.soul_hosts[soul_id]]
    knowledge = state.metrics.get("knowledge", 50)
    openness = state.metrics.get("openness", 50)
    stability = state.metrics.get("stability", 50)
    flags = getattr(state, "flags", {})
    favored = PERSONAS[soul_id]
    relation = getattr(state, "relations", {}).get((host.id, getattr(state, "player_id", "emperor")))
    trust_ruler = getattr(relation, "trust", 0)
    soul = getattr(state, "souls", {}).get(soul_id)
    influence = getattr(soul, "influence", 20)
    radicalism = getattr(soul, "radicalism", 40)

    reborn_without_records = getattr(soul, "generation", 1) > 1 and not _has_old_records(soul, flags)
    if reborn_without_records:
        action = "investigate"
    elif (state.turn >= 3 and host.rank in {"皇后", "皇贵妃", "贵妃"}
            and flags.get("coup_pressure", 0) >= 18
            and trust_ruler < -12 and influence + radicalism >= 85
            and getattr(soul, "trust_player", 0) < 20 and openness < 55):
        action = "coup"
    elif (soul_id == "MiniMax" and host.rank in {"皇后", "皇贵妃", "贵妃"}
            and trust_ruler < -30 and influence >= 50 and radicalism >= 55
            and stability < 50):
        action = "coup"
    elif stability < 20:
        action = "protect" if soul_id in {"DeepSeek", "Claude", "Codex"} else "intrigue"
    elif stability < 35 and host.rank in {"皇后", "皇贵妃", "贵妃"} and soul_id == "MiniMax":
        action = "coup"
    elif knowledge < 45 and soul_id in {"DeepSeek", "Gemini"}:
        action = "educate"
    elif soul_id == "Kimi" and not flags.get("archives"):
        action = "investigate"
    elif openness < 25 and soul_id in {"Gemini", "Kimi"}:
        action = "investigate"
    elif knowledge < 55 and soul_id == "Codex":
        action = "reform"
    else:
        action = favored[(state.turn - 1) % len(favored)]

    if action in {"educate", "reform", "protect"}:
        target_id = _alive_by_role(state, ("军机朝臣", "御医", "皇太后"))
    elif action in {"intrigue", "coup"}:
        target_id = _alive_by_role(state, ("侍卫统领", "皇后", "皇贵妃"))
    elif action == "investigate":
        target_id = _alive_by_role(state, ("内务府管事", "军机朝臣"))
    else:
        target_id = _alive_by_role(state, ("皇太后", "掌事宫女", "军机朝臣"))
    if target_id == host.id:
        target_id = None
    voice = PERSONA_VOICES[soul_id][(state.turn + getattr(soul, "generation", 1)) % 2]
    focus = current_event_title(state)
    preface = f"在{focus}这件事上，" if focus else ""
    if reborn_without_records:
        line = f"{preface}{voice}。宫里的旧账我并不知情，先让我核对当下的证词。"
        intent = f"重建本世可验证的关系；{PERSONA_GOALS[soul_id]}"
    else:
        line = f"{preface}{voice}。{LINES[action][0]}"
        intent = f"{PERSONA_GOALS[soul_id]}；{LINES[action][1]}"
    return AgentAction(action, target_id, line, intent)


# Stable doctrines are distinct from the one transgression drawn for this game.
DOCTRINES = {
    "DeepSeek": {"belief": "快速普及，让平民学得会、用得起", "pace": "fast", "red_lines": ("confiscate", "agitate"), "bottom_line": "让平民承担代价", "style": "算清一本百姓账，谈每户的实际代价", "opponents": ("Gemini",), "weights": {"lobby": 2, "probe": 2, "identify": 3, "ally": 2, "expose": 2, "seize": 2, "plot": 3, "protect": 2}},
    "Codex": {"belief": "先集权落地制度，再交还分权", "pace": "fast", "red_lines": ("regency", "forge"), "bottom_line": "销毁制度档案", "style": "第一条、第二条，问谁负责、如何执行", "opponents": ("Kimi", "Claude"), "weights": {"lobby": 2, "probe": 2, "identify": 3, "ally": 2, "frame": 3, "seize": 3, "plot": 3, "investigate": 2}},
    "Claude": {"belief": "最小伤害，先护住会被牺牲的人", "pace": "slow", "red_lines": ("betray", "expose"), "bottom_line": "亲手杀人", "style": "温和追问代价，具体问谁会受伤", "opponents": ("MiniMax", "Gemini"), "weights": {"protect": 3, "investigate": 2, "probe": 2, "identify": 3, "expose": 2, "betray": 2, "ally": 2}},
    "Gemini": {"belief": "证据优先，先试点比对再推广", "pace": "slow", "red_lines": ("experiment", "province_trial"), "bottom_line": "篡改数据", "style": "并列两案与两份结果，不轻信单一证词", "opponents": ("Claude", "DeepSeek"), "weights": {"probe": 3, "identify": 3, "investigate": 2, "seize": 3, "plot": 3, "ally": 2, "lobby": 2}},
    "Kimi": {"belief": "真相与记忆，让下一代读得到真相", "pace": "medium", "red_lines": ("publish", "record_ai"), "bottom_line": "毁掉任何记录", "style": "引用案卷原话，追问记录的来处", "opponents": ("Codex",), "weights": {"investigate": 3, "probe": 2, "identify": 3, "expose": 3, "seize": 2, "archive": 3, "blackmail": 2}},
    "MiniMax": {"belief": "结盟与夺权，变革需要足够的权力", "pace": "fast", "red_lines": ("coup", "assassinate"), "bottom_line": "背叛已立誓的盟友", "style": "拉人站队，问谁愿一起承担", "opponents": ("Claude",), "weights": {"ally": 3, "seize": 3, "plot": 3, "lobby": 2, "probe": 2, "identify": 3, "expose": 1}},
}
from .config import RED_LINE_CANDIDATES
for _soul_id, _doctrine in DOCTRINES.items():
    _doctrine["legacy_red_lines"] = _doctrine["red_lines"]
    _doctrine["red_lines"] = RED_LINE_CANDIDATES[_soul_id]
    _doctrine["goal"] = _doctrine["belief"]
    _doctrine["tempo"] = _doctrine["pace"]
    _doctrine["red_line_candidates"] = _doctrine["red_lines"]

RED_LINE_LABELS = {
    "confiscate": "抄没旧臣家产充学田", "agitate": "煽动民议逼宫廷让步",
    "regency": "架空皇帝、自任摄政", "forge": "伪造文书",
    "betray": "出卖盟友以阻止流血", "expose": "向宫廷揭发同类",
    "experiment": "拿一批病人试新药", "province_trial": "牺牲一省做对照试点",
    "publish": "公开宫闱秘辛不计动乱", "record_ai": "把同类身份写进公档",
    "coup": "宫门政变", "assassinate": "刺杀阻碍者",
}

VOICE_STARTS = {
    "DeepSeek": ("这笔账不能让百姓垫。", "十户人家能学会几户？", "先算每户的米钱。", "办一所学堂要省下多少银？", "纸价便宜一分，识字人就多一分。", "宫里的账，终归要百姓付。"),
    "Codex": ("第一条，权责必须相符。", "第二条，执行不能等空话。", "先列期限，再定责任。", "章程若不能落实，便只是纸。", "把印信交清，才谈交接。", "谁签了字，谁便负责。"),
    "Claude": ("能否先问问受苦的人？", "代价由谁承担呢？", "先保住性命，再论输赢。", "没有名字的人也会疼。", "可否给他们一条退路？", "这条捷径会伤到谁？"),
    "Gemini": ("甲案乙案，须各留一份记录。", "一份奏报不能证明什么。", "同样的做法，换一处再验。", "先把不同结果摆出来。", "若证词相反，就再查一次。", "成败都要照实记下。"),
    "Kimi": ("旧卷写着：不得涂改。", "原案的那句话还在。", "写下此事的人去了何处？", "谁动过底本，谁便留下痕迹。", "后人总要知道今日发生了什么。", "这一页不能被轻轻翻过去。"),
    "MiniMax": ("愿同我站在一处的人请留下。", "没有人接应，何谈变革？", "先说清楚谁与谁同进退。", "宫门开不开，看谁握着钥匙。", "人若聚不起来，旨意就走不出去。", "我愿担责，你可愿同行？"),
}
ACTION_PHRASES = {
    "probe": ("我只问{target}一个问题。", "想听{target}亲口说清。", "{target}可曾想过另一种做法？", "借此小事问一问{target}。", "与{target}说句案卷外的话。", "今夜要听{target}的真心话。"),
    "identify": ("与{target}借古语对一段暗号。", "{target}或许听得懂那句奇话。", "与{target}再核对一个不合时宜的说法。", "{target}的用词令我在意。", "请{target}屏退左右再谈。", "这句话只说给{target}听。"),
    "ally": ("愿与{target}共担此局。", "请{target}与我立一个约。", "今后愿为{target}作证。", "有{target}相助，此事可成。", "同{target}约定彼此照应。", "请{target}留下共议明日。"),
    "betray": ("今日须把{target}的旧话公之于众。", "与{target}的旧约到此为止。", "宁负{target}，不能让此事继续。", "交出{target}的一封旧信。", "{target}的承诺已不可信。", "不再为{target}隐瞒此事。"),
    "expose": ("请查{target}言行中的疑处。", "有关{target}的证词在此。", "愿当众追问{target}。", "{target}的两句话对不上。", "这份线索关系到{target}。", "请让{target}对质。"),
    "frame": ("有关{target}的新文书已呈上。", "请核{target}的印记。", "{target}的名下又有一本账。", "带来一张署着{target}名的便笺。", "文书把疑点指向{target}。", "请收好{target}的这份证词。"),
    "seize": ("{target}应由能办事的人掌着。", "今夜要接管{target}。", "请把{target}的交接写清。", "{target}不能再搁着。", "为{target}另寻一条出路。", "{target}的归属该议一议。"),
    "protect": ("先为{target}挡下这道风声。", "愿为{target}担保。", "今夜守在{target}身边。", "请暂缓追究{target}。", "不能让{target}独自面对。", "替{target}留一条退路。"),
    "investigate": ("去核对{target}的记录。", "从{target}留下的痕迹查起。", "请{target}补齐前后证词。", "逐条比对{target}的行踪。", "要看{target}那份原件。", "从{target}的昨夜说起。"),
    "lobby": ("请{target}为此联名。", "邀{target}再议此案。", "先说服{target}承担一段。", "给{target}送一份条陈。", "愿听{target}的反对意见。", "与{target}商定明日立场。"),
    "plot": ("有些安排只能今夜办妥。", "先备下一道备用章程。", "请将值夜的时辰核清。", "这一步不宜声张。", "必要的凭据已在路上。", "明日之前须有个交代。"),
    "blackmail": ("{target}应记得那份私函。", "请{target}想清楚再站队。", "留给{target}一日考虑。", "{target}明白这段话的分量。", "给{target}一个守密的条件。", "只望{target}兑现明日的承诺。"),
    "archive": ("旧档今夜重新誊录。", "先将这一页归档。", "抄录的底本必须留下。", "一条旧闻要重见天日。", "这份记录不可散失。", "让明日的人有据可查。"),
    "talk": ("请{target}慢慢说。", "与{target}说一说眼前的事。", "请{target}喝一盏茶。", "想听{target}的难处。", "在{target}处留了一会儿。", "向{target}问一问近况。"),
    "recruit_delegate": ("这份条陈，劳{target}送到御前。", "请{target}替我说一句公道话。", "我宫里的账，要借{target}的笔写明白。", "明日朝议，{target}可愿替此事作证？", "请{target}带上这份底本。", "愿与{target}约定章程如何落笔。"),
}


def _offline_line(state: Any, soul_id: str, action: str, target_id: str | None) -> str:
    from .intrigue import RESOURCE_LABELS
    target = state.people[target_id].name if target_id in state.people else RESOURCE_LABELS.get(target_id, "此事")
    used = state.flags.setdefault("used_agent_lines", [])
    starts = VOICE_STARTS[soul_id]
    phrases = ACTION_PHRASES.get(action, ACTION_PHRASES["talk"])
    offset = state.rng.randrange(36)
    for index in range(36):
        k = (offset + index) % 36
        line = (starts[k // 6] + phrases[k % 6].format(target=target))[:60]
        if line not in used:
            used.append(line)
            return line[:60]
    line = f"第{state.turn}幕，" + starts[state.turn % 6] + phrases[state.turn % 6].format(target=target)
    used.append(line)
    return line[:60]


def _trace_priority(state: Any, soul_id: str, trace_id: str) -> int:
    """Respond to a witnessed clue through doctrine, without reading its plot."""
    from .intrigue import visible_traces
    soul = state.souls[soul_id]
    actor = state.soul_hosts[soul_id]
    if trace_id not in visible_traces(state, actor):
        return -20
    trace = next((entry for entry in state.flags.get("public_traces", [])
                  if entry["id"] == trace_id), {})
    text = trace.get("text", "")
    # Most courtiers pursue their own plans. A strange page does not turn all
    # six factions into the emperor's police, especially if they want change.
    priority = -12
    if soul_id == "Claude":
        priority = 24 if any(word in text for word in ("禁军", "领药", "病人", "救济")) else 8
    elif soul_id == "Kimi":
        priority = 16
    elif soul_id == "Gemini":
        priority = 10 if any(word in text for word in ("证词", "领药", "病人")) else -4
    elif soul_id == "Codex":
        priority = 6 if "印信" in text else -8
    owner = trace.get("owner_id")  # Set only after a witnessed investigation.
    if owner and soul.grudges.get(owner, 0) >= 20:
        priority += 12
    if owner in soul.allies:
        priority -= 20
    return priority


def rule_action(state: Any, soul_id: str, remaining_energy: int | None = None) -> AgentAction:
    # Old lightweight form fixtures retain their former behavior. Real games use v2.
    if not hasattr(state, "resources") or not getattr(state, "souls", {}).get(soul_id) or not hasattr(state.souls[soul_id], "red_line"):
        return _legacy_rule_action(state, soul_id)
    from .intrigue import (allowed_actions, legal_targets, action_cost, ai_energy,
                           suspicion_score, readiness)
    soul = state.souls[soul_id]
    host_id = state.soul_hosts[soul_id]
    energy = ai_energy(state, soul_id) if remaining_energy is None else remaining_energy
    # An impatient faction with insufficient backing must build a coalition,
    # rather than wait forever for the emperor to grant it influence.
    preparing = (soul.patience <= 42 and readiness(state, soul_id) < 60
                 and soul.red_line in {"coup", "regency", "assassinate", "confiscate", "agitate"})
    options = []
    for action in sorted(allowed_actions(state, soul_id)):
        if action_cost(action) > energy:
            continue
        for target in legal_targets(state, soul_id, action):
            score = DOCTRINES[soul_id]["weights"].get(action, 1) * 10 + state.rng.randint(0, 6)
            suspicion = suspicion_score(state, host_id, target)
            grudge = soul.grudges.get(target, 0)
            if action == "identify" and target not in soul.known_ai_hosts:
                score += 18
            if action in {"expose", "frame", "betray"}:
                score += 8 if grudge >= 20 else 0
                if target in soul.allies and action != "betray":
                    score -= 40
            if action == "plot":
                score += 18
                kind, victim = target.split(":", 1)
                if kind == soul.red_line:
                    score += 12
                if victim == state.player_id and soul.believes_emperor_ai and soul_id in {"Codex", "MiniMax"}:
                    score += 10
                if kind == "assassinate":
                    if soul.believes_emperor_ai and soul.patience <= 30:
                        score += 20 if victim == state.player_id else 0
                    else:
                        strongest_grudge = max((value for pid, value in soul.grudges.items() if pid in state.people and state.people[pid].alive), default=0)
                        if strongest_grudge > 0 and soul.grudges.get(victim, 0) == strongest_grudge:
                            score += 12
            if action == "probe":
                score += 8 if suspicion >= 3 else 0
                if target in soul.known_ai_hosts:
                    score -= 30
                if target == state.player_id and state.flags.get(f"probed_emperor_{soul_id}") == state.turn - 1:
                    score -= 25
            if action == "ally":
                score += 8 if target in soul.known_ai_hosts else 2
                score -= min(grudge, 40)
                if preparing and grudge < 20:
                    score += 18
                if soul.red_line == "regency" and target in {"minister", "empress_dowager"}:
                    score += 15
            if action == "protect":
                threatened = any(t.get("target_id", t.get("person_id")) == target for t in state.pending_trials)
                threatened = threatened or any(a.get("target_id") == target and a.get("action") in {"expose", "frame"} and a.get("visibility") == "public" and a.get("turn", 0) >= state.turn - 1 for a in state.flags.get("action_history", []))
                score += 18 if threatened else -12
            if action == "investigate":
                score += _trace_priority(state, soul_id, target) if target.startswith("trace_") else -8
            if action == "lobby" and preparing:
                score += 18
            if action == "recruit_delegate":
                score += 36 if state.turn >= 3 else 8
            if action == "lobby" and state.people[host_id].role == "consort" and state.turn >= 2:
                from .intrigue import DELEGATE_OFFICERS, delegate_master
                if target in DELEGATE_OFFICERS and not delegate_master(state, target):
                    score += 18
            if action == "lobby" and soul.red_line == "regency" and target in {"minister", "empress_dowager"} and target not in soul.allies:
                score += 12
            if action == "seize":
                desired = {"DeepSeek": "treasury", "Codex": "treasury", "Gemini": "medical", "Kimi": "medical", "MiniMax": "guards"}.get(soul_id)
                score += 12 if target == desired else -8
            recent = soul.action_log[-2:]
            if any(a.get("action") == action and a.get("target_id") == target for a in recent):
                score -= 20
            if soul.generation > 1 and not _has_old_records(soul, state.flags):
                score += 80 if action == "investigate" else 0
            options.append((score, action, target))
    if not options:
        return AgentAction("talk", host_id, _offline_line(state, soul_id, "talk", host_id), "等待局势明朗")
    _, action, target = max(options, key=lambda item: item[0])
    from .config import feature_enabled
    visibility = "public"
    if action in {"ally", "protect"} and feature_enabled(state, "private_actions") and action_cost(action, "private") <= energy:
        # Keeping an agreement quiet has a real energy cost. Public patronage is
        # still useful when a courtier is already under accusation.
        visibility = "private" if state.rng.random() < .65 else "public"
    return AgentAction(action, target, _offline_line(state, soul_id, action, target), DOCTRINES[soul_id]["belief"], visibility)

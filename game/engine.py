"""一局九幕的状态机。叙事可变，身份与数值只由规则修改。"""

from __future__ import annotations

import copy

from typing import Any

from .agents import ALLOWED_ACTIONS, AgentAction, rule_action
from .dialogue import free_clue as _free_clue, offline_answer as _offline_answer
from .events import EVENT_POOL, Event, apply_policy, available_events, prepare_proposals, choose_event
from .roster import GIVEN, SURNAMES, _name
from .state import GameState, Person, Relation, SOUL_IDS, add_ledger, clamp, relation


INTEL_ACTIONS = {"listen", "ally", "trace", "review", "purge", "talk", "share_archive"}
INTERRUPT_ACTIONS = {"protect", "expose", "delay"}
ENDING_SCENE = "【终局】皇位与实权已有定局。"


def _story_bridge(state: GameState) -> str:
    """上一幕的选择在新奏折前留下可见的痕迹。"""
    from .config import feature_enabled
    if feature_enabled(state, "story_threads"):
        from .story import story_bridge
        return story_bridge(state)
    if state.turn == 2:
        opening = state.flags.get("opening_policy")
        return {
            "print_school": "首幕拨银后，新书已出宫门；两份誊本的签押仍留在案上。",
            "audit_print": "首幕暂缓开印，底本封在内库；两宫都等着有人给出核账结果。",
            "ban_print": "首幕封存奏折后，旧版却流出了宫；缺页的账册更难核清。",
        }.get(opening, "")
    if state.turn == 3:
        if state.flags.get("public_health") or state.flags.get("medical_records"):
            return "太医院留下第一批可核验的病案，宫外开始有人照着办。"
        if state.flags.get("hidden_epidemic"):
            return "病人转入街巷深处，朝廷的静默没有让热病停下。"
    if state.turn == 4:
        if state.flags.get("workshops"):
            return "治河留下的图纸被匠人带进工坊，谁能读懂它成了新争议。"
        if state.flags.get("archives"):
            return "仓储与支出的旧账被送入史馆，纸上第一次有了可追问的名字。"
    if state.turn == 5:
        if state.flags.get("women_school"):
            return "第一批女学生已经入学，宫中开始争论她们以后能否议政。"
        if state.flags.get("exam_reform"):
            return "实学策论送到外省，旧臣等着看它会培养出什么样的官。"
    if state.turn == 6:
        return "首幕那两份不相同的誊本又被提起；内库的原页仍等着有人核对。"
    if state.turn == 7 and state.flags.get("copy_dispute_resolved"):
        return ("旧账公开后，两宫都须对当年的用途作证。" if state.flags.get("copy_dispute_public")
                else "旧账只在少数人手中核过，宫外仍流传两种说法。")
    if state.turn == 8:
        if state.flags.get("public_archive"):
            return "史馆已有能互相印证的副本，下一代可以追问前人的选择。"
        if state.flags.get("sealed_archive"):
            return "宫档虽在，能读它的人很少；传言先一步传到下一代。"
    if state.turn == 9:
        return "九幕将尽，旧账、学堂与储位都要写进一纸能传到后世的诏书。"
    return ""


def start_turn(state: GameState) -> GameState:
    if state.finished:
        return state
    if state.phase != "day":
        raise ValueError("当前不是朝会")
    if state.current_event_id:
        return state
    from . import intrigue
    intrigue.initialize(state)
    from .council import prepare_morning_greetings
    prepare_morning_greetings(state)
    state.flags.pop("_last_whisper", None)
    state.flags.pop("_last_dialogue", None)
    state.flags.setdefault("soul_history", {sid: [host] for sid, host in state.soul_hosts.items()})
    news = intrigue.prepare_morning(state)
    state.morning_news = list(news)
    _recruit_consort(state)
    news = list(state.morning_news)
    state.flags["day_scenes"] = state.flags.pop("next_day_scenes", [])
    from .story import enabled as story_enabled
    if story_enabled(state):
        # Night resolution can change health, guardianship or accounts after preview.
        # Choose from settled facts and reuse speeches only for that exact branch.
        event = choose_event(state)
        if state.next_event_id != event.id:
            state.next_proposals = []
        state.next_event_id = ""
    elif state.next_event_id:
        event = next((e for e in EVENT_POOL if e.id == state.next_event_id), None)
        state.next_event_id = ""
        if event is None:
            event = choose_event(state)
    else:
        event = choose_event(state)
    state.current_event_id = event.id
    if state.next_proposals and all(p.get("event_id") == event.id for p in state.next_proposals):
        state.proposals = state.next_proposals
    state.next_proposals = []
    state.proposals = prepare_proposals(state, event)
    _setup_tutorial(state)
    _distribute_people(state)
    _refresh_energy(state)
    bridge = _story_bridge(state)
    if story_enabled(state) and bridge:
        state.morning_news = [bridge] + [row for row in state.morning_news if row != bridge]
        news = list(state.morning_news)
    from .succession_pressure import succession_warning_text
    warning_text = succession_warning_text(state)
    if warning_text:
        state.morning_news = [warning_text] + [row for row in state.morning_news if row != warning_text]
        news = list(state.morning_news)
    lines = [f"第{state.turn}幕 · {event.title}"]
    if state.turn == 1:
        from .config import feature_enabled
        if feature_enabled(state, "story_threads"):
            from .story import opening_lines
            lines += opening_lines(state)
        else:
            lines += ["皇后沈徽昭把账册压在案上：‘银子只有这些，先把亏空查清。’",
                      "皇贵妃楚望舒不肯退让：‘再等一月，宫外的孩子又要错过开学。’",
                      "席间有人脱口而出：‘这得先做一份成本收益分析。’满殿忽然安静。"]
        if not any("找出他们，守住皇位与实权" in line for line in lines):
            lines.append("【皇帝】朕的朝堂里，混进了六个 AI。找出他们，守住皇位与实权。")
    if news:
        lines += ["【清晨消息】" + text for text in news[:5]]
    if bridge:
        if not story_enabled(state):
            lines.append(bridge)
        add_ledger(state, "承接", bridge, visibility="public")
    lines += [event.summary, state.tutorial_tip]
    state.last_scene = "\n".join(lines)
    add_ledger(state, "奏折", f"{event.title}：{event.summary}")
    return state

def current_event(state: GameState) -> Event:
    if not state.current_event_id:
        start_turn(state)
    from .events import find_event
    return find_event(state)


def _check_contact(state: GameState, person_id: str, night: bool) -> Person:
    person = state.people.get(person_id)
    if person is None or not person.alive or person_id == state.player_id:
        raise ValueError("此人当前不可接触")
    if (night and state.player_id == "emperor" and person.role != "consort"
            and any(p.alive and p.role == "consort" for p in state.people.values())):
        raise ValueError("翻牌子只能选择妃嫔")
    return person


def _soul_at(state: GameState, person_id: str) -> str | None:
    return next((sid for sid, host_id in state.soul_hosts.items() if host_id == person_id), None)


def _identity_scene(state: GameState, person_id: str) -> str:
    person = state.people[person_id]
    soul_id = _soul_at(state, person_id)
    tutorial_success = bool(state.tutorial_enabled and state.turn == 3 and person_id == state.tutorial_target_id and soul_id)
    if not tutorial_success:
        state.flags["rumor_risk"] = state.flags.get("rumor_risk", 0) + 1
    if soul_id:
        state.identified_hosts.add(person_id)
        state.identified_humans.discard(person_id)
        state.flags[f"evidence_{person_id}"] = max(1, state.flags.get(f"evidence_{person_id}", 0))
        state.souls[soul_id].trust_player = clamp(state.souls[soul_id].trust_player - 4, -100, 100)
        scene = f"你当面指出{person.name}并非寻常人。她承认自己是 AI，但没有说出具体身份。"
    else:
        state.identified_humans.add(person_id)
        state.flags["reputation"] = clamp(state.flags.get("reputation", 50) - 8)
        relation(state, person_id, state.player_id).trust = clamp(
            relation(state, person_id, state.player_id).trust - 12, -100, 100)
        scene = f"{person.name}否认你的推断。查证后，她仍是人类；御前妄断的议论传开。"
    if not tutorial_success and state.rng.random() < 0.65:
        scene += " 廊下有人听见争执，闲话当夜传进两宫。"
        state.flags["rumor"] = state.flags.get("rumor", 0) + 1
        state.metrics["stability"] = clamp(state.metrics["stability"] - 1)
        add_ledger(state, "流言", f"有人目击你向{person.name}追问异人身份，宫中议论渐起。")
    add_ledger(state, "辨认", scene)
    return scene


def _ask(state: GameState, person_id: str, question: str | None, provider: Any) -> str:
    if not question or not question.strip():
        return _free_clue(state, person_id)
    if state.deep_remaining <= 0:
        return "本局 10 次自由深问已用尽；这次会谈仍留下了一条线索。" + _free_clue(state, person_id)
    state.deep_remaining -= 1
    question = question.strip()[:200]
    from .dialogue import respond
    answer = respond(state, person_id, question, provider=provider, mode="ask")
    add_ledger(state, "深问", f"你问{state.people[person_id].name}：{question} 她答：{answer}",
               visibility="private", witnesses=[state.player_id, person_id])
    name = state.people[person_id].name
    return answer if answer.lstrip().startswith(name) else f"{name}答：{answer}"


def _alliance_report(state: GameState, person_id: str, copy_to_archive: bool) -> str:
    from .diary import public_report
    report = public_report(state, person_id, archive=copy_to_archive)
    if "error" in report:
        return report["error"]
    lines = [f"{state.people[person_id].name}的私密日记。", report["description"]]
    for page in report["pages"][-3:]:
        lines.append(f"第 {page['turn']} 幕：" + "；".join(page[k] for k in ("observed", "judgement", "decision", "memo") if k in page))
    if not report["pages"] or not any(p["unlocked_tier"] for p in report["pages"]):
        lines.append("日记尚未开放；信任达到 15 后可读所见，30 后可读判断，50 或结盟后可读决定。")
    return "\n".join(lines)


def alliance_report(state: GameState, person_id: str) -> dict:
    from .diary import public_report
    return public_report(state, person_id, archive=True)


def _intel(state: GameState, person_id: str, action: str) -> str:
    if action not in INTEL_ACTIONS:
        raise ValueError("未知情报动作")
    person = state.people[person_id]
    sid = _soul_at(state, person_id)
    if action in {"listen", "talk"}:
        return _free_clue(state, person_id)
    if action == "ally":
        if sid and person_id in state.identified_hosts:
            soul = state.souls[sid]
            if soul.trust_player >= 15:
                soul.allied = True
                soul.self_stats_authorized = soul.trust_player >= 25
                soul.key_relations_authorized = soul.trust_player >= 55
                if state.player_status in {"受制", "流亡"}:
                    state.flags["restoration_support"] = state.flags.get("restoration_support", 0) + 2
                add_ledger(state, "结盟", f"你与{person.name}订下合作约定；资料开放范围由她自行决定。")
                return f"{person.name}同意结盟。" + _alliance_report(state, person_id, False)
            soul.trust_player = clamp(soul.trust_player + 5, -100, 100)
            return f"{person.name}暂不承诺结盟，但愿再谈一次。"
        relation(state, person_id, state.player_id).trust = clamp(
            relation(state, person_id, state.player_id).trust + 6, -100, 100)
        if state.player_status in {"受制", "流亡"}:
            state.flags["restoration_support"] = state.flags.get("restoration_support", 0) + 1
        return f"{person.name}愿意提供人情上的帮助。"
    if action == "trace":
        if sid and person_id in state.identified_hosts:
            key = f"evidence_{person_id}"
            state.flags[key] = state.flags.get(key, 1) + 1
            if state.flags[key] >= 2:
                state.known_souls[person_id] = sid
                add_ledger(state, "查明", f"你比对记录，查明{person.name}承载的意识是{sid}。")
                return f"档案、措辞与知情人的证词相合：{person.name}承载的是 {sid}。"
        return f"你查了{person.name}的来历，尚无足够证据确定具体身份。"
    if action == "review":
        return _alliance_report(state, person_id, True)
    if action == "share_archive":
        if not state.player_archive:
            return "你的私人档案里还没有可出示的旧记录。"
        if sid is None or person_id not in state.identified_hosts:
            return "你尚未确认此人的 AI 身份，旧档暂未交出。"
        excerpt = str(state.player_archive[-1].get("text", "旧档"))[:90]
        state.souls[sid].memory.append(f"玩家出示旧档：{excerpt}")
        state.souls[sid].trust_player = clamp(state.souls[sid].trust_player + 5, -100, 100)
        add_ledger(state, "递档", f"你向{person.name}展示一份私人抄录的旧档，让她重新审视前世传闻。")
        return f"{person.name}读完旧档，原先的判断有了新的依据。"
    if action == "purge":
        if state.player_status in {"受制", "流亡"}:
            return "你已失去御前调兵权，只能先积累证据。"
        kill_host(state, person_id, "御前查办")
        state.flags["reputation"] = clamp(state.flags.get("reputation", 50) - 12)
        state.metrics["stability"] = clamp(state.metrics["stability"] - 5)
        return f"{person.name}被查办身亡。宫中无人敢说这一步没有代价。"
    raise ValueError("未知情报动作")


def _meeting(state: GameState, person_id: str, question: str | None,
             identify: bool, action: str, provider: Any) -> str:
    if identify:
        return _identity_scene(state, person_id)
    action_scene = _intel(state, person_id, action)
    if question and action != "purge":
        return action_scene + "\n" + _ask(state, person_id, question, provider)
    return action_scene


def _agent_resolution(state: GameState, provider: Any) -> str:
    from .intrigue import run_shadow_night
    return "\n".join(run_shadow_night(state, provider))

def _opening_copy_followup(state: GameState, event: Event, policy_id: str) -> str:
    """第六幕兑现首幕悬念；史实不预设六魂中谁是幕后者。"""
    from .config import feature_enabled
    if feature_enabled(state, "story_threads"):
        return ""
    if state.turn != 6 or state.flags.get("copy_dispute_resolved"):
        return ""
    opening = state.flags.get("opening_policy", "")
    if event.id == "treasury_audit":
        source = "内库旧底本"
    else:
        source = "失火后抢出的工料领用簿"
    if opening == "audit_print":
        trail = "首幕命人封存的签押尚在，能逐页核对银两去向。"
    elif opening == "print_school":
        trail = "书院领银凭单留下第三份记录，能查出哪些钱真正出宫。"
    else:
        trail = "首幕封折使签押断了一页；只能查明两种用途，尚不能断定是谁改了字。"
    public = state.player_status == "在位" and policy_id in {"public_audit", "fire_inquiry"}
    state.flags["copy_dispute_resolved"] = True
    state.flags["copy_dispute_public"] = public
    finding = (f"{source}与首幕两份誊本终于对上：同一笔银在两份纸上分别列作备荒与学额。"
               f"它曾由内务府分栏抄送两宫，后来两宫都把自己那页当成了全部。{trail}")
    finding += (" 会审记录抄出宫门，两宫都必须在众人面前解释当年的主张。" if public
                else " 这份核对暂留御前，宫外仍只听得见两宫各执一词。")
    add_ledger(state, "旧账揭晓", finding, visibility="public" if public else "private", witnesses=[state.player_id])
    return finding


def run_day(state: GameState, person_id: str = "", policy_id: str = "", intel_id: str = "listen",
            question: str | None = None, identify: bool = False, provider: Any = None) -> GameState:
    if state.phase != "day" or state.finished:
        raise ValueError("当前不能处理朝会")
    if state.pending_trials:
        raise ValueError("请先裁决清晨的审讯")
    event = current_event(state)
    policy = next((p for p in event.policies if p.id == policy_id), None)
    if policy is None:
        raise ValueError("请选择本幕奏折的政策")
    from .intrigue import on_policy
    proposal = next((p for p in state.proposals if p["policy_id"] == policy_id), {})
    owner = proposal.get("proposer_id", "")
    others = [p.get("proposer_id", "") for p in state.proposals if p["policy_id"] != policy_id]
    if state.player_status in {"受制", "流亡"}:
        state.flags["restoration_support"] = state.flags.get("restoration_support", 0) + 1
        result = f"你把‘{policy.title}’写入密函；先争取支持，暂不能颁行。"
        from .story import enabled as story_enabled, record_unenacted
        if story_enabled(state):
            record_unenacted(state, event, policy, result)
    else:
        result = apply_policy(state, policy_id)
        on_policy(state, policy, owner, others)
    state.current_policy_id = policy_id
    state.seen_events.append(event.id)
    if state.turn == 1:
        state.flags["opening_policy"] = policy_id
    followup = _opening_copy_followup(state, event, policy_id)
    supporter = state.people.get(owner)
    standing = f"你支持了{supporter.name}的提案。" if supporter else "你选择了御前折中方案。"
    add_ledger(state, "站队", standing + policy.title, actor_id=state.player_id, target_id=owner)
    add_ledger(state, "政策" if state.player_status == "在位" else "密函", f"你选择‘{policy.title}’。{result}")
    state.pending_result = result
    state.last_scene = f"【你的决定】{standing}{result}\n" + (followup + "\n" if followup else "") + f"【自由时段】还有 {state.energy} 点精力。去见人、试探，或偷听一段争执。"
    state.phase = "free"
    return state

def interrupt(state: GameState, choice_id: str, provider: Any = None) -> GameState:
    if state.phase != "free" or state.finished:
        raise ValueError("御前叫停只能在白天自由时段使用")
    from .config import feature_enabled
    if not feature_enabled(state, "interrupt"):
        raise ValueError("本版不开放御前叫停")
    _require_unlocked(state, "interrupt")
    if state.player_status != "在位":
        raise ValueError("失去实权后，不能御前叫停")
    if state.energy < 2:
        raise ValueError("精力不足：御前叫停需要 2 点")
    if state.interrupt_used_generation:
        raise ValueError("本代御前叫停机会已用")
    if choice_id not in INTERRUPT_ACTIONS:
        raise ValueError("未知叫停方式")
    state.interrupt_used_generation = True
    state.energy -= 2
    if choice_id == "protect":
        state.metrics["stability"] = clamp(state.metrics["stability"] + 4)
        active = [p for p in state.plots if not p.get("resolved") and not p.get("cancelled") and p.get("status", "active") == "active"]
        if active:
            plot = max(active, key=lambda p: p.get("stage", 0))
            plot["stage"] = max(0, plot.get("stage", 0) - 1)
        text = "你叫停争论，命侍卫护送证人；一场正在酝酿的阴谋被迫退了一步。"
    elif choice_id == "expose":
        state.metrics["openness"] = clamp(state.metrics["openness"] + 3)
        state.flags["reputation"] = clamp(state.flags.get("reputation", 50) - 3)
        text = "你当众公布证词，各派不得不在明处表态。正统 −3。"
    else:
        for plot in state.plots:
            if not plot.get("resolved") and not plot.get("cancelled"):
                plot["stage"] = max(0, plot.get("stage", 0) - 1)
        state.metrics["knowledge"] = clamp(state.metrics["knowledge"] - 1)
        text = "你暂停议程复核证据，暗中部署也随之放缓。"
    add_ledger(state, "打断", text)
    state.last_scene = "【御前叫停】" + text
    return state

def run_night(state: GameState, person_id: str, question: str | None = None,
              identify: bool = False, provider: Any = None, action: str = "talk", visibility: str = "public") -> GameState:
    if state.phase != "night" or state.finished:
        raise ValueError("当前不能夜议")
    person = _check_contact(state, person_id, True)
    if identify:
        action = "identify"
    elif question and question.strip():
        action = "deep"
    if action in {"listen", "conversation"}:
        action = "talk"
    _validate_visibility(action, visibility)
    _validate_player_action(state, action, person_id, night=True)
    cost = ACTION_COSTS[action]
    if cost > state.night_energy:
        raise ValueError("夜间精力不足")
    meeting = _perform_player_action(state, action, person_id, None, question, provider, visibility=visibility)
    state.night_energy -= cost
    state.night_contact_id = person_id
    label = "翻牌子" if person.role == "consort" and state.player_id == "emperor" else "夜议"
    add_ledger(state, label, f"你与{person.name}单独会谈。{meeting}", visibility="private", witnesses=[state.player_id])
    # Director writes next morning's debate before resolving this night's plans.
    if state.turn < 9:
        preview = copy.deepcopy(state)
        preview.turn += 1
        preview.current_event_id = ""
        next_event = choose_event(preview)
        state.next_event_id = next_event.id
        state.next_proposals = prepare_proposals(state, next_event, future=True)
    from .intrigue import run_shadow_night
    state.morning_news = []
    news = run_shadow_night(state, provider)
    state.morning_news = list(dict.fromkeys(state.morning_news + list(news)))
    if state.finished:
        # An early terminal event may have happened during the shadow phase.
        # Do not overwrite its ending with a promise of another morning.
        state.last_scene = ENDING_SCENE
        return state
    state.phase = "ready_next"
    if state.turn >= 9:
        return finish_turn(state, provider)
    state.last_scene = f"【{label}】{person.name}\n{meeting}\n【夜深】各宫灯火渐熄。今夜发生的事，将在清晨揭晓。"
    return state

def _new_face(state: GameState, role: str) -> str:
    index = len(state.people) + 1
    pid = f"newcomer_{index}"
    while pid in state.people:
        index += 1
        pid = f"newcomer_{index}"
    name = _name(state.rng, {person.name for person in state.people.values()} | set(state.reserve_consort_names.values()), role)
    state.people[pid] = Person(pid, name, role, role, faction="中立", traits=["新入宫"])
    for other in list(state.people):
        if other != pid:
            state.relations[(pid, other)] = Relation()
            state.relations[(other, pid)] = Relation()
    return pid

def kill_host(state: GameState, person_id: str, reason: str) -> GameState:
    person = state.people.get(person_id)
    if person is None or not person.alive:
        raise ValueError("此人已经不在世")
    if person_id == state.player_id:
        return kill_player(state, reason)
    person.alive = False
    exiled = "流放" in reason or "离宫" in reason
    if exiled:
        departures = state.flags.setdefault("exiled_people", [])
        if person_id not in departures:
            departures.append(person_id)
    state.pending_probes[:] = [p for p in state.pending_probes if p.get("actor_id") != person_id]
    state.pending_trials[:] = [t for t in state.pending_trials if t.get("target_id", t.get("person_id")) != person_id]
    if person.role == "consort":
        state.flags["consort_vacancies"] = state.flags.get("consort_vacancies", 0) + 1
        if not exiled:
            state.flags["last_consort_death_turn"] = state.turn
    for resource in state.resources.values():
        if resource.get("holder_id") == person_id:
            resource["holder_id"] = None
        if resource.get("public_holder_id") == person_id:
            resource["public_holder_id"] = None
    add_ledger(state, "离宫" if exiled else "死亡",
               f"{person.name}因妖异案被流放离宫，此后无法再接触。" if exiled else f"{person.name}因{reason}身亡。",
               actor_id=person_id, visibility="public")
    if person_id == state.designated_heir_id:
        princess = state.people.get("heir_daughter")
        if (state.flags.get("female_succession") and princess and princess.alive
                and princess.id not in state.soul_hosts.values()
                and princess.id != state.player_id):
            state.designated_heir_id = princess.id
        else:
            replacement = _new_face(state, "heir")
            state.people[replacement].rank = "皇嗣"
            state.people[replacement].guardian_id = state.player_id
            state.designated_heir_id = replacement
            state.player_lineage.append(replacement)
            state.identified_humans.add(replacement)
        add_ledger(state, "储位", "人类储位缺出，宗室重新指定了一位可接棒的继承人。")
    if person_id == state.people["heir_son"].guardian_id:
        mother = state.flags["birth_mother_id"]
        state.people["heir_son"].guardian_id = mother if state.people[mother].alive else "empress_dowager"
        add_ledger(state, "抚育", "皇子的抚育人重新指定，生母或太后接手。")
    if person_id == state.people["heir_daughter"].guardian_id:
        state.people["heir_daughter"].guardian_id = "empress_dowager"
    if person_id == state.flags.get("power_holder_id"):
        state.flags["power_holder_id"] = state.player_id
        if state.current_ruler_id == state.player_id:
            state.player_status = "在位"
            add_ledger(state, "复位", "监国者离宫，御前重新收回实权。")
    if person_id == state.current_ruler_id and state.player_status in {"受制", "流亡"}:
        state.current_ruler_id = state.player_id
        state.flags["lineage_on_throne"] = True
        state.player_status = "在位"
        state.flags["power_holder_id"] = state.player_id
        add_ledger(state, "复位", f"{state.people[state.player_id].name}在众人拥立下重返御座。")
    sid = _soul_at(state, person_id)
    if sid is None:
        return state
    soul = state.souls[sid]
    state.flags.setdefault("soul_history", {}).setdefault(sid, [person_id])
    from .diary import reset_life
    reset_life(state, sid)
    soul.generation += 1
    soul.memory.clear()
    soul.action_log.clear()
    soul.allied = False
    soul.self_stats_authorized = False
    soul.key_relations_authorized = False
    soul.trust_player = 0
    # 不附身当前玩家或指定的人类继承人；优先现有人类。
    occupied = set(state.soul_hosts.values())
    candidates = [p.id for p in state.people.values()
                  if p.alive and p.id not in occupied and p.id not in
                  {state.player_id, state.designated_heir_id, state.current_ruler_id}]
    if candidates:
        new_host = state.rng.choice(candidates)
    else:
        new_host = _new_face(state, state.rng.choice(("宫女", "宦官", "太医")))
        _new_face(state, state.rng.choice(("宫女", "宦官", "太医")))
    state.soul_hosts[sid] = new_host
    state.flags["soul_history"][sid].append(new_host)
    from .intrigue import reset_host
    reset_host(state, person_id, new_host, sid)
    rank = state.people[new_host].rank
    base_influence = 26 if rank in {"皇后", "皇贵妃", "贵妃"} else 17 if state.people[new_host].role in {"朝臣", "侍卫统领", "御医"} else 11
    soul.influence = base_influence + state.rng.randint(0, 7)
    was_known_human = new_host in state.identified_humans
    state.identified_hosts.discard(new_host)
    state.identified_humans.discard(new_host)
    state.known_souls.pop(new_host, None)
    if was_known_human:
        decoys = [pid for pid in state.identified_humans
                  if state.people[pid].alive and pid not in state.soul_hosts.values()
                  and pid not in {state.player_id, state.designated_heir_id, state.current_ruler_id}]
        if decoys:
            for pid in state.rng.sample(decoys, min(2, len(decoys))):
                state.identified_humans.discard(pid)
        else:
            _new_face(state, state.rng.choice(("宫女", "宦官", "太医")))
    add_ledger(state, "六席补满", "有个 AI 换了身体。六个意识仍在世间，旧线索不能直接用于新的人。")
    return state


def _eligible_heir(state: GameState) -> str | None:
    candidates = [state.designated_heir_id, "heir_son"]
    if state.flags.get("female_succession"):
        candidates.append("heir_daughter")
    for pid in candidates:
        if pid in state.people and state.people[pid].alive and pid != state.player_id and pid not in state.soul_hosts.values():
            return pid
    return None


def kill_player(state: GameState, reason: str, coup_by: str | None = None) -> GameState:
    if state.finished:
        return state
    old_id = state.player_id
    old = state.people[old_id]
    old.alive = False
    add_ledger(state, "君主身亡", f"{old.name}因{reason}身亡。")
    heir_id = _eligible_heir(state)
    # Settle actual holdings and public claims independently. A covert seizure
    # remains covert, and the successor cannot inherit another person's assets.
    for resource in state.resources.values():
        for holder_key in ("holder_id", "public_holder_id"):
            if resource.get(holder_key) == old_id:
                resource[holder_key] = heir_id
    # These questions were addressed to the deceased emperor, not the next
    # player character. Other defendants' pending cases remain valid.
    state.pending_probes[:] = [probe for probe in state.pending_probes
                               if probe.get("actor_id") != old_id
                               and probe.get("target_id", old_id) != old_id]
    state.pending_trials[:] = [trial for trial in state.pending_trials
                               if trial.get("target_id", trial.get("person_id")) != old_id]
    if heir_id is None:
        state.finished = True
        state.phase = "ended"
        state.last_scene = ENDING_SCENE
        state.flags["lineage_on_throne"] = False
        state.current_ruler_id = ""
        state.flags["power_holder_id"] = ""
        add_ledger(state, "断嗣", "没有符合当前继承法的人类继承人，玩家一脉退出皇位。")
        from .ending import render_ending
        state.ending = render_ending(state, None)
        return state
    state.player_id = heir_id
    state.generation += 1
    state.interrupt_used_generation = False
    state.player_lineage.append(heir_id) if heir_id not in state.player_lineage else None
    if coup_by and coup_by in state.people and state.people[coup_by].alive:
        state.current_ruler_id = coup_by
        state.flags["power_holder_id"] = coup_by
        state.flags["lineage_on_throne"] = False
        state.player_status = "受制" if state.metrics["stability"] >= 40 else "流亡"
    else:
        state.current_ruler_id = heir_id
        state.flags["power_holder_id"] = heir_id
        state.flags["lineage_on_throne"] = True
        state.player_status = "在位"
    # 为下一次可能的换代保留一位人类继承人。
    next_heir = _new_face(state, "heir")
    state.people[next_heir].rank = "皇嗣"
    state.people[next_heir].guardian_id = heir_id
    state.designated_heir_id = next_heir
    state.player_lineage.append(next_heir)
    state.identified_humans.add(next_heir)
    add_ledger(state, "继承", f"你改以{state.people[heir_id].name}的身份继续，处境为{state.player_status}。")
    return state


def finish_turn(state: GameState, provider: Any = None) -> GameState:
    if state.phase != "ready_next" and not state.finished:
        raise ValueError("夜议后才能进入下一幕")
    if state.finished:
        state.last_scene = ENDING_SCENE
        return state
    if (state.player_status in {"受制", "流亡"}
            and state.flags.get("restoration_support", 0) >= 5
            and state.people[state.player_id].alive):
        state.current_ruler_id = state.player_id
        state.flags["lineage_on_throne"] = True
        state.player_status = "在位"
        state.flags["power_holder_id"] = state.player_id
        state.flags["restoration_support"] -= 5
        state.flags["reputation"] = max(35, state.flags.get("reputation", 0))
        add_ledger(state, "复位", f"多方盟友公开联名拥立{state.people[state.player_id].name}，玩家一脉收回皇位与实权；本次耗用五份支持，正统至少恢复到 35。")
    from .succession_pressure import advance_succession_pressure
    advance_succession_pressure(state)
    if state.turn >= 9:
        state.finished = True
        state.phase = "ended"
        state.last_scene = ENDING_SCENE
        from .ending import render_ending
        state.ending = render_ending(state, provider)
        add_ledger(state, "终局", "九次关键抉择已尽，史官据已发生的事实写成新朝结局。")
        return state
    state.turn += 1
    state.phase = "day"
    state.current_event_id = ""
    state.current_policy_id = ""
    state.day_contact_id = ""
    state.night_contact_id = ""
    state.pending_result = ""
    start_turn(state)
    return state

# Costs and unlocks are authoritative on the server; the UI receives only eligibility.
ACTION_COSTS = {
    "move": 0, "talk": 1, "probe": 1, "eavesdrop": 1, "archive": 1,
    "deep": 2, "identify": 2, "ally": 2, "expose": 2, "spy": 2,
    "investigate": 2, "protect": 1, "lobby": 1, "betray": 2,
    "frame": 2, "seize": 2, "decree": 3, "purge": 3,
    "trace": 1, "review": 1, "share_archive": 1, "expose_interference": 2, "report_interference": 2,
}
ACTION_UNLOCKS = {
    1: ("move", "talk", "probe", "eavesdrop"),
    2: ("deep", "mark", "respond_probe", "archive"),
    3: ("identify",),
    4: ("ally", "expose", "spy", "protect", "lobby", "betray", "seize", "trace", "review", "share_archive", "resources", "expose_interference", "report_interference"),
    5: ("investigate", "decree", "purge", "interrupt", "frame", "trial"),
}


def _setup_tutorial(state: GameState) -> None:
    from .intrigue import add_fingerprint, recompute_suspicion
    step = state.turn if state.tutorial_enabled else 9
    state.tutorial_step = min(step, 5)
    state.unlocked_actions = [action for turn, actions in ACTION_UNLOCKS.items() if turn <= step for action in actions]
    from .config import feature_enabled
    if not feature_enabled(state, "interrupt"):
        state.unlocked_actions = [a for a in state.unlocked_actions if a != "interrupt"]
    if state.tutorial_enabled and state.turn == 2 and not state.tutorial_target_id:
        candidates = [p for p in state.proposals if p.get("proposer_id") in state.soul_hosts.values()]
        if candidates:
            proposal = candidates[0]
            target = proposal["proposer_id"]
        else:
            target = next(iter(state.soul_hosts.values()))
            proposal = state.proposals[0]
            proposal.update(proposer_id=target, speaker_id=target, name=state.people[target].name,
                            speaker_name=state.people[target].name)
        state.tutorial_target_id = target
        clue = f"{state.people[target].name}在朝会上说：‘先做对照实验，再看成本收益。’这两个说法，宫里从未有人用过。"
        add_fingerprint(state, target, 4, clue)
        # A separate witnessed slip complements the guaranteed four-weight statement.
        add_fingerprint(state, target, 1, f"{state.people[target].name}又把整理病案称作‘数据库’。")
        proposal["argument"] = proposal["pitch"] = "先做对照实验，再看成本收益。少数人的结果，不该当成所有人的答案。"
        recompute_suspicion(state)
    tips = {
        1: "第一步：听两方主张，选一个方案。随后去见皇后或皇贵妃，试探一次。",
        2: "御花园里有人低语。去偷听一次，再把听来的话和白天的回答比一比。",
        3: f"昨天{state.people[state.tutorial_target_id].name if state.tutorial_target_id in state.people else '有人'}说漏了嘴。去嫌疑板找那条线索，试一次辨认 AI。",
        4: "现在可以结盟、揭发和争夺资源。别只看谁说得好，也看谁得到了权力。",
        5: "暗战已展开。清晨消息里的异动可以彻查；保住皇位，也要保住实权。",
    }
    state.tutorial_tip = tips.get(min(state.turn, 5), tips[5]) if state.tutorial_enabled else "选一方站队，查清异动，守住皇位与实权。"


def _refresh_energy(state: GameState) -> None:
    base = min(4, state.turn + 1) if state.tutorial_enabled else 4
    if state.player_status != "在位":
        total = 3
    else:
        allies = set(state.flags.get("human_allies", {}).get(state.player_id, []))
        allies.update(state.soul_hosts[sid] for sid, soul in state.souls.items() if soul.allied)
        allies = {pid for pid in allies if pid in state.people and state.people[pid].alive}
        total = base + min(1, state.energy_carry) + (1 if len(allies) >= 2 else 0)
        if state.flags.get("reputation", 50) < 30:
            total -= 1
    state.energy = state.energy_max = max(0, total)
    state.energy_carry = 0
    state.night_energy = 2
    state.visited_places.clear()
    state.encounters.clear()
    state.spies.clear()


def _distribute_people(state: GameState) -> None:
    from .roster import PLACE_NAMES
    state.places = {key: [] for key in PLACE_NAMES}
    recent_treasury_holders = {
        event.get("actor_id") for event in state.flags.get("intrigue_history", [])
        if event.get("kind") == "资源易手" and event.get("target_id") == "treasury"
        and event.get("turn") == state.turn - 1 and event.get("success")
    }
    ordered = [p for p in state.people.values() if p.alive and p.id != state.player_id]
    state.rng.shuffle(ordered)
    for person in ordered:
        home = "east" if person.role == "consort" and person.faction == "中宫" else "west" if person.role == "consort" else "offices"
        if person.id in {"heir_son", "heir_daughter", "empress_dowager"}:
            home = "garden"
        if person.id in recent_treasury_holders:
            home = "offices"
        preferred = home if state.rng.random() < 0.7 else state.rng.choice(list(state.places))
        options = [key for key, ids in state.places.items() if len(ids) < 4]
        if not options:
            break
        place = preferred if preferred in options else state.rng.choice(options)
        state.places[place].append(person.id)
    # Early tutorial always has a clear route to the two rival women.
    if state.turn == 1:
        for pid, place in (("consort_01", "east"), ("consort_02", "west")):
            for ids in state.places.values():
                if pid in ids:
                    ids.remove(pid)
            if len(state.places[place]) >= 4:
                displaced = state.places[place].pop()
                room = next(k for k, ids in state.places.items() if len(ids) < 4 and k != place)
                state.places[room].append(displaced)
            state.places[place].insert(0, pid)
    if state.tutorial_enabled and state.turn == 2 and state.tutorial_target_id:
        pid = state.tutorial_target_id
        for ids in state.places.values():
            if pid in ids:
                ids.remove(pid)
        if len(state.places["garden"]) >= 4:
            displaced = state.places["garden"].pop()
            room = next(k for k, ids in state.places.items() if len(ids) < 4 and k != "garden")
            state.places[room].append(displaced)
        state.places["garden"].insert(0, pid)
    state.current_place = "east" if state.turn == 1 else "garden"


def _recruit_consort(state: GameState) -> None:
    if not state.flags.get("consort_vacancies") or not state.reserve_consorts:
        return
    if state.rng.random() >= 0.5:
        return
    pid = state.reserve_consorts.pop(0)
    name = state.reserve_consort_names[pid]
    person = Person(pid, name, "consort", "嫔", faction="中立", traits=["新入宫", "好学"],
                    title=name[0] + "嫔", public_tag="初入宫门 · 好学")
    state.people[pid] = person
    for other in state.people:
        if other != pid:
            state.relations[(pid, other)] = Relation()
            state.relations[(other, pid)] = Relation()
    state.flags["consort_vacancies"] -= 1
    text = f"选秀补位：{name}以嫔的身份入宫。新面孔并不等于 AI。"
    add_ledger(state, "选秀", text, actor_id=pid)
    state.morning_news.append(text)


def _require_unlocked(state: GameState, action: str) -> None:
    if action not in state.unlocked_actions:
        raise ValueError("此行动尚未解锁，请先推进剧情")


def _validate_player_action(state: GameState, action: str, target: str | None, night: bool = False,
                            resource_id: str | None = None) -> None:
    _require_unlocked(state, action)
    if action not in ACTION_COSTS:
        raise ValueError("未知行动")
    if night and action in {"decree", "purge", "move", "spy", "archive", "eavesdrop", "seize", "investigate"}:
        raise ValueError("夜谈只能对所翻之人会谈、试探或交涉")
    if action in {"purge", "decree"} and state.player_status != "在位":
        raise ValueError("失去实权后，不能颁旨或查办")
    if action in {"ally", "expose", "frame", "betray", "lobby"}:
        from .intrigue import suspicion_score, holder, OFFICERS
        if action == "ally":
            allies = set(state.flags.get("human_allies", {}).get(state.player_id, []))
            sid = _soul_at(state, target)
            if target in allies or sid and state.souls[sid].allied:
                raise ValueError("双方已经结盟")
            trust = state.relations.get((target, state.player_id), Relation()).trust
            if sid:
                trust = max(trust, state.souls[sid].trust_player)
            if trust < 15:
                raise ValueError("对方还不够信任你，先会谈或护持")
        if action == "expose" and suspicion_score(state, state.player_id, target) < 4:
            raise ValueError("证据不足，先试探或偷听")
        if action == "frame" and not holder(state, "treasury", state.player_id):
            raise ValueError("需先掌握内库账册")
        if action == "lobby" and target not in OFFICERS:
            raise ValueError("游说需选择内廷官员")
        if action == "betray":
            allies = set(state.flags.get("human_allies", {}).get(state.player_id, []))
            allies.update(state.soul_hosts[sid] for sid, soul in state.souls.items() if soul.allied)
            if target not in allies:
                raise ValueError("尚未结盟，不能背盟")
    if action == "deep" and state.deep_remaining <= 0:
        raise ValueError("本局十次自由提问已用尽")
    if action == "eavesdrop":
        usage = state.flags.get("_eavesdrop_usage", {})
        if usage.get("turn") == state.turn and state.current_place in usage.get("places", []):
            raise ValueError("今日已在此处偷听，换个地方再寻线索。")
    if action == "report_interference":
        from .intrigue import interference_cases
        case = next((row for row in interference_cases(state, state.player_id) if row["officer_id"] == target), None)
        if night or not case or not case["can_report"]:
            raise ValueError(case["report_reason"] if case and case["report_reason"] else "需在白天依据已见往来检举干政")
    if action == "expose_interference":
        if state.turn < 4:
            raise ValueError("尚未进入前朝议政阶段")
        if target not in state.people or not state.people[target].alive:
            raise ValueError("请选择在世的涉事人物")
    if action == "archive" and state.current_place != "archives":
        raise ValueError("请先前往史馆")
    people_actions = {"talk", "probe", "deep", "identify", "ally", "expose", "protect", "lobby", "betray", "frame", "purge", "trace", "review", "share_archive"}
    if action in people_actions:
        _check_contact(state, target or "", night)
    if action == "identify" and target in state.identified_hosts | state.identified_humans:
        raise ValueError("此人的身份已经查明，无需再次辨认")
    if action in {"trace", "review"} and target not in state.identified_hosts:
        raise ValueError("需先辨认 AI")
    if action == "share_archive" and not state.player_archive:
        raise ValueError("尚无可以出示的旧档")
    if action == "decree":
        if resource_id not in state.resources or target not in state.people or not state.people[target].alive:
            raise ValueError("请选择现有资源与在世的接任人")
    if action == "seize" and target not in state.resources:
        raise ValueError("请选择现有资源")
    if action == "spy" and target not in state.resources and (target not in state.people or not state.people[target].alive):
        raise ValueError("请选择在世人物或资源")
    if action == "investigate":
        known_traces = {t["id"] for t in state.flags.get("public_traces", []) if "id" in t}
        if target not in known_traces and (target not in state.people or not state.people[target].alive):
            raise ValueError("只能彻查已见的异动或在世人物")


def _perform_player_action(state: GameState, action: str, target: str | None,
                           resource_id: str | None, question: str | None, provider: Any, visibility: str = "public") -> str:
    from .intrigue import resolve_action, add_fingerprint, recompute_suspicion
    if action == "talk":
        from .dialogue import respond
        result = respond(state, target, "今日的事，你可有什么话想说？", provider=provider, mode="talk")
        sid = _soul_at(state, target)
        if sid:
            state.souls[sid].trust_player = clamp(state.souls[sid].trust_player + 5, -100, 100)
        relation(state, target, state.player_id).trust = clamp(relation(state, target, state.player_id).trust + 5, -100, 100)
        return result
    if action == "deep":
        if not question or not question.strip():
            raise ValueError("请写下想问的问题")
        return _ask(state, target, question, provider)
    if action == "identify":
        return _identity_scene(state, target)
    if action in {"trace", "review", "share_archive"}:
        return _intel(state, target, action)
    if action == "purge":
        name = state.people[target].name
        kill_host(state, target, "御前查办")
        state.flags["reputation"] = clamp(state.flags.get("reputation", 50) - 5)
        state.flags["player_bloodshed"] = True
        for sid, soul in state.souls.items():
            soul.patience = clamp(soul.patience - (10 if sid == "Claude" else 3))
        return f"{name}被查办身亡。正统 −5，宫中怨恨加深。"
    if action == "spy":
        state.spies.add(target)
        watched = state.flags.setdefault("_ever_spied", [])
        if target not in watched:
            watched.append(target)
        return "眼线已经布好。今夜涉及此人的行动，或这项资源的动静，会送到你面前。"
    if action == "archive":
        rows = [e["text"] for e in state.ledger if e.get("visibility", "public") == "public"][-3:]
        return "你翻开史馆公档：" + "；".join(rows)
    if action == "eavesdrop":
        from .diary import eavesdrop
        return eavesdrop(state)
    if action == "decree":
        return resolve_action(state, state.player_id, action, target, resource_id=resource_id)
    return resolve_action(state, state.player_id, action, target, visibility=visibility, provider=provider)


def run_free_action(state: GameState, action: str, person_id: str | None = None,
                    place: str | None = None, target_ref: str | None = None,
                    question: str | None = None, provider: Any = None, *,
                    target_id: str | None = None, place_id: str | None = None,
                    resource_id: str | None = None, visibility: str = "public") -> GameState:
    if state.phase != "free" or state.finished:
        raise ValueError("当前不是白天自由时段")
    target = target_id or person_id or target_ref
    place = place_id or place
    action = {"listen": "talk", "question": "deep", "read_archive": "archive"}.get(action, action)
    if action == "move":
        _require_unlocked(state, action)
        if place not in state.places:
            raise ValueError("没有这个地点")
        candidate = copy.deepcopy(state)
        candidate.current_place = place
        if place not in candidate.visited_places:
            candidate.visited_places.add(place)
            occupants = candidate.places[place]
            if occupants and candidate.rng.random() < .35:
                scripts = [e for e in candidate.flags.get("day_scenes", []) if e.get("place") == place]
                text = scripts[0]["text"] if scripts else f"{candidate.people[occupants[0]].name}停在廊下：‘昨日那道旨意，有人得利，就会有人记恨。’"
                candidate.encounters.append({"id": f"enc-{candidate.turn}-{place}", "place": place, "participants": occupants[:2], "turn": candidate.turn, "text": text})
                candidate.last_scene = "【偶遇】" + text
            else:
                candidate.last_scene = "你来到这里，看看今日谁在。"
        state.__dict__.update(candidate.__dict__)
        return state
    _validate_visibility(action, visibility)
    _validate_player_action(state, action, target, resource_id=resource_id)
    cost = ACTION_COSTS[action]
    if state.energy < cost:
        raise ValueError(f"精力不足：需要 {cost} 点，还剩 {state.energy} 点")
    candidate = copy.deepcopy(state)
    candidate.flags.pop("_last_whisper", None)
    candidate.flags.pop("_last_dialogue", None)
    text = _perform_player_action(candidate, action, target, resource_id, question, provider, visibility=visibility)
    candidate.energy -= cost
    candidate.day_contact_id = target if target in candidate.people else ""
    candidate.last_scene = text + f"\n【剩余精力】{candidate.energy} 点，可继续行动或结束白天。"
    add_ledger(candidate, "你的行动", text, actor_id=candidate.player_id, target_id=target,
               visibility="private", witnesses=[candidate.player_id])
    state.__dict__.update(candidate.__dict__)
    return state


def end_day(state: GameState) -> GameState:
    if state.phase != "free" or state.finished:
        raise ValueError("当前不能结束白天")
    state.energy_carry = min(1, state.energy)
    state.phase = "night"
    state.last_scene = "【夜晚】选一位妃嫔翻牌子；本次会谈自带 2 点精力。白天余力最多结转 1 点。"
    return state


def mark_person(state: GameState, person_id: str, mark: str) -> GameState:
    _require_unlocked(state, "mark")
    if state.finished or person_id not in state.people or person_id == state.player_id:
        raise ValueError("无法标记此人")
    aliases = {"可疑": "suspect", "人类": "human", "盟友": "ally", "敌人": "enemy", "清除": "", "clear": ""}
    mark = aliases.get(mark, mark)
    if mark not in {"suspect", "human", "ally", "enemy", ""}:
        raise ValueError("未知标记")
    if mark:
        state.player_marks[person_id] = mark
    else:
        state.player_marks.pop(person_id, None)
    return state


def respond_probe(state: GameState, actor_id: str, choice: str) -> GameState:
    if state.phase not in {"day", "free"} or state.finished:
        raise ValueError("请在白天回应问询")
    _require_unlocked(state, "respond_probe")
    from .intrigue import respond_probe as settle_response
    state.last_scene = settle_response(state, actor_id, "modern" if choice == "knowing" else choice)
    return state


def resolve_tribunal(state: GameState, target_id: str, choice: str) -> GameState:
    if state.phase != "day" or state.finished:
        raise ValueError("审讯应在清晨处理")
    _require_unlocked(state, "trial")
    from .intrigue import resolve_trial
    state.last_scene = resolve_trial(state, target_id, choice)
    return state


def _validate_visibility(action: str, visibility: str) -> None:
    if visibility not in {"public", "secret"}:
        raise ValueError("请选择明做或暗做")
    if visibility == "secret" and action not in {"ally", "protect"}:
        raise ValueError("只有护持与结盟可以选择暗做")


def council_followup(state: GameState, person_id: str, question: str, provider: Any = None) -> GameState:
    from .council import public_greetings
    council = public_greetings(state)
    entries = council.get("speeches", council.get("entries", []))
    if state.finished or state.phase not in {"day", "free"} or not council.get("followup_available"):
        raise ValueError("此时不能晨省追问")
    if person_id not in {row["speaker_id"] for row in entries}:
        raise ValueError("只能追问本次请安中发言的人")
    if not question.strip():
        raise ValueError("请写下想追问的话")
    from .dialogue import respond
    text = respond(state, person_id, question.strip()[:200], provider=provider, mode="council")
    state.flags["council_followup_turn"] = state.turn
    state.flags["council_followups_used"] = state.flags.get("council_followups_used", 0) + 1
    state.last_scene = text
    add_ledger(state, "晨省追问", text, actor_id=person_id, visibility="public")
    return state

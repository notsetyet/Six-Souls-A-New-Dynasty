"""九幕的因果骨架：只记录已经发生的选择，不向玩家预告暗中计划。"""
from __future__ import annotations

from typing import Any
from .state import add_ledger, clamp

THREAD_NAMES = {"illness": "皇子之病", "accounts": "两本账", "gates": "宫门"}
TURN_THREAD = {1: "illness", 2: "illness", 3: "accounts", 4: "accounts", 5: "gates", 6: "accounts", 7: "gates", 8: "illness", 9: "accounts"}


def enabled(state: Any) -> bool:
    # Legacy cards remain available to explicitly replay v2 regression fixtures.
    from .config import feature_enabled
    return feature_enabled(state, "story_threads") and not getattr(state, "flags", {}).get("legacy_events", False)


def initialize_threads(state: Any) -> None:
    if not hasattr(state, "threads"):
        state.threads = {}
    for key, title in THREAD_NAMES.items():
        state.threads.setdefault(key, {"title": title, "progress": 0, "history": [], "outcome": "尚未展开"})
    state.flags.setdefault("prince_condition", "高热")


def prince_alive(state: Any) -> bool:
    prince = state.people.get("heir_son")
    return bool(prince and prince.alive)


def branch_id(state: Any) -> str:
    initialize_threads(state)
    if state.turn == 1:
        return "prince_fever"
    if state.turn == 2:
        if not prince_alive(state):
            return "mourning_second_case"
        return "second_fever_relapse" if state.flags.get("prince_condition") == "反复" else "second_fever"
    if state.turn == 3:
        return "missing_ledger_records" if state.flags.get("medical_records") else "missing_ledger_silence"
    if state.turn == 4:
        return "river_accounts" if state.flags.get("ledger_secured") else "exam_accounts"
    if state.turn == 5:
        return "border_guardianship" if prince_alive(state) else "border_clan_council"
    if state.turn == 6:
        return "dual_books_traceable" if state.flags.get("ledger_secured") else "dual_books_gap"
    if state.turn == 7:
        return "gate_lists_checked" if state.flags.get("guard_joint_register") else "gate_lists_secret"
    if state.turn == 8:
        return "heir_survivor" if prince_alive(state) else "heir_after_loss"
    return "charter_open_accounts" if state.flags.get("audit_open") else "charter_sealed_accounts"


def contextual_event(state: Any, event: Any) -> Any:
    """Adapt public succession options to publicly known absence, never AI identity."""
    if event.id not in {"heir_survivor", "heir_after_loss"}:
        return event
    princess = state.people.get("heir_daughter")
    if princess and princess.alive and princess.id not in {state.current_ruler_id, state.player_id}:
        return event
    from dataclasses import replace
    prince = prince_alive(state) and state.current_ruler_id != "heir_son"
    title = "皇子与宗室同议资格" if prince else "公开核验宗室两支资格"
    description = ("公主现已不在可议储的人选中。把在世皇嗣与宗室候选的抚育记录分开核验，辅佐者不得借旧恩独代决断。")
    result = "候选人的资格须由多方核验；宫中旧日照料的恩情，不能让任何一人独掌储位。"
    replacement = replace(event.policies[0], id="consider_clan_candidates", title=title,
                          description=description, result=result,
                          metric_delta={"openness": 5, "knowledge": 2, "stability": -3},
                          flags={"female_succession": False}, modernity=2,
                          doctrine_tags=("Kimi", "Gemini"))
    return replace(event, policies=(replacement, event.policies[1]))


def opening_lines(state: Any) -> list[str]:
    prince = state.people.get("heir_son")
    pname = prince.name if prince else "皇子"
    # These are the room's visible actions, not a predetermined AI assignment.
    return [
        f"三更过后，皇子{pname}仍在高热。药碗搁凉了，御医只敢伏在帘外。",
        "皇后沈徽昭按住要抱孩子出门的乳母：‘先别移宫。煮布、分开用水，每个时辰都把热度记下来。’",
        "皇贵妃楚望舒拦在门边：‘昨夜已经折腾一回了。先依祖制祈福，再移到干净暖和的宫室，别把孩子当成试法子的物件。’",
        "皇后沈徽昭脱口而出：‘没有连续记录，怎么排除变量？’殿里忽然静了。她垂下眼，把最后两个字咽了回去。",
    ]


def story_bridge(state: Any) -> str:
    initialize_threads(state)
    if state.turn <= 1:
        return ""
    if state.turn == 2:
        if not prince_alive(state):
            return "【皇子之病】昨夜小殿撤了灯，皇子的药碗还在。今晨，照料过他的宫女也开始发热；病案里缺了她的名字。"
        condition = state.flags.get("prince_condition", "反复")
        return f"【皇子之病】上次那碗药之后，皇子病情{condition}。今晨照料他的宫女也发了热，御医终于承认：这不只是一个孩子的病。"
    if state.turn == 3:
        kept = "病案逐日记着用药" if state.flags.get("medical_records") else "几夜药钱只有口头报数"
        return f"【两本账】皇子寝殿的药炉还没撤，内务府先报了失窃。{kept}；如今药单上的银数，竟与内库账不合。"
    if state.turn == 4:
        return ("【两本账】上次封下的残页写着‘河工垫支’。后宫药钱为何流向前朝？官员今日带来河堤与科举两份用银单。"
                if state.flags.get("ledger_secured") else "【两本账】上次允了先补银，失窃旧账却仍缺一页。如今河工、科举都拿同一张借据讨款，必须有人说明银子从哪里来。")
    if state.turn == 5:
        family = "皇子退热后，宫中又为接回抚育的事起了争执。" if prince_alive(state) else "皇子夭折后，宗室已有两支争着送子入宫。"
        previous = next((row for row in state.threads["accounts"]["history"] if row["turn"] == 4), None)
        if previous and not previous.get("enacted", True):
            prior = f"上次关于「{previous['choice']}」的密函尚未获准，"
        elif previous:
            prior = f"上次「{previous['choice']}」的签押还在案上，"
        else:
            prior = "药钱与前朝用银的旧账尚未理清，"
        return f"【宫门】{prior}边军又送来一封请求调兵的边报。{family}谁接走孩子、谁换进侍卫，都要经过同一座宫门。"
    if state.turn == 6:
        if state.flags.get("ledger_secured"):
            return "【两本账】第三幕封下的药钱残页，如今能与新送来的边饷抄本核对。同一笔银在两处各记了一次；要分清是谁签押，不能只听经办人解释。"
        return "【两本账】第三幕失窃的原页仍未找回，内务府却送来了两份新抄账：同一笔银，一份记药钱，一份记边饷。抄本能否代替原件，成了新的争执。"
    if state.turn == 7:
        if state.flags.get("guard_joint_register"):
            return "【宫门】边军按上次的联署名册交班；今晨多出的一行名字，偏偏没有第二人的签押。"
        if "guard_joint_register" in state.flags:
            return "【宫门】上次准许密调的侍卫到了。今晨另一班守门人却不认口令，双方各持一张盖着真印的名单。"
        return "【宫门】上次的换防请求尚未经你施行，宫门前却出现了一班持密令的侍卫。旧班不肯交钥匙，两张名单竟都盖着真印。"
    if state.turn == 8:
        return ("【皇子之病】皇子抱着旧病案走到御前：‘儿臣记得那晚是谁守在床边。’当日谁救过他、谁争过抚育，如今都成了储议里的理由。"
                if prince_alive(state) else "【皇子之病】小殿早已封门，皇子留下的旧病案今日又送到了御前。宗室催着给养子正名；那夜没能救回的孩子，仍在改变今日的储位。")
    settled = state.flags.get("succession_adopted")
    succession = "储位虽已奉旨裁定，" if settled else "储位陈情尚未奉你的旨意施行，"
    return f"【两本账 · 宫门】{succession}药钱、边饷与轮值的争执仍要落到一张章程上。门外等着新口令，案前等着御玺；谁能发出下一道旨意，要看今夜谁仍掌实权。"


def public_threads(state: Any) -> list[dict]:
    initialize_threads(state)
    return [{"id": key, "title": THREAD_NAMES[key], "progress": value["progress"],
             "outcome": value["outcome"], "summary": value["outcome"], "history": [dict(row) for row in value["history"]]}
            for key, value in state.threads.items() if key in THREAD_NAMES]


def _record(state: Any, key: str, event: Any, policy: Any, outcome: str, *, enacted: bool = True) -> None:
    track = state.threads[key]
    track["progress"] += 1
    track["outcome"] = outcome
    track["history"].append({"turn": state.turn, "event_id": event.id, "title": event.title,
                             "choice": policy.title, "outcome": outcome, "enacted": enacted})


def record_unenacted(state: Any, event: Any, policy: Any, result: str) -> None:
    """A captive ruler's letter advances the chronicle, never the proposed effects."""
    initialize_threads(state)
    if state.turn not in TURN_THREAD:
        return
    outcome = f"{result} 此案尚未施行。"
    _record(state, TURN_THREAD[state.turn], event, policy, outcome, enacted=False)
    if state.turn == 5:
        _record(state, "illness", event, policy, "抚育或宗室议立的陈情已送出，尚未获得朝廷采纳。", enacted=False)
    if state.turn == 9:
        _record(state, "gates", event, policy, "宫门与章程的密函已经送出，最终实权仍由实际局势决定。", enacted=False)
    add_ledger(state, "主线", f"【{THREAD_NAMES[TURN_THREAD[state.turn]]}】{outcome}", visibility="private", witnesses=[state.player_id])


def _advance_reform(state: Any, policy: Any) -> str:
    """Pay for enacted follow-through, not merely possessing a facility flag.

    The v3 story replaced the old school/works cards. Their continuing public
    benefits belong to these explicit later decisions, with the same retained
    political costs. A captive ruler's unadopted letter never enters this path.
    """
    if state.player_status != "在位":
        return ""
    f = state.flags
    milestone, delta, flags, text = "", {}, {}, ""
    if state.turn == 2 and policy.id in {"record_safe_care", "save_witness_records"}:
        milestone = "public_care"
        delta, flags = {"knowledge": 2, "livelihood": 3}, {"public_health": True}
        text = "两份病案对照后，太医院把已核验的净水、隔离和护理办法传给城中医馆；未知新药仍不得擅试。"
    elif (state.turn == 4 and policy.id in {"river_public_fund", "exam_verify_places"}
          and f.get("archives") and f.get("medical_records")):
        milestone = "practical_training"
        delta, flags = {"knowledge": 4, "livelihood": 3}, {"schools": True}
        text = "封存的原账使拨款有据可查。官学与工匠合办传习，教人读图、算工料并留底复核，宫外已有第一批人学会使用新法。"
    elif (state.turn == 5 and policy.id == "guard_joint_register"
          and f.get("schools") and (f.get("workshops") or f.get("exam_reform"))):
        milestone = "verified_replication"
        delta = {"knowledge": 3}
        text = "先前传习的匠人参与两班共同检修；失效与修复记录一并送回官学，另一班照着图册也能重做。"
    elif (state.turn == 6 and policy.id == "open_dual_audit"
          and f.get("archives") and f.get("funds_tracked")):
        milestone = "audited_funding"
        delta, flags = {"knowledge": 4, "livelihood": 3}, {"public_archive": True}
        text = "原账与逐项拨银接上了。追回的款项续供医馆和传习，办事者须公开成败、支出与受益名单，外地也能据此复核。"
    elif (state.turn == 9 and policy.id == "charter_checks"
          and f.get("schools") and f.get("public_archive")
          and f.get("guard_joint_register") and f.get("gate_verified")):
        milestone = "public_rollout"
        delta, flags = {"knowledge": 8, "livelihood": 4}, {"reform_rollout": True}
        text = "传习、病案、拨银和交接已有可复核的底本。新章程把培训、续拨与异地照办列为常例，允许平民学徒入学；第一批外地医馆和工坊开始照章运行。"
    if not milestone:
        return ""
    completed = f.setdefault("reform_milestones", {})
    if milestone in completed:
        return ""
    for metric, amount in delta.items():
        state.metrics[metric] = clamp(state.metrics[metric] + amount)
    f.update(flags)
    completed[milestone] = {"turn": state.turn, "policy_id": policy.id,
                            "metric_delta": dict(delta), "text": text}
    add_ledger(state, "新政落实", text, actor_id=state.player_id, visibility="public")
    return text


def resolve_policy(state: Any, event: Any, policy: Any) -> str:
    """Authoritative story settlement. All mortality draws use this game's RNG."""
    initialize_threads(state)
    if not event.id.startswith(tuple(["prince_", "second_", "mourning_", "missing_", "river_", "exam_accounts", "border_guard", "border_clan", "dual_", "gate_lists", "heir_survivor", "heir_after", "charter_"])):
        return ""
    extra = ""
    if state.turn in (1, 2) and prince_alive(state):
        # These are fictional branch odds, not diagnoses or clinical advice.
        mortality = {"separate_and_record": .04, "pray_and_move": .26,
                     "record_safe_care": .03, "unrecorded_old_remedy": .16}.get(policy.id, .08)
        draw = state.rng.random()
        if draw < mortality:
            from .engine import kill_host
            kill_host(state, "heir_son", "热病未愈")
            state.flags["prince_condition"] = "夭折"
            extra = "后半夜，皇子的呼吸停了。御医跪在灯影里，生母把那张未写完的病案攥出了褶。宗室议立的帖子，天亮前就送到了宫门。"
            state.flags["prince_died_turn"] = state.turn
        else:
            recovered = policy.id in {"separate_and_record", "record_safe_care"} or state.turn == 2
            state.flags["prince_condition"] = "渐稳" if recovered else "反复"
            extra = ("天亮时皇子的热势渐退，乳母终于敢换一碗温粥；那份记录被御医折好，收进了病案。" if recovered else
                     "移宫后皇子一度睡去，黎明却又烧起来。守夜宫女的额头也烫了，谁都不敢先开口。")
    elif state.turn == 5:
        if prince_alive(state):
            mother = state.flags.get("birth_mother_id", "consort_01")
            chosen = mother if policy.id == "guard_relieved_border" else "consort_01"
            if chosen not in state.people or not state.people[chosen].alive:
                current_guardian = state.people["heir_son"].guardian_id
                chosen = current_guardian if current_guardian in state.people and state.people[current_guardian].alive else state.player_id
            if chosen in state.people and state.people[chosen].alive:
                state.people["heir_son"].guardian_id = chosen
                extra = f"皇子的抚育暂交{state.people[chosen].name}，病案仍由太医院留底；接送不得另开宫门。"
        else:
            extra = "宗室议立被列入第八幕储议。现有接棒人只作应急安排，公主与宗室子的资格仍待御前裁定。"
    elif state.turn == 8:
        state.flags["succession_adopted"] = policy.id
        if policy.id in {"hear_princess", "princess_succession"}:
            princess = state.people.get("heir_daughter")
            state.flags["female_succession"] = True
            if princess and princess.alive and princess.id != state.player_id:
                state.designated_heir_id = princess.id
                extra = f"{princess.name}的名字第一次写入正储文书；六宫只得安静听完。"
        elif prince_alive(state) and "heir_son" != state.player_id:
            state.designated_heir_id = "heir_son"
            extra = "皇子的储位写入正册，照料旧恩不再是任何一宫独占的权柄。"
        else:
            # kill_host has already established a legal emergency successor.
            candidate = state.people.get(state.designated_heir_id)
            extra = f"宗室子{candidate.name if candidate else '承嗣'}的应急安排转为正式储议；皇子的旧病案另封一匣。"
    reform = _advance_reform(state, policy)
    if reform:
        extra = (extra + " " + reform).strip()
    outcome = (policy.result + (" " + extra if extra else ""))
    _record(state, TURN_THREAD[state.turn], event, policy, outcome)
    if state.turn == 5:
        _record(state, "illness", event, policy, extra)
    if state.turn == 9:
        _record(state, "gates", event, policy, "宫门是否听命，须看今夜实际的守卫与盟友。")
    add_ledger(state, "主线", f"【{THREAD_NAMES[TURN_THREAD[state.turn]]}】{outcome}", visibility="public")
    return extra


def build_events(Event, Policy):
    """18 authored branch cards, including the second-night relapse variation."""
    def p(id, title, description, result, delta, modernity, doctrines, flags=None):
        return Policy(id, title, description, result, delta, flags=flags or {}, modernity=modernity, doctrine_tags=tuple(doctrines))
    def card(id, turn, title, summary, pressure, a, b):
        return Event(id, turn, title, summary, pressure, (a, b))
    cards = [
        card("prince_fever", 1, "皇子高热", "三更，小殿灯火未熄。皇后要隔开病人、沸水煮布并逐时记下热度；皇贵妃主张按祖制祈福，移宫避煞。两人都守着药碗，却不肯让步。", "乳母已经抱起孩子，等你开口。",
            p("separate_and_record", "留在原殿，隔离记病案", "分开用水、煮布，记下每次用药与热度。让皇后负责，但御医每日署名。", "殿门合上，皇后留下守夜。‘热度’二字被御医在病案上圈了一遍。", {"knowledge": 3, "stability": -1}, 3, ("Gemini", "Claude"), {"medical_records": True, "medicine": True}),
            p("pray_and_move", "按旧例祈福移宫", "先由皇贵妃安排祈福和移宫，照旧方用药，免得六宫争执耽误救治。", "祈福的铃声到了廊下；皇贵妃亲自跟着软轿，皇后只留下那张空白病案。", {"stability": 2, "knowledge": -1}, 0, ("Codex", "MiniMax"))),
        card("second_fever", 2, "宫中第二例", "守夜宫女也发了热。御医要把她与皇子的用药并列记录；有人悄悄送来一包‘见效快’的新药，不肯写配方。", "那名宫女正等着今晚的药，不是纸上的一个数。",
            p("record_safe_care", "先救治，留下病案复核", "继续照料，先查配方与用量；把核验过的护理办法传给城中医馆，未知新药不得直接试在病人身上。", "宫女得了照料，两份病案并排留存。送药人却要求拿回包药纸。", {"knowledge": 3, "stability": 1}, 2, ("Claude", "Gemini"), {"medical_records": True, "medicine": True}),
            p("unrecorded_old_remedy", "停新药，按旧方封院救治", "拒绝来路不明的新方，太医院照祖方行事，病情暂不传出内院。", "新药被封起，宫女仍按旧方用药；院门外只听见‘无碍’两个字。", {"stability": 2, "openness": -2}, 0, ("Codex", "Kimi"), {"hidden_epidemic": True})),
        card("mourning_second_case", 2, "白幡下的第二例", "皇子夭折，小殿已挂白幡。照料他的宫女今晨也发了热，御医请保住病案查明传染路径；六宫有人坚持先问罪。", "宫女被押在门外，药还没有送到。",
            p("save_witness_records", "先救人，复核皇子旧病案", "不许拿病人抵罪；把宫女与皇子的用药放在一起核对，再将核验过的护理办法传给城中医馆。", "宫女被送回病榻。旧病案上第一次补写了守夜人的姓名。", {"knowledge": 3, "stability": -1}, 2, ("Claude", "Kimi"), {"medical_records": True, "medicine": True}),
            p("seal_case_inquiry", "封院救治，另审失职者", "先封住病院，医治照旧；由皇后查谁漏报病情，口供暂不公开。", "药照常送进，封条却贴满了院门。人人急着证明自己那夜不在场。", {"stability": 2, "openness": -2}, 0, ("Codex", "MiniMax"), {"hidden_epidemic": True})),
        card("missing_ledger_records", 3, "药单上的缺页", "内务府报称药库失窃。病案记着三十副药，内库却销了九十副；账册恰好缺了那一页。两宫被请来对账，争的是宫中药钱。", "抄账宫女说，原页并没有烧掉。",
            p("seal_ledger_witness", "封原账，保护抄账宫女", "让两宫各留副本，先核药钱，不许私下换人。", "残页被封进匣子，背面露出‘河工垫支’四个字。", {"knowledge": 2, "openness": 2, "stability": -1}, 2, ("Kimi", "Gemini"), {"ledger_secured": True, "archives": True}),
            p("replace_silver_first", "先补药银，内务府自查", "让病人先有药，准内务府限期补账，暂不扩大问罪。", "药银补齐，管事拿回了账匣；送药的宫人说，匣里似乎轻了一张纸。", {"livelihood": 2, "stability": 1}, 1, ("DeepSeek", "Codex"), {"ledger_secured": False})),
        card("missing_ledger_silence", 3, "无人签字的药钱", "病院只报平安，内务府却报药库失窃。皇子那几夜用了多少药，竟没有两份说法相同；账册还少了一页。", "两宫都说银子已经交足，乳母却还欠着药钱。",
            p("recover_ledger_testimony", "逐一问乳母，封存残账", "补记实际用药，留住抄账人，禁止两宫私下对口供。", "乳母认出了一笔没送进寝殿的药银，残账被封存。", {"knowledge": 2, "stability": -2}, 2, ("Kimi", "Claude"), {"ledger_secured": True, "medical_records": True, "archives": True}),
            p("palace_quiet_settle", "两宫补齐欠银，内务府自查", "先把欠药银补上，给内务府一幕时间补账，六宫不得互相指摘。", "欠银还了，宫里暂且安静；抄账宫女却被调离了药库。", {"stability": 2, "openness": -2}, 0, ("Codex", "MiniMax"), {"ledger_secured": False})),
        card("river_accounts", 4, "河堤银从哪里来", "药钱残页指向河工。军机朝臣主张先修堤、逐项公开开支；内务府管事提议先用科举学额的余银填缺口。两份前朝奏议背后，都有人递过话。", "汛期不等审账，挪银也会欠下一笔新账。",
            p("river_public_fund", "先修险堤，逐项公示拨银", "保留药钱原账，河工另立签押；雇匠测水位，图纸留档。有可核病案和原账时，合办官学传习，让平民学徒学会读图算料。", "堤工开了，河工与药库从此不能混填同一张支单。", {"livelihood": 5, "knowledge": 3, "stability": -2}, 2, ("DeepSeek", "Kimi"), {"workshops": True, "funds_tracked": True}),
            p("exam_limited_fund", "先核科举学额，再调余银", "限期清点官学虚额，把余银暂拨河堤；由军机处统一签押。", "虚学额被划去，堤工慢了一步；军机处握住了两项开支的签押。", {"knowledge": 2, "stability": 2, "openness": -1}, 1, ("Codex", "Gemini"), {"exam_reform": True, "funds_tracked": False})),
        card("exam_accounts", 4, "一张借据，两处用银", "失窃账页尚未找回，河工与科举都持同一张借据讨银。军机朝臣请查虚学额、试行算学策论；管事主张先把河工银发下去。", "不先核账就可能再付一次，等核完又可能错过汛期。",
            p("exam_verify_places", "清查学额，试行实学策论", "把虚报的学额与药银借据对照；先在一地试行，不动救急药钱。有可核病案和原账时，用实学名额开办工匠传习。", "学额底册找到了借据编号，河工还在等银，朝臣先为新试卷争了起来。", {"knowledge": 4, "openness": 2, "stability": -2}, 2, ("Gemini", "Kimi"), {"exam_reform": True, "funds_tracked": True}),
            p("river_emergency_advance", "先发河工救急银，事后核账", "停缓学额争论，让内务府统一垫付，汛后限期归账。", "堤工先动起来，第二张借据又盖上了同一枚印。", {"livelihood": 4, "stability": 1, "openness": -2}, 1, ("DeepSeek", "MiniMax"), {"workshops": True, "funds_tracked": False})),
        card("border_guardianship", 5, "边报与接皇子的车", "边军请求检修兵器并换入一班侍卫，海商同时请以军需贸易抵银。宫中送来两份接皇子出入的请示，都要走这次换防的宫门。官员只议军费与守卫，抚育另由御前裁断。", "兵马和孩子的车不能共用一道无人核验的口令。",
            p("guard_joint_register", "检修边军，换防须双签", "先验兵器和名单，两班共同点验；若已办传习，让学徒照图复做并留下失效记录。皇子暂留现居宫室，太医院继续复诊。", "两班侍卫当面签了名，边军开支多留一份底单。", {"knowledge": 3, "stability": 2}, 2, ("Gemini", "Claude"), {"guard_joint_register": True, "military_reform": True}),
            p("guard_relieved_border", "准军需通商，密调亲卫", "以海商军需补银，名单只报御前；皇子暂随在世亲属静养，接送走专门口令。", "海商的银先到了，亲卫换班也快；只有几个人见过完整名单。", {"livelihood": 4, "openness": 1, "stability": -2}, 1, ("MiniMax", "DeepSeek"), {"guard_joint_register": False, "trade_port": True})),
        card("border_clan_council", 5, "边报与宗室议立", "皇子已逝，两支宗室送来的孩子都在宫门外等。边军请增派侍卫，海商愿以军需贸易补银；谁管换防，谁就能决定哪辆车先入宫。", "军费议完，还须给宗室议立一个不受武力左右的章程。",
            p("guard_joint_register", "检修边军，宗室入宫双验", "守卫与宗室名册分别留底；若已办传习，两班检修须照图复做并留记录。不许边军护送任何一支宗室，储议留到第八幕。", "宗室两车同时候在门外，双签名单留下了第一道界限。", {"knowledge": 2, "stability": 2}, 2, ("Gemini", "Claude"), {"guard_joint_register": True, "military_reform": True}),
            p("guard_relieved_border", "准军需通商，御前密定接送", "让海商补军费，亲卫凭密令接送宗室；两支资格仍待储议。", "接送快了，谁握有那张密令却成了新的筹码。", {"livelihood": 4, "openness": 1, "stability": -2}, 1, ("DeepSeek", "MiniMax"), {"guard_joint_register": False, "trade_port": True})),
        card("dual_books_traceable", 6, "两本账终于对上", "被封存的药钱残页、河工借据、边饷支单同时摆在案上。同一笔银在两本账里各花了一次；主事官员互称自己只照另一份签押办事。", "查清一次签押，就可能查出谁在官员背后递话。",
            p("open_dual_audit", "公开两本账，逐笔对质", "保住抄账人，药银、河工、边饷一起核；每笔签押须本人解释。有原账和逐项拨银记录时，追回款项续供医馆、传习并公开成败。", "三份单据首尾相接。亏空公开，幕后递话的人也不能再假装只管宫中。", {"openness": 4, "knowledge": 2, "stability": -3}, 3, ("Kimi", "Gemini"), {"audit_open": True, "copy_dispute_resolved": True, "copy_dispute_public": True}),
            p("seal_dual_audit", "密核追回银，暂留经办人", "由御前掌握两份原本，责令补回差额；暂不公开牵连的宫室。", "亏银追回一部分，经办人继续办事，密封的账匣成了御前筹码。", {"stability": 3, "openness": -2}, 1, ("Codex", "MiniMax"), {"audit_open": False, "copy_dispute_resolved": True, "copy_dispute_public": False})),
        card("dual_books_gap", 6, "补不回来的那一页", "药钱与边饷各有一本账，失窃原页却始终没找回。有人拿新抄本要求销案，抄账宫女认出纸上是后来改的年款。", "新本能让开支继续，也可能把旧亏空洗成合法。",
            p("open_dual_audit", "先保证人，再公开逐笔追查", "不把新抄本当原件；药银、河工和边饷一并复核，暂缓争议款。只有原账和逐项拨银可核时，才续供医馆、传习并公开成败。", "缺页仍在，但伪装完整的账被拆穿了；官员不得不解释是谁催他们销案。", {"openness": 4, "knowledge": 2, "stability": -3}, 3, ("Kimi", "Claude"), {"audit_open": True, "copy_dispute_resolved": True, "copy_dispute_public": True}),
            p("seal_dual_audit", "按新抄本续拨，原案密查", "先保军费与药钱，不让账案拖住日用；新本只在御前备案。", "银继续发，空白也被一行‘已核’盖住。旧案从此只有密匣里的口供能追。", {"stability": 3, "openness": -3}, 0, ("Codex", "MiniMax"), {"audit_open": False, "copy_dispute_resolved": True, "copy_dispute_public": False})),
        card("gate_lists_checked", 7, "名单上多出的名字", "双签轮值册中多了一名没有第二签押的侍卫。侍卫统领称是救急补缺，军机朝臣却认出此人曾随内库送过账。", "今晚换班前，必须决定谁留在门内。",
            p("gate_crosscheck", "复核两班，保留旧口令一夜", "保护递交原册的守卫，逐名查人，御前保留第二道验印。", "多出的名字被暂停，旧班没有撤尽。想只凭一张纸进宫的人，必须再过一道门。", {"stability": 3, "openness": 2}, 2, ("Gemini", "Kimi"), {"gate_verified": True, "guard_reform": True}),
            p("gate_single_command", "立即换班，口令统一归统领", "避免两班争执，由统领签保补缺者，明日再查。", "新班按时入门，旧口令当场焚毁；一枚签押能放行的人更多了。", {"stability": 2, "openness": -3}, 0, ("Codex", "MiniMax"), {"gate_verified": False, "private_guard": True})),
        card("gate_lists_secret", 7, "两道都是真的密令", "一班持密令的亲卫与统领的新班撞在宫门，两张密令都盖着真印。一个说护驾，一个说奉旨换防，谁也不肯交刀；是否真正奉旨，仍须核验。", "若没人能核验原令，争执会替暗处的人开门。",
            p("gate_crosscheck", "当众验原令，分开两班", "让军机与御前共同验印，旧班留守，暂不认后来加上的名字。", "两班被分开，后来补写的名字露了出来；密令的来路终于有人肯作证。", {"stability": 3, "openness": 2}, 2, ("Gemini", "Claude"), {"gate_verified": True, "guard_reform": True}),
            p("gate_single_command", "只认统领，立刻交钥匙", "先结束对峙，把宫门钥匙与解释权一并交给统领。", "刀收回鞘里，钥匙也交了出去。旧班退到宫墙外等明日。", {"stability": 2, "openness": -3}, 0, ("Codex", "MiniMax"), {"gate_verified": False, "private_guard": True})),
        card("heir_survivor", 8, "病案前的储位之议", "皇子已经能独自行礼，宫人带来他病中那份逐日记录。官员在外廷议储，宫中抚育陈情另呈，不得亲提前朝政策。", "旧日救命与照料的恩情，能不能变成永久替储君作主的权力？",
            p("hear_princess", "皇子公主同议，写明监护界限", "以能力与职责议储，公主列入资格；任何一宫不得因抚育而独代储君决断。", "公主入储议，旧病案只作史实，不再是一宫垄断的恩债。", {"openness": 7, "knowledge": 2, "stability": -4}, 3, ("DeepSeek", "Kimi"), {"female_succession": True}),
            p("prince_recorded_heir", "仍立皇子，抚育与朝权分开", "依旧礼立皇子，但病案与抚育往来一并留档，监护不得干预前朝。", "皇子的名字写在第一行，六宫仍须交出抚育往来的记录。", {"stability": 3, "openness": -2}, 1, ("Claude", "Codex"), {"female_succession": False})),
        card("heir_after_loss", 8, "空座与新的名字", "皇子的座位空着，宫人把他的旧病案放到案前。宗室子已按应急安排入宫，如今外廷必须核实所有候选人的资格。", "不能让当年守在病榻旁的人，独占今日决定储位的权利。",
            p("princess_succession", "立公主，明定辅佐界限", "承认公主继承资格，辅臣与宫中监护分别签押，不得代行御权。", "旧礼被改动，公主接过封好的病案；辅臣名单必须另外接受核验。", {"openness": 7, "stability": -4, "knowledge": 2}, 3, ("DeepSeek", "Kimi"), {"female_succession": True}),
            p("clan_succession", "立宗室子，保留公主议事席", "按宗法确认宗室子，公主仍可查阅旧病案与抚育记录，监护不得私改。", "宗室子被正式召入，旧病案留在史馆，那一夜的责任不能随立储一笔勾销。", {"stability": 3, "openness": -2}, 1, ("Claude", "Codex"), {"female_succession": False})),
        card("charter_open_accounts", 9, "明账上的摄政章程", "公开账册已列清药银与边饷，储位文书也被送到案前。官员递上新章程：有人要把核账、换防写进共同签押，有人要求集中到御前的一枚印。宫门外正等新口令。", "纸上的皇位与实际发令的人，未必是同一个。",
            p("charter_checks", "分开账与兵，监国不得代印", "把账册、病案、宫门相互核验写入章程，辅佐者不得独占御玺。若传习、公档与两班核验均已落实，准许外地照章开办医馆工坊并招平民学徒。", "章程写明了谁能查谁；若有人今夜仍想越过御前，必须在现实中夺下宫门。", {"openness": 5, "knowledge": 2, "stability": -2}, 2, ("Kimi", "Claude"), {"charter": True}),
            p("charter_central_seal", "归一签押，交可信之人执行", "所有处分归御前统一签押，再由一名主事者督办，减少争执。", "诏令整齐了，接下来就看执印与督办的人是否仍听你的话。", {"stability": 4, "openness": -5}, 0, ("Codex", "MiniMax"), {"centralized": True})),
        card("charter_sealed_accounts", 9, "密匣旁的摄政章程", "两份账仍未向众人公示，储位文书也摆在案前，围绕摄政的争论却一直没有停下。官员一手捧章程，一手指着宫门轮值册：今晚得有一个说法。", "签字能结束争论，也可能让别人从此替你签字。",
            p("charter_checks", "开匣核旧账，再定监国界限", "公开药银与边饷未决问题，分开掌账和掌兵，监国不得独持御玺。传习、公档与两班核验均落实后，外地才能照章开办医馆工坊并招平民学徒。", "密匣打开，旧账终于回到人前；支持与反对者都要在今夜表明立场。", {"openness": 5, "knowledge": 2, "stability": -3}, 3, ("Kimi", "Claude"), {"charter": True}),
            p("charter_central_seal", "旧案暂封，归一签押止争", "保留密匣，御前授权一名主事者统筹账与兵，以最快速度结束对峙。", "争吵停了，账匣与轮值册送到同一张案上。那个人接下来会听谁的，今夜就见分晓。", {"stability": 4, "openness": -5}, 0, ("Codex", "MiniMax"), {"centralized": True})),
    ]
    # A worsening first-night result carries its own scene, not just a changed stat.
    from dataclasses import replace
    second = next(card for card in cards if card.id == "second_fever")
    cards.append(replace(second, id="second_fever_relapse", title="反复的高热与第二例",
                         summary="皇子移宫后高热反复，陪同的宫女也倒下。有人催着再换一处宫室，御医却抱紧旧药碗：昨夜每次用药究竟是谁经手，没有一笔对得上。",
                         pressure="这次先留下记录，还是继续照旧方守住院门？"))
    return tuple(cards)

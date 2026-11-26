"""Finite event cards. Policies change the world; the engine writes the chronicle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    description: str
    result: str
    metric_delta: dict[str, int]
    reactions: tuple[tuple[str, int, int], ...] = ()  # rank/role, favor, trust
    flags: dict[str, bool] = field(default_factory=dict)
    modernity: int = 0
    doctrine_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Event:
    id: str
    turn: int
    title: str
    summary: str
    pressure: str
    policies: tuple[Policy, ...]
    requires: tuple[str, ...] = ()


def _p(id: str, title: str, description: str, result: str,
       delta: dict[str, int], reactions=(), flags=None) -> Policy:
    return Policy(id, title, description, result, delta, tuple(reactions), flags or {})


EVENT_POOL: tuple[Event, ...] = (
    Event(
        "printing_dispute", 1, "一纸新学奏折", "皇后主张先核印书账册，皇贵妃请准在宫外试办新学。两宫各有一份不相同的誊本。",
        "账册与学额今晚就要用印。",
        (
            _p("print_school", "拨银试办书院", "准印农书与算学，派人核验银两。", "新书传出宫墙；皇后认为协理内廷之权被架空。",
               {"knowledge": 9, "openness": 3, "stability": -3}, (("皇后", -4, -7), ("皇贵妃", 5, 7)), {"schools": True, "archives": True, "printing": True}),
            _p("audit_print", "先查账册再开印", "暂缓拨银，命两宫交出底本对照。", "账目留档，开学稍迟；皇贵妃怀疑皇后借审账夺权。",
               {"knowledge": 2, "stability": 3}, (("皇后", 4, 6), ("皇贵妃", -3, -5)), {"archives": True}),
            _p("ban_print", "封存两份奏折", "以安宫禁为先，暂禁新书。", "夜里有人把旧版偷偷带出宫门。",
               {"knowledge": -5, "openness": -4, "stability": 4}, (("皇后", 2, 2), ("皇贵妃", -6, -7)), {"censored_books": True}),
        ),
    ),
    Event(
        "fever_ward", 2, "热病入城", "京畿发热者骤增，太医院请设隔离病舍，户部只肯拨半数药钱。", "宫内有人趁乱搜集病者名册。",
        (
            _p("fund_ward", "设病舍与净水井", "拨钱隔离并公开洗净水源的办法。", "病舍缓解疫势，库银受压。",
               {"livelihood": -4, "knowledge": 4, "stability": 8}, (("御医", 2, 7),), {"public_health": True, "medicine": True}),
            _p("seal_ward", "闭门严禁往来", "禁人流动，暂不公开病情。", "街巷安静，病者转入地下。",
               {"stability": 1, "openness": -5, "livelihood": -4}, (("御医", -2, -5),), {"hidden_epidemic": True}),
        ),
    ),
    Event(
        "medicine_trial", 2, "太医院新方", "一名御医提议按病例试验新方，保守派要求先问责。", "配方与病案必须由不同人保存。",
        (
            _p("trial_medicine", "准设对照病案", "先救治并记录效果，不宣称神药。", "可核查的病案开始积累。",
               {"knowledge": 5, "stability": 4, "openness": 2}, (("御医", 2, 5),), {"medical_records": True, "medicine": True}),
            _p("punish_doctor", "禁试新方", "避免宫中私试药物。", "新方停在纸上，御医闭口。",
               {"stability": 2, "knowledge": -3}, (("御医", -3, -6),)),
        ),
    ),
    Event(
        "canal_flood", 3, "河堤与工坊", "河堤决口，匠师提出测水位、制水车；赈灾银只能先拨一处。", "堤下百姓等不到下一轮廷议。",
        (
            _p("canal_works", "先救民再建水车", "开仓赈济，命匠师留图。", "洪水退去后，工匠留下可复用的图纸。",
               {"livelihood": 7, "knowledge": 4, "stability": 5}, (("军机朝臣", 2, 3),), {"workshops": True, "archives": True}),
            _p("canal_tax", "强征役银修堤", "用徭役抢工期。", "河堤修好，民怨沿河蔓延。",
               {"livelihood": 3, "stability": -6, "openness": -2}, (("军机朝臣", -2, -2),), {"workshops": True}),
        ),
    ),
    Event(
        "grain_market", 3, "粮价传闻", "商路受阻，城中粮价浮动。内务府有人囤货，有人主张开官仓。", "封仓名单与账册只有一份。",
        (
            _p("open_granary", "开仓平粜", "向百姓平价出售存粮，公布出入账。", "粮价回落，仓储账目也暴露。",
               {"livelihood": 7, "stability": 5, "openness": 3}, (("内务府管事", -2, -4),), {"archives": True}),
            _p("buy_grain", "暗买稳价", "让商人代朝廷买粮。", "粮价暂稳，谁赚了差价无人能证。",
               {"livelihood": 3, "stability": 2, "openness": -2}, (("内务府管事", 2, 3),)),
        ),
    ),
    Event(
        "exam_reform", 4, "科举改题", "新学士子请在策论中增加水利、算学，旧臣称其动摇祖制。", "皇子也在旁听辩论。",
        (
            _p("exam_science", "增设实学策论", "让算学与治河进入科举。", "士子有了新路，旧官场开始结党。",
               {"knowledge": 8, "openness": 5, "stability": -4}, (("军机朝臣", -2, -3),), {"exam_reform": True}),
            _p("exam_pilot", "只在一省试点", "保留旧科目，先观察一省结果。", "变革慢些，但试卷能被核验。",
               {"knowledge": 4, "openness": 2, "stability": 1}, (("军机朝臣", 1, 2),), {"exam_reform": True}),
        ),
    ),
    Event(
        "women_school", 4, "女学的门槛", "公主请开女学，皇贵妃支持，皇后担心被指借女学干政。", "学规会决定哪些人能入学。",
        (
            _p("open_women_school", "准女学与奖学银", "平民女童也可申请。", "宫墙外第一次有人为女童筹书。",
               {"knowledge": 7, "openness": 7, "stability": -3}, (("皇贵妃", 5, 6), ("皇后", -2, -3)), {"women_school": True}),
            _p("noble_women_school", "只准宗室试办", "限制名额，保留观察。", "女学开门很窄，却有第一批学生。",
               {"knowledge": 3, "openness": 2}, (("皇后", 2, 3),), {"women_school": True}),
        ),
    ),
    Event(
        "border_weapons", 5, "边军求器", "边报称旧火器故障频仍，军器局请匠师公开试验。", "战时失败会有人承担罪名。",
        (
            _p("test_weapons", "公开试验与检修", "让将领、匠师共同记录失效。", "兵器改良有凭据，拨款引来非议。",
               {"knowledge": 5, "livelihood": -3, "stability": 5}, (("侍卫统领", 3, 5),), {"workshops": True, "military_reform": True}),
            _p("secret_arsenal", "密造军械", "将图纸封入军库。", "军器增多，朝臣不知道谁掌钥匙。",
               {"stability": 3, "openness": -5, "knowledge": 2}, (("侍卫统领", 4, 4),), {"military_reform": True}),
        ),
    ),
    Event(
        "port_trade", 5, "海商献图", "海商带来星图与机械零件，外廷有人指为异端。", "若许通商，朝廷必须管理税与工匠。",
        (
            _p("open_port", "设官市与译馆", "准有限贸易，公开税则。", "新物与新词进入朝廷。",
               {"knowledge": 5, "livelihood": 5, "openness": 4, "stability": -2}, (("军机朝臣", -1, -2),), {"trade_port": True}),
            _p("close_port", "拒商封图", "暂拒通商，图纸入库。", "商船离去，复制的星图却在民间流转。",
               {"stability": 2, "knowledge": -2, "openness": -4}, (("军机朝臣", 2, 2),), {"censored_books": True}),
        ),
    ),
    Event(
        "workshop_fire", 6, "工坊失火", "造办处新炉失火，死伤者家属要求公开事故账。", "一份旧图纸还在灰中。",
        (
            _p("fire_inquiry", "查明事故并抚恤", "暂缓开工，公开责任。", "工匠敢报告故障，生产一时放慢。",
               {"knowledge": 4, "livelihood": -2, "openness": 4, "stability": 3}, (("内务府管事", -2, -4),), {"archives": True, "safety_rules": True}),
            _p("fire_coverup", "封口抢工", "赔银私了，维持工期。", "工坊复工，火灾缘由被封存。",
               {"livelihood": 4, "openness": -5, "stability": -3}, (("内务府管事", 3, 3),), {"hidden_accident": True}),
        ),
    ),
    Event(
        "treasury_audit", 6, "内库双账", "两宫的银钱账册数目对不上，内务府称是换算有误。", "账册可能揭出开局谁改过誊本。",
        (
            _p("public_audit", "三方会审", "令御史、两宫和内务府同核。", "账本在多人手中复制，私账难藏。",
               {"openness": 6, "stability": -2, "knowledge": 2}, (("皇后", -2, -3), ("皇贵妃", -2, -3)), {"archives": True, "public_audit": True}),
            _p("private_audit", "密查内库", "只让可信之人接触账本。", "查出一部分亏空，外界仍不知原委。",
               {"stability": 3, "openness": -1}, (("内务府管事", -2, -4),), {"private_audit": True}),
        ),
    ),
    Event(
        "palace_gate", 7, "宫门换防", "侍卫统领请准调整禁门轮值，两宫各递来一份不同名单。", "换防也可能是保护或政变的前奏。",
        (
            _p("rotate_guard", "公开轮换禁卫", "轮值名单抄送军机处。", "禁卫少了私门，消息却传得更快。",
               {"stability": 5, "openness": 3}, (("侍卫统领", -1, -2),), {"guard_reform": True}),
            _p("personal_guard", "设私属亲卫", "让一支卫队只听御前。", "御前更安全，朝臣开始猜忌。",
               {"stability": 2, "openness": -5}, (("侍卫统领", 3, 4),), {"private_guard": True}),
        ),
    ),
    Event(
        "public_archive", 7, "史馆争稿", "史馆要把改革得失公开入档，有人担心泄露宫内旧事。", "没有记录，下一代只能信传言。",
        (
            _p("open_archive", "立公档与副本", "事件经核验后留于史馆。", "纸上的教训能穿过一代人的生死。",
               {"knowledge": 4, "openness": 6, "stability": -1}, (("皇后", -1, -2),), {"archives": True, "public_archive": True}),
            _p("hide_archive", "封存宫档", "只有御前能阅。", "档案仍在，传言比它走得更远。",
               {"openness": -5, "stability": 1}, (("皇后", 1, 2),), {"archives": True, "sealed_archive": True}),
        ),
    ),
    Event(
        "heir_reform", 8, "储位之议", "皇子受皇后教养，生母另有所求；皇贵妃请问公主能否同列继承。", "这一笔会改写下一代的权利。",
        (
            _p("equal_heirs", "皇子公主同入储议", "由宗室与朝臣公开评议能力。", "公主获得资格，旧臣集体上书。",
               {"openness": 12, "knowledge": 3, "stability": -8}, (("皇贵妃", 6, 7), ("皇后", -4, -5)), {"female_succession": True}),
            _p("prince_only", "维持皇子独继", "以现有礼法定储。", "朝局暂稳，公主转向宫外学堂。",
               {"stability": 5, "openness": -5}, (("皇后", 4, 5), ("皇贵妃", -5, -6)), {"female_succession": False}),
        ),
    ),
    Event(
        "council_reform", 8, "议政之门", "地方学堂请求派代表入京议政，朝臣担心失去独断。", "若设议局，皇权会受到第一次成文约束。",
        (
            _p("found_council", "设咨询议局", "让商匠与学者提出非约束性议案。", "权力第一次被公开问责。",
               {"openness": 9, "knowledge": 2, "stability": -3}, (("军机朝臣", -3, -4),), {"council": True}),
            _p("court_only", "仍由军机处议定", "暂不增设机构。", "决策快些，民间对朝廷的猜测更多。",
               {"stability": 3, "openness": -4}, (("军机朝臣", 3, 4),)),
        ),
    ),
    Event(
        "dynasty_crossroads", 9, "新朝门槛", "九次抉择积成一条路：谁继位、谁掌权、学校和工坊能否独立于一人存续？", "最后的诏书不能抹掉已经发生的事。",
        (
            _p("write_charter", "立章程分权", "把学堂、工坊与审计写入法令。", "新法压住个人野心，也限制御座。",
               {"openness": 9, "stability": -2, "knowledge": 2}, (("军机朝臣", -3, -4),), {"charter": True}),
            _p("centralize_power", "收权于御前", "令制度只听皇命。", "一时号令齐整，继任者将承受同样的权力诱惑。",
               {"stability": 6, "openness": -8}, (("军机朝臣", 3, 3),), {"centralized": True}),
        ),
    ),
)


# Policy semantics are authored, never inferred by a language model. The two
# leading proposals favour genuinely different methods and constituencies.
POLICY_DOCTRINES = {
    "print_school": (3, ("DeepSeek",)), "audit_print": (1, ("Gemini", "Kimi")), "ban_print": (0, ("Codex",)),
    "fund_ward": (2, ("Claude", "DeepSeek")), "seal_ward": (0, ("Codex",)),
    "trial_medicine": (3, ("Gemini",)), "punish_doctor": (0, ("Claude",)),
    "canal_works": (2, ("Claude", "DeepSeek")), "canal_tax": (1, ("Codex", "MiniMax")),
    "open_granary": (2, ("DeepSeek", "Kimi")), "buy_grain": (1, ("MiniMax",)),
    "exam_science": (3, ("DeepSeek",)), "exam_pilot": (2, ("Gemini",)),
    "open_women_school": (3, ("DeepSeek", "Claude")), "noble_women_school": (1, ("Codex",)),
    "test_weapons": (2, ("Gemini", "Kimi")), "secret_arsenal": (1, ("Codex", "MiniMax")),
    "open_port": (3, ("DeepSeek", "MiniMax")), "close_port": (0, ("Claude",)),
    "fire_inquiry": (2, ("Claude", "Kimi")), "fire_coverup": (0, ("Codex",)),
    "public_audit": (3, ("Kimi",)), "private_audit": (1, ("Codex", "MiniMax")),
    "rotate_guard": (2, ("Kimi", "Gemini")), "personal_guard": (0, ("MiniMax", "Codex")),
    "open_archive": (3, ("Kimi",)), "hide_archive": (0, ("Codex",)),
    "equal_heirs": (3, ("DeepSeek", "MiniMax")), "prince_only": (0, ("Claude", "Codex")),
    "found_council": (3, ("MiniMax", "Kimi")), "court_only": (0, ("Codex",)),
    "write_charter": (3, ("Kimi", "Claude")), "centralize_power": (0, ("Codex", "MiniMax")),
}
EVENT_POOL = tuple(replace(event, policies=tuple(
    replace(policy, modernity=POLICY_DOCTRINES[policy.id][0], doctrine_tags=POLICY_DOCTRINES[policy.id][1])
    for policy in event.policies)) for event in EVENT_POOL)


def _consequence(id, title, summary, pressure, first, second):
    return Event(id, 0, title, summary, pressure, (first, second))


def _cp(id, title, description, result, delta, modernity, tags):
    return replace(_p(id, title, description, result, delta), modernity=modernity, doctrine_tags=tags)


CONSEQUENCE_EVENTS = (
    _consequence("after_guard_seizure", "谁改了禁军名单", "禁军轮值易手，旧班侍卫拒绝交钥匙。两道口令都盖着印。", "今晚守门的人究竟听谁的？",
        _cp("guard_joint_check", "当众核对两道口令", "让旧班与新班共同验印，暂缓换防。", "两班侍卫交出口令，宫门暂时安定；争权者却知道御前已起疑。", {"stability": 3,"openness": 2}, 2, ("Kimi","Gemini")),
        _cp("guard_emergency", "只认新班，立刻交钥匙", "保证换防速度，但权力会集中到新掌事者手里。", "宫门按时换防，旧班被撤；新掌事者独握夜间通行权。", {"stability": -4,"livelihood": 2}, 1, ("Codex","MiniMax"))),
    _consequence("after_treasury_seizure", "丢失的账页", "内库换了掌账人，一页支出凭单却不见了。学堂与赈济都来讨银。", "补账会耽误拨银，先拨又可能填进私账。",
        _cp("treasury_open_copy", "公开副本，让双方核对", "找出谁动过账页，拨款暂缓。", "账页抄送各处，亏空再难私了；等银的学堂只好晚开几日。", {"knowledge": 3,"openness": 4,"stability": -3}, 3, ("Kimi",)),
        _cp("treasury_fast_fund", "先发救急银，事后核查", "保住眼前开支，容许掌账人先签后报。", "急用银发了出去，新掌账人的签押也成了内库惯例。", {"livelihood": 5,"openness": -2}, 1, ("DeepSeek","Codex"))),
    _consequence("after_broken_oath", "被撕开的盟书", "一份盟书被送到御前，立誓的人互指对方先变了心。", "站队会得一位盟友，也会得一位仇人。",
        _cp("oath_public_hearing", "公开听证，双方对质", "把盟书和指控原文留档。", "双方在众人面前对质，再不能各说一套；争吵也传出宫墙。", {"openness": 4,"stability": -4}, 2, ("Kimi","Gemini")),
        _cp("oath_protect_people", "先护住被牵连的宫人", "不急着替谁定罪，先停掉报复。", "宫人暂免牵连，盟书悬而未决；两边都等着御前下一步。", {"stability": 4,"livelihood": 2}, 1, ("Claude",))),
    _consequence("after_unusual_case", "一句怪话引来的罪名", "宫中有人因措辞古怪被指妖异，旁观者争着补上证词。", "怪话是证据，还是有人借机除敌？",
        _cp("case_verify_witness", "逐条核验证词", "把听说与亲见分开，不许连坐。", "几条传言被剔除，告发者不得不为自己的话负责。", {"knowledge": 3,"stability": 2}, 2, ("Gemini","Claude")),
        _cp("case_seal_records", "封存口供，私下审理", "压住宫中议论，但真相只掌在少数人手里。", "流言暂歇，口供随封条藏入内库；被牵连的人仍在等待。", {"stability": 4,"openness": -4}, 0, ("Codex",))),
    _consequence("after_medicine_loss", "病案上少了一个名字", "太医院病案被涂掉一行，死者家属带着旧药单来讨说法。", "谁为试药的代价负责？",
        _cp("medicine_stop_compensate", "停试新药，先抚恤家属", "保住病人，试验也将中断。", "家属得到抚恤，新方暂停；急等药的人又只能回到旧方。", {"livelihood": 4,"knowledge": -2,"stability": 2}, 1, ("Claude",)),
        _cp("medicine_independent_audit", "保留病案，独立复核", "不许删名，另请医官验证后再决定是否停药。", "原始病案留了副本，试验须接受复核；旧主事者被剥去独断权。", {"knowledge": 5,"openness": 3,"stability": -4}, 3, ("Gemini","Kimi"))),
    _consequence("after_plot_trace", "夜半递进宫的密条", "一张轮值抄页被塞进史馆，页边写着一个尚不能解释的暗号。", "当众追查会惊动主谋，装作不知又可能错过时机。",
        _cp("trace_publish", "公开抄页，请众人辨认", "用更多眼睛找证人，也暴露御前正在追查。", "抄页被挂到值房，知情人开始出现；暗处的人也改变了口令。", {"knowledge": 3,"openness": 4,"stability": -3}, 3, ("Kimi",)),
        _cp("trace_watch", "悄悄核查，先保护宫门", "暂不惊动嫌疑人，把守卫移到要处。", "宫门多了一班侍卫，密条仍未公开；主谋暂时不知道谁已看过它。", {"stability": 4,"openness": -1}, 1, ("Claude","MiniMax"))),
)
LEGACY_EVENT_POOL = EVENT_POOL + CONSEQUENCE_EVENTS
from . import story
STORY_EVENTS = story.build_events(Event, Policy)
EVENT_POOL = LEGACY_EVENT_POOL + STORY_EVENTS
STORY_EVENT_IDS = frozenset(event.id for event in STORY_EVENTS)


def is_story_event(event: Event) -> bool:
    return event.id in STORY_EVENT_IDS


def consequence_candidates(state: Any) -> list[Event]:
    """At most two aftermath cards replace ordinary turns, never the tutorial/finale."""
    if state.turn < 4 or state.turn >= 9:
        return []
    seen = set(getattr(state, "seen_events", []))
    if sum(event.id in seen for event in CONSEQUENCE_EVENTS) >= 2:
        return []
    recent = [entry for entry in getattr(state, "ledger", [])
              if entry.get("turn", 0) >= state.turn - 2 and entry.get("visibility") != "private"]
    text = " ".join(str(entry.get("kind", "")) + " " + str(entry.get("text", "")) for entry in recent)
    # The public ledger deliberately strips internal action keys. Match the
    # rule action as well as legacy prose, but never mine unwitnessed secrets.
    public_actions = {entry.get("action") for entry in state.flags.get("action_history", [])
                      if entry.get("turn", 0) >= state.turn - 2
                      and entry.get("visibility") == "public"}
    resources = getattr(state, "resources", {})
    triggers = {
        "after_guard_seizure": resources.get("guards", {}).get("public_holder_id", "guard_captain") != "guard_captain" and "禁军" in text,
        "after_treasury_seizure": resources.get("treasury", {}).get("public_holder_id", "consort_02") != "consort_02" and "账" in text,
        "after_broken_oath": "betray" in public_actions or any(word in text for word in ("背盟", "背弃", "背叛")),
        "after_unusual_case": any(word in text for word in ("揭发", "审讯", "妖异")),
        "after_medicine_loss": "病案" in text and any(word in text for word in ("死亡", "死去", "试药")),
        "after_plot_trace": any(word in text for word in ("宫廷异动", "阴谋痕迹", "轮值名单被")),
    }
    return [event for event in CONSEQUENCE_EVENTS if event.id not in seen and triggers[event.id]]


def available_events(state: Any) -> list[Event]:
    if story.enabled(state):
        branch = story.branch_id(state)
        return [story.contextual_event(state, event) for event in STORY_EVENTS if event.id == branch] if state.turn <= 9 else []
    flags = getattr(state, "flags", {})
    seen = set(getattr(state, "seen_events", []))
    consequences = consequence_candidates(state)
    if consequences:
        return consequences
    cards = [event for event in LEGACY_EVENT_POOL if event.turn == state.turn
             and event.id not in seen and all(flags.get(key) for key in event.requires)]
    if cards or state.turn > 9:
        return cards
    return [Event("routine_memorial", state.turn, "无名奏折", "粮税和学堂仍等着御前定夺。", "银钱只够先做一件。", (
        _cp("routine_invest", "保民生", "拨小额库银解眼前急难。", "百姓暂得喘息。", {"livelihood": 2,"stability": 1}, 1, ("Claude",)),
        _cp("routine_record", "存公档", "让各方留下可查的记录。", "争议留下了副本，后来人不必只听传言。", {"knowledge": 2,"openness": 1}, 2, ("Kimi",)),
    ))]


def choose_event(state: Any) -> Event:
    cards = available_events(state)
    if not cards:
        raise ValueError("当前没有待议奏折")
    return cards[0] if state.turn in (1, 9) or cards[0].turn == 0 else state.rng.choice(cards)


def find_event(state: Any, event_id: str | None = None) -> Event:
    event_id = event_id or state.current_event_id
    event = next((card for card in EVENT_POOL if card.id == event_id), None)
    if event is None:
        event = next((card for card in available_events(state) if card.id == event_id), None)
    if event is None:
        raise ValueError("事件档案缺失")
    return story.contextual_event(state, event) if story.enabled(state) and is_story_event(event) else event


PITCHES = {
    "DeepSeek": ("一户少付一两，百户便多一间学堂。", "先把眼前的银花到百姓用得上的地方。", "算上等不起的人，这笔账才算齐。", "旧例还能等，宫外的人等不起。", "学得会、买得起，办法才算落地。", "不必先造最好的，先让更多人用上。"),
    "Codex": ("第一，统一签押；第二，出了错由主事者担责。", "先归一处管，才能把事情做成。", "一条命令、一个负责的人，别让两宫互相推诿。", "章程可以日后修，今日先把执行权交清。", "先定责任，再定时限；到期必有回奏。", "没有统一的调度，再好的办法也落不了地。"),
    "Claude": ("请先告诉我，失败时会让谁付代价？", "急着前进之前，先给受牵连的人留条活路。", "我愿多等一日，不愿让无名的人替我们试错。", "办法可以再改，人却不能重来。", "先护住最弱的人，再谈能走多远。", "若一定有人受伤，请别把他从奏折里略掉。"),
    "Gemini": ("甲案说得快，乙案却留得下能复核的结果。", "先取一处比对，别把一纸保证当成证据。", "把两种办法的结果并排，再谈谁对谁错。", "一份奏报不够，请留下原始记录。", "先问能否复现，不能只问是否动听。", "先试、再比、最后推广；顺序不能反。"),
    "Kimi": ("档案原话不能删，反对的那一页也要留下。", "今日怕人知道，后人便只能信传言。", "请在旨意旁记下谁赞成、谁担忧。", "两份底本都在，谁也别替另一方改词。", "不许只存报喜的纸，失误也有姓名。", "我求的是一份谁都不能悄悄抹掉的记录。"),
    "MiniMax": ("肯站到一起的人，才能把这件事推下去。", "陛下选这案，就请把能办事的人也护住。", "我愿出面，但要有人与我一起担这场风波。", "先让掌银、掌门的人点头，奏折才出得了宫。", "分散的好心没有用，得有一支肯执行的队伍。", "今日支持谁，明日就得守住这份约定。"),
}
REBUTTALS = {
    "DeepSeek": "再等一轮核验，谁给等不起的人送饭？",
    "Codex": "人人都能插手，出了事究竟由谁负责？",
    "Claude": "请把代价说清，别只把受益写在纸上。",
    "Gemini": "没有比对，凭什么保证换一种做法更好？",
    "Kimi": "若不留原文，日后谁能证明今日说过什么？",
    "MiniMax": "有道理还不够，谁肯把人和银交出来？",
}


def prepare_proposals(state: Any, event: Event, *, future: bool | None = None) -> list[dict]:
    """Choose speakers from rules; a model may only decorate their assigned words."""
    if future is None:
        future = event.turn > state.turn or bool(getattr(state, "current_event_id", "") and event.id != state.current_event_id)
    slot = "next_proposals" if future else "proposals"
    cached = getattr(state, slot, [])
    context = tuple(sorted((pid, getattr(state, "delegates", {}).get(pid, ""), person.alive)
                           for pid, person in state.people.items()))
    contexts = state.flags.setdefault("_proposal_context", {})
    context_matches = not is_story_event(event) or contexts.get(event.id) == context
    if cached and context_matches and {item.get("policy_id") for item in cached} == {policy.id for policy in event.policies} and all(item.get("event_id") == event.id
                      and state.people.get(item.get("proposer_id"))
                      and state.people[item["proposer_id"]].alive for item in cached):
        return cached
    used = set()
    proposals = []
    hosts = getattr(state, "soul_hosts", {})
    for index, policy in enumerate(event.policies):
        sid = None
        speaker_id = state.player_id
        if is_story_event(event) and index < 2:
            if event.turn == 1:
                # Keep the cold-open's two visible speakers attached to their proposal.
                preferred = ("consort_01", "consort_02")[index]
                if state.people.get(preferred) and state.people[preferred].alive:
                    speaker_id = preferred
            elif event.turn <= 3:
                choices = [person.id for person in state.people.values()
                           if person.alive and person.role == "consort" and person.id not in used]
                def score(pid):
                    soul_id = next((s for s, h in hosts.items() if h == pid), None)
                    return (int(soul_id in policy.doctrine_tags), int(soul_id is not None),
                            getattr(state.souls.get(soul_id), "influence", 20), pid)
                if choices:
                    speaker_id = max(choices, key=score)
            else:
                from .intrigue import delegate_master
                officers = [person.id for person in state.people.values()
                            if person.alive and person.id not in used
                            and (person.id in {"minister", "palace_steward", "physician", "guard_captain"}
                                 or person.role in {"军机朝臣", "内务府管事", "御医", "侍卫统领"})
                            and person.role != "consort"]
                def sponsor_score(pid):
                    master = delegate_master(state, pid)
                    voice_id = master or pid
                    soul_id = next((s for s, h in hosts.items() if h == voice_id), None)
                    return (int(soul_id in policy.doctrine_tags), int(bool(master)),
                            getattr(state.souls.get(soul_id), "influence", 20), pid)
                if officers:
                    speaker_id = max(officers, key=sponsor_score)
                else:
                    # A depleted court still cannot turn consorts into ministers.
                    speaker_id = state.player_id
            voice_id = speaker_id
            if event.turn >= 4:
                from .intrigue import delegate_master
                voice_id = delegate_master(state, speaker_id) or speaker_id
            sid = next((s for s, h in hosts.items() if h == voice_id), None)
        elif index < 2:
            choices = [(soul_id, host_id) for soul_id, host_id in hosts.items()
                       if host_id not in used and state.people.get(host_id) and state.people[host_id].alive]
            ranked = sorted(choices, key=lambda item: (
                int(item[0] in policy.doctrine_tags),
                getattr(state.souls.get(item[0]), "influence", 20), item[0]), reverse=True)
            if ranked:
                sid, speaker_id = ranked[0]
            # Familiar officers sometimes support the same method; proposing a
            # clever idea alone must not identify someone as an AI.
            humans = [p for p in state.people.values() if p.alive and p.id not in used
                      and p.id not in hosts.values() and p.id not in {state.player_id,"heir_son","heir_daughter"}
                      and p.role in {"minister","physician","guard_captain","palace_steward"}]
            if humans and index == 1 and (state.seed + state.turn) % 4 == 0:
                speaker_id = humans[(state.seed + state.turn) % len(humans)].id
                sid = None
        used.add(speaker_id)
        speaker = state.people[speaker_id]
        voice = PITCHES[sid][(state.turn + index + state.seed) % 6] if sid else "先把眼前这一件办妥，再论后面的路。"
        argument = f"{policy.description}{voice}"[:80]
        rebuttal = REBUTTALS.get(sid, "另一案也有道理，但眼前的代价不能略过。")
        title = getattr(speaker,"title","") or speaker.rank or speaker.role
        proposals.append({"event_id": event.id, "policy_id": policy.id,
                          "proposer_id": speaker_id,"speaker_id": speaker_id,
                          "name": speaker.name,"title": title,"argument": argument,
                          "pitch": argument,"rebuttal": rebuttal,
                          "stance": policy.title})
    setattr(state, slot, proposals)
    contexts[event.id] = context
    return proposals


def apply_policy(state: Any, policy_id: str) -> str:
    """Only the current card can be adopted, even if its aftermath has changed."""
    current_id = getattr(state, "current_event_id", "")
    cards = [find_event(state, current_id)] if current_id else available_events(state)
    policy = next((policy for event in cards for policy in event.policies if policy.id == policy_id), None)
    if policy is None:
        raise ValueError("政策不属于当前历史节点")
    for metric, delta in policy.metric_delta.items():
        if metric not in state.metrics:
            raise ValueError(f"未知国家指标：{metric}")
        state.metrics[metric] = max(0, min(100, state.metrics[metric] + delta))
    state.flags.update(policy.flags)
    player_id = getattr(state, "player_id", "emperor")
    for role, favor_delta, trust_delta in policy.reactions:
        for person in state.people.values():
            if not person.alive or (person.role != role and person.rank != role):
                continue
            relation = state.relations.get((person.id, player_id))
            if relation is not None:
                relation.favor = max(-100, min(100, relation.favor + favor_delta))
                relation.trust = max(-100, min(100, relation.trust + trust_delta))
    extra = story.resolve_policy(state, cards[0], policy) if story.enabled(state) and is_story_event(cards[0]) else ""
    return policy.result + (" " + extra if extra else "")

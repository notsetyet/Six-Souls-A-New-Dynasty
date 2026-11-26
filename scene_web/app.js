(() => {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]);
  const state = {data:null, manifest:null, selectedId:null, sheet:null, busy:false, settingsBusy:false, beats:[], beatIndex:0, toastTimer:null, focusBefore:null, suspectFilter:"clues", suspectPage:0, nightPage:0, selectedAction:null, resource:null, visibility:"public", councilIndex:0, councilTurn:null, typingTimer:null, typingText:"", typingTarget:null};
  const sessionTokens = window.AISettings?.createSessionTokens(() => window.sessionStorage);
  let aiSettings = null;
  const rankRoom = {"皇后":"room_queen.png","皇贵妃":"room_imperial_noble.png","贵妃":"room_noble.png","妃":"room_consort.png","嫔":"room_concubine.png"};
  const placeRooms = {garden:"room_corridor.png",east:"room_queen.png",west:"room_imperial_noble.png",offices:"room_study.png",archives:"room_archive.png"};
  const placeNames = {garden:"御花园",east:"东六宫",west:"西六宫",offices:"内廷官署",archives:"史馆"};
  const placeSymbols = {garden:"游",east:"东",west:"西",offices:"政",archives:"史"};
  const actions = {
    talk:{label:"会谈",cost:1,desc:"听一条她亲历的线索"},
    probe:{label:"试探",cost:1,desc:"问她对此事真正的看法"},
    deep:{label:"自由提问",cost:2,desc:"自己写问题，全局限十次"},
    identify:{label:"辨认 AI",cost:2,desc:"当面确认，她是否是 AI"},
    ally:{label:"结盟",cost:2,desc:"争取支持，也要回应信任"},
    expose:{label:"揭发",cost:2,desc:"把可疑证据交到御前"},
    report_interference:{label:"检举干政",cost:2,desc:"依据已见往来调取原件；担保不等于有罪，误指正统 −5"},
    expose_interference:{label:"揭发后宫干政",cost:2,desc:"指认代言人身后的主使，查错有代价"},
    investigate:{label:"彻查",cost:2,desc:"查她最近做了什么"},
    spy:{label:"布置眼线",cost:2,desc:"追踪今夜涉及她的行动"},
    protect:{label:"护持",cost:1,desc:"替她挡下指控与暗算"},
    betray:{label:"背盟",cost:2,desc:"公开盟友的把柄"},
    frame:{label:"构陷",cost:2,desc:"伪造指控，也可能败露"},
    lobby:{label:"游说",cost:1,desc:"争取这位官员的帮助"},
    trace:{label:"查她是哪个 AI",cost:1,desc:"比对她说话与做事的痕迹"},
    review:{label:"私密日记",cost:1,desc:"按信任，读她逐渐开放的盘算"},
    share_archive:{label:"出示旧档",cost:1,desc:"让眼前的人读到旧事"},
    purge:{label:"查办",cost:3,desc:"正统受损，对方可能丧命"},
  };
  const v = () => state.data?.view || {};
  const person = id => (v().people || []).find(p => p.id === id);
  const title = p => p?.title || p?.rank || p?.role || "宫中人";
  const fullName = p => p ? `${title(p)} · ${p.name}` : "宫中人";
  const selected = () => person(state.selectedId);
  const disabledFor = reason => reason ? `aria-disabled="true" data-reason="${esc(reason)}"` : "";
  const energy = () => typeof v().energy === "object" ? v().energy : {current:Number(v().energy || 0),max:4,night:2};
  const publicList = (key, alias) => state.data?.[key] || v()[key] || (alias ? v()[alias] : null) || [];
  const probes = () => publicList("probe","pending_probes");
  const trials = () => publicList("tribunal","pending_trials");
  const dawn = () => publicList("dawn","morning_news");
  const places = () => v().places || [];
  const council = () => v().council || {};
  const speeches = () => council().speeches || council().entries || [];
  const whisper = () => v().whisper || {};
  const delegateClues = id => (v().delegate_clues || []).filter(c=>c.officer_id === id || c.suspected_master_id === id);
  const currentPlace = () => places().find(p => p.id === v().current_place) || places()[0];
  const alivePeople = () => (v().people || []).filter(p => p.alive && p.id !== v().player_id);
  const unlocked = name => (v().unlocked_actions || []).includes(name) || (name === "deep" && (v().unlocked_actions || []).includes("ask"));
  function portrait(p) {
    if (!p) return "";
    let item;
    if (p.role === "consort") item=state.manifest?.consorts?.find(c => Number(c.slot) === Number(p.id.replace("consort_","")));
    else item=state.manifest?.characters?.[p.id] || state.manifest?.archetypes?.[p.role];
    const path=item?.portrait || (p.role === "consort" && /^consort_\d+$/.test(p.id) ? `portraits/${p.id}.png` : "");
    return path && /^[\w/.-]+$/.test(path) ? `/assets/${path}` : "";
  }
  function avatar(p) { const src=portrait(p); return `<span class="avatar">${src ? `<img src="${esc(src)}" alt="${esc(fullName(p))}" loading="lazy">` : ""}</span>`; }
  async function api(path, body) {
    const options={credentials:"same-origin",headers:{Accept:"application/json"}};
    const gameRequest=path.startsWith("/api/");
    if (gameRequest && sessionTokens?.get()) options.headers["X-Game-Session"]=sessionTokens.get();
    if (body !== undefined) { options.method="POST"; options.headers["Content-Type"]="application/json"; options.body=JSON.stringify(body); }
    const response=await fetch(path,options);
    if (gameRequest) sessionTokens?.set(response.headers?.get("X-Game-Session"));
    let data;
    try { data=await response.json(); } catch { throw new Error(`暂时无法连接宫中，请稍后重试（${response.status}）`); }
    if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "这个行动暂时无法完成，请重试。");
    return data;
  }
  function toast(message) {
    $("#toast").textContent=message; $("#toast").hidden=false;
    clearTimeout(state.toastTimer); state.toastTimer=setTimeout(() => {$("#toast").hidden=true;},4400);
  }
  // A shared online presentation delay must never depend on a person's identity
  // or on whether their reply came from a model, cache, or fallback template.
  const ONLINE_REPLY_WAIT_MS = 20000;
  function replyWaitMs(path, body) {
    const mode=v().mode || state.data?.mode;
    if (mode?.online !== true) return 0;
    return path === "/api/night" || path === "/api/council" ||
      path === "/api/act" && ["talk", "listen", "deep", "probe"].includes(body?.action)
      ? ONLINE_REPLY_WAIT_MS : 0;
  }
  async function mutate(path,body,options={}) {
    if (state.busy || state.settingsBusy) return;
    state.busy=true; $("#busyIndicator").hidden=false; $("#main").setAttribute("aria-busy","true");
    aiSettings?.setGameBusy(true);
    const oldTurn=v().turn,oldPhase=v().phase,oldSheet=state.sheet;
    try {
      const waitMs=replyWaitMs(path,body);
      // Observe errors immediately, but reveal neither success nor failure early.
      const [result]=await Promise.all([
        api(path,body).then(data=>({data}),error=>({error})),
        waitMs ? new Promise(resolve=>setTimeout(resolve,waitMs)) : Promise.resolve()
      ]);
      if (result.error) throw result.error;
      const data=result.data;
      closeSheet(); render(data);
      if (data.view.finished) {if (state.sheet !== "ending") openSheet("ending");return data;}
      if (options.keepSheet && oldSheet) openSheet(oldSheet,false);
      else if (options.reopen) openSheet(options.reopen,false);
      else if (data.view.turn !== oldTurn && council().active && speeches().length) openSheet("council",false);
      else if (data.view.turn !== oldTurn && dawn().length) openSheet("dawn",false);
      else if (oldPhase === "day" && data.view.phase === "free") toast("朝会已定。现在可以走走，试探一位宫中人。");
      else if (data.view.phase === "night" && oldPhase !== "night") toast("夜晚到了。翻一张牌子，选择一位夜谈对象。");
      return data;
    } catch (error) { toast(error.message); }
    finally { state.busy=false; aiSettings?.setGameBusy(false); $("#busyIndicator").hidden=true; $("#main").removeAttribute("aria-busy"); }
  }
  function normalizeBeats(data) {
    if (data.view.finished) return [];
    if (Array.isArray(data.dialogue_beats) && data.dialogue_beats.length) return data.dialogue_beats;
    const list=Array.isArray(data.beats) && data.beats.length ? data.beats : [data.view.last_scene || data.event?.summary || "宫里每个人，都在等你的下一步。"];
    return list.map(line=>{
      const match=String(line).trim().match(/^【([^】]+)】\s*(.*)$/s);
      return {text:match ? match[2] : String(line).trim(),speaker_role:"旁白",speaker_name:""};
    }).filter(beat=>beat.text);
  }
  function render(data) {
    const previous=state.data?.view;
    state.data=data;
    const view=v();
    const mode=view.mode || data.mode;
    $("#modeBanner").hidden=!!aiSettings || !mode || mode.online === true;
    $("#modeBanner").textContent=mode && mode.online !== true ? mode.label || "当前为离线模式，对白与心声为模板" : "";
    aiSettings?.update(data.model_config);
    if (state.councilTurn !== view.turn) {state.councilTurn=view.turn;state.councilIndex=0;}
    if (previous?.phase !== view.phase || previous?.turn !== view.turn) state.selectedId=null;
    if (!person(state.selectedId)?.alive) state.selectedId=null;
    $("#chapter").textContent=`第 ${view.turn} 幕 / 九幕 · ${view.player_status}`;
    $("#foundCount").textContent=`${view.found_ai ?? alivePeople().filter(p=>p.identity === "已确认 AI").length}/6`;
    const phases=["day","free","night"],index=phases.indexOf(view.phase);
    $("#phaseTrack").innerHTML=[view.turn <= 3 ? "宫中议事" : "朝会","自由时段","夜谈"].map((label,i) => `<li class="${i === index ? "active" : index > i || view.phase === "ready_next" || view.finished ? "complete" : ""}" ${i === index ? 'aria-current="step"' : ""}><span class="step-num">${String(i+1).padStart(2,"0")}</span>${label}</li>`).join("");
    const risk=view.throne_risk;
    $("#throneRisk").innerHTML=risk ? `<span>皇位</span><strong>${esc(risk.label)}</strong><i><b style="width:${Math.max(0,Math.min(100,Number(risk.value || 0)))}%"></b></i>` : "";
    $("#throneRisk").title="皇位风险：夺权威胁与正统受损会增加风险";
    const e=energy(),night=view.phase === "night",amount=night ? e.night ?? 2 : e.current ?? 0,max=night ? 2 : e.max ?? 4;
    $("#energy").innerHTML=`<span class="energy-label">${night ? "夜间" : "今日"}精力</span><span class="energy-dots">${Array.from({length:Math.max(0,Math.min(8,max))},(_,i)=>`<i class="${i < amount ? "" : "empty"}"></i>`).join("")}</span><strong>${amount}/${max}</strong>`;
    $("#energy").title=`${night ? "夜谈自带" : "今日剩余"} ${amount} 点精力${e.carry ? `，结转 ${e.carry} 点` : ""}`;
    $("#tutorialTip").textContent=view.finished ? "" : view.tutorial_tip || "找出他们，守住皇位与实权。";
    state.beats=normalizeBeats(data);state.beatIndex=0;
    renderScene();renderGoal();displayBeat();
    if (view.finished && (!previous?.finished || previous?.ending !== view.ending)) openSheet("ending");
    else if (council().active && speeches().length && (!previous || previous.turn !== view.turn)) openSheet("council");
  }
  function visiblePeople() {
    const view=v();
    if (view.phase === "day") {
      const proposals=publicList("court","proposals");
      const ids=proposals.map(p=>p.speaker_id || p.proposer_id).filter(Boolean);
      if (!ids.length) (state.data.event?.policies || []).forEach(p=>p.proposer_id && ids.push(p.proposer_id));
      if (!ids.length && view.turn === 1) return [person("consort_01"),person("consort_02")].filter(p=>p?.alive);
      return [...new Set(ids)].slice(0,2).map(person).filter(p=>p?.alive);
    }
    if (view.phase === "free") return (currentPlace()?.people || []).map(p=>typeof p === "string" ? person(p) : p).filter(p=>p?.alive).slice(0,4);
    if (view.phase === "night") return selected() ? [selected()] : nightPeople().slice(0,2);
    return selected() ? [selected()] : [person(view.player_id)].filter(Boolean);
  }
  function nightPeople() { const all=alivePeople(),consorts=all.filter(p=>p.role === "consort"); return v().player_id === "emperor" && consorts.length ? consorts : all; }
  function renderScene() {
    const view=v(),phase=view.phase,cast=visiblePeople(),place=currentPlace();
    let room="room_study.png",location="御书房",caption="朝会站队",sub="你支持谁，谁就向权力走近一步。";
    if (phase === "day" && state.data.event) {caption=state.data.event.title || caption;sub=state.data.event.summary || sub;}
    if (phase === "free") {room=placeRooms[place?.id] || "room_corridor.png";location=place?.name || placeNames[view.current_place] || "御花园";caption=cast.length ? "今日，谁在这里" : "暂且独行";sub=cast.length ? "点击人物，听听她话里的另一层意思。" : "这里暂时没有人。去别处走走，也许会有新消息。";}
    if (phase === "night") {const p=selected();room=p ? rankRoom[p.rank] || "room_study.png" : "room_corridor.png";location=p ? `${title(p)}寝殿` : "宫灯初上";caption="今夜，见谁？";sub="一场夜谈，可能换来盟友，也可能留下把柄。";}
    if (phase === "ready_next") {room="room_corridor.png";location="夜尽天明";caption="宫墙里的余波";sub="你看不见的地方，也有人做了选择。";}
    if (view.finished) {room="room_archive.png";location="史馆";caption="九幕之后";sub="有人保住了江山，有人留下了未来。";}
    const opening=phase === "day" && view.turn === 1;
    $("#scene").className=`scene ${phase}${cast.length > 2 ? " has-many" : ""}`;
    $("#scenePhoto").style.backgroundImage=`url('/assets/${room}')`;
    if (phase === "day" && view.turn <= 3) location="内殿议事";
    $("#locationName").textContent=location;
    $("#phaseLabel").textContent=`第 ${view.turn} 幕 · ${({day:view.turn <= 3 ? "宫中议事" : "朝会",free:"自由时段",night:"夜谈",ready_next:"暗战已结",ended:"终章"})[phase] || "终章"}`;
    $("#placeSwitch").hidden=phase !== "free";
    $("#sceneCaption").innerHTML=`<span class="chapter-mark">${opening ? "序" : esc(({day:"议",free:"访",night:"夜",ready_next:"变",ended:"终"})[phase] || "终")}</span><h2>${opening ? "皇子高热，<br>宫灯未熄。" : esc(caption)}</h2><p>${opening ? "朕的朝堂里，混进了六个 AI。<br>找出他们，守住皇位与实权。" : esc(sub)}</p>`;
    $("#cast").className=`cast ${cast.length > 2 ? "multiple" : cast.length === 1 ? "single" : ""}`;
    $("#cast").innerHTML=cast.map(p=>{
      const src=portrait(p),canAct=["free","night"].includes(phase),interactive=canAct || phase === "day";
      const tag=interactive ? "button" : "div",attributes=interactive ? `type="button" data-person="${esc(p.id)}" aria-label="${esc(canAct ? `与${fullName(p)}交谈` : `查看${fullName(p)}的提案`)}"` : "";
      return `<${tag} class="cast-person" ${attributes}>${src ? `<img src="${esc(src)}" alt="${esc(fullName(p))}" draggable="false">` : ""}<span class="nameplate"><strong>${esc(title(p))}</strong><small>${esc(p.name)}${canAct ? " · 交谈 ↗" : ""}</small></span></${tag}>`;
    }).join("");
    const notices=[];
    const reportable=(v().interference_cases || []).filter(c=>c.can_report);
    if (phase === "free" && reportable.length) notices.push(`<button type="button" data-open="interference">官员与后宫往来 · 可检举复核 ${reportable.length}</button>`);
    if (trials().length) notices.push(`<button type="button" data-open="trial">待裁决的妖异案 · ${trials().length}</button>`);
    if (probes().length && ["day","free"].includes(phase)) notices.push(`<button type="button" data-open="probe">有人试探你 · ${probes().length}</button>`);
    if (council().active && speeches().length && ["day","free"].includes(phase)) notices.push('<button type="button" data-open="council">晨省请安 ↗</button>');
    if (dawn().length && phase === "day") notices.push('<button type="button" data-open="dawn">昨夜发生了什么 ↗</button>');
    if (phase === "free" && (publicList("traces","plot_traces")).length) notices.push('<button type="button" data-open="traces">宫廷异动 ↗</button>');
    $("#sceneNotices").innerHTML=notices.join("");
  }
  function renderGoal() {
    const view=v();let goal,buttons;
    if (trials().length && view.phase === "day") {goal="有人被指控言行妖异。听取指控，决定她的命运。";buttons='<button type="button" class="primary" data-open="trial">先审这桩案 →</button>';}
    else if (view.phase === "day") {goal=view.turn === 1 ? "皇子高热未退。先听两种救治办法，再下旨。" : "两种做法都有代价。选一份提案，也是在选择支持谁。";buttons='<button type="button" class="primary" data-open="court">听双方提案 →</button>';}
    else if (view.phase === "free") {
      const amount=energy().current,target=visiblePeople()[0];
      goal=amount > 0 ? (view.turn === 1 ? "找一位宫中人试探，听听她真正的想法。" : "线索藏在言行里。决定把今天的精力花在谁身上。") : "今天的精力用完了。结束白天，准备一场夜谈。";
      buttons=`${amount > 0 && unlocked("eavesdrop") ? '<button type="button" data-act="eavesdrop">偷听 · 1 点</button>' : ""}<button type="button" class="${amount > 0 ? "text-button" : "primary"}" data-submit="end_day">结束白天 ${amount > 0 ? "→" : "· 入夜 →"}</button>${amount > 0 && target ? `<button type="button" class="primary" data-person="${esc(target.id)}">${view.turn === 1 ? "试探" : "找"}${esc(title(target))} →</button>` : amount > 0 ? '<button type="button" class="primary" data-open="places">去别处看看 →</button>' : ""}`;
      if (view.current_place === "archives" && amount > 0 && unlocked("archive")) buttons=`<button type="button" data-act="archive">查档 · 1 点</button>${buttons}`;
    } else if (view.phase === "night") {goal="夜谈自带 2 点精力，只能用在今夜选中的人身上。";buttons='<button type="button" class="primary" data-open="night_roster">翻牌子，选一个人 →</button>';}
    else if (view.finished) {goal="结局只看皇位与实权；他们推动的变革，会另记一笔。";buttons='<button type="button" class="primary" data-open="ending">展开终局史书 →</button>';}
    else {goal="这一夜已经过去。清晨会揭晓新的消息。";buttons=`<button type="button" class="primary" data-submit="next">${view.turn >= 9 ? "写下终局史书" : "进入下一幕"} →</button>`;}
    $("#goalText").textContent=goal;$("#stepActions").innerHTML=buttons;
  }
  function displayBeat() {
    $(".dialogue").hidden=Boolean(v().finished);
    if (v().finished) {
      $("#speakerName").textContent="";$("#dialogueText").textContent="";$("#dialogueProgress").textContent="";
      return;
    }
    const beat=state.beats[state.beatIndex] || {text:"宫里每个人，都在等你的下一步。",speaker_role:"旁白"};
    $("#speakerName").textContent=[beat.speaker_role || "旁白",beat.speaker_name].filter(Boolean).join(" · ");
    const meta=v().dialogue_meta || {},matches=beat.speaker_id && meta.speaker_id === beat.speaker_id;
    const tone=beat.tone || (matches ? meta.tone : ""),slip=beat.slip_text || (matches ? meta.slip : "");
    $("#speakerTone").textContent=tone || "";$("#speakerTone").hidden=!tone;
    if (typeof slip === "string" && slip && beat.text.includes(slip)) $("#dialogueText").innerHTML=esc(beat.text).replace(esc(slip),`<mark class="slip">${esc(slip)}</mark>`);
    else $("#dialogueText").textContent=beat.text;
    $("#dialogueProgress").textContent=state.beats.length > 1 ? `${state.beatIndex+1} / ${state.beats.length}` : "";
    $("#dialogueNext").innerHTML=state.beatIndex < state.beats.length-1 ? '继续故事 <span>↓</span>' : '接下来 <span>↗</span>';
  }
  function nextBeat() {
    if (state.beatIndex < state.beats.length-1) {state.beatIndex++;displayBeat();return;}
    if (v().phase === "day") openSheet(trials().length ? "trial" : "court");
    else if (v().phase === "free") {if (energy().current <= 0) {mutate("/api/end_day",{});return;}const target=visiblePeople()[0];target ? selectPerson(target.id) : openSheet("places");}
    else if (v().phase === "night") openSheet("night_roster");
    else if (v().finished) openSheet("ending");
    else mutate("/api/next",{});
  }
  function closeSheet() {
    finishTyping();
    $("#sheet").hidden=true;$("#scrim").hidden=true;document.body.classList.remove("sheet-open");state.sheet=null;
    if (state.focusBefore?.isConnected) state.focusBefore.focus();
  }
  const sheetTitles={court:["御前廷辩 · 选择即站队","这一次，你支持谁"],meeting:["一言之间 · 真心与试探","私下会谈"],evidence:["只收录你已经见过的迹象","此人的线索"],places:["走出御书房","今日宫中行踪"],suspects:["你知道，宫里恰有六个 AI","嫌疑板"],ledger:["眼见之事，落笔为证","宫中史书"],more:["宫墙之外，还有天下","宫中事务"],new:["旧局封存，新朝将启","开启新朝"],night_roster:["宫灯初上 · 夜谈自带 2 点精力","今夜，与谁说话"],dawn:["清晨揭晓","昨夜，宫中有变"],probe:["话中有话","有人在试探你"],trial:["一言生死","妖异审讯"],interference:["据事检举 · 调取原件","后宫干政复核"],resources:["握住的东西，也会被夺走","宫中权柄"],traces:["蛛丝马迹，未必是小事","宫廷异动"],decree:["御笔一落，必有人失势","改派权柄"],ending:["九幕终章","新朝史书"],help:["先听故事，再做决定","怎么玩"],interrupt:["每一代，仅此一次","御前叫停"],report:["信任渐深，旧页渐开","私密日记"],whisper:["听见的未必是真心","屏风后的低语"],council:["言语有礼，话里有锋","晨省请安"]};
  function openSheet(kind,focus=true) {
    if (!state.data || kind === "interrupt") return;
    finishTyping();
    if (!state.sheet) state.focusBefore=document.activeElement;
    state.sheet=kind;$("#scrim").hidden=false;$("#sheet").hidden=false;document.body.classList.add("sheet-open");
    $("#sheet").classList.toggle("wide",kind === "court");
    const headings=sheetTitles[kind] || ["宫中事务","宫中事务"];
    $("#sheetKicker").textContent=headings[0];$("#sheetTitle").textContent=headings[1];
    const renderers={court:renderCourt,meeting:renderMeeting,evidence:renderEvidence,places:renderPlaces,suspects:renderSuspects,ledger:renderLedger,more:renderMore,new:renderNew,night_roster:renderNightRoster,dawn:renderDawn,probe:renderProbe,trial:renderTrial,interference:renderInterference,resources:renderResources,traces:renderTraces,decree:renderDecree,ending:renderEnding,help:renderHelp,interrupt:renderInterrupt,report:renderReport,whisper:renderWhisper,council:renderCouncil};
    $("#sheetBody").innerHTML=renderers[kind]?.() || "";
    if (kind === "whisper" && whisper().text) typeText("#whisperText",whisper().text);
    if (focus) {$("#sheetBody").scrollTop=0;$("#sheetClose").focus();}
  }
  function proposalFor(policy) { return publicList("court","proposals").find(p=>p.policy_id === policy.id) || {}; }
  function renderCourt() {
    const event=state.data.event;
    if (!event || v().phase !== "day") return '<div class="empty-state">这一次朝会已经结束。下一幕还有新的抉择。</div>';
    const card=policy=>{
      const proposal=proposalFor(policy),speaker=person(policy.proposer_id || proposal.proposer_id || proposal.speaker_id),src=portrait(speaker);
      const name=policy.proposer_name || proposal.speaker_name || speaker?.name || "朝臣";
      const argument=policy.argument || proposal.argument || proposal.pitch || policy.description;
      return `<article class="proposal"><header class="proposal-head">${src ? `<img src="${esc(src)}" alt="${esc(fullName(speaker))}">` : ""}<div><small>${esc(policy.stance || proposal.stance || "呈上提案")}</small><h3>${esc(title(speaker))}</h3><p>${esc(name)}</p></div></header><div class="proposal-body"><h4>${esc(policy.title)}</h4><blockquote>“${esc(argument)}”</blockquote>${proposal.rebuttal || policy.rebuttal ? `<p class="rebuttal">回应另一案：${esc(policy.rebuttal || proposal.rebuttal)}</p>` : ""}<div class="consequence"><strong>这意味着</strong><br>${esc(policy.consequence || policy.description)}</div><button type="button" class="primary" data-policy="${esc(policy.id)}" ${trials().length ? 'aria-disabled="true" data-reason="请先裁决待审案件"' : ""}>支持${esc(speaker ? title(speaker) : name)}的提案 →</button></div></article>`;
    };
    return `${threadBadge(event.thread_label || event.thread_title)}<p class="court-summary">${esc(event.summary)}</p><div class="debate-grid">${event.policies.slice(0,2).map(card).join("")}</div>${event.policies.slice(2).map(p=>`<article class="third-proposal"><div><strong>皇权第三案 · ${esc(p.title)}</strong><p>${esc(p.description)}</p></div><button type="button" data-policy="${esc(p.id)}" ${disabledFor(trials().length ? "请先裁决待审案件" : "")}>另作安排 →</button></article>`).join("")}<p class="muted">${v().player_status === "在位" ? "被采纳的人会更信任你，也会更有势力。" : "你暂未掌实权，立场将以密函传出，为复位争取支持。"}</p>`;
  }
  function localEligibility(action,p) {
    const night=v().phase === "night",amount=night ? energy().night ?? 2 : energy().current ?? 0,cost=actions[action]?.cost ?? 2;
    const server=state.data?.action_availability?.[p?.id]?.[action] || v().action_availability?.[p?.id]?.[action] || v().action_options?.[p?.id]?.[action] || p?.action_options?.[action];
    if (server && (server.enabled === false || server.allowed === false)) return server.reason || "还不满足行动条件";
    if (amount < cost) return `精力不足，需要 ${cost} 点`;
    if (action === "deep" && v().deep_remaining <= 0) return "本局自由提问次数已用完";
    if (["trace","review"].includes(action) && p?.identity !== "已确认 AI") return "需先确认她是 AI";
    if (action === "purge" && v().player_status !== "在位") return "掌握实权时才能查办";
    if (action === "identify" && p?.identity === "已确认 AI") return "已经确认她是 AI";
    if (action === "lobby" && p?.role === "consort") return "只能游说官员";
    if (action === "expose" && !(publicList("evidence","fingerprints")).some(e=>e.actor_id === p?.id)) return "尚未掌握她的可疑证据";
    return "";
  }
  function actionButton(action,p) {
    const def=actions[action],reason=localEligibility(action,p),isAsk=action === "deep";
    return `<button type="button" class="action-choice${state.selectedAction === action ? " selected" : ""}" ${isAsk ? 'data-select-action="deep"' : `data-act="${esc(action)}" data-target="${esc(p.id)}"`} ${reason ? `aria-disabled="true" data-reason="${esc(reason)}"` : ""}><span class="action-title"><strong>${esc(def.label)}</strong><em>${def.cost} 点精力</em></span><small>${esc(reason || def.desc)}</small></button>`;
  }
  function renderMeeting() {
    const p=selected();
    if (!p) return '<div class="empty-state">先选一位宫中人，再与她说话。</div>';
    if (!["free","night"].includes(v().phase)) return `<p>${esc(fullName(p))} · ${esc(p.note || p.tag || "尚未留下更多线索。")}</p><button type="button" data-open="court">回到朝会提案</button>`;
    const night=v().phase === "night",base=["talk","probe","deep"].filter(unlocked),extra=Object.keys(actions).filter(a=>!base.includes(a) && unlocked(a) && a!=="report_interference");
    const evidence=publicList("evidence","fingerprints").filter(e=>e.actor_id === p.id).slice(-1)[0];
    const hint=p.suspicion_hint || p.suspicion_label || "无迹可循";
    let html=`<div class="person-heading">${avatar(p)}<div><h3>${esc(title(p))}</h3><p>${esc(p.name)} · ${esc(p.tag || p.note || "她正等你开口")}</p><span class="pill ${hint === "十分可疑" ? "warn" : ""}">${esc(p.identity === "已确认 AI" ? p.known_soul || "已确认 AI" : hint)}</span></div></div>${evidence ? `<p class="meeting-evidence">你记得：${esc(evidence.text)}</p>` : ""}${delegateClues(p.id).length ? `<p class="meeting-evidence">你查到的转陈线索牵涉此人。<button type="button" class="text-button" data-evidence="${esc(p.id)}">对照干政线索 ↗</button></p>` : ""}${night ? '<div class="info-box">选一个夜谈行动，随后结束本幕。夜间精力不会扣白天结余。</div>' : ""}<div class="action-grid">${base.map(a=>actionButton(a,p)).join("")}</div>`;
    if (state.selectedAction === "deep" && unlocked("deep")) html+=`<label class="field">想问她什么？<textarea id="questionInput" maxlength="200" placeholder="例如：你为什么反对今天的提案？"></textarea></label><div class="sheet-actions"><span class="muted">全局还可提问 ${v().deep_remaining} 次</span><button type="button" class="primary" data-submit="ask">问出口 · 2 点</button></div>`;
    if (["ally","protect"].some(unlocked)) html+=`<fieldset class="visibility-choice"><legend>护持与结盟，如何表态</legend>${[["public","明做","公开表明支持"],["secret","暗做","私下约定，也可能走漏风声"]].map(([id,label,desc])=>`<label><input type="radio" name="visibility" value="${id}" ${state.visibility === id ? "checked" : ""}><span><strong>${label}</strong><small>${desc}</small></span></label>`).join("")}</fieldset>`;
    if (!night && (v().interference_cases || []).some(c=>c.officer_id===p.id || c.suspected_master_id===p.id)) html+=`<div class="info-box">你已见到此人与前朝／后宫的往来。<button type="button" data-open="interference">查看依据，检举干政 ↗</button></div>`;
    if (extra.length) html+=`<details class="actions-extra" ${v().turn === 3 ? "open" : ""}><summary>${v().turn < 4 ? "再查一步" : "更多宫斗行动"}</summary><div class="action-grid">${extra.map(a=>actionButton(a,p)).join("")}</div>${unlocked("identify") && hint === "无迹可循" ? '<p class="muted">目前证据不足。贸然辨认可能招来流言。</p>' : ""}</details>`;
    return html;
  }
  function renderPlaces() {
    return `<p class="muted">前往地点不耗精力。人在哪里，有时也是线索。</p><div class="place-grid">${places().map(place=>`<button type="button" class="place-card ${place.id === v().current_place ? "active" : ""}" data-place="${esc(place.id)}"><span class="place-symbol">${esc(placeSymbols[place.id] || "宫")}</span><strong>${esc(place.name)}</strong><small>${(place.people || []).map(p=>typeof p === "string" ? person(p) : p).filter(Boolean).map(p=>esc(title(p))).join(" · ") || "此处暂时无人"}</small></button>`).join("")}</div><div class="sheet-actions"><button type="button" data-open="suspects">查看宫中名录</button></div>`;
  }
  function renderSuspects() {
    const all=(v().people || []).filter(p=>p.id !== v().player_id),evidence=publicList("evidence","fingerprints");
    let filtered=all.filter(p=>p.alive);
    if (state.suspectFilter === "clues") filtered=filtered.filter(p=>p.identity === "已确认 AI" || evidence.some(e=>e.actor_id === p.id) || delegateClues(p.id).length || p.mark || v().player_marks?.[p.id]);
    if (state.suspectFilter === "departed") filtered=all.filter(p=>!p.alive);
    const pageSize=4,pages=Math.max(1,Math.ceil(filtered.length/pageSize));state.suspectPage=Math.min(state.suspectPage,pages-1);
    const items=filtered.slice(state.suspectPage*pageSize,(state.suspectPage+1)*pageSize);
    return `<div class="suspect-headline"><strong>已找到 AI：${v().found_ai ?? all.filter(p=>p.identity === "已确认 AI").length}/6</strong><p>标记是你的判断，<br>不等于真实身份。</p></div><div class="roster-tabs">${[["clues","有线索的人"],["all","宫中名录"],["departed","故人"]].map(([id,label])=>`<button type="button" class="${state.suspectFilter === id ? "selected" : ""}" data-filter="${id}">${label}</button>`).join("")}</div><div class="suspect-grid">${items.map(p=>{
      const clues=evidence.filter(e=>e.actor_id === p.id),mark=v().player_marks?.[p.id] || p.mark || "",hint=p.identity === "已确认 AI" ? p.known_soul || "已确认 AI" : p.suspicion_hint || "无迹可循";
      return `<article class="suspect-card"><div class="person-heading">${avatar(p)}<div><h3>${esc(title(p))}</h3><p>${esc(p.name)}</p><span class="pill ${hint === "十分可疑" ? "warn" : p.identity === "已确认 AI" ? "good" : ""}">${esc(hint)}</span></div></div><p class="clue-line">${esc(clues.at(-1)?.text || p.recent_action || p.tag || "还没有收集到她的线索。")}</p>${clues.length || delegateClues(p.id).length ? `<button type="button" class="text-button" data-evidence="${esc(p.id)}">查看全部线索${delegateClues(p.id).length ? " · 含干政线索" : ` · ${clues.length} 条`} ↗</button>` : ""}<div class="card-bottom">${unlocked("mark") ? `<select data-mark="${esc(p.id)}" aria-label="标记${esc(p.name)}">${[["","未标记"],["suspect","可疑"],["human","像人类"],["ally","盟友"],["enemy","敌人"]].map(([value,label])=>`<option value="${value}" ${mark === value ? "selected" : ""}>${label}</option>`).join("")}</select>` : '<span class="muted">第二幕解锁标记</span>'}${p.alive && v().phase === "free" ? `<button type="button" data-find="${esc(p.id)}">去找她 ↗</button>` : p.alive && v().phase === "night" && nightPeople().some(n=>n.id===p.id) ? `<button type="button" data-person="${esc(p.id)}">与她夜谈 ↗</button>` : ""}</div></article>`;
    }).join("")}</div>${!items.length ? '<div class="empty-state">还没有留下线索的人。<br>去会谈或试探，听听宫里的说法。</div>' : ""}${pages > 1 ? `<div class="pagination"><button type="button" data-page="-1" ${state.suspectPage === 0 ? "disabled" : ""}>上一页</button><span>${state.suspectPage+1} / ${pages}</span><button type="button" data-page="1" ${state.suspectPage >= pages-1 ? "disabled" : ""}>下一页</button></div>` : ""}`;
  }
  function delegateEvidenceHTML(id) {
    const clues=delegateClues(id);if (!clues.length) return "";
    return `<h4 class="section-label">已经查到的转陈线索</h4><div class="ledger-list">${clues.map(clue=>{
      const officer=person(clue.officer_id),master=person(clue.suspected_master_id);
      const reason=localEligibility("expose_interference",officer);
      return `<article class="ledger-entry"><small>${esc(fullName(officer))} · 疑与${esc(fullName(master))}有往来</small>${(clue.evidence || []).map(text=>`<p>${esc(text)}</p>`).join("")}<p class="muted">${clue.can_expose ? "已有可交叉核验的凭据，可以指认后宫干政。" : "目前只能算线索。继续追查转陈的官员，再决定是否指认。"}</p>${v().phase === "free" ? `<div class="sheet-actions">${unlocked("investigate") ? `<button type="button" data-act="investigate" data-target="${esc(clue.officer_id)}" ${disabledFor(localEligibility("investigate",officer))}>彻查${esc(title(officer))} · 2 点</button>` : unlocked("spy") ? `<button type="button" data-act="spy" data-target="${esc(clue.officer_id)}" ${disabledFor(localEligibility("spy",officer))}>跟查转陈官员 · 2 点</button>` : ""}${clue.can_expose && unlocked("expose_interference") ? `<button type="button" data-act="expose_interference" data-target="${esc(clue.officer_id)}" ${disabledFor(reason)}>揭发后宫干政 · 2 点</button>` : ""}</div>` : ""}</article>`;
    }).join("")}</div>`;
  }
  function renderEvidence() {
    const p=selected();
    if (!p) return '<div class="empty-state">这位人物的线索暂不可读。</div>';
    const clues=publicList("evidence","fingerprints").filter(e=>e.actor_id === p.id);
    return `<div class="person-heading">${avatar(p)}<div><h3>${esc(title(p))}</h3><p>${esc(p.name)} · ${esc(p.identity || "身份未查明")}</p></div></div><p class="muted">把前后说法放在一起看。可疑的言行是线索，不能直接证明身份。</p><div class="ledger-list">${clues.map(e=>`<article class="ledger-entry"><small>第 ${esc(e.turn)} 幕 · 你已见到的迹象</small><p>${esc(e.text)}</p></article>`).join("") || '<div class="empty-state">还没有收集到此人的言行指纹。</div>'}</div>${delegateEvidenceHTML(p.id)}<div class="sheet-actions"><button type="button" data-open="suspects">回到嫌疑板</button>${p.alive && v().phase === "free" ? `<button type="button" class="primary" data-find="${esc(p.id)}">去找${esc(title(p))} →</button>` : ""}</div>`;
  }
  function renderNightRoster() {
    const people=nightPeople(),pages=Math.max(1,Math.ceil(people.length/4));state.nightPage=Math.min(state.nightPage,pages-1);
    return `<p class="muted">今夜只能见一人。先挑一张牌子，再决定聊什么。</p><div class="suspect-grid">${people.slice(state.nightPage*4,(state.nightPage+1)*4).map(p=>`<button type="button" class="suspect-card" data-person="${esc(p.id)}"><span class="person-heading">${avatar(p)}<span><h3>${esc(title(p))}</h3><p>${esc(p.name)}</p><span class="pill">${esc(p.suspicion_hint || p.identity || "未查明")}</span></span></span></button>`).join("")}</div>${pages > 1 ? `<div class="pagination"><button type="button" data-night-page="-1" ${state.nightPage === 0 ? "disabled" : ""}>上一组</button><span>${state.nightPage+1} / ${pages}</span><button type="button" data-night-page="1" ${state.nightPage >= pages-1 ? "disabled" : ""}>下一组</button></div>` : ""}`;
  }
  function renderLedger() { const entries=(v().ledger || []).slice().reverse();return `<p class="muted">只记你已经知道的事。往往是小事，后来改变了结局。</p><div class="ledger-list">${entries.map(e=>`<article class="ledger-entry ${isRumor(e) ? "rumor-entry" : ""}"><small>第 ${esc(e.turn)} 幕 · ${esc(e.kind)}${isRumor(e) ? ' · <span class="rumor-tag">传闻 · 尚未证实</span>' : ""}</small><p>${esc(e.text)}</p></article>`).join("") || '<div class="empty-state">史官尚未落笔。</div>'}</div>`; }
  function renderInterference() {
    const cases=v().interference_cases || [];
    return `<p class="muted">大臣替妃嫔担保、结盟或议事，可以引起怀疑，但不直接构成干政。检举后调取原件，核实是否私下受托操持朝政；查实撤换代言人，误指正统 −5。</p>${cases.map(row=>{
      const officer=person(row.officer_id), master=person(row.suspected_master_id);
      const reason=row.report_reason || localEligibility("report_interference",officer);
      return `<article class="ledger-entry"><h3>${esc(fullName(officer))}与${esc(fullName(master))}</h3>${row.evidence.map(text=>`<p>${esc(text)}</p>`).join("")}<button type="button" data-act="report_interference" data-target="${esc(row.officer_id)}" ${disabledFor(reason)}>检举并复核 · 2 点</button>${reason ? `<p class="muted">${esc(reason)}</p>` : ""}</article>`;
    }).join("") || '<div class="empty-state">尚未见到可供检举的官员与妃嫔往来。留意公开担保、结盟和转陈，再决定是否查办。</div>'}`;
  }
  function renderMore() {
    const view=v(),metrics=view.metrics || {},labels=view.metric_labels || {},risk=view.throne_risk;
    return `<div class="info-box">${esc(view.player_name)} · ${esc(view.player_status)}${risk ? `<br>皇位风险：${esc(risk.label)}` : ""}${view.emperor_rumor ? `<br>宫中对你的议论：${esc(view.emperor_rumor)}` : ""}<br>正统：${esc(view.flags?.reputation ?? 50)}</div><div class="stats-grid">${Object.entries(labels).map(([key,label])=>`<div class="stat"><span>${esc(label)}</span><strong>${Number(metrics[key] || 0)}</strong><div class="stat-bar"><i style="width:${Math.max(0,Math.min(100,Number(metrics[key] || 0)))}%"></i></div></div>`).join("")}</div><p class="muted">变革成果与皇位胜负分开结算。数值好看，未必就能坐稳江山。</p><div class="sheet-actions">${publicList("resources").length ? '<button type="button" data-open="resources">宫中权柄</button>' : ""}${publicList("traces").length ? '<button type="button" data-open="traces">宫廷异动</button>' : ""}${unlocked("report_interference") ? '<button type="button" data-open="interference">检举后宫干政</button>' : ""}<button type="button" data-open="suspects">宫中名录</button><button type="button" data-open="report">私密日记</button><button type="button" data-open="new">重新开始</button></div><p class="muted">当前演出：${esc(view.api_last_source || "离线规则演出")}。角色名代表故事人设，并非同时调用六家模型。</p>`;
  }
  function renderNew() {return '<p>重开后，人物还是这些人，六个 AI 会重新选择附身的人。当前这一局将被替换。</p><label class="field">开局数字（选填，用同一数字可以重玩）<input id="seedInput" inputmode="numeric" type="number" step="1" placeholder="留空，随机开局"></label><label class="checkbox"><input id="skipTutorial" type="checkbox">我已经会玩了，第一幕就解锁全部行动</label><div class="sheet-actions"><button type="button" data-close="sheet">继续这一局</button><button type="button" class="primary" data-submit="new">开启新朝 →</button></div>';}
  function threadBadge(label) {return label ? `<span class="thread-badge">${esc(label)}</span>` : "";}
  function isRumor(item) {return item?.visibility === "rumor" || item?.kind === "传闻" || /^【?传闻/.test(item?.text || "");}
  function renderDawn() {
    const threads=Array.isArray(v().threads) ? v().threads : [];
    return `${threads.length ? `<div class="thread-recap">${threads.filter(t=>t.summary).map(t=>`<article>${threadBadge(t.title)}<p>${esc(t.summary)}</p></article>`).join("")}</div>` : ""}<div class="ledger-list">${dawn().map(raw=>{const item=typeof raw === "string" ? {text:raw} : raw;return `<article class="ledger-entry ${isRumor(item) ? "rumor-entry" : ""}"><small>${esc(item.thread_label || item.thread_title || "昨夜余波")}${isRumor(item) ? ' · <span class="rumor-tag">传闻 · 尚未证实</span>' : ""}</small><p>${esc(item.text)}</p></article>`;}).join("") || '<div class="empty-state">宫中暂且平静。</div>'}</div><div class="sheet-actions">${council().active ? '<button type="button" data-open="council">听晨省请安</button>' : ""}<button type="button" class="primary" data-open="${trials().length ? "trial" : "court"}">${trials().length ? "审理妖异案" : v().turn <= 3 ? "回到宫中议事" : "回到朝会"} →</button></div>`;
  }
  function finishTyping() {
    clearTimeout(state.typingTimer);state.typingTimer=null;
    if (state.typingTarget) {
      const el=$(state.typingTarget);if (el) {el.textContent=state.typingText;el.setAttribute("aria-live","polite");}
      const skip=$("#typingSkip");if (skip) skip.hidden=true;
    }
    state.typingTarget=null;state.typingText="";
  }
  function typeText(selector,text) {
    finishTyping();const el=$(selector);if (!el) return;
    const chars=Array.from(String(text));state.typingText=String(text);state.typingTarget=selector;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {finishTyping();return;}
    el.textContent="";el.setAttribute("aria-live","off");let n=0;
    const step=()=>{if (!state.typingTarget) return;el.textContent=chars.slice(0,++n).join("");if(n < chars.length) state.typingTimer=setTimeout(step,32);else finishTyping();};step();
  }
  function renderWhisper() {
    const item=whisper(),quality=item.quality || item.clarity || "voice";
    const names={clear:"听清",fragment:"只听到残句",voice:"只闻其声",sound:"只闻其声"};
    const hints={clear:"话听清了，心思却未必是真的。试着和白天的言行比对。",fragment:"有人经过，后半句话淹没在脚步声里。",voice:"屏风后传来人声，你没有听清具体的话。"};
    if (!item.text) return '<div class="empty-state">此处没有留下可辨的低语。换个地方寻找线索。</div>';
    return `<article class="whisper-card ${esc(quality)}"><div class="whisper-heading"><span class="whisper-seal" aria-hidden="true">听</span><div><span class="pill">${esc(names[quality] || "只闻其声")}</span><h3>屏风后有人低声说……</h3></div></div>${item.emotion ? `<p class="whisper-emotion">声音里透着${esc(item.emotion)}。</p>` : ""}<blockquote id="whisperText">${esc(item.text)}</blockquote><button type="button" class="text-button" id="typingSkip" data-submit="finish_typing">直接读完 ↓</button><p class="muted">${hints[quality] || hints.voice}</p></article><p class="source-note">${item.source === "model" ? "这是她做决定时写下的盘算，由模型生成并经规则校验。" : "这段低语来自离线模板，经规则校验。"}你只知道声音来自这里，不知道是谁。</p><div class="sheet-actions"><button type="button" data-open="suspects">对照嫌疑板</button><button type="button" class="primary" data-close="sheet">记下，继续走走 →</button></div>`;
  }
  function renderCouncil() {
    const list=speeches();if (!list.length) return '<div class="empty-state">今日没有晨省请安。</div>';
    const index=Math.min(state.councilIndex,list.length),entry=list[index],speaker=entry ? person(entry.speaker_id) : null;
    const heard=list.slice(0,index);
    return `<p class="muted">晨省只议宫中事。听完每个人的话，可免费追问其中一人。</p>${entry ? `<article class="council-speech"><div class="person-heading">${avatar(speaker)}<div><h3>${esc(title(speaker))}</h3><p>${esc(speaker?.name || "宫中人")} · ${index+1} / ${list.length}</p>${entry.tone ? `<span class="pill">${esc(entry.tone)}</span>` : ""}</div></div><blockquote>“${esc(entry.text)}”</blockquote><div class="sheet-actions"><button type="button" class="primary" data-submit="council_next">${index === list.length-1 ? "听完了，追问一句" : "听下一位"} →</button></div></article>` : `<div class="info-box">众人已经说完。那些替人开脱的话，未必只是客套。</div>${council().followup_available ? `<label class="field">向谁追问<select id="councilPerson">${list.map(e=>person(e.speaker_id)).filter(Boolean).map(p=>`<option value="${esc(p.id)}">${esc(fullName(p))}</option>`).join("")}</select></label><label class="field">追问一句<textarea id="councilQuestion" maxlength="200" placeholder="例如：你为什么替她说话？"></textarea></label><div class="sheet-actions"><span class="muted">本次请安可追问一人，不耗精力</span><button type="button" class="primary" data-submit="council_ask">追问 →</button></div>` : '<p class="muted">今日的免费追问已用过。</p>'}`} ${heard.length ? `<details class="council-heard"><summary>回看已听过的 ${heard.length} 句话</summary><div class="ledger-list">${heard.map(e=>`<article class="ledger-entry"><small>${esc(fullName(person(e.speaker_id)))}</small><p>${esc(e.text)}</p></article>`).join("")}</div></details>` : ""}<div class="sheet-actions"><button type="button" data-open="dawn">看清晨消息</button><button type="button" data-close="sheet">暂且离席</button></div>`;
  }
  function diaryHTML(report) {
    if (!report || report.error) return `<div class="info-box">${esc(report?.error || "此人的日记暂不可读。")}</div>`;
    if (report.recognized === false) return '<div class="empty-state">尚未确认此人的身份，日记不可读。</div>';
    const requirements=report.requirements || {1:15,2:30,3:50};
    const field=(page,key,label,tier)=>{
      const locked=key === "decision" && (page.decision_locked || page.decision_requires_alliance);
      const value=page[key];
      if (value !== undefined && value !== null && !locked) return `<div class="diary-field"><dt>${label}</dt><dd>${esc(value)}</dd></div>`;
      return `<div class="diary-field locked"><dt>${label}</dt><dd><span aria-hidden="true">◇</span> ${locked ? "须结盟后开放" : `信任达到 ${requirements[tier]}${tier === 3 ? "，或结盟" : ""} 后开放`}</dd></div>`;
    };
    return `<h3>${esc(report.name || report.host_name || "她")}的日记</h3><p class="source-note">${report.source === "model" ? "这是她做决定时写下的盘算，由模型生成并经规则校验。" : "这些盘算来自离线模板，经规则校验。"}</p><p class="muted">当前开放第 ${Math.max(0,Math.min(3,Number(report.tier ?? report.current_tier ?? 0)))} 档。信任回升会补开旧页，已读内容不会因信任下降消失。</p><div class="diary-pages">${(report.pages || []).slice().reverse().map(page=>`<article class="diary-page"><header><h4>第 ${esc(page.turn)} 夜</h4><small>本页已开放 ${esc(page.unlocked_tier ?? 0)} 档${page.generation ? ` · 第 ${esc(page.generation)} 世` : ""}</small></header><dl>${field(page,"observed","看到了什么",1)}${field(page,"judgement","如何判断",2)}${field(page,"decision","决定做什么",3)}${field(page,"memo","留下的备忘",3)}</dl></article>`).join("") || '<div class="empty-state">这一世还没有写下日记。夜晚结算后会留下新页。</div>'}</div>`;
  }

  function renderProbe() {
    const probe=probes()[0];if (!probe) return '<div class="empty-state">暂时没有人在等你的回应。</div>';
    const p=person(probe.actor_id);
    return `<div class="person-heading">${avatar(p)}<div><h3>${esc(title(p))}</h3><p>${esc(p?.name || "宫中人")}想知道，你究竟懂多少。</p></div></div><div class="info-box">“${esc(probe.question)}”</div><p class="muted">回应不耗精力。守旧能打消一点疑心，会心则可能换来合作，也可能暴露你。</p><div class="trial-actions" style="grid-template-columns:1fr 1fr"><button type="button" data-probe="traditional" data-target="${esc(probe.actor_id)}"><strong>依祖制行事</strong><small>守旧回应 · 降低她对你的怀疑</small></button><button type="button" data-probe="knowing" data-target="${esc(probe.actor_id)}"><strong>朕懂你的意思</strong><small>会心回应 · 让她更确信你与众不同</small></button></div>`;
  }
  function renderTrial() {
    const trial=trials()[0];if (!trial) return '<div class="empty-state">暂时没有待审的案子。</div>';
    const p=person(trial.target_id),accuser=person(trial.accuser_id);
    return `<div class="person-heading">${avatar(p)}<div><h3>${esc(title(p))}被指控妖异</h3><p>${esc(p?.name || trial.target_id)}${accuser ? ` · 揭发者：${esc(fullName(accuser))}` : ""}</p></div></div><div class="info-box">${esc(trial.reason || "宫中有人指称，此人的言行与常理不合。")}</div><p class="muted">可疑不等于有罪。这个决定会改变她的命运，也会影响宫中如何看你。</p><div class="trial-actions"><button type="button" class="danger" data-trial="execute" data-target="${esc(trial.target_id)}"><strong>处死</strong><small>处决被告<br>若杀错人，结局会记下此案</small></button><button type="button" data-trial="exile" data-target="${esc(trial.target_id)}"><strong>流放</strong><small>令其离宫<br>此后无法继续接触</small></button><button type="button" data-trial="protect" data-target="${esc(trial.target_id)}"><strong>保下</strong><small>正统 −8<br>揭发者会因此记恨</small></button></div>`;
  }
  function renderResources() {
    return `<p class="muted">这里记录宫中公认的持有者。暗中易手的东西，还需要你自己查出来。</p><div class="resource-list">${publicList("resources").map(r=>`<article class="resource-row"><header><strong>${esc(r.name)}</strong><span>${esc(r.holder_name || person(r.holder_id)?.name || "暂时无人掌管")}</span></header><p>${esc(r.effect || "这份权柄影响着宫中的局势。")}</p>${v().phase === "free" ? `${unlocked("spy") ? `<button type="button" data-act="spy" data-resource="${esc(r.id)}" ${disabledFor(energy().current < 2 ? "精力不足，需要 2 点" : "")}>布置眼线 · 2 点</button>` : ""}${unlocked("seize") ? `<button type="button" data-act="seize" data-resource="${esc(r.id)}" ${disabledFor(energy().current < 2 ? "精力不足，需要 2 点" : "")}>争夺 · 2 点</button>` : ""}${unlocked("decree") ? `<button type="button" data-decree="${esc(r.id)}" ${disabledFor(v().player_status !== "在位" ? "掌握实权时才能改派权柄" : energy().current < 3 ? "精力不足，需要 3 点" : "")}>颁旨改派 · 3 点</button>` : ""}` : ""}</article>`).join("")}</div>`;
  }
  function renderTraces() { return `<p class="muted">彻查可能揪出主谋并拖慢阴谋。连续查实两次，才有机会将它瓦解。</p><div class="resource-list">${publicList("traces","plot_traces").map(t=>`<article class="resource-row"><header><strong>第 ${esc(t.turn)} 幕 · 异动</strong></header><p>${esc(t.text)}</p>${!t.resolved && t.status !== "resolved" && v().phase === "free" && unlocked("investigate") ? `<button type="button" data-act="investigate" data-target="${esc(t.id)}" ${energy().current < 2 ? 'aria-disabled="true" data-reason="精力不足，需要 2 点"' : ""}>顺着这条线索彻查 · 2 点</button>` : ""}</article>`).join("") || '<div class="empty-state">还没有发现异常痕迹。</div>'}</div>`; }
  function renderDecree() {const r=publicList("resources").find(r=>r.id===state.resource);return `<div class="info-box">将${esc(r?.name || "这份权柄")}交给另一人：消耗 3 点精力、正统 −3，失去权柄的人会记恨。</div><label class="field">新的持有者<select id="decreePerson">${(v().people || []).filter(p=>p.alive).map(p=>`<option value="${esc(p.id)}">${esc(fullName(p))}</option>`).join("")}</select></label><div class="sheet-actions"><button type="button" data-open="resources">暂不改派</button><button type="button" class="primary" data-submit="decree">颁旨改派</button></div>`;}
  function renderEnding() {return `<div class="ending-text">${window.StoryMarkdown.render(v().ending || "史书尚未写完。")}</div><div class="sheet-actions"><button type="button" data-open="ledger">回看每次选择</button><button type="button" class="primary" data-open="new">再开一局 →</button></div>`;}
  function renderHelp() {return `<div class="help-steps"><article class="help-step"><h3>议事：从救皇子到守住宫门</h3><p>皇子之病、两本账、宫门，三条线的旧事会在后面回来。先听两份提案，再决定支持谁。</p></article><article class="help-step"><h3>白天：走动，试探，记线索</h3><p>去哪里不耗精力。会谈和试探各花 1 点，辨认 AI 花 2 点。偷听可能听到某人的盘算，也可能只是残句。把听见的和看见的放在一起，再去嫌疑板标记。</p></article><article class="help-step"><h3>夜晚：选一人，听真心话</h3><p>夜谈另外给 2 点精力。与此同时，宫中人也会结盟、揭发、争夺权柄。第二天看他们做了什么。确认身份后，可按信任逐档读私密日记。</p></article><article class="help-step"><h3>最终：保皇位，也要握实权</h3><p>你可以支持变革，但要防止有人借改革坐大。识破六个 AI 是情报优势，保住皇位与实权才是胜负。</p></article></div><p class="muted">前三幕会逐步教你新行动。精力不必花光，最多可留 1 点到明天。</p>`;}
  function renderInterrupt() {const reason=v().interrupt_used_generation ? "这一代已经用过御前叫停。" : v().phase !== "free" ? "只能在白天自由时段叫停。" : v().player_status !== "在位" ? "掌握实权时才能御前叫停。" : energy().current < 2 ? "御前叫停需要 2 点白天精力。" : "";return `<div class="info-box">每代只有一次。花 2 点精力介入，将局势拉回一点。</div>${reason ? `<p>${esc(reason)}</p>` : `<div class="trial-actions">${[["protect","保全关键人","护送证人，阻碍针对她的阴谋"],["expose","公开证据","让各派在明处表态"],["delay","拖延处置","争取复核证词的时间"]].map(([id,label,desc])=>`<button type="button" data-interrupt="${id}"><strong>${label}</strong><small>${desc}</small></button>`).join("")}</div>`}`;}
  function readDiaryArchiveHTML() {
    const pages=v().diary_archive || [];
    if (!pages.length) return "";
    const fields=[["observed","看到了什么"],["judgement","如何判断"],["decision","决定做什么"],["memo","留下的备忘"]];
    return `<details class="read-diary-archive"><summary>已读旧页 · ${pages.length} 页</summary><p class="muted">这里只保留你曾经读到的内容。即使故人换了身体，你记下的这些话还在。</p><div class="diary-pages">${pages.slice().reverse().map(page=>`<article class="diary-page"><header><h4>${esc(page.host_name || person(page.host_id)?.name || "旧日宿主")}</h4><small>第 ${esc(page.turn)} 夜 · 第 ${esc(page.generation || 1)} 世</small></header><dl>${fields.filter(([key])=>page[key] !== undefined && page[key] !== null).map(([key,label])=>`<div class="diary-field"><dt>${label}</dt><dd>${esc(page[key])}</dd></div>`).join("")}</dl></article>`).join("")}</div></details>`;
  }
  function renderReport() {const known=alivePeople().filter(p=>p.identity === "已确认 AI");return `<p class="muted">确认身份后，信任达到 15 / 30 / 50，会逐档开放她这一世的日记。读过的旧页会保留；针对你的决定须结盟后才能读。</p>${known.length ? `<label class="field">选择人物<select id="reportPerson">${known.map(p=>`<option value="${esc(p.id)}" ${p.id === state.selectedId ? "selected" : ""}>${esc(fullName(p))}</option>`).join("")}</select></label><div class="sheet-actions"><button type="button" class="primary" data-submit="report">查阅日记</button></div>` : '<div class="empty-state">你还没有确认哪位宫中人是 AI。先去收集一些线索。</div>'}<div id="reportResult"></div>${readDiaryArchiveHTML()}`;}
  async function selectPerson(id) {
    const p=person(id);if (!p?.alive) return;
    if (v().phase === "day") {openSheet("court");return;}
    state.selectedId=id;state.selectedAction=null;
    if (v().phase === "free" && !(currentPlace()?.people || []).some(item=>(typeof item === "string" ? item : item.id) === id)) {await findPerson(id);return;}
    if (v().phase === "night" && !nightPeople().some(p=>p.id === id)) {toast("今夜请从可翻的牌子里选择一人。");return;}
    renderScene();openSheet("meeting");
  }
  async function findPerson(id) {
    const place=places().find(place=>(place.people || []).some(item=>(typeof item === "string" ? item : item.id) === id));
    if (!place) {toast("今日还不知道她在何处，可以晚些再找。");return;}
    if (place.id !== v().current_place) {const result=await mutate("/api/act",{action:"move",place_id:place.id});if (!result) return;}
    state.selectedId=id;state.selectedAction=null;renderScene();openSheet("meeting");
  }
  function doAction(action,targetId,resourceId) {
    if (state.busy) return;
    const target=targetId || resourceId || state.selectedId || "";
    const visibility=["ally","protect"].includes(action) ? state.visibility : "public";
    if (v().phase === "night") {mutate("/api/night",{person_id:target,visibility,action:action === "deep" ? "talk" : action,question:action === "deep" ? $("#questionInput")?.value.trim() || "" : null,identify:action === "identify"});return;}
    const request=mutate("/api/act",{action,visibility,target_id:target,resource_id:resourceId || "",question:action === "deep" ? $("#questionInput")?.value.trim() || "" : null},action === "eavesdrop" ? {reopen:"whisper"} : action === "review" ? {reopen:"report"} : {});
    if (action === "review") request.then(result=>{if (result && state.sheet === "report") submit("report");});
  }
  function submit(kind) {
    if (kind === "council_next") {state.councilIndex=Math.min(speeches().length,state.councilIndex+1);openSheet("council",false);}
    if (kind === "council_ask") {
      const question=$("#councilQuestion")?.value.trim(),person_id=$("#councilPerson")?.value;
      if (!question || !person_id) {toast("先选择一人，写下一句追问。");return;}
      mutate("/api/council",{person_id,question});
    }
    if (kind === "finish_typing") finishTyping();
    if (kind === "next") mutate("/api/next",{});
    if (kind === "end_day") mutate("/api/end_day",{});
    if (kind === "ask") {if (!$("#questionInput")?.value.trim()) {toast("先写下你想问的问题。");$("#questionInput")?.focus();return;}doAction("deep",state.selectedId);}
    if (kind === "decree") mutate("/api/act",{action:"decree",target_id:$("#decreePerson")?.value,resource_id:state.resource});
    if (kind === "new") {
      const raw=$("#seedInput")?.value.trim() || "";
      if (raw && (!/^-?\d+$/.test(raw) || !Number.isSafeInteger(Number(raw)))) {toast("开局数字请填一个整数，也可以留空。");return;}
      const skip=$("#skipTutorial")?.checked || false;
      state.selectedId=null;state.suspectPage=0;state.nightPage=0;state.councilTurn=null;state.councilIndex=0;mutate("/api/new",{seed:raw ? Number(raw) : null,skip_tutorial:skip});
    }
    if (kind === "report") {
      const id=$("#reportPerson")?.value;if (!id) return;
      api(`/api/report/${encodeURIComponent(id)}`).then(data=>{
        const report=data.report;
        if (!$("#reportResult")) return;
        if (state.sheet !== "report" || $("#reportPerson")?.value !== id) return;
        $("#reportResult").innerHTML=diaryHTML(report);
      }).catch(e=>toast(e.message));
    }
  }
  document.addEventListener("click",event=>{
    const button=event.target.closest("button");if (!button || (state.busy || state.settingsBusy) && !button.dataset.close && button.id !== "sheetClose") return;
    if (button.getAttribute("aria-disabled") === "true") {toast(button.dataset.reason || "这个行动暂时不可用。");return;}
    if (button.dataset.open) {openSheet(button.dataset.open);return;}
    if (button.dataset.close) {closeSheet();return;}
    if (button.dataset.evidence) {state.selectedId=button.dataset.evidence;openSheet("evidence");return;}
    if (button.dataset.person) {selectPerson(button.dataset.person);return;}
    if (button.dataset.find) {findPerson(button.dataset.find);return;}
    if (button.dataset.place) {mutate("/api/act",{action:"move",place_id:button.dataset.place});return;}
    if (button.dataset.policy) {mutate("/api/day",{policy_id:button.dataset.policy});return;}
    if (button.dataset.act) {doAction(button.dataset.act,button.dataset.target,button.dataset.resource);return;}
    if (button.dataset.selectAction) {state.selectedAction=button.dataset.selectAction;openSheet("meeting",false);$("#questionInput")?.focus();return;}
    if (button.dataset.submit) {submit(button.dataset.submit);return;}
    if (button.dataset.filter) {state.suspectFilter=button.dataset.filter;state.suspectPage=0;openSheet("suspects",false);return;}
    if (button.dataset.nightPage) {state.nightPage+=Number(button.dataset.nightPage);openSheet("night_roster",false);return;}
    if (button.dataset.page) {state.suspectPage+=Number(button.dataset.page);openSheet("suspects",false);return;}
    if (button.dataset.probe) {mutate("/api/probe",{actor_id:button.dataset.target,choice:button.dataset.probe});return;}
    if (button.dataset.trial) {mutate("/api/trial",{target_id:button.dataset.target,choice:button.dataset.trial});return;}
    if (button.dataset.decree) {state.resource=button.dataset.decree;openSheet("decree");return;}
    if (button.dataset.interrupt) {mutate("/api/interrupt",{choice_id:button.dataset.interrupt});return;}
  });
  document.addEventListener("change",event=>{if (event.target.name === "visibility") {state.visibility=event.target.value === "secret" ? "secret" : "public";return;}const select=event.target.closest("select[data-mark]");if (select) mutate("/api/mark",{person_id:select.dataset.mark,mark:select.value},{keepSheet:true});});
  $("#dialogueNext").addEventListener("click",nextBeat);
  $("#sheetClose").addEventListener("click",closeSheet);
  $("#scrim").addEventListener("click",closeSheet);
  document.addEventListener("keydown",event=>{
    if (event.key === "Escape" && state.sheet) {closeSheet();return;}
    if (event.key === "Tab" && state.sheet) {
      const focusable=Array.from($("#sheet").querySelectorAll('button:not(:disabled),a[href],input,select,textarea,summary,[tabindex="0"]')).filter(el=>el.offsetParent !== null),first=focusable[0],last=focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {event.preventDefault();last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first?.focus();}
    }
  });
  async function init() {
    aiSettings=window.AISettings?.mount({document,api,isGameBusy:()=>state.busy,
      onBusyChange:value=>{state.settingsBusy=value;},
      onModeChange:config=>{
        if (!state.data) return;
        state.data.model_config=config;
        const mode={online:config.online === true,label:config.online ? "AI 模式" : "离线模式"};
        state.data.mode=mode;state.data.view.mode=mode;
      }});
    try {state.manifest=await api("/assets/manifest.json?v=darkwar-2");}catch { /* Person IDs still resolve existing consort portraits. */ }
    try {render(await api("/api/state"));await aiSettings?.start(state.data?.model_config);}catch(error) {$("#dialogueText").textContent=error.message;$("#goalText").textContent="暂时没有连上游戏。稍后刷新页面即可重试。";toast(error.message);}
  }
  init();
})();

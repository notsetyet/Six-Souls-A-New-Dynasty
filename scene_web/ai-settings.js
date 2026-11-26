/* Inline, iframe-safe model configuration. API keys never enter Web Storage. */
(function (root, factory) {
  "use strict";
  const library = factory();
  if (typeof module === "object" && module.exports) module.exports = library;
  else root.AISettings = library;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";
  const OFFLINE_DESCRIPTION = "可以完整游玩；角色使用预设对白，尚未开启 AI 自主对话。";
  const TOKEN_KEY = "six-souls:anonymous-session:v1";
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]);

  // This is an opaque game session ID, not an API key or a saved credential.
  // sessionStorage is optional: blocked third-party storage still permits play.
  function createSessionTokens(getStorage) {
    let token = "";
    try { const saved = getStorage()?.getItem(TOKEN_KEY); if (validToken(saved)) token = saved; } catch { /* In-memory mode. */ }
    function validToken(value) { return typeof value === "string" && /^[A-Za-z0-9_-]{20,160}$/.test(value); }
    return {
      get: () => token,
      set(value) {
        if (!validToken(value)) return;
        token = value;
        try { getStorage()?.setItem(TOKEN_KEY, value); } catch { /* Never require a new window. */ }
      },
    };
  }

  function mount({document, api, onModeChange = () => {}, onBusyChange = () => {}, isGameBusy = () => false}) {
    const $ = selector => document.querySelector(selector);
    if (!$("#aiSettings")) return null;
    const elements = Object.fromEntries(["aiSettings", "aiModeTitle", "aiModeDescription", "aiKeyHint", "aiUsage", "aiConfigForm", "aiProvider", "aiModel", "aiApiKey", "aiEnable", "aiRemember", "aiCancel", "aiConfigActions", "aiEdit", "aiResume", "aiOffline", "aiForget", "aiFeedback", "aiProviderNote"].map(id => [id, $("#" + id)]));
    let config = null, editing = true, busy = false, restoring = false, catalogSignature = "", gameBusy = false;
    let feedback = "", feedbackError = false, backendNotice = "", started = false;

    function renderFeedback() {
      // Server status is current, whereas validation feedback belongs to the
      // player's last operation. Clearing one must not erase the other.
      const notices = busy ? [feedback] : [feedback, backendNotice];
      elements.aiFeedback.textContent = [...new Set(notices.filter(Boolean))].join("\n");
      elements.aiFeedback.hidden = !elements.aiFeedback.textContent;
      elements.aiFeedback.classList.toggle("is-error", !!feedback && feedbackError);
    }

    function message(text, error = false) {
      feedback = text || "";
      feedbackError = error;
      renderFeedback();
    }

    function provider() { return (config?.providers || []).find(item => item.id === elements.aiProvider.value); }
    function renderModels(preferred) {
      const item = provider();
      const models = item?.models || [];
      elements.aiModel.innerHTML = models.map(model => `<option value="${escapeHTML(model.id)}">${escapeHTML(model.label || model.id)}</option>`).join("");
      elements.aiModel.value = models.some(model => model.id === preferred) ? preferred : models[0]?.id || "";
      elements.aiProviderNote.textContent = item?.enabled === false ? item.reason || item.unavailable_reason || "该服务暂未在此部署中开放。" : "";
      elements.aiProviderNote.hidden = !elements.aiProviderNote.textContent;
    }

    function renderCatalog(force = false) {
      const providers = config?.providers || [];
      const signature = JSON.stringify(providers);
      if (!force && signature === catalogSignature) return;
      const preferred = !editing && config?.provider ? config.provider : elements.aiProvider.value || config?.provider;
      const previousModel = elements.aiModel.value;
      catalogSignature = signature;
      // Disabled deployments remain discoverable, with the reason shown inline.
      elements.aiProvider.innerHTML = providers.map(item => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.label)}${item.enabled === false ? " · 暂未开放" : ""}</option>`).join("");
      elements.aiProvider.value = providers.some(item => item.id === preferred) ? preferred : providers.find(item => item.enabled !== false)?.id || providers[0]?.id || "";
      renderModels(!editing ? config?.model : previousModel);
    }

    function render() {
      const online = config?.online === true;
      elements.aiSettings.classList.toggle("is-online", online);
      elements.aiSettings.setAttribute("aria-busy", String(busy));
      elements.aiModeTitle.textContent = restoring ? "正在恢复 AI 配置…" : online ? `AI 模式 · ${config.provider_label || config.provider || "已连接"}` : "离线模式";
      elements.aiModeDescription.textContent = online ? "已开启 AI 自主对话。新互动会使用当前模型，已有剧情保持原样。" : OFFLINE_DESCRIPTION;
      elements.aiKeyHint.textContent = config?.key_hint ? `密钥 ${config.key_hint}${config.remembered ? " · 已记住" : " · 本次使用"}` : "";
      elements.aiKeyHint.hidden = !config?.key_hint;
      const usage = config?.usage || {};
      const calls = Number(usage.calls) || 0;
      const tokens = (Number(usage.input_tokens) || 0) + (Number(usage.output_tokens) || 0);
      elements.aiUsage.textContent = `本局调用 ${calls} 次${tokens ? ` · ${tokens.toLocaleString()} tokens` : ""}`;
      elements.aiUsage.hidden = !online && calls === 0;
      elements.aiConfigForm.hidden = !editing;
      elements.aiConfigActions.hidden = editing;
      elements.aiCancel.hidden = !(config?.online || config?.can_resume || config?.remembered);
      elements.aiOffline.hidden = !online;
      elements.aiResume.hidden = online || !(config?.can_resume || config?.remembered);
      elements.aiForget.hidden = !(config?.key_hint || config?.remembered || config?.can_resume);
      const blocked = busy || gameBusy || isGameBusy();
      for (const id of ["aiProvider", "aiModel", "aiApiKey", "aiEnable", "aiRemember", "aiCancel", "aiEdit", "aiResume", "aiOffline", "aiForget"]) elements[id].disabled = blocked || !config;
      elements.aiEnable.disabled = blocked || !config || provider()?.enabled === false || !elements.aiModel.value;
      elements.aiRemember.disabled = blocked || !config?.remember_available;
      if (!config?.remember_available) elements.aiRemember.checked = false;
      elements.aiRemember.title = config?.remember_available ? "保存在当前浏览器中；清除网站数据后需重新输入。" : "当前部署暂不支持记住密钥，仍可在本页连续游玩。";
      elements.aiEnable.textContent = busy ? "正在连接…" : online ? "验证并更换" : "开启 AI 模式";
      renderFeedback();
    }

    function update(value) {
      if (!value || typeof value !== "object") return;
      const first = config === null;
      if (!first && !busy && (config.online === true) !== (value.online === true)) {
        // Another tab may revoke the credential; a prior "AI enabled" receipt
        // no longer describes this mode. Same-mode repaints keep user feedback.
        feedback = "";
        feedbackError = false;
      }
      config = value;
      backendNotice = typeof config.notice === "string" ? config.notice : "";
      if (first) editing = !config.online && !config.can_resume && !config.remembered;
      renderCatalog();
      render();
    }

    function setBusy(value) {
      busy = value;
      onBusyChange(value);
      render();
    }

    async function apply(path, body, {restore = false, remember = false} = {}) {
      if (busy || gameBusy || isGameBusy()) { message("当前操作还在进行，请稍候再调整 AI 配置。"); return false; }
      restoring = restore;
      message(restore ? "正在恢复 AI 配置，请稍候…" : "");
      setBusy(true);
      try {
        const next = await api(path, body);
        config = next;
        backendNotice = typeof config.notice === "string" ? config.notice : "";
        editing = !(config.online || config.can_resume || config.remembered);
        elements.aiApiKey.value = "";
        renderCatalog(true);
        onModeChange(config);
        let notice = config.online ? "AI 模式已开启，从接下来的互动开始生效。" : "已切回离线模式，当前进度保持不变。";
        if (remember && config.online) {
          // Confirm a browser round trip rather than claiming Set-Cookie worked.
          try {
            const verified = await api("/api/model-config");
            config = verified;
            backendNotice = typeof config.notice === "string" ? config.notice : "";
            onModeChange(config);
            if (!verified.remembered) notice = "AI 模式已开启，但当前浏览器未能记住配置。本页仍可连续游玩；刷新或关闭后可能需要重新输入。";
          } catch { notice = "AI 模式已开启，暂未确认密钥保存结果。本页可继续游玩，下次进入时请检查模式状态。"; }
        }
        message(notice);
        return true;
      } catch (error) {
        // Keep the previous configuration on failed replacement, and never echo input.
        message(error?.message || "暂时连接不上，当前进度已保留，请稍后重试。", true);
        return false;
      } finally { restoring = false; setBusy(false); }
    }

    async function save(event) {
      event?.preventDefault();
      const key = elements.aiApiKey.value.trim();
      if (!key) { message("请先输入你的 API Key。", true); elements.aiApiKey.focus(); return false; }
      const remember = !!elements.aiRemember.checked && !!config?.remember_available;
      return apply("/api/model-config", {provider: elements.aiProvider.value, model: elements.aiModel.value, api_key: key, remember}, {remember});
    }

    elements.aiConfigForm.addEventListener("submit", save);
    elements.aiProvider.addEventListener("change", () => { renderModels(); message(""); render(); });
    elements.aiEdit.addEventListener("click", () => { if (busy) return; editing = true; renderCatalog(true); message(""); render(); elements.aiApiKey.focus(); });
    elements.aiCancel.addEventListener("click", () => { editing = false; elements.aiApiKey.value = ""; message(""); render(); });
    elements.aiOffline.addEventListener("click", () => apply("/api/model-config/offline", {}));
    elements.aiResume.addEventListener("click", () => apply(config?.can_resume ? "/api/model-config/resume" : "/api/model-config/restore", {}, {restore: true, remember: !!config?.remembered}));
    elements.aiForget.addEventListener("click", async () => {
      if (await apply("/api/model-config/forget", {})) {
        elements.aiRemember.checked = false;
        editing = true;
        message("已删除此浏览器的密钥配置，当前对局继续以离线模式进行。");
        render();
      }
    });

    async function start(initial) {
      if (started) return;
      started = true;
      try {
        update(initial || await api("/api/model-config"));
        if (config.restore_pending && !config.online) await apply("/api/model-config/restore", {}, {restore: true, remember: true});
      } catch { message("暂时无法加载 AI 配置，可先离线游玩。", true); render(); }
    }
    render();
    return {update, start, save, setGameBusy(value) { gameBusy = value; render(); }};
  }
  return {mount, createSessionTokens};
});

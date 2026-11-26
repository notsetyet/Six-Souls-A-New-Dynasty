/* The ending uses a small, local Markdown subset. Raw HTML and links stay text. */
(function (root) {
  "use strict";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);

  function inline(text) {
    // Each matched payload is escaped separately. Generated tags never become
    // input for a later replacement, so formatting cannot create executable HTML.
    const tokens = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|_([^_\n]+)_/g;
    let result = "", offset = 0;
    for (const match of text.matchAll(tokens)) {
      result += escape(text.slice(offset, match.index));
      const tag = match[1] !== undefined ? "code" : match[2] !== undefined || match[3] !== undefined ? "strong" : "em";
      result += `<${tag}>${escape(match.slice(1).find(value => value !== undefined))}</${tag}>`;
      offset = match.index + match[0].length;
    }
    return result + escape(text.slice(offset));
  }

  function render(markdown) {
    const lines = String(markdown ?? "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [], paragraph = [];
    let list = null, fence = null, code = [];
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
      paragraph.length = 0;
    };
    const flushList = () => {
      if (!list) return;
      const start = list.type === "ol" && list.start !== 1 ? ` start="${list.start}"` : "";
      blocks.push(`<${list.type}${start}>${list.items.map(item => `<li>${inline(item)}</li>`).join("")}</${list.type}>`);
      list = null;
    };
    const flushText = () => { flushParagraph(); flushList(); };
    const flushCode = () => {
      blocks.push(`<pre><code>${escape(code.join("\n"))}</code></pre>`);
      code = []; fence = null;
    };
    for (const raw of lines) {
      const line = raw.trim();
      if (fence) {
        if (line.startsWith(fence)) flushCode();
        else code.push(raw);
        continue;
      }
      const fenced = line.match(/^(`{3,}|~{3,})/);
      if (fenced) { flushText(); fence = fenced[1]; continue; }
      if (!line) { flushText(); continue; }
      const heading = line.match(/^(#{1,6})\s+(.+?)(?:\s+#+)?$/);
      if (heading) {
        flushText();
        const level = heading[1].length;
        blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        continue;
      }
      if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) { flushText(); blocks.push("<hr>"); continue; }
      const item = line.match(/^(?:([-+*])\s+|(\d{1,9})[.)]\s+)(.*)$/);
      if (item) {
        flushParagraph();
        const type = item[1] ? "ul" : "ol";
        if (list?.type !== type) { flushList(); list = {type, start: item[2] ? Number(item[2]) : 1, items: []}; }
        list.items.push(item[3]);
        continue;
      }
      if (list && /^\s{2,}\S/.test(raw)) {
        list.items[list.items.length - 1] += " " + line;
        continue;
      }
      flushList(); paragraph.push(line);
    }
    flushText();
    if (fence) flushCode();
    return blocks.join("\n");
  }
  const api = {render};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.StoryMarkdown = api;
})(typeof window !== "undefined" ? window : globalThis);

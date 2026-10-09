"use strict";
// Dashboard for the BoardRoom AI API. All server data is rendered with textContent only.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { config: null, roles: {}, scenarios: {}, current: null, cursor: 0, timer: null };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function headers() {
    const h = { "Content-Type": "application/json" };
    const key = $("apikey").value.trim();
    if (key) h["X-API-Key"] = key;
    return h;
  }

  async function api(path, options) {
    const res = await fetch(path, Object.assign({ headers: headers() }, options || {}));
    const ctype = res.headers.get("content-type") || "";
    const body = ctype.includes("json") ? await res.json() : await res.text();
    if (!res.ok) {
      let detail = body && body.detail !== undefined ? body.detail : body;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      throw new Error(res.status + ": " + (typeof detail === "string" ? detail : JSON.stringify(detail)));
    }
    return body;
  }

  function setStatus(text) { $("status").textContent = text; }

  function roleLabel(id) {
    const r = state.roles[id];
    return r ? r.title + " (" + r.name + ")" : id;
  }

  function optionTitle(id) {
    const sc = state.current && state.current.scenario;
    const opt = sc && sc.options.find((o) => o.id === id);
    return opt ? opt.title : id;
  }

  async function init() {
    try {
      state.config = await api("/api/config");
    } catch (err) { setStatus(err.message); return; }
    const cfg = state.config;
    $("mode").textContent = cfg.access_mode + " | v" + cfg.version + (cfg.sync_runs ? " | sync" : "");
    $("key-wrap").hidden = !cfg.auth_required;
    $("custom-wrap").hidden = !cfg.custom_scenarios_allowed;
    $("rounds").max = String(cfg.max_rounds);
    $("rounds").value = String(cfg.default_rounds);
    $("apikey").value = sessionStorage.getItem("boardroom-key") || "";
    if (cfg.auth_required && !$("apikey").value) { setStatus("Enter an API key to continue."); }
    await loadCatalog();
    const match = /#decision=([A-Za-z0-9_-]+)/.exec(location.hash);
    if (match) openDecision(match[1]);
  }

  async function loadCatalog() {
    try {
      const [sc, roles] = await Promise.all([api("/api/scenarios"), api("/api/roles")]);
      state.roles = {};
      roles.roles.forEach((r) => { state.roles[r.id] = r; });
      const select = $("scenario");
      select.replaceChildren();
      sc.scenarios.forEach((s) => {
        state.scenarios[s.id] = s;
        const opt = el("option", null, s.title);
        opt.value = s.id;
        select.appendChild(opt);
      });
      if (state.config.custom_scenarios_allowed) {
        const opt = el("option", null, "Custom scenario (JSON below)");
        opt.value = "__custom";
        select.appendChild(opt);
      }
      showScenario();
      refreshHistory();
    } catch (err) { setStatus(err.message); }
  }

  function showScenario() {
    const s = state.scenarios[$("scenario").value];
    $("question").textContent = s ? s.question : "Paste a scenario JSON below.";
    const list = $("options");
    list.replaceChildren();
    if (s) s.options.forEach((o) => list.appendChild(el("li", null, o.title + " [" + o.id + "]")));
    if (!s) $("custom-wrap").open = true;
  }

  async function run() {
    const body = { rounds: Number($("rounds").value) };
    const choice = $("scenario").value;
    if (choice === "__custom") {
      try { body.scenario = JSON.parse($("custom").value); }
      catch (err) { setStatus("Custom scenario is not valid JSON."); return; }
    } else {
      body.scenario_id = choice;
    }
    sessionStorage.setItem("boardroom-key", $("apikey").value.trim());
    $("run").disabled = true;
    setStatus("The board is debating...");
    try {
      const created = await api("/api/decisions", { method: "POST", body: JSON.stringify(body) });
      await startView(created);
      if (created.state === "finished" || created.state === "error") {
        (created.events || []).forEach(addEvent);
        finish(created);
      } else {
        poll();
      }
    } catch (err) {
      setStatus(err.message);
      $("run").disabled = false;
    }
  }

  async function openDecision(id) {
    try {
      const detail = await api("/api/decisions/" + encodeURIComponent(id));
      await startView(detail);
      poll();
    } catch (err) { setStatus(err.message); }
  }

  async function startView(detail) {
    clearTimeout(state.timer);
    state.current = { id: detail.id, scenario: null, memo: null };
    state.cursor = 0;
    history.replaceState(null, "", "#decision=" + detail.id);
    $("result").hidden = false;
    $("transcript").replaceChildren();
    $("chart").replaceChildren();
    $("memo").replaceChildren();
    $("headline").textContent = "Debate in progress: " + detail.title;
    const cur = state.current;
    if (state.scenarios[detail.scenario_id] && $("scenario").value !== detail.scenario_id) {
      $("scenario").value = detail.scenario_id;
      showScenario();
    }
    if (state.scenarios[detail.scenario_id]) {
      try { cur.scenario = await api("/api/scenarios/" + encodeURIComponent(detail.scenario_id)); }
      catch (err) { /* titles fall back to option ids */ }
    }
  }

  async function poll() {
    const cur = state.current;
    if (!cur) return;
    try {
      const page = await api("/api/decisions/" + cur.id + "/events?since=" + state.cursor);
      page.events.forEach(addEvent);
      state.cursor = page.next_cursor;
      if (page.done) {
        finish(await api("/api/decisions/" + cur.id));
        return;
      }
    } catch (err) { setStatus(err.message); }
    state.timer = setTimeout(poll, 600);
  }

  function addEvent(ev) {
    const p = ev.position;
    const li = el("li", p.fallback ? "fallback" : null);
    const head = el("div");
    head.appendChild(el("span", "who", roleLabel(p.role_id)));
    head.appendChild(el("span", "stage", ev.stage));
    li.appendChild(head);
    const score = p.scores[p.preferred];
    li.appendChild(el("div", null, "Prefers " + optionTitle(p.preferred) +
      (score !== undefined ? " (" + Number(score).toFixed(1) + "/10)" : "")));
    const why = p.rationale[p.preferred];
    if (why) li.appendChild(el("p", "small", why));
    (p.critiques || []).forEach((c) => li.appendChild(el("p", "small",
      "Challenges " + roleLabel(c.target_role) + " on " + optionTitle(c.option_id) + ": " + c.point)));
    (p.blockers || []).forEach((b) => li.appendChild(el("p", "block", "Blocks " + optionTitle(b))));
    (p.concerns || []).slice(0, 2).forEach((c) => li.appendChild(el("p", "small", "Concern: " + c)));
    $("transcript").appendChild(li);
  }

  function finish(detail) {
    $("run").disabled = false;
    refreshHistory();
    if (detail.state === "error" || !detail.memo) {
      $("headline").textContent = "Debate failed: " + (detail.error || "unknown error");
      setStatus("");
      return;
    }
    const memo = detail.memo;
    state.current.memo = memo;
    setStatus("Done.");
    const head = $("headline");
    head.replaceChildren();
    head.appendChild(el("div", null, "Recommendation"));
    head.appendChild(el("strong", null, memo.recommendation_title));
    head.appendChild(el("span", "conf-" + memo.confidence, "  " + memo.confidence + " confidence"));
    head.appendChild(el("p", "small", memo.summary));
    renderChart(memo);
    renderMemo(memo);
  }

  function renderChart(memo) {
    const chart = $("chart");
    chart.replaceChildren();
    memo.ranking.forEach((r, i) => {
      const row = el("div", "bar-row");
      row.appendChild(el("span", null, r.title));
      const track = el("div");
      const bar = el("div", "bar" + (r.blocked_by.length ? " blocked" : i === 0 ? " top" : ""));
      bar.style.width = Math.max(2, Math.min(100, r.weighted_score * 10)) + "%";
      track.appendChild(bar);
      row.appendChild(track);
      row.appendChild(el("span", null, r.weighted_score.toFixed(2) +
        (r.blocked_by.length ? " blocked" : " | " + r.votes + " votes")));
      chart.appendChild(row);
    });
  }

  function section(root, title, items, cls) {
    if (!items || !items.length) return;
    root.appendChild(el("h3", null, title));
    const ul = el("ul");
    items.forEach((t) => ul.appendChild(el("li", cls, t)));
    root.appendChild(ul);
  }

  function renderMemo(memo) {
    const root = $("memo");
    root.replaceChildren();
    root.appendChild(el("h3", null, memo.title));
    root.appendChild(el("p", null, memo.question));
    section(root, "Security flags", memo.security_flags, "flag");
    section(root, "Dissent", memo.dissent);
    section(root, "Risks", memo.risks);
    section(root, "Conditions", memo.conditions);
    section(root, "Next steps", memo.next_steps);
  }

  async function memoMarkdown() {
    return api("/api/decisions/" + state.current.id + "/memo.md");
  }

  async function copyMemo() {
    try { await navigator.clipboard.writeText(await memoMarkdown()); setStatus("Memo copied."); }
    catch (err) { setStatus("Copy failed: " + err.message); }
  }

  async function downloadMemo() {
    try {
      const blob = new Blob([await memoMarkdown()], { type: "text/markdown" });
      const a = el("a");
      a.href = URL.createObjectURL(blob);
      a.download = state.current.id + "-memo.md";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (err) { setStatus("Download failed: " + err.message); }
  }

  async function refreshHistory() {
    try {
      const list = await api("/api/decisions?limit=10");
      const ul = $("history");
      ul.replaceChildren();
      if (!list.decisions.length) ul.appendChild(el("li", "small", "No decisions yet."));
      list.decisions.forEach((d) => {
        const li = el("li");
        const a = el("a", null, d.title);
        a.href = "#decision=" + d.id;
        a.addEventListener("click", (e) => { e.preventDefault(); openDecision(d.id); });
        li.appendChild(a);
        li.appendChild(el("span", "small", "  " + d.state +
          (d.recommendation ? " -> " + d.recommendation + " (" + d.confidence + ")" : "")));
        ul.appendChild(li);
      });
    } catch (err) { /* history is optional */ }
  }

  function switchTab(name) {
    document.querySelectorAll(".tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    ["debate", "ranking", "memo"].forEach((t) => { $("tab-" + t).hidden = t !== name; });
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("scenario").addEventListener("change", showScenario);
    $("run").addEventListener("click", run);
    $("copy").addEventListener("click", copyMemo);
    $("download").addEventListener("click", downloadMemo);
    $("apikey").addEventListener("change", loadCatalog);
    document.querySelectorAll(".tabs button").forEach((b) => {
      b.addEventListener("click", () => switchTab(b.dataset.tab));
    });
    init();
  });
})();

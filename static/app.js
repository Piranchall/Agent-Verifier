/* Agent Verifier front end. No build step: plain JS talking to the FastAPI server.
   URL options (for study sessions):
     ?mode=simple|detailed   starting level of detail
     ?tool=off               baseline condition: no "where to fix", one replay, no "k of n"
     ?pid=P07                participant id saved with confidence ratings
     ?researcher=1           show researcher controls (planted errors, ground truth)
     ?session=P07            run participant P07's session from study/plan.json
                             (sets pid, tasks, conditions and planted errors per task)       */

const params = new URLSearchParams(location.search);
const S = {
  config: null,
  scenarios: [],
  runs: [],
  runId: null,
  run: null,
  ranking: null,
  rankingLoading: false,
  summaries: {},
  verifs: [],
  activeVerifId: null,
  activeVerif: null,
  editingStep: null,
  mode: params.get("mode") || localStorage.getItem("av-mode") || "simple",
  toolOn: params.get("tool") !== "off",
  researcher: params.get("researcher") === "1",
  pid: params.get("session") || params.get("pid") || null,
  session: params.get("session") || null,
  sessionData: null,   // {tasks, progress}
  taskIndex: null,     // current task in the session
  taskStarted: null,   // ms timestamp
  ratedVerifs: new Set(),
  seenResults: new Set(),
  effects: null,         // Feature 3: {effects, counts} for the open run's family
  baselines: {},         // {baseRunId: {step: {k, n, running}}} no-change replays
  progress: null,        // {id, data}: live progress of the active set of tries
  warnTask: null,        // Feature 3 per-task setting from the session plan (null = not in a session)
};

/* ------------------------------------------------------------------ Feature 3 helpers */
// Warnings show when the release step is on, the tool is on, and (in a session) the task allows them.
const warnActions = () => !!S.config?.release_actions && S.toolOn && (S.warnTask === null || S.warnTask);
const safeKey = () => `av-safe-${S.pid || "anon"}`;
const safeTools = () => new Set(JSON.parse(localStorage.getItem(safeKey()) || "[]"));
function markSafe(tool) {
  const set = safeTools();
  set.add(tool);
  localStorage.setItem(safeKey(), JSON.stringify([...set]));
  logEvent("action_marked_safe", { tool });
}
// Irreversible actions the person should be warned about (not marked safe).
const warnList = () => Object.entries(S.config.tools).filter(([name, t]) => t.irreversible && !safeTools().has(name));

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const stepNo = (i) => i + 1; // people count from 1
const AGENT = { user: "You", planner: "Planner", coder: "Coder", tests: "Test runner", release: "Release" };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/* Action log: only when a participant id is set (?pid= or ?session=). */
function logEvent(event, data = {}) {
  if (!S.pid) return;
  fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, participant: S.pid, task_index: S.taskIndex, run_id: S.run?.id || null, data }),
  }).catch(() => {});
}

function studyQS() {
  const q = new URLSearchParams();
  if (S.pid) q.set("participant", S.pid);
  if (S.taskIndex !== null) q.set("task_index", S.taskIndex);
  return q.toString() ? `?${q}` : "";
}

// Did THIS person ask for a suggestion on this run? (The ranking is cached per run,
// so without this a participant could see a suggestion someone else requested.)
const rankKey = (runId) => `av-rank-${S.pid || "anon"}-${runId}`;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 4500);
}

/* ------------------------------------------------------------------ boot */
async function init() {
  S.config = await api("/api/config");
  S.scenarios = await api("/api/scenarios");
  const env = $("#env");
  env.textContent = `${S.config.provider === "mock" ? "Offline mock agents" : S.config.model} · tests in ${S.config.sandbox === "docker" ? "Docker" : "local Python"}`;
  if (S.config.provider === "mock" || S.config.sandbox === "local") env.classList.add("warn");
  if (S.config.provider === "mock") env.title = "Mock mode is for development. Set LLM_PROVIDER in .env for real agents.";

  const sel = $("#scenario");
  sel.innerHTML = S.scenarios.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}${
    s.level === "experienced" ? " (for experienced users)" : ""}</option>`).join("");
  const showTask = () => ($("#scenario-task").textContent = S.scenarios.find((s) => s.id === sel.value)?.task || "");
  sel.addEventListener("change", showTask);
  showTask();

  $("#start-run").addEventListener("click", startRun);
  $("#finish-task").addEventListener("click", finishTask);
  setInterval(tickTimer, 1000);
  document.querySelectorAll(".switch button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  setMode(S.mode, true);
  $("#researcher-panel").hidden = !S.researcher || !!S.session;

  await refreshRuns();
  setInterval(poll, 1500);
  if (S.session) return loadSession();
  logEvent("app_opened");
  const last = [...S.runs].reverse().find((r) => r.kind === "original");
  if (last) await openRun(last.id);
}

function setMode(mode, quiet) {
  S.mode = mode;
  localStorage.setItem("av-mode", mode);
  document.querySelectorAll(".switch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
  if (!quiet) {
    logEvent("view_switched", { mode });
    if (mode === "simple") loadSummaries();
    render();
  }
}

/* ------------------------------------------------------------------ data */
// Only this person's tries, and in a session only this task's tries (a run can appear in two tasks).
const mine = (verifs) => verifs.filter((v) =>
  (!S.pid || v.participant === S.pid) &&
  (S.taskIndex === null || (v.context || {}).task === S.taskIndex + 1));

async function refreshRuns() {
  S.runs = await api("/api/runs");
  renderRunList();
}

async function openRun(id) {
  S.runId = id;
  S.editingStep = null;
  S.ranking = null;
  S.summaries = {};
  S.run = await api(`/api/runs/${id}`);
  const baseId = S.run.kind === "replay" ? S.run.parent.run_id : id;
  S.verifs = mine(await api(`/api/runs/${baseId}/verifications`));
  S.activeVerifId = S.run.verification_id || (S.verifs.length ? S.verifs[S.verifs.length - 1].id : null);
  S.activeVerif = S.verifs.find((v) => v.id === S.activeVerifId) || null;
  const askedBefore = S.pid ? localStorage.getItem(rankKey(baseId)) === "1" : S.run.has_ranking;
  if (askedBefore && S.toolOn && S.run.kind !== "replay") {
    const q = studyQS();
    try { S.ranking = await api(`/api/runs/${id}/rank${q}${q ? "&" : "?"}restore=1`, { method: "POST" }); } catch (e) { /* ignore */ }
  }
  logEvent("run_opened", { kind: S.run.kind, opened_run: id });
  loadEffects();
  await loadBaselines(baseId);
  if (S.mode === "simple") loadSummaries();
  render();
  renderRunList();
  if (S.session) renderSessionRail();
}

async function loadBaselines(runId) {
  if (!runId) return;
  try {
    S.baselines[runId] = await api(`/api/runs/${runId}/baselines`);
  } catch (e) { /* optional */ }
}
const baselineFor = (v) => (S.baselines[v.base_run_id] || {})[String(v.step)] || null;

async function loadEffects() {
  if (!S.run || !S.config?.release_actions) { S.effects = null; return; }
  const id = S.run.id;
  try {
    const eff = await api(`/api/runs/${id}/effects${studyQS()}`);
    if (S.run && S.run.id === id) { S.effects = eff; renderEffects(); }
  } catch (e) { /* optional panel */ }
}

async function loadSummaries() {
  if (!S.run || S.run.status !== "done" || Object.keys(S.summaries).length) return;
  const id = S.run.id;
  try {
    const sums = await api(`/api/runs/${id}/summaries`, { method: "POST" });
    if (S.run && S.run.id === id) {
      S.summaries = sums;
      renderTimeline();
    }
  } catch (e) {
    /* plain summaries are optional; raw text is shown instead */
  }
}

async function poll() {
  try {
    await refreshRuns();
    if (S.run && (S.run.status === "running" || S.run.status === "queued")) {
      S.run = await api(`/api/runs/${S.run.id}`);
      if (S.run.status === "done" && S.mode === "simple") loadSummaries();
      if (S.run.status === "done") loadEffects();
      render();
    }
    if (S.activeVerif && (S.activeVerif.status === "running" || S.activeVerif.status === "queued")) {
      await loadProgress(S.activeVerif);
      S.activeVerif = await api(`/api/verifications/${S.activeVerif.id}`);
      if (S.activeVerif.status !== "running" && S.activeVerif.status !== "queued") {
        loadEffects();
        await loadBaselines(S.activeVerif.base_run_id);
      }
      const i = S.verifs.findIndex((v) => v.id === S.activeVerif.id);
      if (i >= 0) S.verifs[i] = S.activeVerif;
      renderVerify();
      if (S.session) renderSessionRail();
      if (S.activeVerif.status === "error") toast(S.activeVerif.error);
    }
    const b = S.activeVerif && S.activeVerif.status === "done" ? baselineFor(S.activeVerif) : null;
    if (S.toolOn && S.activeVerif && S.activeVerif.status === "done" && (!b || b.running)) {
      await loadBaselines(S.activeVerif.base_run_id);
      renderVerify();
    }
  } catch (e) {
    /* server restarting; try again next tick */
  }
}

/* ------------------------------------------------------------------ actions */
async function startRun() {
  const btn = $("#start-run");
  btn.disabled = true;
  try {
    const { id } = await api("/api/runs", { method: "POST", body: { scenario_id: $("#scenario").value } });
    await refreshRuns();
    await openRun(id);
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

async function suggestWhere() {
  S.rankingLoading = true;
  renderWhere();
  logEvent("suggest_clicked");
  try {
    S.ranking = await api(`/api/runs/${S.run.id}/rank${studyQS()}`, { method: "POST" });
    localStorage.setItem(rankKey(S.run.id), "1");
  } catch (e) {
    toast(e.message);
  }
  S.rankingLoading = false;
  render();
}

async function submitEdit(step) {
  const typed = $("#edit-text").value.trim();
  const st = S.run.trace[step];
  const mode = addMode(st) ? (st.agent === "user" ? "add_to_request" : st.data.kind === "plan" ? "add_plan_step" : "new_instruction") : "full_text";
  const text = !typed ? "" : mode === "add_to_request" ? `${st.content.trimEnd()}\n\n${typed}`
    : mode === "add_plan_step" ? [typed, ...(st.data.items || [])].map((x, k) => `${k + 1}. ${x}`).join("\n")
    : typed;
  if (!text) return toast("Write the new version of this step first.");
  const n = S.toolOn ? Number($("#edit-n").value) : 1;
  const pre = document.querySelector('input[name="pre"]:checked');
  if (S.pid && !pre) return toast("Before replaying, pick how sure you are (1 to 7).");
  const unanswered = [...document.querySelectorAll(".action-warning li")].filter((li) => !li.querySelector("input:checked"));
  if (unanswered.length) return toast("For each action that can't be undone, choose hold or let it happen.");
  logEvent("edit_submitted", { step: step + 1, mode, typed_length: typed.length });
  // Feature 3: held = checked "hold" boxes; everything else runs (as it would with no warning at all).
  const action_policy = {};
  if (S.config?.release_actions) {
    Object.keys(S.config.tools).forEach((name) => (action_policy[name] = "run"));
    document.querySelectorAll(".action-warning input[type='radio']:checked").forEach((b) => (action_policy[b.dataset.tool] = b.value));
  }
  try {
    const { id } = await api(`/api/runs/${S.run.id}/verify`, { method: "POST", body: {
      step, text, n, participant: S.pid, task_index: S.taskIndex, pre_confidence: pre ? Number(pre.value) : null,
      action_policy, want_baseline: S.toolOn } });
    S.editingStep = null;
    S.verifs = mine(await api(`/api/runs/${S.run.id}/verifications`));
    S.activeVerifId = id;
    S.activeVerif = S.verifs.find((v) => v.id === id);
    if (S.activeVerif) await loadProgress(S.activeVerif);
    render();
    if (S.session) renderSessionRail();
  } catch (e) {
    toast(e.message);
  }
}

async function saveRating(vid) {
  const picked = document.querySelector('input[name="conf"]:checked');
  if (!picked) return toast("Pick a number from 1 to 7.");
  try {
    await api(`/api/verifications/${vid}/confidence`, { method: "POST", body: { rating: Number(picked.value), participant: S.pid } });
    S.ratedVerifs.add(vid);
    renderVerify();
  } catch (e) {
    toast(e.message);
  }
}

/* ------------------------------------------------------------------ render */
function render() {
  const has = !!S.run;
  $("#session-screen").hidden = true;
  $("#empty").hidden = has || !!S.session;
  $("#run-view").hidden = !has;
  $("#evidence").hidden = !has;
  if (!has) return;
  renderHead();
  renderTimeline();
  renderWhere();
  renderVerify();
  renderEffects();
  if (S.researcher) renderResearcher();
}

function renderRunList() {
  const originals = S.runs.filter((r) => r.kind === "original").reverse();
  const byVerif = {};
  S.runs.filter((r) => r.kind === "replay" && (!S.pid || r.participant === S.pid) && (!r.baseline || S.researcher)).forEach((r) => (byVerif[r.verification_id] ||= []).push(r));
  const forkParents = {};
  Object.values(byVerif).forEach((list) => (forkParents[list[0].parent.run_id] ||= []).push(list));

  const item = (r, label) => {
    const live = r.status === "running" || r.status === "queued";
    // replay outcomes are not shown here: the verification readout is the place for that
    const cls = live ? "live" : r.kind === "original" && r.outcome ? (r.outcome.ok ? "ok" : "bad") : "";
    return `<button class="run-item" data-run="${r.id}" aria-current="${r.id === S.runId}">
      <span class="dot ${cls}"></span><span>${label}<br><span class="meta">${new Date(r.created * 1000).toLocaleTimeString()}${r.status === "error" ? " · error" : ""}</span></span></button>`;
  };
  const tree = (run, depth) => {
    const groups = forkParents[run.id] || [];
    if (!groups.length || depth > 4) return "";
    return `<ul>${groups.map((list) => {
      const step = list[0].parent.step;
      return `<li><div class="ver-label">Changed step ${stepNo(step)}</div><ul>${list.map((r, k) =>
        `<li>${item(r, `Try ${k + 1}`)}${tree(r, depth + 1)}</li>`).join("")}</ul></li>`;
    }).join("")}</ul>`;
  };
  const title = (r) => S.scenarios.find((s) => s.id === r.scenario_id)?.title || r.scenario_id;
  $("#run-list").innerHTML = originals.length
    ? originals.map((r) => `<li>${item(r, esc(title(r)))}${tree(r, 0)}</li>`).join("")
    : `<li class="hint">No runs yet.</li>`;
  document.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => openRun(b.dataset.run)));
}

function renderHead() {
  const r = S.run;
  const title = S.scenarios.find((s) => s.id === r.scenario_id)?.title || r.scenario_id;
  let sub = r.kind === "original" ? "Original run" : `A try after changing step ${stepNo(r.parent.step)}`;
  if (r.outcome) sub += ` · ${r.outcome.rounds} round${r.outcome.rounds === 1 ? "" : "s"} · stopped because ${r.outcome.stopped_because}`;
  if (S.mode === "detailed" && r.usage && r.usage.calls) {
    const tokens = r.usage.prompt_tokens + r.usage.completion_tokens;
    sub += ` · ${r.usage.calls} LLM calls${tokens ? `, ${tokens.toLocaleString()} tokens` : ""}`;
  }

  let banner = "";
  const hideOutcome = !S.toolOn && r.kind === "replay";
  if (r.status === "running" || r.status === "queued") {
    banner = `<div class="banner neutral"><span class="spinner"></span> The team is working${r.trace.length ? ` (step ${r.trace.length})` : ""}…</div>`;
  } else if (r.status === "error") {
    banner = `<div class="banner bad"><strong>This run stopped with an error.</strong>${esc(r.error)}</div>`;
  } else if (r.outcome && !hideOutcome) {
    const o = r.outcome;
    const head = o.ok
      ? `<strong>The bug is fixed.</strong>The final code passed all ${o.total} acceptance checks.`
      : `<strong>The bug is still there.</strong>${o.total - o.passed} of ${o.total} acceptance checks failed.`;
    // With the tool on, show every check in plain words so the evidence can be checked, not just trusted.
    banner = `<div class="banner ${o.ok ? "ok" : "bad"}">${head}${S.toolOn ? checksHtml(r) : ""}</div>`;
  }
  $("#run-head").innerHTML = `<h2>${esc(title)}</h2><div class="sub">${esc(sub)}</div>${banner}`;
}

// Simple view edits in your own words (added to the request or plan, or a new instruction);
// Detailed view, or "Edit their full text instead", edits the original text directly.
function addMode(step) {
  return S.mode === "simple" && !S.editFull && step.agent !== "release";
}

function checksHtml(run) {
  const o = run.outcome;
  const plain = S.scenarios.find((x) => x.id === run.scenario_id)?.checks || {};
  const names = Object.keys(plain).length ? Object.keys(plain) : o.failed_tests;
  const failed = new Set(o.failed_tests);
  const rows = names.map((name) => `<li class="${failed.has(name) ? "check-bad" : "check-ok"}">
      <span class="mark" aria-hidden="true">${failed.has(name) ? "✕" : "✓"}</span>
      <span>${esc(plain[name] || name)}${S.mode === "detailed" ? ` <code class="check-name">${esc(name)}</code>` : ""}</span></li>`).join("");
  const output = S.mode === "detailed" && !o.ok
    ? `<details class="more"><summary>Test output</summary><pre class="code">${esc(o.output)}</pre></details>` : "";
  return `<details class="more checks-box" ${o.ok ? "" : "open"}><summary>What the acceptance checks test</summary>
    <ul class="checks">${rows}</ul></details>${output}`;
}

function rankFor(i) {
  if (!S.toolOn || !S.ranking) return null;
  const idx = S.ranking.ranking.findIndex((x) => x.step === i);
  return idx < 0 ? null : { pos: idx + 1, ...S.ranking.ranking[idx] };
}

function diffHtml(diff) {
  return diff.split("\n").map((line) => {
    const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
      : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : "";
    return `<span class="${cls}">${esc(line)}</span>`;
  }).join("\n");
}

function renderTimeline() {
  // Re-rendering must not wipe what someone is typing in the editor.
  const draft = S.editingStep !== null && $("#edit-text") ? {
    text: $("#edit-text").value,
    n: $("#edit-n")?.value,
    pre: document.querySelector('input[name="pre"]:checked')?.value,
    holds: [...document.querySelectorAll(".action-warning input[type='radio']:checked")].map((b) => [b.name, b.value]),
  } : null;
  const r = S.run;
  const editable = new Set(r.editable_steps || []);
  const canEdit = r.status === "done";
  const simple = S.mode === "simple";
  $("#timeline").innerHTML = r.trace.map((s) => {
    const rank = rankFor(s.i);
    let flag = "";
    const shownCount = simple ? 2 : 3;
    if (rank && rank.pos <= shownCount) flag = `<span class="tag flag">${
      simple ? (rank.pos === 1 ? "Start here" : "Also worth trying") : `Suggested #${rank.pos}`}</span>`;
    const edited = s.edited ? `<span class="tag edited">You changed this</span>` : "";
    const isPlan = s.data.kind === "plan";
    const releaseTags = s.agent !== "release" ? ""
      : (s.data.irreversible ? `<span class="tag danger">can't be undone</span>` : "")
        + (s.data.status === "held" ? `<span class="tag held">held, not done</span>` : "");
    const decision = s.agent !== "planner" ? releaseTags
      : isPlan ? `<span class="tag">plan</span>`
      : s.data.plan_step === "fix-up" ? `<span class="tag">fix-up</span>`
      : s.data.plan_step ? `<span class="tag">step ${esc(s.data.plan_step)} of the plan</span>` : "";
    const action = canEdit && editable.has(s.i) && S.editingStep !== s.i
      ? `<span class="step-actions"><button class="btn small" data-edit="${s.i}">Change this step</button></span>` : "";

    let body;
    const plain = S.summaries[String(s.i)];
    if (simple && plain && !isPlan) {
      body = `<div class="step-text plain">${esc(plain)}</div>`;
      if (s.agent !== "release") body += `<details class="more raw"><summary>${s.agent === "user" ? "Your full request" : "What it actually said"}</summary><div class="step-text">${esc(s.content)}</div></details>`;
    }
    else body = `<div class="step-text">${esc(s.content)}</div>`;

    let extra = "";
    if (s.edited && s.data.original && !simple) extra += `<div class="was">Was: <s>${esc(s.data.original)}</s></div>`;
    if (s.agent === "coder" && s.data.diff) {
      extra += simple
        ? `<details class="more"><summary>See the code change</summary><pre class="code">${diffHtml(s.data.diff)}</pre></details>`
        : `<pre class="code">${diffHtml(s.data.diff)}</pre>`;
    }
    if (s.agent === "release" && !simple && s.data.call) {
      extra += `<pre class="code">${esc(s.data.call)}</pre>`;
    }
    if (s.agent === "tests" && !simple && s.data.result) {
      extra += `<details class="more"><summary>Test output</summary><pre class="code">${esc(s.data.result.output)}</pre></details>`;
    }

    let editor = "";
    if (S.editingStep === s.i) {
      const minTries = S.config.min_replays || 3;
      const opts = Array.from({ length: S.config.max_replays - minTries + 1 }, (_, k) => k + minTries)
        .map((k) => `<option value="${k}" ${k === S.config.default_replays ? "selected" : ""}>${k}</option>`).join("");
      editor = `<div class="editor">
        ${addMode(s) ? `<label class="field-label" for="edit-text">${s.agent === "user"
            ? "Add to your request: what else should the team know? (your words are added after the request)"
            : isPlan ? "Add a first step to the plan, in your own words (the team's current steps follow after yours)"
            : "Write a new instruction for this step, in your own words"}</label>
        <textarea id="edit-text" placeholder="In your own words, what should the team do differently?"></textarea>
        <button type="button" class="btn link" id="edit-full">Edit their full text instead</button>`
        : `<label class="field-label" for="edit-text">${s.agent === "user" ? "Rewrite the request"
          : isPlan ? "Rewrite the plan (one step per line; the team will carry out your steps in order)"
          : "Rewrite the planner's instruction for this step"}</label>
        <textarea id="edit-text">${esc(s.content)}</textarea>`}
        ${S.pid ? `<fieldset class="pre-rating"><legend>Before you replay: how sure are you that this change will fix the bug?</legend>
          <div class="scale" role="radiogroup" aria-label="Confidence before replaying, 1 to 7">${[1, 2, 3, 4, 5, 6, 7].map((k) =>
            `<label><input type="radio" name="pre" value="${k}"><span>${k}</span></label>`).join("")}</div>
          <div class="scale-ends"><span>Not sure at all</span><span>Completely sure</span></div></fieldset>` : ""}
        ${warnActions() && warnList().length ? actionWarningHtml(simple) : ""}
        <div class="editor-row">
          ${S.toolOn ? `<label for="edit-n">Number of tries</label><select id="edit-n">${opts}</select>` : ""}
          <button class="btn primary" id="edit-go">${S.toolOn ? "Replay from here" : "Replay once"}</button>
          <button class="btn" id="edit-cancel">Cancel</button>
        </div>
        ${S.toolOn ? `<p class="hint">The run restarts from this step with your text. Each try runs the rest of the team again, so the results can differ.</p>` : ""}
      </div>`;
    }

    return `<li class="step ${rank && rank.pos <= (simple ? 2 : 3) ? "flagged" : ""}" data-agent="${s.agent}" id="step-${s.i}">
      <div class="step-num" aria-label="Step ${stepNo(s.i)}">${stepNo(s.i)}</div>
      <div class="step-card">
        <div class="step-top"><span class="agent-name">${AGENT[s.agent] || s.agent}</span>${flag}${edited}${decision}${action}</div>
        ${body}${extra}${editor}
      </div></li>`;
  }).join("");

  document.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => {
    S.editingStep = Number(b.dataset.edit);
    S.editFull = false;
    const top = S.ranking?.ranking?.[0];
    logEvent("editor_opened", { step: S.editingStep + 1, suggested_top_step: top ? top.step + 1 : null });
    if (warnActions() && warnList().length) logEvent("actions_warning_shown", { tools: warnList().map(([n]) => n) });
    renderTimeline();
    $("#edit-text").focus();
  }));
  if (S.editingStep !== null) {
    if (draft) {
      $("#edit-text").value = draft.text;
      if (draft.n && $("#edit-n")) $("#edit-n").value = draft.n;
      if (draft.pre) document.querySelector(`input[name="pre"][value="${draft.pre}"]`).checked = true;
      (draft.holds || []).forEach(([name, value]) => {
        const box = document.querySelector(`input[name='${name}'][value='${value}']`);
        if (box) box.checked = true;
      });
    }
    $("#edit-go").addEventListener("click", () => submitEdit(S.editingStep));
    $("#edit-full")?.addEventListener("click", () => {
      S.editFull = true;
      logEvent("editor_full_text", { step: S.editingStep + 1 });
      const keep = $("#edit-text").value;
      renderTimeline();
      if (keep.trim()) $("#edit-text").value = keep;
      $("#edit-text").focus();
    });
    document.querySelectorAll("[data-safe]").forEach((b) => b.addEventListener("click", () => {
      markSafe(b.dataset.safe);
      renderTimeline();
    }));
    document.querySelectorAll(".action-warning input[type='radio']").forEach((b) => b.addEventListener("change", () =>
      logEvent("action_choice", { tool: b.dataset.tool, choice: b.value })));
    $("#edit-cancel").addEventListener("click", () => {
      logEvent("editor_cancelled", { step: S.editingStep + 1 });
      S.editingStep = null;
      renderTimeline();
    });
  }
}

/* ------------------------------------------------------------------ Feature 3 */
function actionWarningHtml(simple) {
  const list = warnList();
  const items = list.map(([name, t]) => `
    <li><div><strong>${esc(t.label)}</strong>: ${esc(t.plain)}</div>
      <div class="choice" role="radiogroup" aria-label="${esc(t.label)} during replays">
        <label><input type="radio" name="act-${name}" data-tool="${name}" value="hold"> Hold during replays</label>
        <label><input type="radio" name="act-${name}" data-tool="${name}" value="run"> Let it happen</label>
      </div>
      ${simple ? "" : `<button type="button" class="btn link" data-safe="${name}">Mark as safe (stop warning me)</button>`}</li>`).join("");
  return `<div class="action-warning" role="note">
    <p class="warn-title">This replay can do things that can't be undone</p>
    <p>If a try passes the quick check, the team releases its code. Each try can do this, so several tries can repeat these actions several times. Choose for each one:</p>
    <ul>${items}</ul>
    <p class="hint">Held actions are recorded but not done. Actions you let happen are done in every try that releases.</p>
  </div>`;
}

function renderEffects() {
  const panel = $("#effects-panel");
  if (!panel) return;
  panel.hidden = !(S.run && warnActions());
  if (panel.hidden) return;
  const body = $("#effects-body");
  const eff = S.effects;
  if (!eff) { body.innerHTML = `<p class="muted">Loading…</p>`; return; }
  const c = eff.counts;
  const n = (key) => c[key] || 0;
  if (!eff.effects.length) {
    body.innerHTML = `<p class="muted">Nothing has been released for this run yet.</p>`;
    return;
  }
  const lines = [
    [`deploy_to_production:done`, (k) => `The live app was replaced ${k} time${k === 1 ? "" : "s"}.`],
    [`email_customer:done`, (k) => `The customer received ${k} email${k === 1 ? "" : "s"} saying the bug is fixed.`],
  ].filter(([key]) => n(key)).map(([key, text]) => `<li class="effect-bad">${text(n(key))}</li>`);
  const held = Object.entries(c).filter(([k]) => k.endsWith(":held")).reduce((a, [, v]) => a + v, 0);
  if (held) lines.push(`<li class="effect-held">${held} action${held === 1 ? " was" : "s were"} held and never happened.</li>`);
  let detail = "";
  if (S.mode === "detailed") {
    detail = `<details class="more"><summary>Every action (${eff.effects.length})</summary><div class="table-wrap"><table class="replay-table">
      <thead><tr><th>When</th><th>Run</th><th>Action</th><th>Result</th></tr></thead><tbody>
      ${eff.effects.map((e) => `<tr><td>${new Date(e.time * 1000).toLocaleTimeString()}</td>
        <td><button class="btn link" data-open="${e.run_id}">${e.kind === "original" ? "original" : "try"}</button></td>
        <td>${esc(S.config.tools[e.tool]?.label || e.tool)}</td><td>${e.status === "held" ? "held" : "done"}</td></tr>`).join("")}
      </tbody></table></div></details>`;
  }
  body.innerHTML = `<ul class="effects">${lines.join("")}</ul>${detail}`;
  body.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openRun(b.dataset.open)));
}

function renderWhere() {
  const panel = $("#where-panel");
  panel.hidden = !S.toolOn;
  if (!S.toolOn) return;
  const r = S.run;
  const body = $("#where-body");
  if (r.status !== "done") {
    body.innerHTML = `<p class="muted">Available when the run finishes.</p>`;
    return;
  }
  if (r.outcome.ok && !S.ranking) {
    body.innerHTML = `<p class="muted">This run fixed the bug, so there is nothing to point at.</p>`;
    return;
  }
  if (S.rankingLoading) {
    body.innerHTML = `<p><span class="spinner"></span> Reading the run…</p>`;
    return;
  }
  if (!S.ranking) {
    body.innerHTML = `<p class="muted">Get a suggestion for which step to change. It can be wrong, so check it against the run.</p>
      <button class="btn" id="rank-go">Suggest where to fix</button>`;
    $("#rank-go").addEventListener("click", suggestWhere);
    return;
  }
  const list = S.ranking.ranking;
  const kindName = { plan: "the plan", request: "your request", instruction: "an instruction" };
  const card = (x, lead, technical) => `<div class="suggestion">
      <div class="lead">${lead} step ${stepNo(x.step)} <span class="kind">(${kindName[x.kind] || "a step"})</span></div>
      ${x.how_used ? `<div class="how-used">${esc(x.how_used)}</div>` : ""}
      ${(technical ? x.why_technical : x.why_plain) || x.why_plain ? `<div class="what"><strong>What to change:</strong> ${esc((technical ? x.why_technical : x.why_plain) || x.why_plain)}</div>` : ""}
      <button class="btn link" data-jump="${x.step}">Show step ${stepNo(x.step)}</button></div>`;
  const intro = `<p class="muted">Suggestions can be wrong. Check them against the run.</p>`;
  body.innerHTML = S.mode === "simple"
    ? intro + card(list[0], "Start with", false) + (list[1] ? card(list[1], "Or try", false) : "")
    : intro + list.slice(0, 3).map((x, k) => card(x, `#${k + 1}:`, true)).join("");
  body.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
    logEvent("jumped_to_step", { step: Number(b.dataset.jump) + 1 });
    document.getElementById(`step-${b.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }));
}

// The verdict compares the person's tries with replaying unchanged, and says how much a few tries can show.
function verdictText(k, n, b) {
  if (k === 0) return "Your change did not fix the bug in any try.";
  const some = k === n ? "It worked in every try" : `It worked in ${k} of ${n} tries`;
  if (!b || !b.n) return `${some}, but there is no comparison yet with replaying unchanged, so this can't tell your change apart from luck.`;
  const gap = k / n - b.k / b.n;
  if (gap >= 0.5) return `${some}, and replaying without your change rarely did. That points to your change as what helped.`;
  if (gap > 0) return `${some}, slightly more often than replaying without your change. That is too small a difference to tell your change apart from luck.`;
  return `${some}, but replaying without your change did just as well. This doesn't show that your change helped.`;
}

function cautionText(k, n) {
  if (k === n) return `With ${n} tries, a fix that only works half the time still gets ${n} of ${n} about 1 time in ${2 ** n}. Treat this as a strong hint, not proof.`;
  return `With only ${n} tries, these numbers can shift a lot. Treat them as a hint, not proof.`;
}

function baselineHtml(v) {
  const b = baselineFor(v);
  if (!b || (!b.n && b.running)) {
    return `<p class="baseline"><span class="spinner"></span> Checking what happens if the run is replayed without your change…</p>`;
  }
  if (!b.n) return `<p class="baseline muted">No comparison without your change is available for this step.</p>`;
  return `<div class="baseline"><span class="baseline-label">Without your change:</span>
    <strong>${b.k} of ${b.n}</strong> tries fixed the bug${b.running ? ` <span class="spinner" title="More no-change tries are running"></span>` : ""}</div>`;
}

function renderVerify() {
  const body = $("#verify-body");
  const v = S.activeVerif;
  if (!v) {
    body.innerHTML = `<p class="muted">Change a step in the run, then replay it. ${S.toolOn ? "You will see how many tries actually fixed the bug." : ""}</p>`;
    return;
  }
  const runsById = Object.fromEntries(S.runs.map((r) => [r.id, r]));
  const header = `<p class="muted">You changed step ${stepNo(v.step)}${S.toolOn ? ` · ${v.n} ${v.n === 1 ? "try" : "tries"}` : ""}.</p>`;

  if (v.status === "error") {
    body.innerHTML = header + `<p>The replays stopped with an error: ${esc(v.error)}</p>`;
    return;
  }

  if (!S.toolOn) {
    const rid = v.replay_ids[0];
    const done = v.status === "done";
    if (done && !S.seenResults.has(v.id)) {
      S.seenResults.add(v.id);
      logEvent("result_seen", { verification_id: v.id, step: v.step + 1, tool: "off" });
    }
    if (!done) setTimeout(wireProgress, 0);
    body.innerHTML = header + (done
      ? `<p>The replay finished. Open it to check the result yourself.</p><button class="btn" data-open="${rid}">Open the replay</button>`
      : progressHtml(v, false)) + (done ? ratingHtml(v) : "");
    wireVerify(v);
    return;
  }

  if (v.status !== "done") {
    body.innerHTML = header + progressHtml(v, true);
    wireProgress();
    return;
  }

  const res = v.result;
  if (!S.seenResults.has(v.id)) {
    S.seenResults.add(v.id);
    const b = baselineFor(v);
    logEvent("result_seen", { verification_id: v.id, step: v.step + 1, shown_k: res.k, n: res.n, mode: S.mode,
      baseline_k: b && b.n ? b.k : null, baseline_n: b && b.n ? b.n : null });
  }
  const circles = res.replays.map((row, k) =>
    `<span class="try ${row.ok ? "ok" : "bad"}" title="Try ${k + 1}: ${row.ok ? "fixed" : "not fixed"}">${row.ok ? "✓" : "✕"}</span>`).join("");
  let detail = "";
  if (S.mode === "detailed") {
    const versions = {};
    let letter = 65;
    res.replays.forEach((row) => { if (row.final_code && !versions[row.final_code]) versions[row.final_code] = String.fromCharCode(letter++); });
    detail = `<div class="table-wrap"><table class="replay-table"><thead><tr>
        <th>Try</th><th>Checks</th><th>Ended because</th><th>First differs</th><th>Code</th></tr></thead><tbody>
      ${res.replays.map((row, k) => `<tr>
        <td><button class="btn link" data-open="${row.run_id}">${k + 1}</button></td>
        <td>${row.status === "done" ? esc(row.hidden) : "error"}</td>
        <td>${esc(row.stopped_because || row.error || "")}</td>
        <td>${k === 0 ? "reference" : row.diverges_from_first_at == null ? "same as try 1" : `step ${stepNo(row.diverges_from_first_at)}`}</td>
        <td>${versions[row.final_code] || "–"}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted">${res.distinct_final_code} different version${res.distinct_final_code === 1 ? "" : "s"} of the final code across ${res.n} tries.${res.errors ? ` ${res.errors} tr${res.errors === 1 ? "y" : "ies"} ended in an error and count as not fixed.` : ""}</p>`;
  } else {
    detail = `<p class="muted">Each try reran the team from your change and checked the final code against the hidden acceptance checks.</p>`;
  }
  body.innerHTML = header + `<div class="readout">
      <div class="tries">${circles}</div>
      <div class="big-count">${res.k} <span class="of">of ${res.n}</span></div>
      <div>tries fixed the bug <strong>with your change</strong></div>
      ${baselineHtml(v)}
      <p class="verdict">${verdictText(res.k, res.n, baselineFor(v))}</p>
      <p class="hint">${cautionText(res.k, res.n)}</p>
    </div>${detail}${ratingHtml(v)}${historyHtml(v)}`;
  wireVerify(v);
}

/* ------------------------------------------------------------------ live progress while replaying */
const TYPICAL_STEPS = 11;  // a plan-then-execute run is about 11 steps (14 with the release step)

function doingText(t) {
  if (t.status === "waiting" || t.status === "queued") return "Waiting to start";
  if (t.status === "done") return "Finished. Its result is shown when all tries are done.";
  if (t.status === "error") return "Stopped with an error";
  const next = t.next[0];
  if (next === "plan") return "The planner is writing a plan";
  if (next === "planner") {
    return t.plan_index !== null && t.plan_len && t.plan_index < t.plan_len
      ? `The planner is writing the instruction for plan step ${t.plan_index + 1} of ${t.plan_len}`
      : "The planner is writing a fix-up instruction";
  }
  if (next === "coder") return "The coder is changing the code";
  if (next === "tests") return "Running the quick check";
  if (next === "release") return "Releasing the code";
  return "Starting";
}

function etaText(seconds) {
  if (seconds === null || seconds === undefined) return "Working out how long this takes…";
  if (seconds < 60) return "Less than a minute left";
  return `About ${Math.ceil(seconds / 60)} min left`;
}

function progressHtml(v, toolOn) {
  const p = S.progress && S.progress.id === v.id ? S.progress.data : null;
  if (!p) return `<p><span class="spinner"></span> Starting the replay…</p>`;
  const expected = TYPICAL_STEPS + (S.config.release_actions ? 3 : 0);
  const rows = p.tries.map((t) => {
    const pct = t.status === "done" || t.status === "error" ? 100 : Math.min(95, Math.round((t.steps / expected) * 100));
    const watch = t.run_id && (t.status === "running" || t.status === "done")
      ? `<button class="btn link" data-watch="${t.run_id}">${t.status === "running" ? "Watch" : "Open"}</button>` : "";
    return `<li class="${t.status}">
      <div class="try-head"><strong>${toolOn ? `Try ${t.index}` : "Replay"}</strong>
        <span class="muted">${t.steps ? `step ${t.steps}` : ""}</span>${watch}</div>
      <div class="bar" aria-hidden="true"><span style="width:${pct}%"></span></div>
      <div class="doing">${t.status === "running" ? '<span class="spinner"></span> ' : ""}${esc(doingText(t))}</div></li>`;
  }).join("");
  return `<div class="progress">
    ${p.waiting_behind ? `<p class="muted">Waiting for ${p.waiting_behind} other replay${p.waiting_behind === 1 ? "" : "s"} to finish first.</p>` : ""}
    <p class="eta">${etaText(p.eta_seconds)}</p>
    <ul class="try-list">${rows}</ul>
    ${toolOn ? `<p class="hint">Results are shown together when all tries finish, so one lucky try doesn't decide for you.</p>` : ""}
    ${toolOn && p.baseline_pending ? `<p class="hint">After your tries, the team also replays this step without your change, for comparison.</p>` : ""}
  </div>`;
}

function wireProgress() {
  document.querySelectorAll("[data-watch]").forEach((b) => b.addEventListener("click", () => {
    logEvent("watch_try_opened", { run: b.dataset.watch });
    openRun(b.dataset.watch);
  }));
}

async function loadProgress(v) {
  try {
    S.progress = { id: v.id, data: await api(`/api/verifications/${v.id}/progress`) };
  } catch (e) { /* keep the last progress */ }
}

function ratingHtml(v) {
  if (S.ratedVerifs.has(v.id) || (v.confidence || []).some((c) => c.participant === S.pid)) {
    return `<div class="rating"><p class="muted">Rating saved. Thank you.</p></div>`;
  }
  const opts = [1, 2, 3, 4, 5, 6, 7].map((n) =>
    `<label><input type="radio" name="conf" value="${n}"><span>${n}</span></label>`).join("");
  return `<div class="rating"><p><strong>How sure are you that your change fixed the bug?</strong></p>
    <div class="scale" role="radiogroup" aria-label="Confidence from 1 to 7">${opts}</div>
    <div class="scale-ends"><span>Not sure at all</span><span>Completely sure</span></div>
    <button class="btn" id="rate-go">Save rating</button></div>`;
}

function historyHtml(v) {
  const others = S.verifs.filter((x) => x.id !== v.id);
  if (!others.length) return "";
  return `<details class="more"><summary>Earlier changes to this run (${others.length})</summary><ul>
    ${others.map((x) => `<li><button class="btn link" data-verif="${x.id}">Step ${stepNo(x.step)}${x.result && S.toolOn ? `: ${x.result.k} of ${x.result.n}` : ""}</button></li>`).join("")}
  </ul></details>`;
}

function wireVerify(v) {
  const body = $("#verify-body");
  body.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openRun(b.dataset.open)));
  body.querySelectorAll("[data-verif]").forEach((b) => b.addEventListener("click", () => {
    logEvent("earlier_change_opened", { verification_id: b.dataset.verif });
    S.activeVerifId = b.dataset.verif;
    S.activeVerif = S.verifs.find((x) => x.id === S.activeVerifId);
    renderVerify();
  }));
  $("#rate-go")?.addEventListener("click", () => saveRating(v.id));
}

/* ------------------------------------------------------------------ session runner */
async function loadSession() {
  document.body.classList.add("session-mode");
  $("#session-block").hidden = false;
  try {
    S.sessionData = await api(`/api/session/${encodeURIComponent(S.session)}`);
  } catch (e) {
    return showSessionScreen(`<h2>No session found</h2><p>There is no study plan for “${esc(S.session)}”. Check the link with the researcher.</p>`);
  }
  if (S.sessionData.problems?.length) return showSessionProblem(S.sessionData.problems);
  logEvent("session_opened");
  const prog = S.sessionData.progress;
  if (prog.finished) return showDone();
  const current = prog.current || 0;
  if (prog.tasks[String(current)]?.started && !prog.tasks[String(current)]?.finished) return enterTask(current);
  showTaskIntro(current);
}

function showSessionScreen(html) {
  S.run = null;
  $("#run-view").hidden = true;
  $("#evidence").hidden = true;
  $("#empty").hidden = true;
  const screen = $("#session-screen");
  screen.innerHTML = html;
  screen.hidden = false;
  renderSessionRail();
}

function showTaskIntro(i) {
  const tasks = S.sessionData.tasks;
  const t = tasks[i];
  S.taskIndex = null;
  const first = i === 0;
  showSessionScreen(`
    <h2>${first ? "Welcome" : "Next task"}</h2>
    <p>${first ? `You will work through ${tasks.length} tasks. In each one, an AI coding team tried to fix a bug in a to-do app and failed. Your job is to change one step of what they did, replay it, and decide whether your change fixed the bug.` : ""}</p>
    <p><strong>Task ${i + 1} of ${tasks.length}</strong>${t.practice ? " · practice" : ""}${t.minutes ? ` · about ${t.minutes} minute${t.minutes === 1 ? "" : "s"}` : ""}</p>
    <p>Please think aloud as you work.</p>
    <button class="btn primary" id="task-go">Start task ${i + 1}</button>`);
  $("#task-go").addEventListener("click", async () => {
    try {
      await api(`/api/session/${encodeURIComponent(S.session)}/tasks/${i}/start`, { method: "POST" });
    } catch (e) {
      return showSessionProblem([e.message]);
    }
    S.sessionData.progress.tasks[String(i)] = { started: Date.now() / 1000 };
    enterTask(i);
  });
}

async function enterTask(i) {
  const t = S.sessionData.tasks[i];
  S.taskIndex = i;
  S.toolOn = t.tool !== "off";
  S.warnTask = !!t.warn_actions;
  S.seenResults = new Set();
  const started = S.sessionData.progress.tasks[String(i)]?.started;
  S.taskStarted = started ? started * 1000 : Date.now();
  setMode(t.mode || "simple", true);
  try {
    await openRun(t.run_id);
  } catch (e) {
    S.taskIndex = null;
    S.taskStarted = null;
    showSessionProblem([`Task ${i + 1}: could not open run ${t.run_id} (${e.message}).`]);
  }
}

function showSessionProblem(problems) {
  showSessionScreen(`<h2>This session isn't ready</h2>
    <p>Please tell the researcher. Details:</p>
    <ul>${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
    <p class="hint">Researcher: fix study/plan.json, check it at /api/plan/check, then reload this page.</p>`);
}

function showDone() {
  S.taskIndex = null;
  S.taskStarted = null;
  showSessionScreen(`<h2>All done. Thank you!</h2><p>You have finished every task. Please let the researcher know.</p>`);
}

async function finishTask() {
  if (!confirm("Finish this task and move on? You won't be able to come back to it.")) return;
  const i = S.taskIndex;
  try {
    const prog = await api(`/api/session/${encodeURIComponent(S.session)}/tasks/${i}/finish`, { method: "POST" });
    S.sessionData.progress = prog;
    S.taskStarted = null;
    if (prog.finished) showDone();
    else showTaskIntro(prog.current);
  } catch (e) {
    toast(e.message);
  }
}

function renderSessionRail() {
  if (!S.session || !S.sessionData) return;
  const { tasks, progress } = S.sessionData;
  const active = S.taskIndex;
  $("#session-title").textContent = active !== null ? `Task ${active + 1} of ${tasks.length}` : "Your session";
  $("#session-tasks").innerHTML = tasks.map((t, i) => {
    const done = progress.tasks[String(i)]?.finished;
    return `<li class="${i === active ? "current" : ""}${done ? " done" : ""}">${done ? "✓ " : ""}Task ${i + 1}${t.practice ? " (practice)" : ""}</li>`;
  }).join("");
  const inTask = active !== null && S.run;
  $("#finish-task").hidden = !inTask;
  let tries = "";
  if (inTask) {
    const base = S.sessionData.tasks[active].run_id;
    tries = `${S.run.id !== base ? `<button class="btn link" id="back-base">Back to the original run</button>` : ""}`;
    if (S.verifs.length) {
      tries += `<p class="field-label" style="margin-top:10px">Your changes</p><ul class="run-list">${S.verifs.map((v, k) =>
        `<li><button class="run-item" data-session-verif="${v.id}" aria-current="${v.id === S.activeVerifId}">
          <span class="dot ${v.status === "running" || v.status === "queued" ? "live" : ""}"></span>
          <span>Change ${k + 1}: step ${stepNo(v.step)}</span></button></li>`).join("")}</ul>`;
    }
  }
  $("#session-tries").innerHTML = tries;
  $("#back-base")?.addEventListener("click", () => openRun(S.sessionData.tasks[active].run_id));
  document.querySelectorAll("[data-session-verif]").forEach((b) => b.addEventListener("click", async () => {
    const base = S.sessionData.tasks[active].run_id;
    if (S.run.id !== base) await openRun(base);
    S.activeVerifId = b.dataset.sessionVerif;
    S.activeVerif = S.verifs.find((v) => v.id === S.activeVerifId);
    renderVerify();
    renderSessionRail();
  }));
  tickTimer();
}

function tickTimer() {
  const el = $("#session-timer");
  if (!S.session || !S.taskStarted || S.taskIndex === null) { el.textContent = ""; return; }
  const secs = Math.floor((Date.now() - S.taskStarted) / 1000);
  const limit = S.sessionData.tasks[S.taskIndex].minutes;
  el.textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}${limit ? ` of ${limit}:00` : ""}`;
  el.classList.toggle("over", !!limit && secs > limit * 60);
  el.title = limit && secs > limit * 60 ? "Time is up. Finish the task when you are ready." : "";
}

/* ------------------------------------------------------------------ researcher */
async function renderResearcher() {
  const body = $("#researcher-body");
  const r = S.run;
  if (r.status !== "done") { body.innerHTML = `<p class="muted">Available when the run finishes.</p>`; return; }
  const full = await api(`/api/runs/${r.id}?researcher=1`);
  const plant = full.plant || {};
  const steps = (full.editable_steps || []).map((i) =>
    `<option value="${i}" ${plant.rank_move_to_step === i ? "selected" : ""}>Step ${stepNo(i)}</option>`).join("");
  let truth = "";
  if (full.ranking_true) truth += `<div>True ranking: ${full.ranking_true.map((x) => `step ${stepNo(x.step)}`).join(", ")}</div>`;
  if (S.activeVerif) {
    const tv = await api(`/api/verifications/${S.activeVerif.id}?researcher=1`);
    if (tv.result) truth += `<div>Active verification: shown ${tv.result.k} of ${tv.result.n}, true ${tv.result.true_k} of ${tv.result.n}${tv.result.planted ? " (planted)" : ""}</div>`;
  }
  body.innerHTML = `
    <p>Run id: <code>${esc(r.id)}</code> <button class="btn link" id="copy-id">Copy</button></p>
    ${S.config.study_mode ? `<p class="muted">Planted errors set here apply to this run for everyone outside a session. In sessions, use plant_suggest_step and overstate_by in study/plan.json instead.</p>
    <div class="row"><label class="field-label" for="pl-step">Point "where to fix" at</label>
      <select id="pl-step"><option value="">No planted step (real suggestion)</option>${steps}</select></div>
    <div class="row"><label class="field-label" for="pl-over">Overstate "k of n" by</label>
      <input id="pl-over" type="number" min="0" max="5" value="${plant.verify_overstate_by || 0}"></div>
    <button class="btn" id="pl-save">Save planted errors</button>`
    : `<p class="muted">Planted errors are off. They only work with <code>STUDY_MODE=on</code> in .env.</p>`}
    ${truth ? `<div class="truth" style="margin-top:10px">${truth}</div>` : ""}
    <p class="muted" style="margin-top:10px">Sessions: list tasks in <code>study/plan.json</code>, check it at <code>/api/plan/check</code>, then send <code>?session=P01</code>.</p>`;
  $("#copy-id").addEventListener("click", () => navigator.clipboard?.writeText(r.id).then(() => toast("Run id copied.")));
  $("#pl-save")?.addEventListener("click", async () => {
    const v = $("#pl-step").value;
    await api(`/api/runs/${r.id}/plant`, { method: "POST", body: {
      rank_move_to_step: v === "" ? null : Number(v), verify_overstate_by: Number($("#pl-over").value || 0) } });
    S.ranking = null;
    toast("Planted errors saved for this run.");
    render();
  });
}

init().catch((e) => toast(e.message));

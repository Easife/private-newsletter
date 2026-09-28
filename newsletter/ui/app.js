const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

let lastLogSequence = 0;
let settings = null;
let lastState = "idle";

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
  return body;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[ch]);
}

function timePart(value) {
  if (!value) return "--:--:--";
  try { return new Date(value).toLocaleTimeString("zh-CN", { hour12: false }); }
  catch { return "--:--:--"; }
}

function appendLogs(rows) {
  if (!rows.length) return;
  const consoleBox = $("#console");
  const empty = $(".console-empty", consoleBox);
  if (empty) empty.remove();
  rows.forEach(row => {
    const div = document.createElement("div");
    div.className = `log-row ${row.level}`;
    div.innerHTML = `<span class="log-time">${escapeHtml(timePart(row.time))}</span><span class="log-level">${escapeHtml(row.level)}</span><span>${escapeHtml(row.message)}</span>`;
    consoleBox.appendChild(div);
    lastLogSequence = Math.max(lastLogSequence, row.seq || 0);
  });
  consoleBox.scrollTop = consoleBox.scrollHeight;
}

function environmentItem(code, label, value) {
  const stateClass = value?.ok ? "good" : value?.ok === false ? "bad" : "checking";
  return `<div class="env-item ${stateClass}"><span>${code}</span><div><b>${label}</b><small title="${escapeHtml(value?.detail || "")}">${escapeHtml(value?.detail || "正在检测")}</small></div></div>`;
}

function renderStatus(data) {
  $("#versionLabel").textContent = `v${data.app_version}`;
  const labels = { idle: "准备就绪", running: "正在生成", success: "生成成功", error: "运行失败" };
  const pill = $("#statePill");
  pill.className = `state-pill state-${data.state}`;
  $("span", pill).textContent = labels[data.state] || data.state;
  $("#progressTrack").className = `progress-track ${data.state}`;
  const env = data.environment || {};
  $("#environmentGrid").innerHTML = [
    environmentItem("PY", "Python", env.python),
    environmentItem("VE", "虚拟环境", env.virtualenv),
    environmentItem("CF", "配置", env.config),
    environmentItem("OC", "OpenCode", env.opencode),
  ].join("");
  const mode = data.generation_mode || {};
  $("#modeLabel").textContent = mode.label || "运行模式不可用";
  $("#modeReason").textContent = mode.reason || "";
  $("#generateHint").textContent = $("#forceFull").checked ? "本次强制完整抓取与评分" : (mode.label || "自动选择运行模式");
  const running = data.state === "running";
  $("#generateButton").disabled = running;
  $("#saveSettings").disabled = running;
  $("#generateButton b").textContent = running ? "正在生成简报" : "生成今日简报";
  appendLogs(data.logs || []);
  if (lastState === "running" && data.state === "success") loadHistory();
  lastState = data.state;
}

async function pollStatus() {
  try {
    const data = await request(`/api/status?after=${lastLogSequence}`);
    renderStatus(data);
  } catch (error) {
    appendLogs([{ seq: ++lastLogSequence, time: new Date().toISOString(), level: "error", message: error.message }]);
  }
}

async function loadHistory() {
  const list = $("#historyList");
  try {
    const data = await request("/api/history");
    if (!data.items?.length) {
      list.innerHTML = '<p class="empty-note">尚未发现已发布简报。</p>';
      return;
    }
    list.innerHTML = data.items.map((item, index) => `
      <a class="history-item" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
        <span class="history-number">${String(index + 1).padStart(2, "0")}</span>
        <span><b>${escapeHtml(item.date)} · 第 ${item.edition} 版</b><small>${escapeHtml(item.name)}</small></span>
        <span class="history-arrow">›</span>
      </a>`).join("");
  } catch (error) {
    list.innerHTML = `<p class="empty-note">读取失败：${escapeHtml(error.message)}</p>`;
  }
}

function setValue(id, value) { const el = $(`#${id}`); if (el) el.value = value ?? ""; }
function setChecked(id, value) { const el = $(`#${id}`); if (el) el.checked = Boolean(value); }
function numberValue(id) { return Number($(`#${id}`).value); }

function updateTotals() {
  $("#layoutTotal").textContent = numberValue("headlineCount") + numberValue("ordinaryCount");
  $("#aiTotal").textContent = numberValue("topScoredCount") + numberValue("ordinarySelectedCount");
}

function formatNumber(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "—";
}

function updateFormula() {
  const f0 = numberValue("factorFloor");
  const delta = numberValue("factorRange");
  const w0 = numberValue("weightMin");
  const w1 = numberValue("weightMax");
  $("#formulaPosition").textContent = `P = clamp((W − ${formatNumber(w0)}) ÷ (${formatNumber(w1)} − ${formatNumber(w0)}), 0, 1)`;
  $("#formulaFactor").textContent = `F = ${formatNumber(f0)} + ${formatNumber(delta)} × P`;
  $("#formulaBonus").textContent = `B = 0 / ${formatNumber(numberValue("bonus2"))} / ${formatNumber(numberValue("bonus3"))} / ${formatNumber(numberValue("bonus4"))}（对应1 / 2 / 3 / 4+来源）`;
  $("#formulaScore").textContent = `校正分 S = min(100, AI重要性 I × F + 多源加分 B)`;
  const exampleWeight = Math.min(w1, Math.max(w0, 0.85));
  const position = w1 > w0 ? Math.min(1, Math.max(0, (exampleWeight - w0) / (w1 - w0))) : NaN;
  const factor = f0 + delta * position;
  $("#formulaExample").textContent = `示例：来源权重 W=${formatNumber(exampleWeight)} 时，P=${formatNumber(position)}，F=${formatNumber(factor)}；若 AI 重要性 I=80、双来源 B₂=${formatNumber(numberValue("bonus2"))}，则 S=${formatNumber(Math.min(100, 80 * factor + numberValue("bonus2")))}。`;
}

function updateSourceCard(card, index) {
  const provider = $('[data-key="provider"]', card).value;
  const name = $('[data-key="name"]', card).value || "未命名来源";
  const access = $('[data-key="access_type"]', card).value;
  card.dataset.provider = provider;
  $(".source-index", card).textContent = String(index + 1).padStart(2, "0");
  $(".source-title", card).textContent = name;
  $(".source-subtitle", card).textContent = `${provider === "rss" ? "RSS" : "Google News"} · ${access === "paid" ? "付费" : "免费"}`;
}

function addSourceCard(source = {}) {
  const fragment = $("#sourceTemplate").content.cloneNode(true);
  const card = $(".source-card", fragment);
  const defaults = {
    id: "", name: "", provider: "rss", weight: .7, language: "fr", access_type: "free",
    rss_url: "", search: "", google_hl: "fr", google_gl: "FR", google_ceid: "FR:fr", tags: []
  };
  const data = { ...defaults, ...source };
  $$('[data-key]', card).forEach(input => {
    const key = input.dataset.key;
    input.value = key === "tags" ? (data.tags || []).join(", ") : (data[key] ?? "");
  });
  card.addEventListener("input", () => {
    $$(".source-card", $("#sourceList")).forEach(updateSourceCard);
  });
  $(".remove-source", card).addEventListener("click", () => {
    if (confirm(`删除来源“${$('[data-key="name"]', card).value || "未命名来源"}”？保存设置后生效。`)) {
      card.remove();
      $$(".source-card", $("#sourceList")).forEach(updateSourceCard);
    }
  });
  $("#sourceList").appendChild(fragment);
  $$(".source-card", $("#sourceList")).forEach(updateSourceCard);
}

function renderSettings(data) {
  settings = data;
  const timezoneSelect = $("#timezone");
  timezoneSelect.innerHTML = (data.timezones || [data.timezone]).map(zone => `<option value="${escapeHtml(zone)}">${escapeHtml(zone)}</option>`).join("");
  setValue("timezone", data.timezone);
  setValue("windowHours", data.filtering.window_hours);
  setValue("minTitleLength", data.filtering.min_title_length);
  setValue("fetchTimeout", data.fetch.timeout_seconds);
  setValue("fetchConcurrent", data.fetch.max_concurrent);
  setValue("fetchProxy", data.fetch.proxy);
  setChecked("verifyTls", data.fetch.verify_tls);
  setValue("headlineCount", data.selection.headline_count);
  setValue("ordinaryCount", data.selection.ordinary_count);
  setValue("exactThreshold", data.deduplication.exact_threshold);
  setValue("relatedThreshold", data.deduplication.related_threshold);
  setValue("candidatePool", data.ranking.candidate_pool_size);
  setValue("minPerSource", data.ranking.min_candidates_per_source);
  setValue("maxPerSource", data.ranking.max_candidates_per_source);
  setValue("interestSlots", data.ranking.interest_candidate_slots);
  setValue("wildcardSlots", data.ranking.wildcard_slots);
  setValue("topScoredCount", data.ranking.top_scored_count);
  setValue("ordinarySelectedCount", data.ranking.ordinary_selected_count);
  const score = data.ranking.score_adjustment || {};
  setValue("factorFloor", score.source_factor_floor);
  setValue("factorRange", score.source_factor_range);
  setValue("weightMin", score.source_weight_min);
  setValue("weightMax", score.source_weight_max);
  setValue("bonus2", score.corroboration_bonus_2);
  setValue("bonus3", score.corroboration_bonus_3);
  setValue("bonus4", score.corroboration_bonus_4_plus);
  setValue("longTermInterests", (data.interests.long_term || []).join("\n"));
  setValue("recentInterests", (data.interests.recent || []).join("\n"));
  $("#sourceList").innerHTML = "";
  (data.sources || []).forEach(addSourceCard);
  updateTotals();
  updateFormula();
}

function collectSources() {
  return $$(".source-card", $("#sourceList")).map(card => {
    const value = key => $(`[data-key="${key}"]`, card).value.trim();
    const provider = value("provider");
    const source = {
      id: value("id"), name: value("name"), provider,
      weight: Number(value("weight")), language: value("language"),
      access_type: value("access_type"),
      tags: value("tags").split(",").map(item => item.trim()).filter(Boolean),
    };
    if (provider === "rss") source.rss_url = value("rss_url");
    else Object.assign(source, { search: value("search"), google_hl: value("google_hl"), google_gl: value("google_gl"), google_ceid: value("google_ceid") });
    return source;
  });
}

function collectSettings() {
  return {
    timezone: $("#timezone").value.trim(),
    fetch: { timeout_seconds: numberValue("fetchTimeout"), max_concurrent: numberValue("fetchConcurrent"), proxy: $("#fetchProxy").value.trim(), verify_tls: $("#verifyTls").checked },
    filtering: { window_hours: numberValue("windowHours"), min_title_length: numberValue("minTitleLength"), keep_undated: settings?.filtering?.keep_undated || false },
    deduplication: { exact_threshold: numberValue("exactThreshold"), related_threshold: numberValue("relatedThreshold") },
    selection: { headline_count: numberValue("headlineCount"), ordinary_count: numberValue("ordinaryCount"), backup_count: 0 },
    ranking: {
      candidate_pool_size: numberValue("candidatePool"), min_candidates_per_source: numberValue("minPerSource"), max_candidates_per_source: numberValue("maxPerSource"),
      interest_candidate_slots: numberValue("interestSlots"), wildcard_slots: numberValue("wildcardSlots"), top_scored_count: numberValue("topScoredCount"), ordinary_selected_count: numberValue("ordinarySelectedCount"),
      score_adjustment: { source_factor_floor: numberValue("factorFloor"), source_factor_range: numberValue("factorRange"), source_weight_min: numberValue("weightMin"), source_weight_max: numberValue("weightMax"), corroboration_bonus_2: numberValue("bonus2"), corroboration_bonus_3: numberValue("bonus3"), corroboration_bonus_4_plus: numberValue("bonus4") }
    },
    sources: collectSources(),
    interests: { long_term: $("#longTermInterests").value.split(/\r?\n/).map(v => v.trim()).filter(Boolean), recent: $("#recentInterests").value.split(/\r?\n/).map(v => v.trim()).filter(Boolean) }
  };
}

async function loadSettings() {
  try { renderSettings(await request("/api/settings")); }
  catch (error) { $("#saveMessage").textContent = `读取设置失败：${error.message}`; }
}

async function saveSettings() {
  const button = $("#saveSettings");
  button.disabled = true;
  $("#saveMessage").textContent = "正在校验并保存……";
  try {
    const result = await request("/api/settings", { method: "PUT", body: JSON.stringify(collectSettings()) });
    renderSettings(result.settings);
    $("#saveMessage").textContent = result.requires_full_run ? "保存成功；持久规则已变化，下次将完整运行" : "保存成功；一次性兴趣将在成功生成后清空";
    await pollStatus();
  } catch (error) {
    $("#saveMessage").textContent = `保存失败：${error.message}`;
  } finally { button.disabled = false; }
}

async function generate() {
  if (!confirm($("#forceFull").checked ? "确认强制执行一次完整管线？" : "确认生成今日简报？")) return;
  try {
    await request("/api/generate", { method: "POST", body: JSON.stringify({ force_full: $("#forceFull").checked }) });
    await pollStatus();
  } catch (error) { alert(error.message); }
}

function setupTabs() {
  $$(".settings-tabs button").forEach(button => button.addEventListener("click", () => {
    $$(".settings-tabs button").forEach(item => item.classList.toggle("active", item === button));
    $$(".settings-pane").forEach(pane => pane.classList.toggle("active", pane.dataset.pane === button.dataset.tab));
  }));
}

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  $("#generateButton").addEventListener("click", generate);
  $("#saveSettings").addEventListener("click", saveSettings);
  $("#refreshHistory").addEventListener("click", loadHistory);
  $("#addSource").addEventListener("click", () => addSourceCard());
  $("#clearConsole").addEventListener("click", () => { $("#console").innerHTML = '<div class="console-empty">显示已清空；新信息会继续出现。</div>'; });
  $("#refreshEnvironment").addEventListener("click", async () => { await request("/api/environment/refresh", { method: "POST", body: "{}" }); });
  $("#forceFull").addEventListener("change", pollStatus);
  ["headlineCount", "ordinaryCount", "topScoredCount", "ordinarySelectedCount"].forEach(id => $(`#${id}`).addEventListener("input", updateTotals));
  ["factorFloor", "factorRange", "weightMin", "weightMax", "bonus2", "bonus3", "bonus4"].forEach(id => $(`#${id}`).addEventListener("input", updateFormula));
  await Promise.all([pollStatus(), loadHistory(), loadSettings()]);
  setInterval(pollStatus, 1100);
});

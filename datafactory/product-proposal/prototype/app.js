const App = document.getElementById("app");
const Dialog = document.getElementById("dialog");
const Announce = document.getElementById("announce");
const StorageKey = "datafactory-product-prototype";
const Views = {};
const InitialState = {
  sources: [], snapshots: [], runs: [], decisions: {}, release: [],
  split: { train: 80, valid: 10, test: 10, seed: 42, fixed: false },
  budget: 60, drafts: {}, audit: [],
};
let state = readState();
let noticeTimer;
let pendingSource;

function readState() {
  try {
    return { ...structuredClone(InitialState), ...JSON.parse(localStorage.getItem(StorageKey)) };
  } catch {
    return structuredClone(InitialState);
  }
}

function save(action, target) {
  state.audit.unshift({ action, target, time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) });
  try {
    localStorage.setItem(StorageKey, JSON.stringify(state));
  } catch {
    // Some browsers restrict storage for local files.
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function routeState() {
  const [path, query] = (location.hash.startsWith("#/") ? location.hash.slice(2) : "").split("?");
  const [route, id] = path.split("/");
  const params = new URLSearchParams(query);
  return { route: Object.hasOwn(RouteNames, route) ? route : "overview", id, params };
}

function activeType(fallback = "embed") {
  const requested = routeState().params.get("type");
  return Object.hasOwn(Types, requested) ? requested : fallback;
}

function taskPath(route, type) {
  return route + "?type=" + type;
}

function go(path) {
  if (Dialog.open) Dialog.close();
  if (location.hash === "#/" + path) render();
  else location.hash = "/" + path;
}

function link(path, label, style = "") {
  return '<a ' + (style ? 'class="button ' + style + '" ' : "") + 'href="#/' + escapeHtml(path) + '">' + escapeHtml(label) + "</a>";
}

function button(action, label, style = "", value = "", disabled = false) {
  return '<button type="button" class="button ' + style + '" data-action="' + escapeHtml(action) + '" data-value="' +
    escapeHtml(value) + '"' + (disabled ? " disabled" : "") + ">" + escapeHtml(label) + "</button>";
}

function selectOptions(items, selected) {
  return items.map(([value, label]) => '<option value="' + escapeHtml(value) + '"' +
    (String(value) === String(selected) ? " selected" : "") + ">" + escapeHtml(label) + "</option>").join("");
}

function pill(label, tone = "") {
  return '<span class="pill ' + tone + '">' + escapeHtml(label) + "</span>";
}

function status(label) {
  const tone = ["已完成", "已同步", "已通过", "已发布", "已修复", "已配置", "通过", "已仲裁"].includes(label) ? "ok"
    : ["已暂停", "待授权", "待审", "有新版本", "待复核"].includes(label) ? "warn"
      : ["运行中", "排队中"].includes(label) ? "info" : label === "阻断" || label === "已退回" ? "err" : "";
  return pill(label, tone);
}

function note(content, tone = "") { return '<div class="note ' + tone + '">' + content + "</div>"; }
function tag(label) { return '<span class="tag">' + escapeHtml(label) + "</span>"; }
function money(value) { return "¥" + Number(value).toFixed(2); }
function number(value) { return Number(value).toLocaleString("zh-CN"); }
function title(name, detail, actions = "") {
  return '<header class="page-head"><div><h1 id="page-title" tabindex="-1">' + escapeHtml(name) +
    "</h1>" + (detail ? "<p>" + escapeHtml(detail) + "</p>" : "") + '</div><div class="flex">' + actions + "</div></header>";
}
function card(name, content, action = "", detail = "") {
  return '<section class="card"><header class="card-head"><div><h2>' + escapeHtml(name) + "</h2>" +
    (detail ? "<p>" + escapeHtml(detail) + "</p>" : "") + "</div>" + action + "</header>" + content + "</section>";
}
function stat(name, value, detail, tint = false, extra = "") {
  return '<div class="card stat' + (tint ? " tint" : "") + '"><span>' + escapeHtml(name) + '</span><strong class="number">' +
    escapeHtml(value) + '</strong><span class="muted">' + escapeHtml(detail) + "</span>" + extra + "</div>";
}
function kv(pairs) {
  return '<dl class="kv">' + pairs.map(([key, value]) => "<dt>" + escapeHtml(key) + "</dt><dd>" + value + "</dd>").join("") + "</dl>";
}
function progress(value, label = "进度") {
  return '<span class="progress" role="progressbar" aria-label="' + escapeHtml(label) +
    '" aria-valuenow="' + value + '" aria-valuemin="0" aria-valuemax="100"><span style="width:' + value + '%"></span></span>';
}
function ratioBars(rows) {
  return rows.map(([name, value, label]) => '<div class="chart-row"><span>' + escapeHtml(name) +
    "</span>" + progress(value, name) + '<span class="number">' + escapeHtml(label) + "</span></div>").join("");
}
function table(headers, rows, id = "") {
  return '<div class="table-wrap" tabindex="0" role="region" aria-label="' + escapeHtml(headers[0] + "列表") + '"><table' +
    (id ? ' id="' + id + '"' : "") + "><thead><tr>" + headers.map((h) => '<th scope="col">' + escapeHtml(h) + "</th>").join("") +
    "</tr></thead><tbody>" + rows.map((row) => '<tr data-row>' + row.map((cell) => "<td>" + cell + "</td>").join("") + "</tr>").join("") +
    '<tr data-empty' + (rows.length ? " hidden" : "") + '><td class="empty" colspan="' + headers.length +
    '">没有符合条件的记录。修改筛选条件后重试。</td></tr></tbody></table></div>';
}
function searchBox(id, label, hint) {
  return '<div class="toolbar"><label>' + escapeHtml(label) + '<input type="search" data-filter="' + id +
    '" placeholder="' + escapeHtml(hint) + '"></label><span class="muted fine" data-count="' + id + '" aria-live="polite"></span></div>';
}
function tabs(items, current) {
  return '<nav class="tabs" aria-label="当前页视图">' + items.map(([key, label, path]) =>
    '<a href="#/' + escapeHtml(path) + '"' + (key === current ? ' aria-current="page"' : "") + ">" + escapeHtml(label) + "</a>").join("") + "</nav>";
}
function typeTabs(route, type) {
  return tabs(Object.entries(Types).map(([key, data]) => [key, data.name, taskPath(route, key)]), type);
}
function code(value) { return "<pre>" + escapeHtml(JSON.stringify(value, null, 2)) + "</pre>"; }
function decision(sample) { return state.decisions[sample.id]?.status ?? "待审"; }
function samplesFor(type) { return Samples.filter((sample) => sample.type === type); }
function blocks(type) {
  const ids = { embed: "E-0317", rerank: "R-0062", sft: "S-0093", dpo: "P-0021" };
  const sample = Samples.find((row) => row.id === ids[type]);
  const findings = decision(sample) === "待审" ? [sample.issue] : [];
  if (type === "embed" && !state.split.fixed) findings.push("文档家族跨集合");
  return findings;
}
function allSources() { return [...state.sources, ...BuiltinSources]; }
function allSnapshots() { return [...state.snapshots, ...Snapshots]; }
function allRuns() {
  const changed = new Set(state.runs.map((row) => row.id));
  return [...state.runs, ...BuiltinRuns.filter((row) => !changed.has(row.id))];
}
function sampleId(id, type) { return Samples.find((sample) => sample.id === id) ?? samplesFor(type)[0]; }
function auditRows() { return [...state.audit, { action: "导入授权清单", target: "设备手册知识库", time: "09:42" }]; }

function showDialog(name, content) {
  Dialog.innerHTML = '<div class="dialog-head"><h2 id="dialog-title">' + escapeHtml(name) +
    "</h2>" + button("close", "关闭") + "</div>" + content;
  if (!Dialog.open) Dialog.showModal();
  else Dialog.querySelector("[autofocus], button").focus();
}

function toast(text) {
  clearTimeout(noticeTimer);
  Announce.hidden = false;
  Announce.textContent = text;
  noticeTimer = setTimeout(() => { Announce.hidden = true; }, 3800);
}

function nav(route) {
  const active = Parents[route] ?? route;
  return Nav.map(([section, items]) => '<p class="nav-group">' + section + "</p>" + items.map(([path, icon]) =>
    '<a class="nav-link" href="#/' + path + '"' + (active === path ? ' aria-current="page"' : "") +
    '><span class="nav-icon" aria-hidden="true">' + icon + "</span>" + RouteNames[path] + "</a>").join("")).join("");
}

function render(focusTitle = false) {
  const ctx = routeState();
  const view = (Views[ctx.route] ?? Views.overview)(ctx);
  const parent = Parents[ctx.route];
  document.title = RouteNames[ctx.route] + " · DataFactory";
  if (ctx.route === "login") App.innerHTML = view;
  else App.innerHTML = '<a href="#content" class="skip" data-action="skip">跳至主内容</a>' +
    '<div class="shell"><aside class="rail"><a class="brand" href="#/overview"><span class="mark" aria-hidden="true"></span>DataFactory</a>' +
    '<a class="project-link" href="#/settings"><span class="project-key" aria-hidden="true">设</span><strong>设备知识库</strong><span aria-hidden="true">⌄</span></a>' +
    '<nav aria-label="主导航">' + nav(ctx.route) + '</nav><div class="rail-foot">交互原型 · 演示数据</div></aside>' +
    '<div><header class="topbar"><div class="breadcrumbs">' + button("menu", "菜单", "menu-toggle") +
    '<a href="#/overview">设备知识库</a><span aria-hidden="true" class="crumb-divider">/</span>' +
    (parent ? link(parent, RouteNames[parent]) + '<span aria-hidden="true" class="crumb-divider">/</span>' : "") +
    "<strong>" + RouteNames[ctx.route] + '</strong></div><div class="flex">' +
    '<button class="button" type="button" data-action="guide">页面导览 <kbd>Ctrl K</kbd></button>' +
    '<a href="#/settings" class="avatar" aria-label="项目设置">DF</a></div></header>' +
    '<main id="content" class="page" tabindex="-1">' + view + "</main></div></div>";
  if (focusTitle) document.getElementById("page-title")?.focus({ preventScroll: true });
}

function filteredRows(field) {
  const tableId = field.dataset.filter;
  const query = field.value.trim().toLocaleLowerCase();
  const list = document.getElementById(tableId);
  let total = 0;
  for (const row of list.querySelectorAll("[data-row]")) {
    row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
    if (!row.hidden) total++;
  }
  list.querySelector("[data-empty]").hidden = total > 0;
  document.querySelector('[data-count="' + tableId + '"]').textContent = "显示 " + total + " 条";
}

function runDialog(type, preview) {
  const task = Types[type];
  showDialog(preview ? "小批预览" : "开始生产", '<form class="form" data-form="run">' +
    '<input type="hidden" name="type" value="' + type + '"><input type="hidden" name="mode" value="' + (preview ? "preview" : "production") + '">' +
    note(preview ? "用生产配置生成少量样本，先核对证据和标签。预览不写入正式数据集。" : "运行将锁定所选快照、配方和模型版本。") +
    '<label>语料快照<select name="snapshot">' + selectOptions(allSnapshots().map((row) => [row.id, row.name])) +
    '</select></label><label>样本上限<input name="size" type="number" value="' + (preview ? 20 : task.count) +
    '" min="1" max="' + (preview ? 50 : 100000) + '" required></label>' +
    '<label>预算上限（元）<input name="limit" type="number" value="' + Math.min(preview ? 5 : 30, state.budget) +
    '" min="1" max="' + state.budget + '" required></label>' +
    '<div class="actions"><button class="button primary">创建' + (preview ? "预览" : "运行") + "</button></div></form>");
}

function example(type, adapter) {
  const query = "收到 E17 超温报警后怎样处理？";
  const prompt = [{ role: "user", content: query }];
  const chosen = [{ role: "assistant", content: Positive }];
  if (adapter === "foundry" && type === "dpo") {
    return { input: { messages: prompt }, preferred_output: chosen, non_preferred_output: [{ role: "assistant", content: "直接复位并继续工作。" }] };
  }
  if (type === "sft") return { messages: [...prompt, ...chosen] };
  if (type === "dpo") {
    return { prompt, chosen, rejected: [{ role: "assistant", content: "直接复位并继续工作。" }] };
  }
  if (type === "rerank" && adapter === "flag") {
    return { query, pos: [Positive], neg: [Negative], pos_scores: [4.2], neg_scores: [-1.8] };
  }
  if (type === "rerank") {
    return { query, candidates: [{ text: Positive, relevance: 3 }, { text: Negative, relevance: 0 }] };
  }
  return { query, pos: [Positive], neg: [Negative] };
}

const Actions = {
  close() { Dialog.close(); },
  skip() { document.getElementById("content").focus(); },
  menu(_, target) {
    const open = target.closest(".shell").classList.toggle("nav-open");
    target.setAttribute("aria-expanded", String(open));
  },
  guide() {
    showDialog("页面导览", '<label>筛选页面<input id="guide-search" type="search" placeholder="例如审核" autofocus></label>' +
      '<div class="search-list">' + Object.entries(RouteNames).map(([path, name]) => link(path, name, "secondary")).join("") +
      '</div><div class="actions">' + button("reset-confirm", "清除演示变更", "danger") + "</div>");
  },
  "reset-confirm"() {
    showDialog("清除本地演示变更", '<p>恢复初始样例，当前浏览器记录的授权、审核、运行与发布变更会被清除。</p>' +
      '<div class="actions">' + button("reset", "确认清除", "danger") + "</div>");
  },
  reset() {
    state = structuredClone(InitialState);
    try { localStorage.removeItem(StorageKey); } catch { /* Storage may be unavailable. */ }
    go("overview");
    toast("已还原演示数据");
  },
  "new-task"() {
    showDialog("选择制作任务", '<div class="grid">' + Object.entries(Types).map(([type, task]) =>
      '<div class="card stack"><h3>' + task.name + "</h3><p class='muted fine'>" + task.description +
      "</p>" + link(taskPath("recipe", type), "配置配方", "primary") + "</div>").join("") + "</div>");
  },
  "apply-source"() {
    if (!pendingSource) return;
    state.sources.unshift(pendingSource);
    save("确认演示授权", pendingSource.name);
    const id = pendingSource.id;
    pendingSource = undefined;
    go("source/" + id);
    toast("演示源已加入项目");
  },
  snapshot(sourceId) {
    const options = allSources().filter((row) => row.status !== "待授权").map((row) => [row.id, row.name]);
    showDialog("冻结语料快照", '<form class="form" data-form="snapshot"><label>快照名称<input name="name" value="设备语料 v1.4" maxlength="60" required></label>' +
      '<label>授权数据源<select name="source">' + selectOptions(options, sourceId) + "</select></label>" +
      '<div class="actions"><button class="button primary">冻结快照</button></div></form>');
  },
  preview(type) { runDialog(type, true); },
  start(type) { runDialog(type, false); },
  "run-status"(id) {
    const run = allRuns().find((row) => row.id === id);
    const next = { ...run, status: run.status === "运行中" ? "已暂停" : "运行中" };
    state.runs = [next, ...state.runs.filter((row) => row.id !== id)];
    save("更新运行状态", id + " " + next.status);
    render();
    toast(next.status);
  },
  "split-fix"() {
    state.split.fixed = true;
    save("按文档家族重新分组", "候选训练集");
    render();
    toast("已重新分组，可检查预检结果");
  },
  "freeze-confirm"(type) {
    if (blocks(type).length) return;
    showDialog("确认冻结版本", '<p>以演示审批角色确认已核查数据权利、审核和质量报告。冻结后该版本只读。</p>' +
      '<div class="actions">' + button("freeze", "批准并冻结演示版", "primary", type) + "</div>");
  },
  freeze(type) {
    if (blocks(type).length || state.release.includes(type)) return;
    state.release.push(type);
    save("冻结演示版本", Types[type].dataset + " v1.1");
    go(taskPath("release", type));
    toast("v1.1 已冻结");
  },
  "download-example"(value) {
    const [type, adapter] = value.split("/");
    const file = adapter === "qrels" ? "query-id\tcorpus-id\tscore\nq-317\tseg-64\t1\n" : JSON.stringify(example(type, adapter)) + "\n";
    const url = URL.createObjectURL(new Blob([file], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "datafactory-demo-" + type + (adapter === "qrels" ? ".tsv" : ".jsonl");
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast("已生成当前格式的示例文件");
  },
  "check-model"(name) {
    showDialog("连接诊断", kv([["模型", escapeHtml(name)], ["模式", "演示验证"], ["检查项", "端点可用性、模型能力、输入限制、项目授权"], ["结果", status("通过")]]));
  },
  "evaluation-case"(type) {
    const row = EvaluationCases[type];
    showDialog("比较记录 " + row.id, '<div class="stack"><p class="sample-title">' + escapeHtml(row.input) + "</p>" +
      kv([["基线", escapeHtml(row.base)], ["候选", escapeHtml(row.candidate)], ["评测范围", "锁定测试集"]]) +
      note(escapeHtml(row.detail)) + "</div>");
  },
  "budget-edit"() {
    showDialog("设置演示运行预算", '<form class="form" data-form="budget"><label>可用预算（元）<input type="number" name="value" min="5" max="5000" required value="' +
      state.budget + '"></label><div class="actions"><button class="button primary">保存预算</button></div></form>');
  },
};

const Forms = {
  source(data) {
    const name = data.get("name").trim();
    const grant = data.get("scope").trim();
    if (!name || !grant) return toast("请填写来源名称和授权范围");
    pendingSource = {
      id: "demo-" + Date.now(), name, kind: data.get("kind"),
      grant, files: "4", status: "已同步", time: "刚刚",
    };
    showDialog("确认导入范围", note("原型使用四份示例文档验证流程。") +
      kv([["名称", escapeHtml(pendingSource.name)], ["接入类型", escapeHtml(pendingSource.kind)], ["授权范围", escapeHtml(pendingSource.grant)]]) +
      '<div class="actions">' + button("apply-source", "确认授权并接入", "primary") + "</div>");
  },
  snapshot(data) {
    const name = data.get("name").trim();
    if (!name) return toast("请填写快照名称");
    const source = allSources().find((row) => row.id === data.get("source"));
    const row = { id: "demo-" + Date.now(), name, count: 8640, date: "刚刚", sources: source.name };
    state.snapshots.unshift(row);
    save("冻结快照", row.name);
    go("snapshot/" + row.id);
  },
  recipe(data) {
    const type = data.get("type");
    const step = Number(data.get("step"));
    const steps = state.drafts[type] ?? {};
    state.drafts[type] = { ...steps, [step]: { amount: Number(data.get("amount")), model: data.get("model"), note: data.get("note").trim() } };
    save("保存演示配方", Types[type].name);
    toast("配置已保存，可创建小批预览");
  },
  run(data) {
    const type = data.get("type");
    const preview = data.get("mode") === "preview";
    const run = {
      id: "RUN-D" + String(Date.now()).slice(-6), name: Types[type].dataset + (preview ? " · 小批预览" : " · 生产"),
      type, status: preview ? "已完成" : "排队中", progress: preview ? 100 : 0,
      date: "刚刚", size: Number(data.get("size")), limit: Number(data.get("limit")), snapshot: data.get("snapshot"),
      recipe: structuredClone(state.drafts[type] ?? {}),
    };
    state.runs.unshift(run);
    save("创建演示运行", run.id);
    go("run/" + run.id);
  },
  review(data) {
    const sample = Samples.find((row) => row.id === data.get("sample"));
    const verdict = data.get("decision");
    const reason = data.get("reason").trim();
    if (!reason) return toast("请填写判定依据");
    const reviewed = ["标为正例", "维持负例", "A 优先", "B 优先"].includes(verdict);
    const excluded = ["退回", "平局", "均不合格"].includes(verdict);
    state.decisions[sample.id] = { status: reviewed ? "已仲裁" : excluded ? "已退回" : "已通过", verdict, reason };
    save(verdict, sample.id);
    render();
    toast("已保存审核结果");
  },
  split(data) {
    const train = Number(data.get("train")), valid = Number(data.get("valid")), test = Number(data.get("test"));
    if (train + valid + test !== 100) return toast("训练、验证和测试比例合计必须为 100%");
    state.split = { ...state.split, train, valid, test, seed: Number(data.get("seed")) };
    save("保存划分策略", "候选训练集");
    render();
    toast("已更新划分方案");
  },
  budget(data) {
    state.budget = Number(data.get("value"));
    save("调整演示预算", money(state.budget));
    Dialog.close();
    render();
    toast("演示预算已保存");
  },
};

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  event.preventDefault();
  Actions[target.dataset.action]?.(target.dataset.value, target);
});
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.dataset.form) return;
  event.preventDefault();
  Forms[form.dataset.form]?.(new FormData(form, event.submitter));
});
document.addEventListener("input", (event) => {
  const field = event.target;
  if (field.dataset.filter) filteredRows(field);
  if (field.id === "guide-search") {
    for (const item of Dialog.querySelectorAll(".search-list a")) {
      item.hidden = !item.textContent.includes(field.value.trim());
    }
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && Dialog.open) {
    event.preventDefault();
    Dialog.close();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    Actions.guide();
  }
});
window.addEventListener("hashchange", () => {
  if (Dialog.open) Dialog.close();
  render(true);
  window.scrollTo(0, 0);
});
window.addEventListener("DOMContentLoaded", () => render());

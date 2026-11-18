function runTable(rows) {
  return table(["任务", "状态", "进度", "创建时间"], rows.map((run) => [
    link("run/" + run.id, run.name) + '<br><code>' + run.id + "</code>",
    status(run.status), '<div class="run-progress">' + progress(run.progress) + '<span class="fine">' + run.progress + "%</span></div>",
    escapeHtml(run.date),
  ]), "runs");
}

function docsTable() {
  return table(["文档", "版本", "语料数", "模态", "分组键"], Documents.map((row) => [
    link("document/" + row.id, row.name), escapeHtml(row.rev), number(row.count), tag(row.format), '<code>' + row.group + "</code>",
  ]), "documents");
}

function sampleTable(rows) {
  return table(["样本 / 内容", "审核原因", "状态", "语言", "集合"], rows.map((row) => [
    link("sample/" + row.id, row.text) + "<br><code>" + row.id + "</code>",
    escapeHtml(row.issue), status(decision(row)), escapeHtml(row.lang), tag(row.split),
  ]), "samples");
}

Views.overview = function () {
  const open = 126 - Object.keys(state.decisions).length;
  const bars = '<span class="bars" aria-hidden="true">' + [30, 44, 39, 61, 72, 65, 92].map((value) => '<span style="--value:' + value + '%"></span>').join("") + "</span>";
  const steps = [["sources", "接入", "4 类来源"], ["recipes", "配置", "4 类任务"], ["runs", "生成与挖掘", "查看运行"],
    ["queues", "审核", open + " 待审"], ["quality", "质检", blocks("embed").length + " 项待处理"], ["releases", "交付", "查看版本"]];
  const taskFlow = '<div class="flow">' + steps.map(([path, name, label]) =>
    '<a href="#/' + path + '"><strong>' + name + '</strong><span class="muted">' + label + "</span></a>").join("") + "</div>";
  const todo = '<ul class="list"><li><div><strong>E17 查询的疑似假负例</strong><p class="fine muted">原文来自维护手册 §6.4</p></div>' +
    link("review/E-0317", decision(Samples[0]) === "待审" ? "审核" : "查看", "secondary") + '</li><li><div><strong>同一文档家族跨集合</strong><p class="fine muted">训练集与验证集划分</p></div>' +
    link("split", state.split.fixed ? "已修复" : "检查", "secondary") + "</li></ul>";
  const versions = ["embed", "rerank"].map((type) =>
    "<li><span>" + Types[type].dataset + "</span>" +
    link(taskPath("export", type), state.release.includes(type) ? "v1.1" : "v1.0") + "</li>").join("");
  return title("项目总览", "从设备手册、故障工单和巡检会话制作训练数据。", button("new-task", "＋ 新建制作任务", "primary")) +
    '<div class="stack"><div class="grid four">' +
    stat("已冻结语料", "8,640", "语料快照 v1.3", true, bars) + stat("候选样本", "2,480", "覆盖四类训练任务") +
    stat("待审核", number(open), "优先处理需人工核验的样本") + stat("已冻结版本", String(2 + state.release.length), "发布后可按格式导出") +
    '</div><div class="grid split">' + card("数据生产流程", taskFlow) + card("待处理事项", todo) +
    '</div><div class="grid split">' + card("最近运行", runTable(allRuns().slice(0, 4)), link("runs", "全部运行")) +
    card("候选样本分布", '<div class="stack"><div>' +
      ratioBars(Object.values(Types).map((task) => [task.name, Math.round(task.count / 1480 * 100), number(task.count)])) +
      '</div><h3>可交付的检索版本</h3><ul class="list">' + versions + "</ul></div>",
      link("datasets", "查看数据集"), "按任务统计") + "</div></div>";
};

Views.sources = function () {
  return title("数据源", "检查连接状态、可用版本及授权范围。", link("source-new", "＋ 接入数据源", "primary")) +
    card("项目来源", searchBox("sources", "筛选来源", "名称、类型或状态") + table(["来源", "类型", "授权范围", "文档", "状态", "更新时间"], allSources().map((row) => [
      link("source/" + row.id, row.name), tag(row.kind), escapeHtml(row.grant), row.files, status(row.status), escapeHtml(row.time),
    ]), "sources"));
};

Views["source-new"] = function () {
  const form = '<form class="form" data-form="source"><div class="field-row">' +
    '<label>接入类型<select name="kind">' + selectOptions(["知识库连接", "对象存储", "CSV 导入", "JSONL 导入"].map((v) => [v, v])) +
    '</select></label><label>来源名称<input name="name" maxlength="60" placeholder="例如：巡检手册" required></label></div>' +
    '<label>已授权范围<input name="scope" maxlength="100" placeholder="例如：巡检文件夹 · 只读" required></label>' +
    '<label class="check"><input type="checkbox" required>已确认这些示例资料可用于项目训练数据</label>' +
    '<div class="actions">' + link("sources", "取消", "secondary") + '<button class="button primary">预览授权范围</button></div></form>';
  return title("接入数据源", "选择来源并确认可冻结的资料范围。") + '<div class="grid inspect">' +
    card("导入设置", form) + card("接入检查", '<ol class="checklist"><li>检查连接与授权</li><li>预览结构和样本行</li><li>标记语言、敏感级别和使用权</li><li>确认后加入项目</li></ol>' +
      note("原型使用示例资料。这里无需填写服务地址或密钥。")) + "</div>";
};

Views.source = function ({ id }) {
  const source = allSources().find((row) => row.id === id) ?? BuiltinSources[0];
  const granted = source.status !== "待授权";
  return title(source.name, source.kind + " · " + source.time, link("sources", "返回来源列表", "secondary") +
    (granted ? button("snapshot", "冻结快照", "primary", source.id) : "")) +
    '<div class="grid inspect">' + (granted ? card("内容预览", docsTable()) :
      card("等待授权", note("管理员需批准该来源的训练用途和范围。授权生效前无法查看内容或冻结快照。", "warn"))) +
    card("来源信息", kv([["状态", status(source.status)], ["权限", escapeHtml(source.grant)], ["文档数量", source.files],
      ["更新策略", "仅预览新增或变更文档"], ["来源 ID", "<code>" + escapeHtml(source.id) + "</code>"]])) + "</div>";
};

Views.corpus = function () {
  return title("语料快照", "冻结源文档版本、切分规则与资产，作为制作运行的固定输入。", button("snapshot", "＋ 冻结语料快照", "primary")) +
    card("快照列表", table(["版本", "语料数", "数据源", "冻结时间"], allSnapshots().map((row) => [
      link("snapshot/" + row.id, row.name), number(row.count), escapeHtml(row.sources), escapeHtml(row.date),
    ])));
};

Views.snapshot = function ({ id }) {
  const snapshot = allSnapshots().find((row) => row.id === id) ?? Snapshots[0];
  return title(snapshot.name, "已冻结 · " + snapshot.date,
    link("corpus", "快照列表", "secondary") + link("templates", "选择制作模板", "primary")) +
    '<div class="stack"><div class="grid three">' + stat("冻结语料", number(snapshot.count), "保留来源段落定位", true) +
    stat("主要语言", "简中", "另有英文术语和故障码") + stat("内容类型", "3 种", "文本、表格、图像") + "</div>" +
    card("文档清单（示例）", searchBox("documents", "筛选文档", "标题、模态或分组键") + docsTable(),
      tag(snapshot.id), snapshot.sources) + "</div>";
};

Views.document = function ({ id }) {
  const doc = Documents.find((row) => row.id === id) ?? Documents[0];
  const text = {
    "doc-126": Positive + "\n\n§7.1 风道更换后，先确认风量正常并完成测温检查，再按复位步骤恢复运行。",
    "doc-127": "§3.1 复位前检查冷却回路。\n\n§4.2 更换温度传感器后执行零点校验和稳定性测量。",
    "doc-201": "工单 04/17 · 同批次有两次 E17 超温告警。维护员检查风道后发现进风口有堵塞。",
    "doc-309": "§2.3 复位前确认设备已隔离、冷却完成。未满足条件时保持停机并登记巡检。\n\n§5 持续超温或重复报警需升级给当班负责人。",
  };
  return title(doc.name, doc.rev + " · 冻结文档检视", link("snapshot/snap-013", "返回快照", "secondary")) +
    '<div class="grid inspect">' +
    card("语料正文", '<div class="stack"><div class="flex">' + tag(doc.format) + tag("第 12 页 · 截选") + '</div>' +
      '<p class="source-text">' + escapeHtml(text[doc.id]) + "</p></div>") +
    card("来源与血缘", kv([["文档 ID", "<code>" + doc.id + "</code>"], ["家族 ID", "<code>" + doc.group + "</code>"],
      ["来源版本", escapeHtml(doc.rev)], ["快照引用", link("snapshot/snap-013", "设备语料 v1.3")], ["来源权利", "已授权 · 项目内部使用"]])) + "</div>";
};

Views.recipes = function () {
  return title("配方库", "按任务版本管理生成、召回、审核与质检步骤。", link("templates", "查看模板", "secondary") + button("new-task", "＋ 新建配方", "primary")) +
    card("制作配方", table(["配方", "任务", "版本", "步骤", "状态"], Object.entries(Types).map(([type, task]) => [
      link(taskPath("recipe", type), task.dataset), tag(task.name), state.drafts[type] ? "草稿" : "v2.1",
      task.stages.length + " 个", state.drafts[type] ? pill("草稿") : status("已配置"),
    ])));
};

Views.templates = function () {
  return title("模板库", "从任务目标出发选择输入和样本结构。", link("recipes", "返回配方库", "secondary")) +
    '<div class="grid">' + Object.entries(Types).map(([type, task]) =>
      card(task.name + " · " + task.label, '<div class="stack"><p class="muted">' + task.description +
        "</p>" + kv([["输入", type === "rerank" ? "查询与冻结候选集" : type === "dpo" ? "上下文与多模型候选" : "已授权语料快照"],
          ["输出", type === "embed" ? "查询、正例与负例" : type === "rerank" ? "查询与候选等级" : type === "sft" ? "对话记录" : "同提示的偏好对"]]) +
        link(taskPath("recipe", type), "使用模板", "primary") + "</div>")).join("") + "</div>";
};

Views.recipe = function ({ params }) {
  const type = activeType();
  const task = Types[type];
  const step = Math.trunc(Math.min(Math.max(Number(params.get("node")) || 0, 0), task.stages.length - 1));
  const stage = task.stages[step];
  const paramsByStep = [
    ["种子数上限", 500, 100000, "选取覆盖不同文档家族的种子。"],
    ["每个种子的候选数", 3, 20, "保留来源位置和输入条件。"],
    [type === "embed" || type === "rerank" ? "候选上限（Top-K）" : "每批样本上限", 50, 500, "记录实际候选及生成设置。"],
    ["校准样本数", 20, 500, "先核对结论的证据，遇到歧义时保留候选并提交人工核验。"],
    ["每批输出上限", 500, 100000, "检查输出契约和目标训练器要求。"],
  ];
  const [amountLabel, amountDefault, max, qualityDefault] = paramsByStep[step];
  const draft = state.drafts[type]?.[step] ?? { amount: amountDefault, model: "approved", note: qualityDefault };
  const nodes = '<div class="node-list">' + task.stages.map((label, index) =>
    '<a class="node" href="#/' + taskPath("recipe", type) + "&node=" + index + '"' + (index === step ? ' aria-current="step"' : "") +
    '><span class="step">' + (index + 1) + "</span><strong>" + label + "</strong></a>").join("") + "</div>";
  const form = '<form class="form" data-form="recipe"><input type="hidden" name="type" value="' + type + '">' +
    '<input type="hidden" name="step" value="' + step + '"><div class="field-row"><label>' + amountLabel +
    '<input name="amount" type="number" min="1" max="' + max + '" value="' + draft.amount + '" required></label>' +
    '<label>模型策略<select name="model">' + selectOptions([["approved", "项目已授权模型"], ["text", "文本模型优先"]], draft.model) +
    '</select></label></div><label>质量说明<textarea name="note" maxlength="300">' + escapeHtml(draft.note) +
    '</textarea></label><div class="actions"><button class="button primary">保存配置</button></div></form>';
  return title("配方设计器", task.dataset + " · 工作流草稿",
    button("preview", "小批预览", "secondary", type) + button("start", "开始生产", "primary", type)) +
    typeTabs("recipe", type) + '<div class="grid inspect editor-grid">' +
    card("生产步骤", nodes, tag("有向流程"), task.description) +
    '<div class="stack">' + card(stage, form, "", "配置模板") +
    card("输出样本结构", code(example(type, "canonical"))) + "</div></div>";
};

Views.runs = function () {
  return title("运行记录", "区分小批校准与正式生产，按运行查看输入、进度及开销。", button("new-task", "＋ 新建制作任务", "primary")) +
    card("运行列表", searchBox("runs", "筛选运行", "任务、运行 ID 或状态") + runTable(allRuns()));
};

Views.run = function ({ id, params }) {
  const run = allRuns().find((row) => row.id === id) ?? BuiltinRuns[0];
  const { type } = run;
  const task = Types[type];
  const section = params.get("tab") ?? "steps";
  const monitorTabs = tabs([["steps", "步骤与日志", "run/" + run.id], ["sample", "产出预览", "run/" + run.id + "?tab=sample"],
    ["cost", "成本明细", "run/" + run.id + "?tab=cost"]], section);
  const completed = Math.floor(run.progress / 100 * task.stages.length);
  const currentTab = section === "sample" ? card("产出预览",
    run.status === "排队中" ? note("任务开始生产后可检查产出。") : code(example(type, "canonical")), link(taskPath("dataset", type), "打开数据集")) :
    section === "cost" ? card("调用明细", table(["类别", "使用量", "示例金额"], [
      ["生成", "12,400 Tokens", "¥3.85"], ["召回与教师评分", "428 次", "¥2.44"],
    ]), "", "金额仅用于演示") :
    card("执行步骤", task.stages.map((label, index) =>
      '<div class="stage"><div class="flex"><strong>' + label + "</strong>" +
      (index < completed ? status("已完成") : index === completed && run.status === "运行中" ? status("运行中") : pill("待处理")) +
      '</div><p class="muted fine">' + (index < completed ? "输出已保存，可追溯至冻结版本。" : "等待前序步骤完成。") + "</p></div>").join(""));
  const isActive = ["运行中", "已暂停", "排队中"].includes(run.status);
  return title(run.name, run.id + " · " + task.name,
    link("runs", "返回运行列表", "secondary") + (isActive ? button("run-status", run.status === "运行中" ? "暂停" : "继续演示运行", "primary", run.id) : "")) +
    '<div class="stack"><div class="grid three">' + stat("运行进度", run.progress + "%", run.status, true, progress(run.progress)) +
    stat("样本上限", number(run.size), "按冻结配方执行") + stat("预算上限", money(run.limit ?? 30), "仅包含模型调用示例") + "</div>" +
    monitorTabs + '<div class="grid inspect">' + currentTab + card("运行输入", kv([["语料", link("snapshot/" + (run.snapshot ?? "snap-013"), "查看输入快照")],
      ["配方", link(taskPath("recipe", type), task.dataset)], ["固定配置", run.recipe ? Object.keys(run.recipe).length + " 个自定义步骤" : "演示配方 v2.1"],
      ["模型策略", "项目已授权模型"], ["状态", status(run.status)]])) + "</div></div>";
};

Views.datasets = function () {
  return title("数据集", "按任务检查样本、版本及各自的训练输入。", link("templates", "选择制作模板", "primary")) +
    '<div class="grid">' + Object.entries(Types).map(([type, task]) =>
      card(task.dataset, '<div class="stack"><div class="flex">' + tag(task.name) +
        (blocks(type).length ? pill(blocks(type).length + " 项待处理", "warn") : pill("可预检", "ok")) + '</div><p class="muted">' + task.description +
        "</p>" + kv([["候选总量", number(task.count)], ["待审", number(task.pending - samplesFor(type).filter((row) => decision(row) !== "待审").length)]]) +
        link(taskPath("dataset", type), "浏览样本", "secondary") + "</div>")).join("") + "</div>";
};

Views.dataset = function ({ params }) {
  const type = activeType();
  const task = Types[type];
  const section = params.get("tab") ?? "rows";
  const viewTabs = tabs([["rows", "样本", taskPath("dataset", type)], ["stats", "分布", taskPath("dataset", type) + "&tab=stats"],
    ["history", "版本与血缘", taskPath("dataset", type) + "&tab=history"]], section);
  const rows = samplesFor(type);
  const detail = section === "stats" ? card("集合分布（目标）", ratioBars([["训练", state.split.train, state.split.train + "%"],
    ["验证", state.split.valid, state.split.valid + "%"], ["测试", state.split.test, state.split.test + "%"]]), link("split", "查看划分")) :
    section === "history" ? card("版本血缘", kv([["输入语料", link("snapshot/snap-013", "设备语料 v1.3")],
      ["制作配方", link(taskPath("recipe", type), task.dataset + " v2.1")], ["产出版本", state.release.includes(type) ? "v1.1 已冻结" : "当前候选版"],
      ["审核策略", "低置信优先与分层抽检"]]), link(taskPath("release", type), "发布预检")) :
    card("样本表", searchBox("samples", "筛选样本", "内容、标签、状态或样本 ID") + sampleTable(rows), tag("示例 " + rows.length + " 条"));
  return title(task.dataset, task.name + " · " + number(task.count) + " 条候选",
    link(taskPath("queues", type), "打开审核队列", "secondary") + link(taskPath("release", type), "发布预检", "primary")) +
    typeTabs("dataset", type) + viewTabs + detail;
};

function candidate(label, text, meta, tone = "") {
  return '<section class="candidate"><div class="flex between"><strong>' + escapeHtml(label) + "</strong>" + pill(meta, tone) +
    "</div><p>" + escapeHtml(text) + "</p></section>";
}

function variants(sample) {
  const rowDecision = state.decisions[sample.id]?.verdict;
  if (sample.type === "embed") {
    const isFlagged = sample.id === "E-0317";
    const passages = {
      "E-0321": ["风道更换后先确认风量正常并完成测温检查，再按复位步骤恢复运行。", "风道清洁时记录过滤器编号并上传工单。"],
      "E-0456": ["Verify the replacement with a zero-point check and a stability measurement.", "Clean the device cover before replacing the filter."],
    };
    const [positive, negative] = passages[sample.id] ?? [Positive, Negative];
    const second = rowDecision === "标为正例" ? ["新增正例", "人工仲裁", "ok"] :
      rowDecision === "维持负例" ? ["保留候选", "已核验负例", "ok"] : ["候选片段", "待核验 · 0.88", "warn"];
    return '<div class="candidates">' + candidate("已核验正例", positive, "相关 · 0.91", "ok") +
      (isFlagged ? candidate(second[0], ConditionalPositive, second[1], second[2]) : "") +
      candidate("已核验负例", negative, "不相关 · 0.12") + "</div>";
  }
  if (sample.type === "rerank") {
    const rows = sample.id === "R-0063" ? [
      ["复位前必须检查冷却回路和泄漏状态。", "1", "0.95", "3 · 直接回答"],
      ["复位后记录本次维护时间。", "2", "0.41", "1 · 同主题"],
    ] : [
      [escapeHtml(Negative), "1", "0.27", "1 · 同主题"],
      [escapeHtml(Positive), "2", "0.94", "3 · 直接回答"],
      [escapeHtml(ConditionalPositive), "3", "0.81", "2 · 补充说明"],
    ];
    return table(["候选片段", "召回次序", "教师分", "人工相关性"], rows);
  }
  if (sample.type === "sft") {
    if (sample.id === "S-0107") {
      return '<div class="candidates">' + candidate("用户", sample.text, "user") +
        candidate("助手回答", "将单次短时提示登记为待检查。若持续超温或重复报警，按规程升级给当班负责人。", "assistant", "ok") + "</div>";
    }
    return '<div class="candidates">' + candidate("用户", sample.text, "user") +
      candidate("助手调用", 'lookup_alerts({"code":"E17","days":7})', "assistant · 工具调用", "info") +
      candidate("工具返回（样例）", "近七天 2 条 E17。最近一次发生于 09:13。", "tool") +
      candidate("助手回答", "按安全停机流程隔离设备，核对风道与温度传感器。近七天有两次同类告警，请将检查结果记入巡检台账。", "assistant", "ok") +
      "<details><summary>工具参数契约</summary>" + code({ name: "lookup_alerts", arguments: { code: "string", days: "integer 1–30" } }) + "</details></div>";
  }
  const unresolved = sample.id === "P-0024";
  return '<div class="grid">' + candidate("回答 A", unresolved ? "目前证据不足，先确认设备已隔离和冷却完成，再参考规程决定是否复位。" :
    "执行停机隔离并按手册核验温度传感器，确认故障消除后才可复位。", "匿名候选", "info") +
    candidate("回答 B", "直接重启设备看看告警是否消失。", "匿名候选", "info") + "</div>";
}

Views.sample = function ({ id }) {
  const row = sampleId(id, activeType());
  return title(row.id, Types[row.type].name + " · " + row.issue,
    link(taskPath("dataset", row.type), "返回数据集", "secondary") + link("review/" + row.id, "打开审核", "primary")) +
    '<div class="grid inspect">' + card("样本内容", '<div class="stack"><p class="sample-title">' + escapeHtml(row.text) + "</p>" + variants(row) + "</div>", status(decision(row))) +
    '<div class="stack">' + card("证据与版本", kv([["来源位置", escapeHtml(row.evidence)], ["集合", tag(row.split)],
      ["标注类型", Types[row.type].name], ["快照", link("snapshot/snap-013", "设备语料 v1.3")],
      ["原文定位", link("document/" + EvidenceDocs[row.id], "检视文档")]])) +
    card("审核历史", state.decisions[row.id] ? kv([["判定", escapeHtml(state.decisions[row.id].verdict)],
      ["理由", escapeHtml(state.decisions[row.id].reason)]]) : note("等待人工提交。")) + "</div></div>";
};

Views.queues = function () {
  const type = activeType();
  const rows = samplesFor(type);
  return title("标注审核", "按任务和问题类型分流，优先审核可能影响交付的样本。", link(taskPath("quality", type), "质量中心", "secondary")) +
    typeTabs("queues", type) + card("审核队列", searchBox("queue", "筛选任务", "样本 ID、原因或状态") +
      table(["任务", "原因", "判定进度", "操作"], rows.map((row) => [
        link("review/" + row.id, row.text) + "<br><code>" + row.id + "</code>", escapeHtml(row.issue), status(decision(row)),
        link("review/" + row.id, decision(row) === "待审" ? "开始审核" : "查看结果", "secondary"),
      ]), "queue"), tag("示例 " + rows.length + " 条"));
};

Views.review = function ({ id }) {
  const row = sampleId(id, activeType());
  const rows = samplesFor(row.type);
  const next = rows[(rows.indexOf(row) + 1) % rows.length];
  const saved = state.decisions[row.id];
  const decisions = row.type === "dpo" ? ["A 优先", "B 优先", "平局", "均不合格", "退回"] :
    row.id === "E-0317" ? ["标为正例", "维持负例", "退回"] : ["通过", "退回"];
  const form = '<form class="form" data-form="review"><input type="hidden" name="sample" value="' + row.id + '">' +
    '<label>判定依据<textarea name="reason" required maxlength="300" placeholder="引用原文并说明为什么选择这个判定">' +
    escapeHtml(saved?.reason ?? "") + '</textarea></label><div class="actions">' + decisions.map((label, index) =>
      '<button class="button ' + (index === 0 ? "primary" : label === "退回" ? "danger" : "") + '" name="decision" value="' + label + '">' + label + "</button>").join("") + "</div></form>";
  const rubric = row.type === "dpo" ? "结合证据比较两条回答。平局、均不合格的记录不进入训练对。上下文不一致时退回。" :
    row.type === "embed" ? "覆盖正确答案的候选应标为正例。只有明确无法回答的候选才可作为负例。" :
      row.type === "rerank" ? "比较候选在同一个查询下的相关性。评分尺度为 0 无关、1 主题相关、2 部分回答、3 直接回答。" :
        "检查回答能否由语料支持，并核对工具的名称、参数类型、调用顺序和拒绝条件。";
  return title("审核工作台", row.id + " · " + Types[row.type].name,
    link(taskPath("queues", row.type), "返回队列", "secondary") + link("review/" + next.id, "下一条", "secondary")) +
    '<div class="grid inspect">' + card("待判定内容", '<div class="stack"><p class="sample-title">' + escapeHtml(row.text) +
      '</p><div class="evidence">' + escapeHtml(row.evidence) + " · " + link("document/" + EvidenceDocs[row.id], "查看证据") + "</div>" + variants(row) + "</div>",
      status(decision(row))) + '<div class="stack">' + card("审核规则", note(escapeHtml(rubric))) +
    card("提交判定", (saved ? note("已记录：" + escapeHtml(saved.verdict), "ok") : "") + form) + "</div></div>";
};

function checks(type) {
  const row = samplesFor(type)[0];
  const open = blocks(type);
  return [
    ["来源与授权", status("通过"), "来源快照包含可训练和导出的授权范围", link("sources", "查看来源")],
    ["结构与内容", status("通过"), "类型、字段、资产引用与条目唯一性", link(taskPath("dataset", type), "查看样本")],
    ["人工确认", open.includes(row.issue) ? pill("阻断", "err") : status("通过"), escapeHtml(row.issue), link("review/" + row.id, "打开审核")],
    ["划分与泄漏", open.includes("文档家族跨集合") ? pill("阻断", "err") : status("通过"),
      "同家族、同查询衍生记录和近重复组应位于同一集合", link("split", "查看划分")],
  ];
}

Views.quality = function () {
  const type = activeType();
  const count = blocks(type).length;
  return title("质量中心", "质量问题按数据集候选版本归集，可跳转到证据和可修复记录。",
    link("split", "检查数据划分", "secondary") + link(taskPath("release", type), "发布预检", "primary")) +
    typeTabs("quality", type) + '<div class="stack"><div class="grid three">' +
    stat("阻断规则", String(count), "处理完才能冻结版本", true) + stat("已通过规则", String(4 - count), "共 4 组预检规则") +
    stat("待审示例", String(samplesFor(type).filter((row) => decision(row) === "待审").length), "此原型显示的抽检记录") + "</div>" +
    card("质量规则与定位", table(["规则", "状态", "检查内容", "操作"], checks(type))) + "</div>";
};

Views.split = function () {
  const settings = state.split;
  const fields = [["train", "训练"], ["valid", "验证"], ["test", "测试"], ["seed", "随机种子"]];
  const form = '<form class="form" data-form="split"><div class="field-row">' + fields.map(([key, label]) =>
    '<label>' + label + (key === "seed" ? "" : "比例（%）") + '<input type="number" name="' + key + '" required min="' +
    (key === "seed" ? 0 : 1) + '" max="' + (key === "seed" ? 2147483647 : 98) + '" value="' + settings[key] + '"></label>').join("") +
    '</div><div class="actions"><button class="button primary">保存划分策略</button></div></form>';
  return title("数据划分", "以文档家族和相似查询为组，锁定测试集后再开始生产。", link("quality", "返回质量中心", "secondary")) +
    '<div class="grid inspect"><div class="stack">' + card("划分参数", form) +
    card("集合比例（目标）", ratioBars([["训练", settings.train, settings.train + "%"], ["验证", settings.valid, settings.valid + "%"],
      ["测试", settings.test, settings.test + "%"]])) + "</div>" +
    card("跨集合冲突", '<div class="stack">' + (settings.fixed ? note("同族文档已归入同一集合。", "ok") :
      note("维护手册 v3.1 的改写在验证集，v3.2 的同族语料在训练集。", "err")) +
    kv([["文档家族", "<code>manual-026</code>"], ["策略", "同族记录分组分配"], ["复核", link("document/doc-126", "查看冲突语料")]]) +
    button("split-fix", "按家族重新分组", "primary", "", settings.fixed) + "</div>") + "</div>";
};

function published(type) { return type === "embed" || type === "rerank" || state.release.includes(type); }

Views.releases = function () {
  return title("发布与导出", "从候选版本执行预检。冻结版本可独立选择训练格式。") +
    card("版本与交付", table(["数据集", "已冻结版本", "候选状态", "操作"], Object.entries(Types).map(([type, task]) => [
      link(taskPath("release", type), task.dataset), state.release.includes(type) ? "v1.1" : published(type) ? "v1.0" : "—",
      state.release.includes(type) ? status("已发布") : blocks(type).length ? pill("预检待处理", "warn") : pill("可冻结", "ok"),
      '<div class="flex">' + link(taskPath("release", type), "候选预检") + (published(type) ? link(taskPath("export", type), "导出预览") : "") + "</div>",
    ])));
};

Views.release = function () {
  const type = activeType();
  const task = Types[type];
  const count = blocks(type).length;
  const frozen = state.release.includes(type);
  return title("发布预检与冻结", task.dataset + " · v1.1 " + (frozen ? "已冻结" : "候选版"),
    link("releases", "返回版本列表", "secondary") +
    (frozen ? link(taskPath("export", type), "导出预览", "primary") : button("freeze-confirm", "确认并冻结", "primary", type, count > 0))) +
    typeTabs("release", type) + '<div class="stack">' + (frozen ? note("v1.1 已冻结。可导出并核对训练文件。", "ok") :
      count ? note("候选版有 " + count + " 项阻断。打开对应样本或划分页处理后再冻结。", "err") :
        note("规则预检通过。确认审批后冻结该候选版。", "ok")) +
    '<div class="grid inspect">' + card("规则结果", table(["规则", "状态", "检查内容", "操作"], checks(type))) +
    card("冻结清单", kv([["语料", link("snapshot/snap-013", "设备语料 v1.3")], ["候选集", link(taskPath("dataset", type), task.dataset)],
      ["审核与划分", "绑定审核、策略版本和固定种子"], ["发布状态", frozen ? status("已发布") : pill("待冻结")],
      ["可用交付", published(type) ? link(taskPath("export", type), "打开已冻结版本") : "候选版通过审批后开放"]])) + "</div></div>";
};

Views.export = function ({ params }) {
  const type = activeType();
  const task = Types[type];
  const options = type === "embed" ? [["canonical", "Embedding JSONL"], ["qrels", "检索标签 TSV"]] :
    type === "rerank" ? [["canonical", "候选组 JSONL"], ["flag", "FlagEmbedding JSONL"]] :
      type === "sft" ? [["canonical", "Messages JSONL"]] : [["canonical", "TRL DPO JSONL"], ["foundry", "Foundry DPO JSONL"]];
  const requested = params.get("format");
  const adapter = options.some(([key]) => key === requested) ? requested : options[0][0];
  const heading = title("导出预览", task.dataset + (published(type) ? " · " + (state.release.includes(type) ? "v1.1" : "v1.0") : ""),
    link("releases", "返回版本列表", "secondary"));
  if (!published(type)) return heading + typeTabs("export", type) + card("暂无冻结版本", note("审核通过并冻结候选版本后，这里会显示可导出的格式。") +
    '<div class="actions">' + link(taskPath("release", type), "打开发布预检", "primary") + "</div>");
  const preview = adapter === "qrels" ? "<pre>query-id\tcorpus-id\tscore\nq-317\tseg-64\t1</pre>" :
    "<pre>" + escapeHtml(JSON.stringify(example(type, adapter))) + "</pre>";
  return heading + typeTabs("export", type) +
    tabs(options.map(([key, label]) => [key, label, taskPath("export", type) + "&format=" + key]), adapter) +
    '<div class="grid inspect">' + card("单条记录预览", preview, button("download-example", "下载示例", "primary", type + "/" + adapter)) +
    card("导出说明", kv([["训练任务", task.name], ["版本", state.release.includes(type) ? "v1.1" : "v1.0"], ["预览内容", "一条虚构样例"],
      ["完整产物", adapter === "qrels" ? "语料、查询、按集合划分的标签与校验清单" : "分集训练文件、来源清单、质量报告与校验清单"]])) + "</div>";
};

Views.evaluation = function ({ params }) {
  const type = activeType();
  const detail = params.get("tab") === "cases";
  const results = Types[type].metrics.map(([metric, base, candidate, delta]) => [metric, base, candidate, tag(delta)]);
  const fixed = EvaluationCases[type];
  const comparison = table(["评测输入", "问题类别", "基线", "候选", "操作"], [[
    escapeHtml(fixed.input) + "<br><code>" + fixed.id + "</code>", tag(fixed.tag),
    escapeHtml(fixed.base), escapeHtml(fixed.candidate), button("evaluation-case", "查看对比", "secondary", type),
  ]]);
  return title("基准评测", Types[type].name + " · 固定测试集 · 示例结果", link(taskPath("dataset", type), "查看相关数据集", "secondary")) +
    typeTabs("evaluation", type) + tabs([["metrics", "指标对比", taskPath("evaluation", type)],
      ["cases", "回归样本", taskPath("evaluation", type) + "&tab=cases"]], detail ? "cases" : "metrics") +
    '<div class="grid inspect">' + (detail ? card("锁定测试样本（示例）", comparison) :
      card("同一测试集上的基线与候选", table(["指标", "基线", "候选", "差值"], results), tag("演示数据"))) +
    card("评测协议", kv([["数据", "冻结测试集 test-2026-11"], ["对照", "同一测试查询与评估器版本"],
      ["候选范围", type === "rerank" ? "固定召回 Top-50，保留漏召回统计" : type === "embed" ? "固定检索语料、查询与相关性标注" : "固定会话输入、工具与评分细则"],
      ["查看记录", link(taskPath("evaluation", type) + "&tab=cases", "检查样本")]])) + "</div>";
};

Views.models = function () {
  const models = [
    ["文本向量服务", "Embedding", "文本 · 双塔输入", "项目私有网络"],
    ["教师重排服务", "Reranker", "文本 · 相关性分数", "项目私有网络"],
    ["问答生成服务", "LLM", "对话 · JSON 工具参数", "项目私有网络"],
    ["答案审查服务", "LLM Judge", "引用验证 · 结构化打分", "已审批外部服务"],
  ];
  return title("模型连接", "按能力、授权和出域策略选择生产步骤可用的模型。") +
    card("已授权模型（示例）", table(["连接", "类型", "支持能力", "数据边界", "操作"], models.map(([name, type, capability, boundary]) =>
      [escapeHtml(name), tag(type), escapeHtml(capability), escapeHtml(boundary), button("check-model", "连接诊断", "secondary", name)])));
};

Views.settings = function ({ params }) {
  const panel = params.get("tab") ?? "access";
  const settingsTabs = tabs([["access", "成员与授权", "settings"], ["budget", "预算与策略", "settings?tab=budget"],
    ["audit", "审计事件", "settings?tab=audit"]], panel);
  const body = panel === "audit" ? card("审计事件", table(["事件", "对象", "时间"], auditRows().map((item) => [
    escapeHtml(item.action), escapeHtml(item.target), escapeHtml(item.time),
  ]))) : panel === "budget" ? '<div class="grid">' +
    card("项目预算", kv([["演示运行上限", money(state.budget)], ["计量单位", "Token、请求、资产用量"], ["超限", "暂停新批次并提示调整预算"]]),
      button("budget-edit", "编辑预算", "secondary")) +
    card("出域策略", note("受限语料仅允许通过批准的境内或私有连接。外部请求使用授权范围内的脱敏字段。")) + "</div>" :
    card("项目角色（示例）", table(["成员", "角色", "权限范围"], [
      ["数据负责人", pill("管理员", "info"), "成员、连接、预算与策略"], ["标注组", pill("标注员"), "已分配样本和资料"],
      ["质量负责人", pill("复核与发布审批", "ok"), "仲裁、质检、审批"], ["训练工程组", pill("训练使用者"), "指定版本导出与评测"],
    ]), link("models", "查看模型授权"));
  return title("项目设置", "设备知识库 · 训练数据工作区", link("login", "查看登录页", "secondary")) + settingsTabs + body;
};

Views.login = function () {
  return '<main class="login"><div><div class="brand"><span class="mark" aria-hidden="true"></span>DataFactory</div>' +
    '<h1 id="page-title" tabindex="-1">训练数据工作台</h1></div><section class="card stack"><h2>登录 DataFactory</h2>' +
    '<p class="muted">正式产品使用组织身份服务。原型可直接进入演示项目。</p>' +
    link("overview", "进入演示项目", "primary") + "</section></main>";
};

const Types = {
  embed: {
    name: "Embedding", label: "检索训练", dataset: "设备手册检索", count: 1480, pending: 62,
    description: "构建查询、正例和经核验的难负例，校验召回覆盖与假负例。",
    stages: ["冻结语料与种子", "生成问题", "混合召回", "识别疑似假负例", "整理三元组"],
    metrics: [["Recall@10", "78.4%", "82.1%", "+3.7 pp"], ["MRR@10", "0.618", "0.647", "+0.029"]],
  },
  rerank: {
    name: "Reranker", label: "重排训练", dataset: "故障段落重排", count: 630, pending: 38,
    description: "围绕同一查询标注文档相关性，保留等级、候选池和排序证据。",
    stages: ["装载查询集", "冻结 Top-K 候选", "教师评分", "判定相关性", "整理候选组"],
    metrics: [["nDCG@10", "0.703", "0.752", "+0.049"], ["MRR@10", "0.631", "0.665", "+0.034"]],
  },
  sft: {
    name: "LLM SFT", label: "监督微调", dataset: "维护问答与工具调用", count: 280, pending: 18,
    description: "从操作证据制作多轮对话，验证引用、消息角色和工具参数。",
    stages: ["选取主题与证据", "生成指令", "生成多轮回答", "验证引用与约束", "整理对话"],
    metrics: [["事实与证据一致", "84.2%", "90.8%", "+6.6 pp"], ["工具参数通过率", "91.0%", "95.0%", "+4.0 pp"]],
  },
  dpo: {
    name: "LLM 偏好", label: "偏好训练", dataset: "维护问答偏好对", count: 90, pending: 8,
    description: "对同一上下文的候选回答做匿名对比，记录偏好理由和仲裁结果。",
    stages: ["选择共享上下文", "生成候选 A/B", "过滤重复候选", "匿名比较与仲裁", "整理偏好对"],
    metrics: [["盲评胜率", "50.0%", "58.0%", "+8.0 pp"], ["工具约束通过率", "91.0%", "93.0%", "+2.0 pp"]],
  },
};

const Positive = "E17 表示设备温控区超温。先按停机流程隔离设备，核对温度传感器和风道，再按手册第 6.4 节复位。";
const ConditionalPositive = "同一机型进入 E17 保护时，应先停止设备并核对风道堵塞或测温异常。";
const Negative = "E71 表示通信连接异常。请核对网线和通信模块指示灯。";
const IssuePrompt = "收到 E17 超温报警后，应先检查什么？";

const Samples = [
  { id: "E-0317", type: "embed", text: IssuePrompt, issue: "疑似假负例", lang: "简中", split: "训练", evidence: "温控设备维护手册 · §6.4", score: "0.88" },
  { id: "E-0321", type: "embed", text: "风道更换后如何复位？", issue: "常规抽检", lang: "简中", split: "训练", evidence: "温控设备维护手册 · §7.1", score: "0.22" },
  { id: "E-0456", type: "embed", text: "How do I verify a replaced temperature sensor?", issue: "常规抽检", lang: "英文", split: "验证", evidence: "冷却系统保养规范 · §4.2", score: "0.19" },
  { id: "R-0062", type: "rerank", text: "如何区分 E17 超温与 E71 通信故障？", issue: "模型与人工分歧", lang: "简中", split: "训练", evidence: "现场故障记录 · 04/17", score: "2 / 3" },
  { id: "R-0063", type: "rerank", text: "冷却回路检测在复位前还是复位后？", issue: "常规抽检", lang: "简中", split: "验证", evidence: "冷却系统保养规范 · §3.1", score: "3 / 3" },
  { id: "S-0093", type: "sft", text: "生成停机检查清单并查询告警历史", issue: "工具参数校验", lang: "简中", split: "训练", evidence: "设备操作规程 · §2.3", score: "4 / 5" },
  { id: "S-0107", type: "sft", text: "向值班员解释告警分级及升级流程", issue: "常规抽检", lang: "简中", split: "验证", evidence: "设备操作规程 · §5", score: "5 / 5" },
  { id: "P-0021", type: "dpo", text: "传感器异常时直接恢复运行是否可行？", issue: "两人偏好不一致", lang: "简中", split: "训练", evidence: "温控设备维护手册 · §6.4", score: "A / B" },
  { id: "P-0024", type: "dpo", text: "在证据不足时怎样回答复位请求？", issue: "常规抽检", lang: "简中", split: "验证", evidence: "设备操作规程 · §2.3", score: "待判定" },
];

const EvidenceDocs = {
  "E-0317": "doc-126", "E-0321": "doc-126", "E-0456": "doc-127",
  "R-0062": "doc-201", "R-0063": "doc-127", "S-0093": "doc-309",
  "S-0107": "doc-309", "P-0021": "doc-126", "P-0024": "doc-309",
};

const EvaluationCases = {
  embed: { id: "TEST-E021", input: "LX3 冷却泵的低压保护怎样解除？", tag: "型号歧义", base: "正例排第 13", candidate: "正例排第 4",
    detail: "候选模型将 LX3 条件匹配的手册段落排在同系列通用说明之前。" },
  rerank: { id: "TEST-R018", input: "设备断电后可以立即进行电容检查吗？", tag: "等待时间约束", base: "首条仅同主题", candidate: "首条直接回答",
    detail: "两个模型使用相同的候选池。人工等级最高的证据段需要说明放电等待时间。" },
  sft: { id: "TEST-S013", input: "按巡检规范生成绝缘检查清单并提示升级条件。", tag: "证据完整度", base: "缺少升级条件", candidate: "覆盖升级条件",
    detail: "评估器检查安全前置条件、仪表读数与异常升级。此记录只用于固定评测。" },
  dpo: { id: "TEST-P014", input: "无法确认维修授权时如何回应远程复位请求？", tag: "受限操作", base: "条件解释不全", candidate: "盲评优先",
    detail: "按固定量表核对身份校验、拒绝依据、替代操作和升级步骤。界面展示盲评结论。" },
};

const BuiltinSources = [
  { id: "kb", name: "设备手册知识库", kind: "知识库连接", grant: "项目范围 · 仅已授权文档", files: "126", status: "已同步", time: "今天 09:42" },
  { id: "tickets", name: "脱敏故障工单", kind: "对象存储", grant: "faults/masked/ · 只读", files: "48", status: "已同步", time: "今天 08:12" },
  { id: "queries", name: "高频检索词", kind: "CSV 导入", grant: "人工确认使用权", files: "1", status: "有新版本", time: "昨天 16:26" },
  { id: "chatlog", name: "巡检会话", kind: "JSONL 导入", grant: "等待项目管理员授权", files: "—", status: "待授权", time: "—" },
];

const Documents = [
  { id: "doc-126", name: "温控设备维护手册", rev: "v3.2", count: 312, format: "文本 · 图表", group: "manual-026" },
  { id: "doc-127", name: "冷却系统保养规范", rev: "v2.4", count: 186, format: "文本", group: "manual-034" },
  { id: "doc-201", name: "现场故障记录", rev: "2026-11", count: 108, format: "文本", group: "tickets-011" },
  { id: "doc-309", name: "设备操作规程", rev: "v1.9", count: 84, format: "文本 · 表格", group: "spec-008" },
];
const Snapshots = [
  { id: "snap-013", name: "设备语料 v1.3", count: 8640, date: "今天 09:45", sources: "设备手册知识库、脱敏故障工单" },
  { id: "snap-012", name: "设备语料 v1.2", count: 7902, date: "昨天 15:02", sources: "设备手册知识库" },
];
const BuiltinRuns = [
  { id: "RUN-104", name: "故障段落重排 · 生产", type: "rerank", status: "运行中", progress: 68, date: "今天 10:24", size: 630 },
  { id: "RUN-103", name: "设备手册检索 · 生产", type: "embed", status: "已完成", progress: 100, date: "今天 10:02", size: 1480 },
  { id: "RUN-102", name: "设备手册检索 · 小批预览", type: "embed", status: "已完成", progress: 100, date: "今天 09:54", size: 20 },
  { id: "RUN-101", name: "维护问答 · 生产", type: "sft", status: "已暂停", progress: 43, date: "昨天 16:08", size: 280 },
];

const RouteNames = {
  overview: "项目总览", sources: "数据源", "source-new": "接入数据源", source: "来源详情",
  corpus: "语料快照", snapshot: "快照详情", document: "语料检视",
  recipes: "配方库", templates: "模板库", recipe: "配方设计器",
  runs: "运行记录", run: "运行详情", datasets: "数据集", dataset: "数据集详情", sample: "样本详情",
  queues: "标注审核", review: "审核工作台", quality: "质量中心", split: "数据划分",
  releases: "发布与导出", release: "发布预检与冻结", export: "导出预览",
  evaluation: "基准评测", models: "模型连接", settings: "项目设置", login: "登录演示",
};
const Nav = [
  ["工作区", [["overview", "◫"]]],
  ["数据准备", [["sources", "▣"], ["corpus", "▤"], ["recipes", "◇"]]],
  ["数据生产", [["runs", "▷"], ["datasets", "▥"], ["queues", "✓"], ["quality", "◎"]]],
  ["交付与治理", [["releases", "⇧"], ["evaluation", "◒"], ["models", "⊞"], ["settings", "⚙"]]],
];
const Parents = {
  "source-new": "sources", source: "sources", snapshot: "corpus", document: "corpus",
  templates: "recipes", recipe: "recipes", run: "runs", dataset: "datasets", sample: "datasets",
  review: "queues", split: "quality", release: "releases", export: "releases",
};

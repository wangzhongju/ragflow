# DataFactory 前端开发指导

DataFactory 平台的前端，与 RAGFlow 同源部署在 `/factory/`。产品与交互基线见 [../design/PRODUCT_DESIGN.md](../design/PRODUCT_DESIGN.md) 第 12 章；平台整体工程规则见 [../CLAUDE.md](../CLAUDE.md)。这是一个独立应用：RAGFlow `web/` 的代码、其 Go/Python 双后端变体约定以及共享 UI 目录均不适用于此处，也不得导入。

## 核心立场

- 每种行为只保留一种实现；被替代的组件、Hook 和样式在同一次改动中删除。不使用 `Legacy`/`New`/`V2` 命名，不保留被注释掉的 JSX，不为旧路径保留功能开关。
- 严禁简陋页面。每个页面都要交付设计好的加载、空、错误、部分完成四种状态（设计文档 §12.12），并遵循 §12.4–§12.10 的布局。工作台类页面不接受"页面上放一个表单"的交付。
- 后端 OpenAPI Schema 是 API 类型的唯一来源。不得手写与其重复的响应类型。

## 技术栈

- React 18 + TypeScript（strict）+ Vite，React Router（data router）。
- Tailwind CSS，设计 token 以 CSS 变量定义；Radix 原语封装为 `src/ui/` 下的自有组件。
- TanStack Query（服务端状态）、TanStack Table + TanStack Virtual（大表格/长列表）、Zustand（仅限本地 UI 状态）、react-hook-form + zod（表单）、i18next（zh、en）。
- `@xyflow/react`（配方画布，自动布局用 `elkjs`）、Monaco（`@monaco-editor/react`）用于 Jinja/JSON 编辑器、ECharts（canvas 渲染）用于图表和万级以上散点图。
- `dayjs`、`ahooks`、`uuid`（不要用 `crypto.randomUUID`，内网 HTTP 部署下不可用）、`openapi-typescript` + `openapi-fetch`。
- 工具链：oxlint、oxfmt（若不可用则用 Prettier，二选一并删除另一个）、Vitest + Testing Library、Playwright（e2e）、Storybook（`src/ui` 及带可视状态的业务组件）。

## 常用命令

```bash
npm ci
npm run dev           # Vite 运行于 :9391，base 为 /factory/，/api/factory 代理到 :9390
npm run gen:api       # openapi-typescript openapi.json -> src/api/schema.d.ts
npm run lint
npm run type-check
npm run test          # Vitest
npm run e2e           # Playwright，针对开发环境
npm run build         # 输出 dist/，供 Nginx /factory/ 使用
npm run storybook
```

后端 API 变更后执行 `gen:api`，并将重新生成的 Schema 与使用它的改动一起提交。

## 目录结构

```
src/
├─ app/            路由、Provider（QueryClient、i18n、主题）、登录守卫、错误边界、布局框架
├─ api/            schema.d.ts（生成）、client.ts（唯一的 openapi-fetch 实例）、sse.ts
├─ features/
│  ├─ overview/
│  ├─ projects/
│  ├─ corpus/      快照向导、快照详情、切片浏览器、体检报告
│  ├─ recipes/     配方设计器（画布、列库、检查器、预览抽屉）、模板、版本与差异
│  ├─ runs/        运行列表、运行监控（时间线、吞吐、错误、日志）
│  ├─ datasets/    样本浏览器（分面、分布图、虚拟表格）、样本详情抽屉
│  ├─ review/      审核队列、审核台
│  ├─ releases/    门禁清单、发布详情、差异、导出对话框
│  ├─ evaluation/
│  └─ settings/    成员、预算、模型、提示词/量表资源
│     每个 feature 包含：api.ts（查询键 + Hook）、components/、routes.tsx、types.ts、__tests__/
├─ ui/             设计系统组件（Button、Badge、StatusBadge、DataTable、Drawer、Inspector、KpiCard、EmptyState、ErrorState、Skeleton、Kbd、CommandPalette 等）
├─ content/        ContentPart 渲染器：TextPart、ImagePart、TablePart（净化后的 HTML）、AudioPart、VideoPart、PageHighlight
├─ charts/         使用统一主题的 ECharts 封装
├─ lib/            格式化（数字、字节、Token、货币、时长）、键盘、ID、净化
├─ locales/        zh.ts、en.ts
└─ styles/         tokens.css（亮/暗）、tailwind.css
```

规则：

- feature 只从 `ui/`、`content/`、`charts/`、`lib/`、`api/` 和自身目录导入。feature 之间不导入彼此的内部实现；第二个 feature 需要时，把共享部分移到 `ui/` 或 `content/`。
- 路由组件保持精简：只读取参数并组合 feature 组件，不承担其他职责。

## 数据请求

- `src/api/client.ts` 使用一个 openapi-fetch 客户端。平台请求使用 HttpOnly Cookie，只有 `/me` 可读取同源 RAGFlow `Authorization` 作为首次建立会话的凭证。创建类请求添加 `Idempotency-Key`。`/me` 的 401 由登录守卫处理，`POST /session` 的 401 由登录表单处理，其余 401 由客户端跳转 `/factory/login`。
- Hook 放在各 feature 的 `api.ts` 中。每个 feature 定义查询键工厂 `{Feature}Keys`，返回 `as const` 元组；所有 `useQuery` 与 `invalidateQueries` 都引用它。不写内联键数组。
- 查询在渲染其数据的组件中发起，而不是在父页面中。互斥视图拆成独立组件，而不是层层传递 `enabled` 标志。
- 长任务（快照构建、预览、运行、导出）使用 `api/sse.ts` 的 SSE 流；SSE 事件通过 `setQueryData` 或失效刷新更新 Query 缓存。已有 SSE 主题时不要轮询。
- 审核台的操作（通过/驳回/提升为正例）必须乐观更新，失败时回滚并给出提示。
- 游标分页使用 `useInfiniteQuery`；长列表通过 TanStack Virtual 渲染。

## 设计系统

- 所有颜色、圆角、阴影、间距和字体都来自 `styles/tokens.css` 的变量，经 Tailwind 主题键暴露（`bg-surface`、`text-muted`、`border-subtle`、`status-success`、`modality-image` 等）。组件中不使用原始 hex/RGB 值或 Tailwind 默认调色板类名。
- 字体与间距按设计文档 §12.11：表格正文 13px、正文 14px、4px 栅格、6/10px 圆角、指标使用等宽数字、ID/JSON 使用等宽字体。
- 状态始终通过 `StatusBadge` 以"图标 + 文字 + 颜色"表达，不只靠颜色。模态通过 `ModalityBadge` 展示。
- 亮色和暗色主题都必须可用；每个新组件都要在 Storybook 中检查两种主题。
- 动效 150–200ms，遵从 `prefers-reduced-motion`。
- `src/ui/` 是共享组件库：修改要慎重，为每种状态补充 Storybook 用例，并检查所有调用处。不要在 feature 内复制一份 `ui` 组件，而是通过 props 或组合扩展。

## 页面专项要求

- **配方设计器：** 画布节点与连线由配方配置推导（连线来自计算得出的 `required_columns`），用户不能手动连线。检查器通过 react-hook-form 编辑配置，zod Schema 由列的 `config_schema` 生成。画布位置只保存到 `ui_layout`。不得把表单状态的结构写入配方配置，反之亦然——配置只有一种结构，即后端的结构。Monaco Jinja 编辑器提供上游列的变量补全、未定义变量标记，以及针对选中预览行的渲染后提示词预览。预览抽屉支持"仅重跑已变更列"和逐单元格的 trace 浮层。
- **运行监控：** 按列的泳道时间线、吞吐与并发图、链接到失败行的错误分桶、预算表；取消操作须二次确认，并说明已发出的模型调用无法撤销。
- **样本浏览器：** 分面筛选同步到 URL 查询参数；分布图带（评审分直方图、正例与最难负例散点图并支持框选筛选、类型/模态堆叠条）；虚拟表格；详情抽屉包含 样本 / 原文 / 血缘 / Trace / 修订 五个 Tab。
- **审核台：** 全键盘操作（`J/K`、`↑/↓`、`A`、`R` + 数字选原因、`E`、`N`、`X`、`1–4`、`O`、`Z`、`?`），焦点可见，快捷键帮助浮层，队列进度，预取下一条样本。通过类操作的单样本中位按键数 ≤ 3。
- **发布与导出：** 门禁清单可点击跳转到问题样本；适配器卡片显示支持的任务类型和模态，不兼容时说明原因；导出对话框在生成前渲染前 3 条输出记录。
- **内容渲染：** 所有 `ContentPart` 渲染都经 `src/content/`。表格 HTML 在渲染前用 DOMPurify 净化。图片从 `/api/factory/v1/assets/{asset_id}` 懒加载，并使用固定宽高比容器避免布局抖动。页面高亮使用段的 `region` 坐标。

## 性能预算

- 10 万样本时样本浏览器首屏 < 1.5s，滚动保持 60fps（行与列虚拟化，单元格渲染器 memo 化）。
- 超过 5000 个点的散点图使用 ECharts canvas 并开启 `large: true`。
- 路由级代码分割；Monaco、xyflow、ECharts 只在使用它们的页面加载。
- DOM 中不出现无界列表；不使用间隔短于 5 秒的轮询。

## 编码约定

- 组件与顶层常量使用 PascalCase；Hook 命名 `useXxx`；文件名 kebab-case。
- JSX 事件属性上不写内联箭头函数；处理函数具名（如 `handleApprove`）。
- props 按语义命名（`activeTab`/`onTabChange`），而不是沿用底层原语的 API 名称。
- 使用 react-i18next 的 `useTranslation`；每个用户可见文案都有 zh 与 en 词条；en 使用句首大写。领域术语遵循设计文档 §17.1 的术语表。
- 日期用 `dayjs` 按用户语言格式化；数字用 `lib/format`。
- 修复布局问题时，检查完整的 flex/overflow 祖先链，先说明根因再修改类名。
- 无障碍：所有交互元素可通过键盘到达、带有标签，并在两种主题下满足 WCAG AA 对比度。

## 测试

- 测试放在代码旁的 `__tests__/` 目录或命名为 `foo.test.ts(x)`；不使用 `tests/` 目录。
- 对转换逻辑做单元测试（配方 ↔ 画布推导、分面 ↔ URL 同步、内容渲染器、审核台键盘 reducer）。
- 组件测试使用基于生成 Schema 类型构造的 MSW handler。
- Playwright e2e 覆盖主流程：登录 → 快照 → 从模板创建配方 → 预览 → 运行 → 审核 → 发布 → 导出对话框预览。
- 每个 `ui/` 与 `content/` 组件都有 Storybook 用例：默认、加载、空、错误、暗色主题。

## 与 RAGFlow 的集成

- RAGFlow 前端唯一的改动是在导航中增加一个指向 `/factory/` 的入口；该改动属于 RAGFlow 的 `web/`，遵循那里的 `web/CLAUDE.md`。
- `/factory/login` 经 DataFactory `POST /api/factory/v1/session` 校验 RAGFlow 账号，获得平台自己的 HttpOnly 会话。有效平台 Cookie 优先于 RAGFlow 令牌。DataFactory 只读取 `Authorization` 用于同源首次会话建立，令牌由 RAGFlow 自己管理。
- 不直接调用 RAGFlow API 获取业务数据；RAGFlow 的知识库、文档和模型通过 `/api/factory/v1/ragflow/*` 读取。

## 审阅清单

- 使用生成的 API 类型，没有手写重复类型；`api/client.ts` 之外没有直接请求。
- 处处使用查询键工厂；查询与其视图放在一起。
- 四种状态都已设计；两种主题都已检查；键盘与焦点正确。
- 只使用 token，没有原始颜色；状态不只靠颜色表达。
- 配方配置只有一种结构；画布只保存布局。
- 被替代的组件和样式已删除。

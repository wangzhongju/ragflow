#!/usr/bin/env python3
"""Generate the complete source responsibility tree from Git and source declarations."""

import argparse
import ast
from collections import Counter
import html
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/project-structure.html"

DIRECTORIES = {
    ".agents": "工程内代理技能与协作约定",
    ".github": "GitHub 协作模板及自动化工作流",
    ".github/workflows": "提交、发布、镜像及多后端 CI 工作流",
    "admin": "Python 管理服务：管理路由、认证与服务启动",
    "agent": "Python 工作流画布、组件执行、工具与流程模板",
    "agent/component": "Python 工作流节点的参数校验和执行实现",
    "agent/tools": "供工作流调用的外部工具适配器",
    "agent/templates": "可导入的工作流 DSL 模板",
    "api": "Quart HTTP API、请求处理、认证及业务服务",
    "api/apps": "HTTP 路由与请求/响应处理；SDK 路由位于 sdk 子目录",
    "api/db": "关系数据库模型、数据库初始化与业务数据服务",
    "api/db/services": "Python 业务数据查询、持久化及事务服务",
    "bin": "Go/原生可执行文件输出位置；Git 仅保留占位文件",
    "cmd": "Go 服务与 CLI 可执行程序入口",
    "common": "Python 跨模块配置、连接器、类型、日志及公共工具",
    "common/data_source": "外部数据源连接、读取与同步适配",
    "conf": "默认配置、模型目录、提示词及业务规则资源",
    "deepdoc": "Python 文档解析、OCR、版面/表格识别与视觉模型接口",
    "deepdoc/parser": "各文档格式的 Python 解析实现",
    "deepdoc/vision": "OCR、布局、表格等视觉推理与后处理",
    "docker": "应用/存储部署、镜像构建、运行入口及运维工具",
    "docker/compose": "分离部署与单机部署共用的 app/storage Compose 定义",
    "docker/config": "部署环境样例、服务配置模板及 Nginx 配置",
    "docker/config/nginx": "Nginx 主配置、代理参数与不同后端的路由配置",
    "docker/runtime": "容器入口、宿主用户映射、镜像工具安装与源码启动",
    "docker/scripts": "宿主初始化/构建/备份与容器内检查维护程序",
    "docker/manifests": "镜像、模型目录与现场验证的可复核记录；不保存凭据",
    "docker/ci": "CI 专用 Python/Go × 多存储后端配置；不用于 91/92 业务部署",
    "docs": "用户、开发、API、现场操作和工程文件说明",
    "docs/references": "HTTP API、SDK、配置等参考文档",
    "example": "调用 SDK/API、工作流等可参考示例",
    "helm": "Kubernetes Helm Chart、默认值及资源模板",
    "internal": "Go 后端内部实现和 C++/Rust 原生绑定，不作为外部 SDK",
    "internal/agent": "Go 工作流画布、节点、工具绑定与执行运行时",
    "internal/cli": "Go CLI 参数解析、HTTP 传输、命令及输出格式",
    "internal/dao": "Go 数据访问与数据库持久化操作",
    "internal/deepdoc": "Go DeepDOC 接口与 PDF/DOCX 原生解析集成",
    "internal/engine": "Go Elasticsearch、Infinity 等检索索引后端",
    "internal/entity": "Go 跨层业务实体、请求响应与模型定义",
    "internal/handler": "Go HTTP 请求处理和业务接口入口",
    "internal/ingestion": "Go 文档摄取、画布适配、组件调度与任务编排",
    "internal/ingestion/component": "Go 文件、解析、切块、分词及抽取阶段实现",
    "internal/ingestion/pipeline": "Go 摄取 DSL、画布执行、检查点与恢复逻辑",
    "internal/parser": "Go 文档解析、块处理及相关运行时库",
    "internal/parser/parser": "Markdown/HTML/PDF/DOCX/XLSX 等类型化解析结果处理",
    "internal/parser/chunk": "Go 切块算子及 DSL/类型化执行接口",
    "internal/service": "Go 业务服务；连接 HTTP 层、数据访问和模型能力",
    "internal/storage": "Go 存储适配及内存测试替身",
    "internal/router": "Go HTTP 路由注册与中间件组合",
    "internal/server": "Go 服务引导、依赖装配、配置与启动",
    "internal/cpp": "Go 原生能力使用的 C++ 源码、构建及绑定资源",
    "memory": "对话记忆、存储检索和记忆管理实现",
    "mcp": "RAGFlow MCP 服务及客户端工具接入",
    "rag": "Python 摄取、检索、模型调用、Graph RAG 和任务执行",
    "rag/app": "按文档用途划分的解析、切块策略",
    "rag/llm": "Chat、Embedding、Rerank、视觉和语音模型提供商适配",
    "rag/nlp": "分词、检索、查询处理及 NLP 公共逻辑",
    "rag/graphrag": "图谱抽取、构建、社区与图检索",
    "rag/svr": "后台任务 Worker、数据同步与执行调度",
    "rag/res": "分词词典、规则、字表及模型配套资源",
    "ragflow_deps": "离线资源下载清单、下载器及依赖镜像材料",
    "scripts": "工程维护、测试资料拉取和可重复生成的文件索引",
    "sdk": "对外 SDK 源码、包定义与调用接口",
    "sdk/python": "Python SDK 发布与客户端接口",
    "test": "Python/API/SDK/集成测试与受控测试资料",
    "test/unit_test": "定向单元测试及部署工具契约检查",
    "tools": "开发工具、代码检查钩子、维护脚本与辅助运行程序",
    "tools/hooks": "提交前格式、许可证、文件及代码一致性检查",
    "web": "React + TypeScript + Vite 前端源码、静态资源与构建配置",
    "web/src": "前端页面、组件、状态、路由、服务调用及样式",
    "web/src/pages": "产品页面及页面内组件、表单和交互",
    "web/src/components": "跨页面复用的 React 界面组件",
    "web/src/services": "前端 HTTP API 请求封装",
    "web/src/hooks": "前端数据请求、状态与交互 Hook",
    "web/src/locales": "界面多语言文本；与已删除的根目录多语言 README 无关",
    "web/src/utils": "前端公共数据转换与浏览器工具",
    "web/src/constants": "前端常量、枚举与共享约定",
    "web/public": "浏览器可直接访问的图标、图片等静态文件",
}

FILES = {
    ".dockerignore": "镜像构建上下文排除规则，避免把凭据、日志和本地产物送入构建器。",
    ".gitignore": "Git 忽略规则；区分源码、私有配置和可重建运行/构建产物。",
    ".gitattributes": "Git 文件属性：Shell/YAML 行尾和二进制测试资料的字节保持规则。",
    ".rooignore": "Roo 开发工具的文件忽略配置。",
    ".trivyignore": "Trivy 安全扫描忽略项及对应维护说明。",
    "AGENTS.md": "工程协作准则、代码职责及 Go 测试分层约定。",
    "LICENSE": "工程 Apache-2.0 许可证正文。",
    "SECURITY.md": "安全漏洞报告渠道及安全策略。",
    "README.md": "英文项目介绍、能力概览和部署/开发入口。",
    "README_zh.md": "简体中文项目介绍、能力概览和部署/开发入口。",
    "build.sh": "Go/原生构建及分层测试主入口，装配 CGO 静态库和链接参数。",
    "run_go_tests.sh": "Go 测试执行辅助脚本；日常优先使用 build.sh 注入原生环境。",
    "run_tests.py": "跨平台测试运行调度器，解析测试选项并调用相应测试流程。",
    "test.py": "独立 FastAPI 请求体回显小程序，监听 8000；不是 RAGFlow 服务入口。",
    "show_env.sh": "收集系统、CPU、运行环境及仓库诊断信息。",
    "pyproject.toml": "Python 包元数据、依赖/可选依赖、uv 源及测试/检查工具配置。",
    "uv.lock": "uv 锁定的 Python 依赖版本与分发校验，配合 pyproject.toml 构建依赖环境。",
    "go.mod": "Go 模块路径、语言版本、依赖及 replace 定义。",
    "go.sum": "Go 模块下载内容校验记录。",
    "codecov.yml": "覆盖率上传后的 Codecov 统计与报告策略。",
    "lefthook.yml": "Lefthook Git 钩子和提交检查任务。",
    "docker/docker.sh": "唯一部署命令入口：显式选择 app/storage/all；构建、健康等待、启停、日志和 into。",
    "docker/README.md": "部署入口用法与配置步骤；目录职责统一由本索引维护。",
    "docker/Dockerfile": "从依赖镜像和源码构建完整运行镜像，包括 Python 环境、前端及交互工具。",
    "docker/Dockerfile.runtime": "从已核验 v0.27.2 基础镜像构建挂载式运行环境，安装工具并保留离线资源。",
    "docker/Dockerfile.base": "构建 CI/开发使用的基础依赖镜像。",
    "docker/Dockerfile.ci": "CI 测试镜像的专用构建定义。",
    "docker/Dockerfile.go": "Go 服务专用镜像构建定义。",
    "docker/Dockerfile.deepdoc": "DeepDOC 原生解析相关镜像构建定义。",
    "docker/compose/compose.app.yml": "应用服务、端口、资源配额、健康检查、工程/用户目录绑定和依赖只读卷。",
    "docker/compose/compose.storage.yml": "MySQL、Redis、MinIO、ES 及管理界面的服务、持久卷和健康检查。",
    "docker/runtime/env.sh": "在应用容器内创建/匹配宿主用户 UID/GID，配置 sudo、PS1、Bash 补全与 Vim。",
    "docker/runtime/install-dev-tools.sh": "镜像构建时安装常用工具，将 Python/NLTK 资源移至普通用户可访问的位置。",
    "docker/runtime/entrypoint-mounted.sh": "挂载式应用入口：初始化用户、补齐镜像离线资源，再启动应用进程。",
    "docker/runtime/entrypoint.sh": "应用进程入口：生成服务配置，启动 Nginx、API、管理服务与 Worker。",
    "docker/scripts/init_env.py": "首次生成配套 app.env/storage.env 和随机凭据，拒绝覆盖既有文件。",
    "docker/scripts/build_runtime.sh": "核验固定基础镜像、构建最小运行镜像并写入镜像身份记录。",
    "docker/scripts/backup.sh": "验证应用停写和卷归属后执行本工程七卷冷备、校验并恢复原存储运行状态。",
    "docker/scripts/configure_storage.sh": "配置本工程 ES/Kibana 服务账号及存储初始化参数。",
    "docker/scripts/inspect_task.py": "读取文档任务状态、日志和相关执行信息，用于任务排障。",
    "docker/scripts/verify_storage.py": "唯一名称探针的 create/verify/clean；检查四类存储读写及重启保持。",
    "docker/scripts/verify_runtime.py": "离线核验挂载源码、Python、tokenizer、Tika、OCR 与前端依赖。",
    "docker/scripts/sync_model_catalog.py": "模型目录计划、应用、核验与回退；私有快照放入指定工作目录。",
    "docker/.gitignore": "部署私有 env、日志、用户目录、备份及 CI 生成数据的 Git 排除规则。",
    "docker/env/.gitkeep": "保留 env 目录的空占位；真实 app.env/storage.env 必须单独安全准备。",
    "docker/ci/env.example": "CI 测试矩阵默认变量样例，工作流复制为被忽略的 .env。",
    "docker/ci/compose.base.yml": "CI 的共享数据库、索引和对象存储服务定义。",
    "docker/ci/compose.python.yml": "CI 中 Python 后端的应用服务及测试挂载。",
    "docker/ci/compose.go.yml": "CI 中 Go 后端的应用服务及测试挂载。",
    "docker/config/env.example": "首次部署变量清单与凭据占位；init_env.py 按角色生成私有 env。",
    "docker/config/infinity.toml": "Infinity 索引引擎的节点、网络、日志与存储设置。",
    "docker/config/init.sql": "关系数据库初始化 SQL，供对应 Compose 数据库服务首次建库使用。",
    "docker/config/init-clickhouse.sql": "ClickHouse 初始化数据库 SQL，供 CI 的对应存储服务使用。",
    "docker/config/oceanbase/init.d/vec_memory.sql": "OceanBase 初始化时设置向量索引的内存参数。",
    "docker/config/service_conf.yaml.template": "91/92 挂载部署的服务配置模板；入口用 app.env 替换连接参数。",
    "docker/config/service_conf.ci.yaml.template": "CI 及完整构建的服务配置模板，覆盖测试矩阵中的多后端配置。",
    "docker/config/tongyi-sync-policy.json": "通义模型目录的能力映射、公告处理和同步策略。",
    "docker/config/nginx/nginx.conf": "Nginx 全局进程、日志、HTTP 与子配置加载设置。",
    "docker/config/nginx/proxy.conf": "Nginx 代理超时、请求头及转发参数。",
    "docker/config/nginx/ragflow.conf.python": "前端静态文件与 Python API/Admin 服务的 Nginx 路由。",
    "docker/config/nginx/ragflow.conf.golang": "Go 后端 API 与静态资源的 Nginx 路由。",
    "docker/config/nginx/ragflow.conf.hybrid": "Python/Go 混合后端的 Nginx 路由选择。",
    "docker/config/nginx/ragflow.https.conf": "HTTPS 站点、证书路径及反向代理配置样例。",
    "docker/runtime/entrypoint-go.sh": "Go 镜像的配置准备和服务进程启动入口。",
    "docker/runtime/launch_backend_service.sh": "源码开发方式启动 Python 服务的 Shell 入口。",
    "docker/runtime/oceanbase-entrypoint.sh": "OceanBase 容器引导与初始化 SQL 执行入口。",
    "docker/scripts/finalize_graph.py": "定点检查 Graph 产物并修复任务完成状态；默认只读，写操作需 --apply。",
    "docker/scripts/registry_bridge.py": "部署维护中使用的镜像仓库 HTTP 桥接辅助程序。",
    "docker/manifests/images.lock.json": "应用及存储镜像的版本、标签与身份核验记录。",
    "docker/manifests/patch-image.lock.json": "此前补丁镜像身份记录，供历史部署核查和回退。",
    "docker/manifests/runtime-image.lock.json": "运行环境最近一次构建的标签、config ID、基础镜像与构建主机记录。",
    "docker/manifests/deployment-20261029.json": "2026-10-29 目录重构后两机应用镜像和资源限制核验记录。",
    "docker/manifests/tongyi-catalog-20261026.json": "2026-10-26 通义模型下线处理的来源与模型清单。",
    "docs/operations.html": "含自动目录、浏览器编辑/保存功能的部署及容器内操作手册。",
    "docs/update.md": "按日期精炼记录问题、解决过程与验证结果。",
    "docs/project-structure.html": "本页：覆盖所有源码文件的完整递归职责索引及忽略产物恢复说明。",
    "scripts/project_inventory.py": "扫描 Git 源码清单、提取真实声明并生成本索引；--check 检测过期。",
    "scripts/source_manifest.py": "输出完整源码 SHA-256 清单用于三端比较；统一文本行尾，读取实际符号链接目标，不读取私有忽略文件。",
    "docker/manifests/dev-environment-20261029.json": "两台主机应用用户改造后的镜像身份、资源上限及干净源码离线依赖检查结果。",
    "scripts/fetch_deepdoc_testdata.sh": "拉取外部 DeepDOC 测试文档到缓存，并将测试路径链接到缓存；不参与应用启动。",
    "web/index.html": "Vite 前端 HTML 入口，提供根挂载节点并加载 TypeScript 应用。",
    "web/package.json": "前端 npm 依赖、脚本、Node 版本与包覆盖配置。",
    "web/package-lock.json": "前端 npm 精确依赖树与分发完整性锁定，供 npm ci 复现安装。",
    "web/.env.development": "Vite 开发模式的公开环境变量；不会自动进入生产模式。",
    "web/.env.production": "Vite 生产构建的公开环境变量；前端变量不能存放服务端密钥。",
    "web/.npmrc": "npm 安装和包管理行为配置。",
    "web/.gitignore": "前端依赖、构建输出与本地配置的 Git 排除规则。",
    "web/postcss.config.cjs": "PostCSS 构建插件配置，用于转换前端样式。",
    "web/jest-esbuild-transformer.cjs": "Jest 测试使用的 esbuild 源码转换器。",
    "web/jest-setup.ts": "前端 Jest 测试环境初始化、全局模拟与断言扩展。",
    "web/jest.config.ts": "前端测试发现、环境、模块别名与转换规则。",
    "web/tsconfig.json": "应用 TypeScript 编译器选项、模块解析及源码范围。",
    "web/tsconfig.node.json": "Vite/Node 配置文件使用的 TypeScript 编译检查选项。",
    "web/vite.config.ts": "Vite 开发/生产构建：插件、代理、打包与压缩策略。",
    "web/tailwind.config.js": "Tailwind 扫描范围、主题和组件样式扩展。",
}

RUNTIME = {
    "VERSION": ("忽略文件", "当前运行镜像的版本标记；入口从 /opt/ragflow-runtime/VERSION 补齐，不用于替代 Git 提交号。"),
    "9b5ad71b2ce5302211f9c61530b329a4922fc6a4": ("忽略文件", "cl100k_base.tiktoken 的本地 BPE 缓存；名称是编码下载 URL 的 SHA-1，不是 Git 提交或垃圾文件。common/token_utils.py 将工程根设为缓存目录；入口从镜像补齐，供离线分词。"),
    "tika-server-standard-3.3.0.jar": ("忽略文件", "Apache Tika Java 服务包，供 tika-python 离线解析；TIKA_SERVER_JAR 指向本文件。入口从运行镜像补齐，不能当无用文件删除。"),
    "tika-server-standard-3.3.0.jar.md5": ("忽略文件", "Tika JAR 配套 MD5 值，用于本地完整性校验；必须与 JAR 同版本。随镜像资源补齐。"),
    ".venv": ("生成目录", "Python 依赖环境；部署时由运行镜像填充按镜像 ID 命名的只读卷，宿主机不必预装。源码开发使用 uv sync --python 3.13 --all-extras 重建。"),
    "rag/res/deepdoc": ("生成目录", "OCR/布局/表格等 ONNX 模型与配套资源；运行镜像填充只读模型卷；源码构建由 ragflow_deps/download_deps.py 下载。"),
    "web/dist": ("生成目录", "前端编译产物；默认使用运行镜像的只读卷。修改前端后 npm ci && npm run build，再显式设置 APP_WEB_DIST 指向宿主产物。"),
    "web/node_modules": ("生成目录", "npm 依赖，npm ci 按 web/package-lock.json 重建；不作为源码同步。"),
    "docker/env/app.env": ("私有文件", "应用 IP/端口、镜像、资源上限及存储连接凭据。首次 init 生成；已有系统必须安全分发原配置，不得重新生成密码。"),
    "docker/env/storage.env": ("私有文件", "存储监听 IP 与 MySQL/Redis/MinIO/ES 凭据。与 app.env 成对；保存在存储主机，权限 600。"),
    "docker/state/service_conf.yaml": ("生成私有文件", "入口按配置模板和 app.env 渲染的运行配置；启动前创建文件，容器内单文件挂载。可重建，不提交密钥。"),
    "docker/home": ("持久目录", "应用用户的 .bashrc、.profile、.ragflow_env、.vimrc、命令历史和开发缓存，绑定 /home；env.sh 仅在文件不存在时创建，之后由用户自行管理。"),
    "docker/logs": ("运行目录", "API、Worker 等运行日志；按运行产生，缺失时可重建；含业务上下文，不发布。"),
    "docker/backups": ("私有目录", "数据库、存储和维护计划备份；必须独立保管，源码和镜像不能重建业务数据。"),
    "docker/evidence": ("私有目录", "现场诊断原始证据；按排障任务生成，不是启动依赖。"),
    "docker/ci/.env": ("生成文件", "CI 环境配置，由 docker/ci/env.example 复制并按测试矩阵设置；与生产私有 env 分开。"),
    "bin/*（除 .gitkeep）": ("生成文件", "Go/原生二进制，bash build.sh --go 或 --all 构建；当前 Python 部署依赖镜像提供对应卷，不能据此认为 Go 构建不需要原生库。"),
    "ragflow_deps/*.zip、huggingface.co/、nltk_data/、cl100k_base.tiktoken": ("下载产物", "离线依赖与模型下载结果，按 ragflow_deps/download_deps.py 下载清单恢复；完整源码镜像构建需要这些依赖或已构建的依赖镜像。"),
    "internal/deepdoc/parser/pdf/testdata、internal/deepdoc/native/testdata": ("测试资料", "外部文档样本或缓存链接，按 scripts/fetch_deepdoc_testdata.sh 获取；不参与当前 Python 应用启动。"),
    ".git": ("仓库元数据", "Git 对象、索引、引用及本地配置；非产品源码，内部对象不逐条列为工程文件。源码清单与软链接目标以 Git 索引为准。"),
    "__pycache__、.ruff_cache、.pytest_cache、.vscode、.idea、build、target": ("工具产物", "解释器/检查器缓存、个人 IDE 配置和构建输出；由各工具生成，不属于部署源码或业务数据。"),
}


def source_files():
    entries = {}
    data = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT)
    for item in data.decode().split("\0"):
        if item:
            metadata, path = item.split("\t", 1)
            if (ROOT / path).exists() or metadata.startswith("120000"):
                entries[path] = metadata.split()[0]
    for path in subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0"):
        if path and (ROOT / path).is_file():
            entries[path] = "100644"
    entries[OUTPUT.relative_to(ROOT).as_posix()] = "100644"
    return dict(sorted(entries.items()))


def context(path):
    parent = str(PurePosixPath(path).parent)
    while parent != ".":
        if parent in DIRECTORIES:
            return DIRECTORIES[parent]
        parent = str(PurePosixPath(parent).parent)
    return "工程根配置与工具"


def read_source(path, mode):
    if mode == "120000":
        return subprocess.check_output(["git", "show", ":" + path], cwd=ROOT).decode().strip()
    if path == "docs/project-structure.html":
        return ""
    data = (ROOT / path).read_bytes()
    if b"\0" in data[:8192] or len(data) > 3_000_000:
        return ""
    return data.decode("utf-8", errors="replace")


def declarations(path, source):
    names = []
    suffix = Path(path).suffix
    if suffix == ".py":
        try:
            tree = ast.parse(source)
            names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        except SyntaxError:
            pass
    elif suffix == ".go":
        names = re.findall(r"^(?:func\s+(?:\([^\n]+?\)\s+)?|type\s+)(\w+)", source, re.M)
    elif suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
        names = re.findall(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const)\s+(\w+)", source, re.M)
    elif suffix in {".cpp", ".h", ".hpp", ".rs"}:
        names = re.findall(r"\b(?:class|struct|enum|fn)\s+(\w+)", source)
    elif suffix == ".sh":
        names = re.findall(r"^(?:function\s+)?(\w+)\s*\(\)", source, re.M)
    return list(dict.fromkeys(names))[:12]


def source_summary(path, source, symbols):
    """Use authored comments as evidence, without treating them as instructions."""
    comment = ""
    if path.endswith(".py"):
        try:
            tree = ast.parse(source)
            comment = ast.get_docstring(tree) or ""
            if not comment:
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        comment = ast.get_docstring(node) or ""
                        if comment:
                            break
        except SyntaxError:
            pass
    elif path.endswith(".go") and symbols:
        match = re.search(r"^//\s*" + re.escape(symbols[0]) + r"\s+(.+)", source, re.M)
        if match:
            comment = symbols[0] + " " + match.group(1)
    if "copyright" in comment.lower() or "licensed under" in comment.lower():
        return ""
    return comment.strip().split("\n")[0][:220]


def describe(path, mode):
    source = read_source(path, mode)
    if mode == "120000":
        return f"符号链接 → {source}；复用目标内容，不维护第二份实现。", ""
    if path in FILES:
        return FILES[path], ""
    name, suffix = Path(path).name, Path(path).suffix.lower()
    owner = context(path)
    symbols = declarations(path, source)
    evidence = "声明：" + "、".join(symbols) if symbols else ""
    summary = source_summary(path, source, symbols)
    if summary:
        evidence = "源码说明：" + summary + (" ｜ " + evidence if evidence else "")
    stem = Path(path).stem
    if name == ".gitkeep":
        return "空目录占位，使 Git 保留所属目录；没有运行逻辑。", ""
    if name == "__init__.py":
        return f"{owner}：Python 包入口，组织导出与初始化。" if source.strip() else f"{owner}：空包标记。", evidence
    if "/testdata/" in path or "/fixtures/" in path or "/golden/" in path or suffix in {".pdf", ".docx", ".xlsx", ".doc", ".pptx", ".msg", ".eml"}:
        return f"{owner}：{name} 测试/示例输入或预期输出，供相邻解析与回归用例消费。", evidence
    if name.endswith("_test.go") or name.startswith("test_") or ".test." in name or ".spec." in name or name == "conftest.py":
        return f"{owner}：{stem} 的测试用例或测试夹具，校验下列行为。", evidence
    if suffix in {".md", ".mdx", ".rst", ".html"}:
        title = re.search(r"^#{1,3}\s+(.+)", source, re.M)
        if not title:
            title = re.search(r"<title>([^<]+)</title>", source)
        return f"{owner}：{title.group(1).strip() if title else stem} 说明、示例或参考资料。", ""
    if suffix == ".json":
        try:
            obj = json.loads(source)
            if isinstance(obj, dict):
                evidence = "顶层字段：" + "、".join(list(obj)[:12])
            elif isinstance(obj, list):
                evidence = f"结构：数组，{len(obj)} 项"
        except (ValueError, TypeError):
            pass
        return f"{owner}：{stem} 的结构化配置、DSL 或数据资源。", evidence
    if suffix in {".yml", ".yaml", ".toml", ".ini", ".conf", ".template", ".example", ".properties", ".cfg"} or name.startswith("Dockerfile"):
        return f"{owner}：{name} 配置/构建模板，定义所属工具或服务的参数。", evidence
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".wav"}:
        return f"{owner}：{stem} 图标、展示素材或媒体资源（{suffix[1:].upper()}）。", ""
    if suffix in {".css", ".scss", ".less"}:
        return f"{owner}：{stem} 的布局、颜色和组件样式。", ""
    if suffix in {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".h", ".hpp", ".rs", ".c", ".sh", ".mjs"}:
        role = "界面组件/页面" if suffix in {".tsx", ".jsx"} else "执行脚本" if suffix == ".sh" else "模块实现"
        return f"{owner}：{stem} {role}。", evidence
    if name.endswith("lock") or "lock." in name or suffix == ".sum":
        return f"{owner}：依赖版本与内容校验锁文件，保证工具按约定解析依赖。", ""
    if suffix == ".sql":
        return f"{owner}：{stem} 的 SQL 结构定义、初始化或查询脚本。", ""
    if suffix in {".txt", ".csv", ".tsv", ".dict", ".dic", ".pkl", ".bpe", ".tiktoken", ".jsonl"}:
        return f"{owner}：{name} 文本/词典/数据资源，由相邻代码或测试读取。", ""
    return f"{owner}：{name} 配套资源或工具输入；按所属模块消费。", evidence


def generate():
    files = source_files()
    tree = {}
    for path in files:
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = path
    directory_count = 0

    def render(node, parent=""):
        nonlocal directory_count
        result = ['<ul class="tree">']
        for name, value in sorted(node.items(), key=lambda item: (not isinstance(item[1], dict), item[0].lower())):
            path = f"{parent}/{name}".lstrip("/")
            escaped = html.escape(path, quote=True)
            if isinstance(value, dict):
                directory_count += 1
                description = DIRECTORIES.get(path, f"{context(path + '/_')}：{name} 子模块/资源集合；逐文件职责见下列条目。")
                result.append(f'<li data-path="{escaped}"><details id="{escaped}"{ " open" if not parent else ""}><summary><b>{html.escape(name)}/</b> <span>{html.escape(description)}</span></summary>{render(value, path)}</details></li>')
            else:
                desc, evidence = describe(path, files[path])
                result.append(f'<li class="file" data-path="{escaped}"><a href="../{escaped}">{html.escape(name)}</a> <span>{html.escape(desc)}</span>{"<small>" + html.escape(evidence) + "</small>" if evidence else ""}</li>')
        result.append("</ul>")
        return "\n".join(result)

    body = render(tree)
    runtime_rows = "\n".join(f"<tr><td><code>{html.escape(p)}</code></td><td>{kind}</td><td>{html.escape(desc)}</td></tr>" for p, (kind, desc) in RUNTIME.items())
    counts = Counter(p.split("/")[0] for p in files)
    navigation = " · ".join(f'<a href="#{html.escape(p)}">{html.escape(p)}/ ({counts[p]})</a>' for p in tree if isinstance(tree[p], dict))
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAGFlow 完整工程文件职责索引</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f8;color:#182a3b;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1500px;margin:auto;background:white;padding:32px}}h1{{font-size:30px}}a{{color:#006a8c}}header{{position:sticky;top:0;background:#fffef5;padding:12px;border-bottom:1px solid #c6d6df;z-index:1}}input{{width:min(650px,100%);padding:9px;font-size:16px}}button{{padding:9px;margin:4px}}nav{{line-height:2.2}}.tree{{list-style:none;padding-left:20px;margin:4px 0}}.tree .tree{{border-left:1px solid #dbe5eb}}li{{padding:4px 0;overflow-wrap:anywhere}}summary{{cursor:pointer}}summary span,.file span{{color:#435c6a;margin-left:12px}}.file a{{font-family:Consolas,monospace}}small{{display:block;color:#62747e;padding-left:16px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d9e2e8;padding:10px;text-align:left;vertical-align:top}}td:first-child{{width:27%;overflow-wrap:anywhere}}.note{{background:#edf5f8;padding:16px}}[hidden]{{display:none!important}}@media(max-width:700px){{main{{padding:15px}}.tree{{padding-left:12px}}summary span,.file span{{display:block;margin-left:8px}}}}@media print{{header{{position:static}}button,input{{display:none}}}}
</style></head><body><main>
<h1>RAGFlow 完整工程文件职责索引</h1>
<p>本页集中维护目录职责。源码树逐项列出 <strong id="file-count">{len(files)}</strong> 个文件、<strong>{directory_count}</strong> 个目录，包含隐藏配置、Python/Go/前端、测试资料及 Docker；无目录截断或“其余文件略”。</p>
<p>清单来自 Git 跟踪文件和未忽略的新文件。每个文件均有职责；“声明/字段”直接来自源文件，便于定位入口，不代表完整调用关系。符号链接读取 Git 中的目标，不递归展开同一资料。私有运行数据、第三方安装包内部、Git 对象与工具缓存不当作源码展开，其职责和恢复方式集中列在下表。</p>
<p><a href="operations.html">部署与可编辑操作手册</a> · <a href="update.md">工作日志</a> · <a href="../docker/README.md">Docker 命令说明</a></p>
<header><label for="search">搜索路径 / 职责 / 声明：</label> <input id="search" type="search" placeholder="例如 tika、docker/runtime、Embedding、UserService">
<button id="expand">展开全部</button><button id="collapse">折叠全部</button><span id="status" role="status"></span></header>
<h2 id="runtime">忽略文件、下载资源与部署恢复</h2>
<p class="note">Git 忽略不等于可以删除。当前挂载式部署需要：完整源码 + 已核验运行镜像 + 配套私有 env + 既有业务存储卷。镜像填充的依赖卷和入口生成文件可恢复；凭据与业务数据必须从受控备份恢复。新机器先 init、准备镜像，再 start；已有机器沿用原 env。主机 IP/内存配置应按角色不同，不能为了“代码一致”覆盖私有配置。</p>
<table><thead><tr><th>路径 / 文件</th><th>性质</th><th>职责与来源</th></tr></thead><tbody>{runtime_rows}</tbody></table>
<h2 id="source-tree">完整递归源码树</h2><nav>{navigation}</nav><section id="tree">{body}</section>
<h2>更新索引</h2><p>新增、删除或修改源码声明后，在工程根运行 <code>python scripts/project_inventory.py</code>；使用 <code>python scripts/project_inventory.py --check</code> 验证索引未过期。精确职责映射维护在生成器的 FILES/DIRECTORIES；请勿直接修改本生成页。</p>
</main><script>
const root=document.querySelector('#tree'), input=document.querySelector('#search'), status=document.querySelector('#status');
function filter(){{const term=input.value.toLowerCase().trim();let count=0;
for(const li of root.querySelectorAll('li.file')){{const match=!term||(li.dataset.path+' '+li.textContent).toLowerCase().includes(term);li.hidden=!match;if(match)count++;}}
for(const details of [...root.querySelectorAll('details')].reverse()){{const visible=[...details.querySelectorAll('li.file')].some(li=>!li.hidden);details.parentElement.hidden=!visible;if(term)details.open=visible;}}
status.textContent=term?`匹配 ${{count}} 个源码文件`:'';}}
input.addEventListener('input',filter);
document.querySelector('#expand').onclick=()=>root.querySelectorAll('details').forEach(d=>d.open=true);
document.querySelector('#collapse').onclick=()=>root.querySelectorAll('details').forEach(d=>d.open=false);
window.addEventListener('hashchange',()=>{{const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(target){{for(let p=target;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView();}}}});
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = generate()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != output:
            raise SystemExit("File inventory is stale; run python scripts/project_inventory.py")
        print("Complete source inventory is current")
    else:
        OUTPUT.write_text(output, encoding="utf-8", newline="\n")
        print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()

> 本工程部署与二次开发请先阅读 [Docker 目录说明](docker/README.md) 和 [操作手册](docs/operations.html)。应用通过宿主机工程挂载运行。

<div align="center">
<a href="https://cloud.ragflow.io/">
<img src="https://raw.githubusercontent.com/infiniflow/ragflow/main/web/src/assets/logo-with-text.svg" width="520" alt="ragflow logo">
</a>
</div>

<p align="center">
  <a href="./README.md"><img alt="README in English" src="https://img.shields.io/badge/English-DFE0E5"></a>
  <a href="./README_zh.md"><img alt="简体中文版自述文件" src="https://img.shields.io/badge/简体中文-DBEDFA"></a>
  <a href="./README_tzh.md"><img alt="繁體版中文自述文件" src="https://img.shields.io/badge/繁體中文-DFE0E5"></a>
  <a href="./README_ja.md"><img alt="日本語のREADME" src="https://img.shields.io/badge/日本語-DFE0E5"></a>
  <a href="./README_ko.md"><img alt="한국어" src="https://img.shields.io/badge/한국어-DFE0E5"></a>
  <a href="./README_fr.md"><img alt="README en Français" src="https://img.shields.io/badge/Français-DFE0E5"></a>
  <a href="./README_id.md"><img alt="Bahasa Indonesia" src="https://img.shields.io/badge/Bahasa Indonesia-DFE0E5"></a>
  <a href="./README_pt_br.md"><img alt="Português(Brasil)" src="https://img.shields.io/badge/Português(Brasil)-DFE0E5"></a>
  <a href="./README_ar.md"><img alt="README in Arabic" src="https://img.shields.io/badge/Arabic-DFE0E5"></a>
  <a href="./README_tr.md"><img alt="Türkçe README" src="https://img.shields.io/badge/Türkçe-DFE0E5"></a>
  <a href="./README_ru.md"><img alt="Русская версия README" src="https://img.shields.io/badge/Русский-DFE0E5"></a>
</p>

<p align="center">
    <a href="https://x.com/intent/follow?screen_name=infiniflowai" target="_blank">
        <img src="https://img.shields.io/twitter/follow/infiniflow?logo=X&color=%20%23f5f5f5" alt="follow on X(Twitter)">
    </a>
    <a href="https://cloud.ragflow.io" target="_blank">
        <img alt="Static Badge" src="https://img.shields.io/badge/Get-Started-4e6b99">
    </a>
    <a href="https://hub.docker.com/r/infiniflow/ragflow" target="_blank">
        <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/infiniflow/ragflow-stats/main/badges/docker-pulls.json&style=flat-square&logo=docker&logoColor=white" alt="docker pull infiniflow/ragflow:v0.27.2">
    </a>
    <a href="https://github.com/infiniflow/ragflow/releases/latest">
        <img src="https://img.shields.io/github/v/release/infiniflow/ragflow?color=blue&label=Latest%20Release" alt="Latest Release">
    </a>
    <a href="https://github.com/infiniflow/ragflow/blob/main/LICENSE">
        <img height="21" src="https://img.shields.io/badge/License-Apache--2.0-ffffff?labelColor=d4eaf7&color=2e6cc4" alt="license">
    </a>
    <a href="https://deepwiki.com/infiniflow/ragflow">
        <img alt="Ask DeepWiki" src="https://deepwiki.com/badge.svg">
    </a>
</p>

<h4 align="center">
  <a href="https://cloud.ragflow.io">Cloud</a> |
  <a href="https://ragflow.io/docs/dev/">Document</a> |
  <a href="https://github.com/infiniflow/ragflow/issues/12241">Roadmap</a> |
  <a href="https://discord.gg/NjYzJD3GM3">Discord</a>
</h4>

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="RAGFlow in the GitHub Octoverse" src="https://raw.githubusercontent.com/infiniflow/ragflow-docs/refs/heads/image/image/ragflow-octoverse.png" width="1200"/>
</div>

<div align="center">
<a href="https://trendshift.io/repositories/9064" target="_blank"><img src="https://trendshift.io/api/badge/repositories/9064" alt="infiniflow%2Fragflow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</div>

<details open>
<summary><b>📕 目录</b></summary>

- 💡 [RAGFlow 是什么？](#-RAGFlow-是什么)
- 🎮 [快速开始](#-快速开始)
- 📌 [近期更新](#-近期更新)
- 🌟 [主要功能](#-主要功能)
- 🔎 [系统架构](#-系统架构)
- 🎬 [自主托管](#-自主托管)
- 🔧 [系统配置](#-系统配置)
- 🔨 [以源代码启动服务](#-以源代码启动服务)
- 📚 [技术文档](#-技术文档)
- 📜 [路线图](#-路线图)
- 🏄 [贡献指南](#-贡献指南)
- 🙌 [加入社区](#-加入社区)
- 🤝 [商务合作](#-商务合作)

</details>

## 💡 RAGFlow 是什么？

[RAGFlow](https://ragflow.io/) 是一款领先的开源检索增强生成（[RAG](https://ragflow.io/basics/what-is-rag)）引擎，通过融合前沿的 RAG 技术与 Agent 能力，为大型语言模型提供卓越的上下文层。它提供可适配任意规模企业的端到端 RAG 工作流，凭借融合式[上下文引擎](https://ragflow.io/basics/what-is-agent-context-engine)与预置的 Agent 模板，助力开发者以极致效率与精度将复杂数据转化为高可信、生产级的人工智能系统。

## 🎮 快速开始

请登录网址 [https://cloud.ragflow.io](https://cloud.ragflow.io) 体验云服务。

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="Chunking demonstration" src="https://raw.githubusercontent.com/infiniflow/ragflow-docs/refs/heads/image/image/chunking.gif" width="1200"/>
<img alt="Agentic workflow demonstration" src="https://raw.githubusercontent.com/infiniflow/ragflow-docs/refs/heads/image/image/agentic-dark.gif" width="1200"/>
</div>

## 🔥 近期更新

- 2026-06-15 支持飞书、Discord、Telegram、Line 等多种聊天渠道。
- 2026-04-24 支持 DeepSeek v4.
- 2026-03-24 发布 [RAGFlow 官方 Skill](https://clawhub.ai/yingfeng/ragflow-skill) — 提供官方 Skill 以通过 OpenClaw 访问 RAGFlow 数据集。
- 2025-12-26 支持 AI 代理的"记忆"功能。
- 2025-11-19 支持 Gemini 3 Pro。
- 2025-11-12 支持从 Confluence、S3、Notion、Discord、Google Drive 进行数据同步。
- 2025-10-23 支持 MinerU 和 Docling 作为文档解析方法。
- 2025-10-15 支持可编排的数据管道。
- 2025-08-08 支持 OpenAI 最新的 GPT-5 系列模型。
- 2025-08-01 支持 agentic workflow 和 MCP。
- 2025-05-23 Agent 新增 Python/JS 代码执行器组件。
- 2025-03-19 PDF 和 DOCX 中的图支持用多模态大模型去解析得到描述。


## 🎉 关注项目

⭐️ 点击右上角的 Star 关注 RAGFlow，可以获取最新发布的实时通知 !🌟

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="RAGFlow feature updates" src="https://github.com/user-attachments/assets/18c9707e-b8aa-4caf-a154-037089c105ba" width="1200"/>
</div>

## 🌟 主要功能

### 🍭 **"Quality in, quality out"**

- 基于[深度文档理解](./deepdoc/README.md)，能够从各类复杂格式的非结构化数据中提取真知灼见。
- 真正在无限上下文（token）的场景下快速完成大海捞针测试。

### 🍱 **基于模板的文本切片**

- 不仅仅是智能，更重要的是可控可解释。
- 多种文本模板可供选择

### 🌱 **有理有据、最大程度降低幻觉（hallucination）**

- 文本切片过程可视化，支持手动调整。
- 有理有据：答案提供关键引用的快照并支持追根溯源。

### 🍔 **兼容各类异构数据源**

- 支持丰富的文件类型，包括 Word 文档、PPT、excel 表格、txt 文件、图片、PDF、影印件、复印件、结构化数据、网页等。

### 🛀 **全程无忧、自动化的 RAG 工作流**

- 全面优化的 RAG 工作流可以支持从个人应用乃至超大型企业的各类生态系统。
- 大语言模型 LLM 以及向量模型均支持配置。
- 基于多路召回、融合重排序。
- 提供易用的 API，可以轻松集成到各类企业系统。

## 🔎 系统架构

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="RAGFlow system architecture" src="https://github.com/user-attachments/assets/31b0dd6f-ca4f-445a-9457-70cb44a381b2" width="1000"/>
</div>

## 🎬 自主托管

本工程的分离部署、单机部署、工程挂载和配置统一见 [Docker 目录说明](docker/README.md) 与 [操作手册](docs/operations.html)。

## 🔧 系统配置

本工程的分离部署、单机部署、工程挂载和配置统一见 [Docker 目录说明](docker/README.md) 与 [操作手册](docs/operations.html)。

## 🔧 源码编译 Docker 镜像

See [Docker build commands](docker/README.md) and the [operations manual](docs/operations.html). Runtime deployments bind-mount the checkout.

```bash
bash docker/docker.sh build runtime
# Full dependency/frontend build:
bash docker/docker.sh build source ragflow-local:my-release
```

## 🔨 以源代码启动服务

See [development from source](docs/develop/launch_ragflow_from_source.md). The deployed application reads the mounted checkout; reload Python changes with `bash docker/docker.sh restart app`.

## 📚 技术文档

- [Quickstart](https://ragflow.io/docs/dev/)
- [Configuration](https://ragflow.io/docs/dev/configurations)
- [Release notes](https://ragflow.io/docs/dev/release_notes)
- [User guides](https://ragflow.io/docs/category/user-guides)
- [Developer guides](https://ragflow.io/docs/category/developer-guides)
- [References](https://ragflow.io/docs/dev/category/references)
- [FAQs](https://ragflow.io/docs/dev/faq)

## 📜 路线图

详见 [RAGFlow Roadmap 2026](https://github.com/infiniflow/ragflow/issues/12241) 。

## 🏄 开源社区

- [Discord](https://discord.gg/NjYzJD3GM3)
- [X](https://x.com/infiniflowai)
- [GitHub Discussions](https://github.com/orgs/infiniflow/discussions)

## 🙌 贡献指南

RAGFlow 只有通过开源协作才能蓬勃发展。秉持这一精神,我们欢迎来自社区的各种贡献。如果您有意参与其中,请查阅我们的 [贡献者指南](https://ragflow.io/docs/dev/contributing) 。

## 🤝 商务合作

- [预约咨询](https://aao615odquw.feishu.cn/share/base/form/shrcnjw7QleretCLqh1nuPo1xxh)

## 👥 加入社区

扫二维码添加 RAGFlow 小助手，进 RAGFlow 交流群。

<p align="center">
  <img alt="RAGFlow assistant QR code" src="https://github.com/infiniflow/ragflow/assets/7248/bccf284f-46f2-4445-9809-8f1030fb7585" width=50% height=50%>
</p>

> 本工程部署与二次开发请先阅读 [Docker 目录说明](docker/README.md) 和 [操作手册](docs/operations.html)。应用通过宿主机工程挂载运行。

<div align="center">
<a href="https://cloud.ragflow.io/">
<img src="https://raw.githubusercontent.com/infiniflow/ragflow/main/web/src/assets/logo-with-text.svg" width="520" alt="ragflow logo">
</a>
</div>

<p align="center">
  <a href="./README.md"><img alt="README in English" src="https://img.shields.io/badge/English-DBEDFA"></a>
  <a href="./README_zh.md"><img alt="简体中文版自述文件" src="https://img.shields.io/badge/简体中文-DFE0E5"></a>
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
  <a href="https://ragflow.io/docs/dev/">Documentation</a> |
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
<summary><b>📕 Table of Contents</b></summary>

- 💡 [What is RAGFlow?](#-what-is-ragflow)
- 🎮 [Get Started](#-get-started)
- 🔥 [Latest Updates](#-latest-updates)
- 🌟 [Key Features](#-key-features)
- 🔎 [System Architecture](#-system-architecture)
- 🎬 [Self-Hosting](#-self-hosting)
- 🔧 [Configurations](#-configurations)
- 🔧 [Build a Docker Image](#-build-a-docker-image)
- 🔨 [Launch Service from Source for Development](#-launch-service-from-source-for-development)
- 📚 [Documentation](#-documentation)
- 📜 [Roadmap](#-roadmap)
- 🏄 [Community](#-community)
- 🙌 [Contributing](#-contributing)

</details>

> Local project guides: [Operations](docs/operations.html) · [Complete file inventory](docs/project-structure.html) · [Docker deployment](docker/README.md)

## 💡 What is RAGFlow?

[RAGFlow](https://ragflow.io/) is a leading open-source Retrieval-Augmented Generation ([RAG](https://ragflow.io/basics/what-is-rag)) engine that fuses cutting-edge RAG with Agent capabilities to create a superior context layer for LLMs. It offers a streamlined RAG workflow adaptable to enterprises of any scale. Powered by a converged [context engine](https://ragflow.io/basics/what-is-agent-context-engine) and pre-built agent templates, RAGFlow enables developers to transform complex data into high-fidelity, production-ready AI systems with exceptional efficiency and precision.

## 🎮 Get Started

Try our cloud service at [https://cloud.ragflow.io](https://cloud.ragflow.io).

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="Chunking demonstration" src="https://raw.githubusercontent.com/infiniflow/ragflow-docs/refs/heads/image/image/chunking.gif" width="1200"/>
<img alt="Agentic workflow demonstration" src="https://raw.githubusercontent.com/infiniflow/ragflow-docs/refs/heads/image/image/agentic-dark.gif" width="1200"/>
</div>

## 🔥 Latest Updates

- 2026-06-15 Support multiple chat channels such as Feishu, Discord, Telegram, Line, etc.
- 2026-04-24 Supports DeepSeek v4.
- 2026-03-24 [RAGFlow Skill on OpenClaw](https://clawhub.ai/yingfeng/ragflow-skill) — Provides an official skill for accessing RAGFlow datasets via OpenClaw.
- 2025-12-26 Supports 'Memory' for AI agent.
- 2025-11-19 Supports Gemini 3 Pro.
- 2025-11-12 Supports data synchronization from Confluence, S3, Notion, Discord, Google Drive.
- 2025-10-23 Supports MinerU & Docling as document parsing methods.
- 2025-10-15 Supports orchestrable ingestion pipeline.
- 2025-08-08 Supports OpenAI's latest GPT-5 series models.
- 2025-08-01 Supports agentic workflow and MCP.
- 2025-05-23 Adds a Python/JavaScript code executor component to Agent.
- 2025-03-19 Supports using a multi-modal model to make sense of images within PDF or DOCX files.

## 🎉 Stay Tuned

⭐️ Star our repository to stay up-to-date with exciting new features and improvements! Get instant notifications for new
releases! 🌟

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="RAGFlow feature updates" src="https://github.com/user-attachments/assets/18c9707e-b8aa-4caf-a154-037089c105ba" width="1200"/>
</div>

## 🌟 Key Features

### 🍭 **"Quality in, quality out"**

- [Deep document understanding](./deepdoc/README.md)-based knowledge extraction from unstructured data with complicated
  formats.
- Finds "needle in a data haystack" of literally unlimited tokens.

### 🍱 **Template-based chunking**

- Intelligent and explainable.
- Plenty of template options to choose from.

### 🌱 **Grounded citations with reduced hallucinations**

- Visualization of text chunking to allow human intervention.
- Quick view of the key references and traceable citations to support grounded answers.

### 🍔 **Compatibility with heterogeneous data sources**

- Supports Word, Slides, Excel, TXT, images, scanned copies, structured data, web pages, and more.

### 🛀 **Automated and effortless RAG workflow**

- Streamlined RAG orchestration catered to both personal and large businesses.
- Configurable LLMs as well as embedding models.
- Multiple recall paired with fused re-ranking.
- Intuitive APIs for seamless integration with business.

## 🔎 System Architecture

<div align="center" style="margin-top:20px;margin-bottom:20px;">
<img alt="RAGFlow system architecture" src="https://github.com/user-attachments/assets/31b0dd6f-ca4f-445a-9457-70cb44a381b2" width="1000"/>
</div>

## 🎬 Self-Hosting

For this checkout, follow [Docker deployment](docker/README.md) and the [operations manual](docs/operations.html) for split or single-host deployment, source mounts, and configuration.

## 🔧 Configurations

For this checkout, follow [Docker deployment](docker/README.md) and the [operations manual](docs/operations.html) for split or single-host deployment, source mounts, and configuration.

## 🔧 Build a Docker Image

See [Docker build commands](docker/README.md) and the [operations manual](docs/operations.html). Runtime deployments bind-mount the checkout.

```bash
bash docker/docker.sh build runtime
# Full dependency/frontend build:
bash docker/docker.sh build source ragflow-local:my-release
```

## 🔨 Launch Service from Source for Development

See [development from source](docs/develop/launch_ragflow_from_source.md). The deployed application reads the mounted checkout; reload Python changes with `bash docker/docker.sh restart app`.

## 📚 Documentation

- [Quickstart](https://ragflow.io/docs/dev/)
- [Configuration](https://ragflow.io/docs/dev/configurations)
- [Release notes](https://ragflow.io/docs/dev/release_notes)
- [User guides](https://ragflow.io/docs/category/user-guides)
- [Developer guides](https://ragflow.io/docs/category/developer-guides)
- [References](https://ragflow.io/docs/dev/category/references)
- [FAQs](https://ragflow.io/docs/dev/faq)

## 📜 Roadmap

See the [RAGFlow Roadmap 2026](https://github.com/infiniflow/ragflow/issues/12241)

## 🏄 Community

- [Discord](https://discord.gg/NjYzJD3GM3)
- [X](https://x.com/infiniflowai)
- [GitHub Discussions](https://github.com/orgs/infiniflow/discussions)

## 🙌 Contributing

RAGFlow flourishes via open-source collaboration. In this spirit, we embrace diverse contributions from the community.
If you would like to be a part, review our [Contribution Guidelines](https://ragflow.io/docs/dev/contributing) first.

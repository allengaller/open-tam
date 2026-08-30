# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

纯静态 HTML/CSS/JS（单页，零构建依赖，可部署 GitHub Pages 等静态托管）。用户确认；仓库本体为 Python，无前端构建链，GTM/ 文件夹自包含。

## Users

- 首要受众：TAM（Technical Account Manager）/ SRE 及相关岗位（运维工程师、平台工程师）。场景：被告警驱动的重复排查（查指标 → 翻日志 → 定位 → 写报告）消耗大量时间；夜间 on-call；TAM 在客户现场做故障响应与复盘。
- 访客看完应完成的动作（推断，未逐字确认）：认同「告警进 → 根因报告出」的价值，去仓库跑无 Key 演示（快速开始 / 查看源码）。

## Product Purpose

open-tam 是基于 AgentScope + MCP 的多 Agent SRE 排障系统：告警进来，自动查指标、翻日志，产出结构化根因报告（结论摘要 + 异常清单 + 建议动作）；排查过程每步思考/工具调用/观察落盘为结构化语料（JSONL trace），可回流语料库沉淀 Skill。对标阿里云 SREAgent 平台能力。

## Positioning

三个相邻产品无法照抄的机制：

1. **排查即语料**——每次排查全程落盘为结构化 trace 与报告，是可评测、可复用的资产，不是一次性对话。
2. **MCP 工具总线**——query_metrics / query_logs 签名固定，mock 与真实后端（alibabacloud-observability / SLS）互换零改动。
3. **护栏前置**——命令白名单 + dry-run + 敏感操作人工确认 + 审计日志。

## Operating Context

- 交付形态：CLI 先行（`open-tam` 命令），M4 补轻量 Web UI；本页面是该项目的 Go-To-Market 落地页，输出到 `GTM/`。
- 模型：DashScope Qwen（主备自动切换，默认 qwen-plus/qwen-turbo）；无 Key 演示用 FakeChatModel 闭环。
- 数据源：先 mock 后实盘（M5 接云监控 webhook + alibabacloud-observability MCP；SLS 日志）。
- 故障模式注册表（同时是评测集）：cpu_spike / slow_query / oom / connection_pool_exhausted。
- 演进路线：M0 骨架 → M1 排查闭环 → M2 多 Agent + 语料 → M3 护栏 + 巡检 → M4 Web UI → M5 实盘接入 →（K8sGPT · ACS Sandbox · OpenSRE 式评测）。

## Capabilities and Constraints

- 已实现（M0–M2）：告警注入 → ReAct 排查 → 指标/日志双证据 → 三段式根因报告落盘 `reports/`；trace 落盘 `traces/*.jsonl`；M2 多子 Agent（orchestrator + metric-agent + log-agent）。
- 术语：AlertEvent（对齐云监控告警格式）、排查闭环、故障注入（`fault inject/clear/list`）、根因命中率 / 平均步数 / token 成本（评测指标）。
- 非目标（MVP 外）：K8s / K8sGPT、ACS Sandbox、告警风暴抑制、多租户、数据库持久化。
- 评测维度存在但尚无公开数字：不得编造根因命中率、性能、客户数等任何商业/事实主张。

## Brand Commitments

- 名称：open-tam（小写，产品名保留英文）。
- 无 logo、无配色承诺、无既有视觉资产；GTM 页是新视觉世界的起点。

## Evidence on Hand

- README.md 快速开始（uv sync / pytest / 无 Key 演示 / DashScope 真实模型）。
- docs/architecture.md 架构一页纸（mermaid 图、mock→实盘替换路径表、演进路线）。
- docs/superpowers/specs/2026-08-28-sre-agent-design.md 设计文档（已确认）。
- M1 真实模型验收通过（DashScope qwen-plus 排查闭环）；M2 多 Agent + 语料落盘进行中（feat/m2-multi-agent 分支）。
- demo_app/：被诊断对象 FastAPI 应用（/health /metrics /faults）。
- 无真实客户、无基准测试数字、无现成截图资产——页面演示数据可由仓库事实合成并标注为演示；不得虚构商业主张。

## Product Principles

1. 排查即语料：排查过程本身是资产（trace → 语料库 → Skill）。
2. 大脑与手脚分离：编排层只推理，数据获取全走 MCP。
3. 护栏前置：白名单 + dry-run + 人工确认 + 审计，先于自主性。
4. mock 先行、实盘可换：固定签名让 mock 与真实后端互换零改动。

## Accessibility & Inclusion

- 未确认特殊需求；按 WCAG AA 常规执行（对比度、键盘可达、语义化标签）。

## Open decisions

- CTA 目标链接（GitHub 仓库 URL / 演示入口）未确认：页面上用占位，交付时列入替换清单。
- 域名/部署目标未确认（静态托管即可）。

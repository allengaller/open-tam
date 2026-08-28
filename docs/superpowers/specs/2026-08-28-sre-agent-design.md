# open-tam SRE Agent 设计文档

- 日期：2026-08-28
- 状态：已确认（用户批准后实施）

## 1. 背景与目标

复刻一个生产级 SRE Agent（对标阿里云 SREAgent 平台能力），基于 AgentScope + MCP 协议构建，双主线并行：

1. **排查闭环作品**：合成告警 → 全自动多 Agent 排查 → 结构化根因报告，全程可演示。
2. **语料工程主线**：排查过程（每步思考/工具调用/观察）结构化落盘，报告与 trace 均为语料资产，可回流工单语料库并沉淀为 Skill。

成功标准：预埋故障模式下，Agent 自动产出根因命中的报告；根因命中率、平均步数、token 成本可统计。

## 2. 已确认决策

| 决策点 | 结论 |
|---|---|
| 交付物 | 架构一页纸（docs/architecture.md）+ MVP 分阶段清单（docs/mvp-plan.md） |
| 数据源 | 先 mock 后实盘；M5 接云监控 webhook + alibabacloud-observability MCP |
| K8s / K8sGPT | 不进 MVP，后期引入（kind/minikube 或 ACK） |
| 交互形态 | CLI 先行，M4 补轻量 Web UI（FastAPI + 单页聊天） |
| 技术路线 | 方案 A：AgentScope 单进程多 Agent + MCP 工具总线 |
| 模型 | DashScope Qwen，配置主备模型自动切换；测试使用假模型 |
| 沙箱 | MVP 用命令白名单 + dry-run + 人工确认；ACS Agent Sandbox 后期升级 |
| 假设 | Python 3.12（uv 管理虚拟环境）；包名 `open_tam` |

## 3. 架构

### 3.1 组件

| 组件 | 职责 | 依赖 |
|---|---|---|
| `orchestrator` | 运维专家 Agent（AgentScope ReActAgent）：接告警 → 排查计划 → 调度工具/子 Agent → 汇总报告 | AgentScope、DashScope |
| `alert-receiver` | 告警入口：CLI 注入 + HTTP webhook，标准化为 AlertEvent | FastAPI（webhook 模式） |
| `mock-metrics-mcp-server` | 合成时序指标，内置预埋故障模式 | mcp (FastMCP) |
| `mock-logs-mcp-server` | 结构化日志查询，与故障模式联动 | mcp (FastMCP) |
| `metric-agent` / `log-agent` | 数据查询子 Agent。MVP v1 以工具形式被专家直接调用，M2 升级为独立子 Agent 协作 | AgentScope |
| `guardrails` | 命令白名单、dry-run 预览、敏感操作人工确认、审计日志 | — |
| `reporting` | 结构化根因报告生成（结论摘要 + 异常清单 + 建议动作），Markdown 落盘 | — |
| `tracing` | 每步思考/工具调用/观察以 JSONL 落盘，供语料回溯 | — |
| `demo-app` | 被诊断对象：简单 Web 服务 + 故障注入脚本，mock 数据与它联动 | FastAPI |
| CLI | 交互入口（M0 起） | typer |

### 3.2 MCP 工具接口（mock 与真实实现共用签名）

```
query_metrics(metric: str, service: str, start: str, end: str) -> 时序点列表
query_logs(service: str, start: str, end: str, level: str | None, keyword: str | None) -> 日志记录列表
```

### 3.3 数据契约

- `AlertEvent`：`alert_id, alert_name, severity, service, metric, threshold, current_value, triggered_at, labels`，字段对齐云监控告警格式。
- 报告输出：`reports/<date>-<alert-id>.md`，三段结构：结论摘要、异常清单、建议动作。
- trace 输出：`traces/<alert-id>.jsonl`，每行一个步骤事件。

### 3.4 故障模式注册表（同时是评测集）

`cpu_spike` / `slow_query` / `oom` / `connection_pool_exhausted`，每项定义：指标异常特征 + 日志特征 + 根因 + 建议动作。

## 4. 数据流

1. 告警注入 → `alert-receiver` 标准化为 `AlertEvent`。
2. orchestrator 收到告警 → ReAct 循环制定排查计划。
3. 通过 MCP 调 `query_metrics` 确认异常 → 需要现场证据时调 `query_logs`，观察结果进入下一轮思考。
4. 满足停止条件（根因明确 / 步数上限）→ 生成结构化报告写入 `reports/`。
5. 每步思考/工具调用/观察全程落盘为结构化 trace。

## 5. 错误处理

| 故障点 | 策略 |
|---|---|
| 模型调用失败 | AgentScope 主备模型自动切换 + 重试退避 |
| MCP 工具超时/报错 | 失败信息作为观察继续规划；连续 3 次失败降级输出"已排除项 + 数据不可用" |
| 排查发散 | 最大步数 15 + token 预算双重上限，超限强制收敛为"未定位根因报告" |
| 告警风暴 | MVP 串行队列处理，不合并去重 |
| 危险命令 | 白名单外直接拒绝并记录审计日志 |

## 6. 测试策略

1. **单元测试**（pytest）：mock MCP 数据生成、AlertEvent 标准化、护栏白名单逻辑。
2. **集成测试**：每个预埋故障模式跑一次完整排查，断言报告产出且根因命中（LLM 用假模型）。
3. **行为评测**：故障模式注册表即评测集，统计根因命中率 / 平均步数 / token 成本。
4. **手动验收**：CLI / 浏览器端到端演示。

## 7. MVP 里程碑概览

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| M0 骨架 | 项目初始化 + demo-app + mock-metrics-mcp + CLI | CLI 查一次指标返回数据 |
| M1 闭环 | alert-receiver + orchestrator ReAct 排查（query_metrics 工具，query_logs 随 M2 接入）→ 报告落盘 | 注入 CPU 飙升故障，全自动产出根因报告 |
| M2 多 Agent + 语料 | log 子 Agent 协作 + trace 结构化落盘 | 慢查询故障用上日志证据，报告含三段结构 |
| M3 护栏 + 巡检 | 白名单 / dry-run / 审计 + 定时巡检 | 危险命令被拦截可审计，巡检报告按时生成 |
| M4 Web UI | FastAPI + 单页聊天 | 浏览器发起排查并看到流式过程 |
| M5 实盘接入 | 云监控 webhook + alibabacloud-observability MCP | 一条真实告警跑通闭环 |

## 8. 非目标（MVP 范围外）

- K8s 集群与 K8sGPT 接入
- ACS Agent Sandbox 隔离执行
- 告警合并、风暴抑制、多租户
- 数据库持久化（报告/trace 用文件系统）

## 9. 后期演进

M5 实盘接入 → K8sGPT（kind/ACK）→ ACS Agent Sandbox → OpenSRE 式评测扩展 → 排查语料回流、沉淀为可复用 Skill。

# open-tam · SRE Agent MVP 分阶段清单

> 每个阶段独立可验收。详细设计见 `docs/superpowers/specs/2026-08-28-sre-agent-design.md`，架构图见 `docs/architecture.md`。

## M0 骨架

- [x] 项目脚手架（uv + pyproject + pytest）
- [x] 数据模型：AlertEvent / MetricPoint / LogRecord
- [x] `demo-app`：简单 Web 服务 + 故障注入（cpu_spike 可注入）
- [x] `mock-metrics-mcp-server`：故障模式联动时序数据（cpu_spike 模式）
- [x] CLI：`open-tam metrics query` 直连 MCP 查指标
- **验收**：`open-tam metrics query` 返回注入故障前后的指标序列 ✅（2026-08-28，inline 与 MCP 双后端输出一致）

## M1 排查闭环

- [x] `alert-receiver`：CLI 告警注入 + AlertEvent 标准化
- [x] `orchestrator`：AgentScope ReActAgent 排查循环（M1 仅挂 query_metrics，query_logs 随 M2 接入）
- [x] `reporting`：结构化报告生成落盘 `reports/`
- [x] 主备模型配置（DashScope Qwen）+ 步数/token 双上限
- **验收**：注入 CPU 飙升故障 → 全自动产出根因报告 ✅（2026-08-28，--fake 路径与真实模型路径均已验证；真实路径经 DashScope qwen-plus 两轮工具调用收敛，报告含证据与排除项）

## M2 多 Agent + 语料

- [x] `mock-logs-mcp-server`（slow_query 模式日志）
- [x] `metric-agent` / `log-agent` 升级为独立子 Agent 协作
- [x] `tracing`：每步思考/工具调用/观察 JSONL 落盘（含子 Agent 内部步骤，agent 字段区分）
- [x] 故障模式扩充：slow_query / oom / connection_pool_exhausted
- **验收**：慢查询故障排查引用日志证据；报告含三段结构；trace 可回放 ✅（2026-08-29，真实模型路径：log 子 Agent 迭代查询命中慢查询日志签名，根因精确引用 SQL 原文；trace 含三 Agent 完整委托链）

## M3 护栏 + 巡检

- [x] `guardrails`：命令白名单 + dry-run 预览 + 敏感操作人工确认
- [x] 审计日志 `audit.log`
- [x] 定时巡检任务（阈值巡检，输出巡检报告）
- [x] orchestrator 接入 `execute_action`（agent 路径 safe 动作可执行、敏感动作自动拒绝）
- **验收**：白名单外命令被拦截且审计可查；巡检报告按时生成 ✅（2026-08-31，见验收记录）

## M4 Web UI

- [ ] FastAPI 服务 + 单页聊天界面
- [ ] 排查过程流式展示（步骤/工具调用实时可见）
- **验收**：浏览器发起排查并看到流式过程

## M5 实盘接入

- [ ] 云监控 webhook 告警接入
- [ ] alibabacloud-observability MCP 替换 mock 后端
- [ ] （可选）K8sGPT + kind 集群排障
- [ ] （可选）ACS Agent Sandbox 隔离执行
- **验收**：一条真实告警跑通完整闭环

## 行为评测（随 M2 起持续）

- 评测集 = 故障模式注册表
- 指标：根因命中率 / 平均步数 / token 成本
- 对标 OpenSRE 的 Planner + Sub-Agent 评估思路

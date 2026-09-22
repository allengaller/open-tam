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
- **验收**：白名单外命令被拦截且审计可查；巡检报告按时生成 ✅（2026-08-31，`action run deploy_to_prod` 返回 `{"denied": true, "reason": "白名单外动作: deploy_to_prod"}` 且 audit 记录 decision=denied；clear_fault --dry-run 输出预览未实际执行；rollback_release --yes 走人工确认输出 simulated；patrol run 产出巡检报告含 cpu_spike 异常（峰值 92.0 超阈值 45.0）与异常跟进段；fake 路径 investigate 全流程回归无异常；全量 92 passed + 1 skipped）

## M4 Web UI

- [x] FastAPI 服务 + 单页聊天界面
- [x] 排查过程流式展示（步骤/工具调用实时可见）
- [x] SSE 流式推送 + InvestigationHub 会话注册表
- [x] `open-tam serve` 命令
- [x] 故障模板快捷入口 + fake 开关
- **验收**：浏览器发起排查并看到流式过程 ✅（2026-08-31，feat/m4-web-ui 分支 10 commits；`open-tam serve` 127.0.0.1:8765 起服务，选 cpu_spike 故障模板一键注入并预填告警 JSON，fake 路径浏览器流式渲染 orchestrator/子 Agent 事件与最终报告卡片（根因/置信度/证据/建议动作/报告路径），报告落盘且 trace 可回放；5 个 API 用例全绿；107 passed + 1 skipped）

## M5 实盘接入

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M5

- [x] 云监控 webhook 告警接入（签名验证 + 多格式适配 + 去重）
- [x] alibabacloud-observability MCP 替换 mock-metrics 后端
- [x] SLS 日志服务替换 mock-logs 后端
- [x] 后端切换配置（metrics_backend / logs_backend）
- **验收**：webhook → 多格式适配 → 去重 → 排查全链路可用 ✅（2026-09-22 核验，commit 967faa6；CMS/AlertManager/native 三格式自动检测与 severity 映射、HMAC-SHA256 签名验证、300s 滑窗去重、webhook 端点集成测试全绿（test_m5_realtime.py 25 例）；`OPEN_TAM_METRICS_BACKEND`/`OPEN_TAM_LOGS_BACKEND=aliyun` 路由 aliyun-metrics（CMS）/aliyun-logs（SLS）MCP 后端，工具签名与 mock 完全一致；真实云端凭证按 README 配置即插即用）

## M6 知识沉淀与 Skill 系统

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M6

- [x] `open-tam skill learn` 从 trace 中提取排查模板
- [x] Skill YAML 存储 + 匹配 + 注入 ReAct system prompt
- [x] `open-tam skill list/create/delete/show` 管理命令
- [x] Web UI 知识库标签页
- **验收**：历史排查经验被自动提取为 Skill，新排查时 Skill 被加载并影响排查路径 ✅（2026-09-22 核验，commit cc4be71；`skill learn` 从 traces/ 批量提取工具调用序列 + 根因模板，按告警名/服务 fnmatch 聚合，每条 trace 置信度 +0.1；排查时匹配最高置信度模板注入 orchestrator system prompt；`skill list/show/delete` CLI 冒烟通过；test_m6_skills.py 全绿）。Web UI 知识库标签页 ✅（2026-09-22，commit 1a26ff9；GET /api/skills 置信度降序 + /{id} 详情懒加载 + DELETE 仅 manage_skills 角色（viewer/operator 403）；done 事件带 skill_used，前端显示"参考了 1 条历史经验"；浏览器实测列表/详情/删除/403 提示；test_web_skills.py 9 例全绿）

## M7 多租户与生产化

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M7

- [x] SQLite 持久化层（替代 JSON 文件）
- [x] API Key 认证 + 角色权限（admin / operator / viewer）
- [x] 通知集成（钉钉 / 飞书 / Slack webhook）
- [x] 排查历史持久化 + 检索 API
- [x] Web UI 登录 + 历史列表 + 敏感操作 Web 确认
- **验收**：CLI 侧多租户能力全绿（2026-09-22 核验，commit 1520483；SQLite WAL 持久化 users/investigations/alerts/audit_entries + `db migrate` 版本迁移；AuthMiddleware X-API-Key/Bearer + 三角色权限集测试全绿（test_m7_multitenant.py）；钉钉/飞书/Slack webhook fail-soft；`user create/list/delete`、`history list/show` CLI 冒烟通过）。Web UI ✅（2026-09-22：登录遮罩 + 排查历史标签页 commit 6d71d61；敏感操作 Web 确认 commit e458993——SSE confirm_request 弹窗 + POST /api/investigations/{id}/confirm 裁决，WebConfirmer 线程阻塞 120s 超时 fail-safe 拒绝，CLI 路径保持 AutoDeny 不变；test_web_confirm.py 7 例全绿，含真 uvicorn 端口 SSE 中途确认端到端）

## M8 K8s 与基础设施排障

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M8

- [ ] K8sGPT MCP 接入
- [ ] `k8s-agent` 子 Agent（与 metric/log-agent 并列）
- [ ] 新故障模式：pod_crash_loop / node_not_ready / dns_failure / cert_expiry
- [ ] （可选）ACS Agent Sandbox 隔离执行
- **验收**：Pod CrashLoopBackOff 告警触发 k8s-agent 诊断，产出包含 Pod 事件与日志的根因报告

## M9 高级评测与质量闭环

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M9

- [x] 多维度评测：根因命中 + 证据充分性 + 误报率 + 排查效率
- [x] LLM-as-Judge 证据充分性评分
- [x] A/B 模型对比评测（`open-tam eval --compare`）
- [x] CI 集成回归评测（`--min-hit-rate` 阈值）
- [x] Web UI 评测标签页（趋势图 + 详情）
- **验收**：CI 每次 PR 自动跑评测，命中率低于阈值告警 ✅（2026-09-22 冒烟，commit 7fe288e；`eval --fake --min-hit-rate 0.8` 跑通全部 8 种故障模式：定位率 100% / 关键词命中率 100% / 平均步数 3.0，退出码 0，报告落盘 reports/eval-*.md；EvidenceJudge LLM-as-Judge 证据充分性 0–1 锚定评分纳入评测；`eval-compare` A/B 多模型对比 Markdown 报告；定位率低于阈值退出码 1 可接 CI；test_m9_eval.py 全绿）。Web UI 评测标签页 ✅（2026-09-22，commit 0cc83a1；eval 结果落库 eval_runs（schema v2 迁移），GET /api/evals 趋势列表 + /{id} 含 runs 明细；前端 SVG 折线趋势图 + A/B 对比表 + 详情懒加载；test_web_evals.py 7 例全绿）

## M10 告警风暴与高级编排

> 详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md` §M10

- [x] 告警关联聚合（时间窗口 + 服务重叠 + 指标相关性）
- [x] 优先级排查队列（P0 抢占 P2）
- [x] 修复 Playbook 编排（YAML 定义 + 护栏逐条执行）
- [x] 跨集群/跨区域排查
- **验收**：关联告警聚合与 Playbook 编排全绿（2026-09-22 核验，commit 86bd6ab；AlertCorrelator 时间窗口 + 服务重叠 + 依赖配置聚合告警风暴为 AlertGroup；PriorityQueue（heapq）P0–P3 分级、P0 抢占 P2；修复 Playbook YAML 编排经 Guardrails 逐条执行，on_failure=abort/continue/rollback + confidence_threshold 门槛；test_m10_storm.py 全绿）。跨集群/跨区域排查 ✅（2026-09-22，commit d81e505；FaultState.activate 支持 region 区域隔离（无 region 故障全局生效，兼容旧用法），query_metrics/query_logs 的 region 参数下沉 mock 数据层与 MCP server；MultiRegionBackend 线程池并行 fan-out 所有区域并聚合 {"regions": [...]}，单区域错误隔离、k8s 类无 region 工具透传主区域不包壳；OPEN_TAM_REGIONS 多区域配置接入 investigate 自动 fan-out，CLI `fault inject --region`；冒烟：cpu_spike @ cn-hangzhou 杭州峰值 92.95 异常 / 上海 33.04 正常；test_m10_regions.py 10 例全绿）

## 行为评测（随 M2 起持续）

- 评测集 = 故障模式注册表
- 指标：根因命中率 / 证据充分性 / 平均步数 / token 成本 / 误报率
- 对标 OpenSRE 的 Planner + Sub-Agent 评估思路
- M9 起：LLM-as-Judge + A/B 对比 + CI 集成

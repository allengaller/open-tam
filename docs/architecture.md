# open-tam · SRE Agent 架构一页纸

**一句话定位**：基于 AgentScope + MCP 的多 Agent 排障系统——告警进来，自动查指标、翻日志，产出结构化根因报告；排查过程全程落盘为语料。

## 架构图

```mermaid
flowchart TB
    subgraph 入口层
        CLI[CLI · Typer]
        WH[云监控 Webhook<br/>POST /alerts · M5]
        AM[AlertManager Webhook<br/>M5]
        AR[alert-receiver<br/>AlertEvent 标准化<br/>云监控字段别名自动映射]
        DD[告警去重器<br/>滑动窗口 · M5]
        SC[告警关联聚合<br/>时间窗口+服务重叠 · M10]
        PQ[优先级队列<br/>P0 抢占 · M10]
        CLI --> AR
        WH --> AR
        AM --> AR
        AR --> DD
        DD --> SC
        SC --> PQ
    end

    subgraph 编排层
        ORC[Orchestrator<br/>手写 ReActLoop<br/>think → act → observe<br/>max_steps + char_budget 双预算]
        MA[Metric-Agent<br/>SpecialistAgent<br/>独立 prompt + 工具 + trace]
        LA[Log-Agent<br/>SpecialistAgent<br/>独立 prompt + 工具 + trace]
        KA[K8s-Agent<br/>SpecialistAgent · M8<br/>K8sGPT 诊断]
        SK[Skill 注入<br/>M6 先验知识]
        ORC -- ask_metric_agent --> MA
        ORC -- ask_log_agent --> LA
        ORC -- ask_k8s_agent --> KA
        ORC -- execute_action --> GR
        SK -.system prompt.-> ORC
    end

    subgraph 护栏层
        GR[Guardrails 引擎<br/>白名单 → 参数校验 → dry-run<br/>→ 敏感操作确认 → 执行]
        AUD[AuditLogger<br/>var/audit.log · JSONL<br/>每条决策逐落]
        PB[Playbook 执行器<br/>M10 多步修复]
        GR --> AUD
        GR --> PB
    end

    subgraph 模型层
        LLM[AgentScope ChatModel<br/>DashScope Qwen 主备切换<br/>消息/工具格式自动转换<br/>FakeChatModel 无 Key 替身]
        JUDGE[LLM-as-Judge<br/>M9 评测评分]
        ORC --> LLM
        MA --> LLM
        LA --> LLM
        KA --> LLM
        JUDGE -.评估报告.-> ORC
    end

    subgraph MCP 工具总线
        direction LR
        IB[InlineBackend<br/>直连本地 mock 函数]
        MCP[McpStdioBackend<br/>按 metrics_backend / logs_backend<br/>配置路由 mock 或 aliyun]
        MM[mock-metrics<br/>mock-logs]
        ALI[aliyun-metrics<br/>CMS DescribeMetricData]
        SLS[aliyun-logs<br/>SLS 日志服务]
        K8S[mock-k8s<br/>K8sGPT 风格 4 工具]
        SB[ACS Sandbox<br/>规划中]
        IB --> MM
        MCP --> MM
        MCP --> ALI
        MCP --> SLS
        MCP --> K8S
        MCP -.规划.-> SB
    end

    MA --> IB
    LA --> IB
    KA --> MCP

    subgraph 输出层
        REP[reports/*.md<br/>三段式根因报告<br/>结论摘要 · 异常清单 · 建议动作]
        TRC[traces/*.jsonl<br/>排查语料<br/>alert_received · tool_call<br/>observation · final]
        PAT[patrol-*.md<br/>阈值巡检报告<br/>8 故障模式 × 窗口峰值]
        DB[(SQLite<br/>M7 持久化)]
        SKD[skills/*.yaml<br/>M6 知识库]
    end

    subgraph 通知层
        NT[通知调度器 · M7]
        DT[钉钉]
        FS[飞书]
        SL[Slack]
        NT --> DT
        NT --> FS
        NT --> SL
        AUTHM[AuthMiddleware<br/>X-API-Key / Bearer<br/>admin / operator / viewer]
    end

    ORC --> REP
    ORC --> TRC
    ORC --> DB
    MA --> TRC
    LA --> TRC
    KA --> TRC
    GR -.审计.-> AUD
    TRC -.M6 提取.-> SKD
    NT -.排查完成/敏感确认.-> ORC
```

## 核心设计原则

1. **MCP 工具总线统一接口**：`query_metrics` / `query_logs` 签名固定，mock 与 aliyun 后端按 `metrics_backend` / `logs_backend` 配置路由，排查代码零改动。
2. **大脑与手脚分离**：编排层只做推理与调度，数据获取全部走 MCP；高危命令执行迁入 ACS Agent Sandbox（规划）。
3. **排查即语料**：每步思考/工具调用/观察落 JSONL，报告与 trace 都可回流语料库、沉淀 Skill。
4. **护栏前置**：命令白名单 + dry-run + 敏感操作人工确认 + 审计逐条落盘；Playbook 修复也经 Guardrails 逐条执行。
5. **Skill 反哺**（M6 起）：历史排查经验提取为 Skill，注入 system prompt 作为先验知识，不限制 LLM 自由度。

> 分层说明：ReAct 排查循环自研（`orchestrator/loop.py`）；AgentScope 仅用于模型接入（`orchestrator/llm.py`），负责 DashScope 调用、主备切换与消息/工具格式转换。

## 替换路径（mock → 实盘）

| MVP 阶段 | 后期替换为 | 接入里程碑 |
|---|---|---|
| mock-metrics-mcp-server | alibabacloud-observability MCP（云监控指标） | M5 |
| mock-logs-mcp-server | SLS 日志服务（同 MCP 框架接入） | M5 |
| 本地白名单沙箱 | ACS Agent Sandbox（MicroVM 隔离） | M8 |
| 云监控 Webhook（M5 起） | 真实告警源 | M5 |
| JSON 文件存储 | SQLite → PostgreSQL | M7 |
| 无 Skill 系统 | trace → Skill → system prompt 注入 | M6 |
| 单 Agent 排障 | + k8s-agent（K8sGPT） | M8 |
| 手动评测 | LLM-as-Judge + A/B 对比 + CI 集成 | M9 |
| 串行排查 | 告警关联聚合 + 优先级队列 | M10 |
| 单步动作 | 修复 Playbook 多步编排 | M10 |

## 演进路线

M0 骨架 → M1 排查闭环 → M2 多 Agent + 语料落盘 → M3 护栏 + 巡检 → M4 Web UI → M5 实盘接入 → M6 知识沉淀与 Skill 系统 → M7 多租户与生产化 → M8 K8s 与基础设施排障 → M9 高级评测与质量闭环 → M10 告警风暴与高级编排

> 全阶段详细设计见 `docs/superpowers/specs/2026-09-08-m5-to-m10-roadmap-design.md`

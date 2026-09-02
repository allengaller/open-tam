# Surface brief · GTM 落地页（open-tam）

## Scope & visitor mode
Persuade。单页 GTM 落地页，输出到 `GTM/`，纯静态 HTML/CSS/JS，中文文案（产品名/命令保留英文）。

## Audience / job / action
TAM / SRE 及相关岗位。Job：判断「告警自动排查」是否可信、是否值得试用。Action：去仓库跑无 Key 演示 / 查看源码（CTA 链接占位，交付时替换）。

## Proof / content（仅仓库事实，不虚构商业主张）
- 机制：AlertEvent 进 → orchestrator（ReAct）调度 metric-agent / log-agent → 三段式根因报告（结论摘要/异常清单/建议动作）；trace 全程 JSONL 落盘。
- 真实演示数据：cpu_spike（cpu_usage 92.5 vs 阈值 80，service demo-app）；故障注册表 cpu_spike / slow_query / oom / connection_pool_exhausted 即评测集。
- 替换路径：mock-metrics → alibabacloud-observability MCP；mock-logs → SLS；护栏：白名单 + dry-run + 审计。
- 路线：M0→M5，当前 M2 进行中。

## Chosen direction & memorable moment
「接线总机」：整页即一台排障设备。批准构图：`.impeccable/mocks/decision/assigned.png`（approved: true）。
Memorable moment：琥珀信号沿 告警线→汇流排→端子排→报告口 流过，端子依次点亮；报告从 OUT 口吐出。

## 实现保真清单（comp 读作设计系统）

### 采样色（comp 像素优先，覆盖决策色卡）
| 角色 | hex |
|---|---|
| 面板漆 ground | #A99883（内部）/ 边缘晕影 #746747 |
| 端子黑 | #0B0A08 |
| 铜汇流排 | #5E4020（高光 #7A5426） |
| 纸/标签 cream | #E2D7C9 |
| 琥珀缆线 | #CE7A19 |
| 信号红按钮 | #842014 |
| jewel 绿 | #6DB80F；jewel 琥珀心 #FFEA8B |
| 铭牌金属 | #B5A99F → #847165 渐变 |

### 组件语法
- 模块块：近方角（2-4px）、2px 内嵌描边、四角十字螺丝。
- 端子排：重复黑色块 + 螺丝圆点；空闲端子 = ghost-cell（未点亮也设计）。
- 标签：cream 芯片、1px 深描边、mono 字。
- jewel 灯：金属环 + 径向渐变；灭灯 = 幽灵格。
- 按钮：圆形金属 bezel；主 CTA 红色实体钮带按压态。
- 纸报告：cream 纸、微旋转、撕边底。
- 线重：丝印 1-2px；无大圆角、无玻璃、无渐变标题。

### 字体 ramp
- 中文 display：Noto Sans SC 900（丝印大字）。
- 拉丁 display：Saira Condensed 600/700（工程丝印）。
- 正文：Noto Sans SC 400/500。
- 数据/标签/命令：JetBrains Mono。

### 介质清单
| 构件 | 介质 |
|---|---|
| 面板漆颗粒/纸纤维 | 代码：SVG feTurbulence 噪点叠层（若截图对比不足再换 raster） |
| 琥珀缆线/跳线 | SVG path（圆头） |
| 端子排/螺丝/汇流排 | CSS/SVG 重复几何 |
| jewel 灯/按钮 bezel | CSS 径向渐变 |
| 报告纸内容 | 语义 HTML 文本 |
| 图标 | 世界内自绘 SVG 丝印图形 |

### 密度承诺
- hero 端子排 2 行 × ≥12 端子；语料账本 ≥7 行（行号+孔位）；故障标签 4 枚；路线模块 M0–M5。

### 主行动行
- 主 CTA「运行无 Key 演示」= 红色实体按钮（代码绘制 3D + 按压态），href 占位。
- 次 CTA「查看源码」= 黑色按钮，href 占位。

## Unresolved decisions
- CTA 真实链接（GitHub URL）占位 `#`，交付清单列出替换点。
- 夜间档（dark）作为面板上的物理拨动开关「日班/夜班」实现。

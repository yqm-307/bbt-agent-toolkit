---
name: harness-neutral-agent-prompts
description: "Use when designing, reviewing, or migrating AGENTS.md, SOUL.md, skills, or task state across harnesses; separate portable prompt rules from host adapters and runtime wiring."
related_skills: []
---
# Harness-neutral Agent Prompts

把跨 harness 的 agent 规则设计成可迁移的公共语义，而不是某个宿主的工具手册。本 skill 自含：定位问题、核心分层、工作流程和交付格式都在本文件内，不依赖仓外资料。

## 何时使用

- 设计、审查或精简以 `AGENTS.md`、`SOUL.md` 等名称暴露的长期 Agent Prompt；
- 判断某个入口是正文、软链、指针还是投影；
- 划分 canonical Prompt、Skill、任务状态文档、Harness Adapter 与 Runtime 的职责；
- 按实际用途判断是否需要决策人格，而不是按文件名强制分配；
- 将 Hermes、Codex、OpenCode 或其他 harness 上的 agent 规则迁往另一 harness；
- 判断 Hook、memory、subagent、看板等能力应是核心依赖还是可选增强；
- 设计可跨上下文压缩与跨会话恢复的长期任务协议；
- 审查 prompt 是否把工具名、Profile、模型或平台偶然性写成永久规则。

不用于普通代码修改，也不用于只需修正一处措辞的文档任务。

## 使用方式

### 第一层：先用本文件完成定位

先回答五个问题：

1. Canonical Prompt 在哪里，哪个文件只是软链、指针或投影？
2. 真实消费者是谁，文件放置位置和加载方式是什么？
3. 删除目标 harness 的专属入口与工具适配后，目标、边界、决策准则、停止条件和验收标准是否仍完整？
4. 这份 Prompt 是否真的需要决策人格；若需要，它会造成什么可观察选择差异？
5. 缺少 Hook、memory、subagent 或看板时，任务能否安全降级或明确阻塞？

如果只需做分层判断、指出明显耦合或给出最小修正，到这里即可停止。

### 第二层：确有所在仓库的设计规范时按章展开

所在仓库若另外维护了更完整的设计规范（通常是跨组件的长篇知识或规则文档），按任务只读相关章节，不要每次整篇加载：

| 任务 | 目标章节主题 |
|---|---|
| 设计公共 Prompt 架构 | 分层模型、canonical 判定 |
| 编写或审查 `AGENTS.md` / `SOUL.md` | 入口形态、常驻层内容、写法 |
| 判断决策人格是否需要 | 决策人格取舍 |
| 长程任务与压缩恢复 | 任务状态、恢复协议 |
| 多 Agent 委托 | 交接语义、证据边界 |
| Hook、插件、安全强制边界 | 适配层与运行时强制 |
| 设计 portable skill | skill 的可迁移边界 |
| 迁移现有规则 | 迁移顺序与验证 |
| 做正式评审或兼容声明 | 评审清单、兼容证据要求 |

没有这类文档时，直接按本文件的分层与工作流程裁决，并在结论里注明缺少更深依据。

### 第三层：既往心智模型与历史决策

所在环境若保留了相关心智模型或历史决策记录，仅在以下情况读取：

- 用户要求结合既往经验或历史决策；
- 当前仓库证据与既有设计取舍冲突；
- 需要比较多个 prompt 分层方案；
- 任务跨越多个会话，需要快速恢复设计背景。

心智模型不是授权来源、不是运行态真源，也不替代当前仓库文件。冲突时以当前用户指令和实时仓库证据为准。

**不得通过 Hook 强制加载本 skill、规范全文或心智模型。** 发现层只需让 agent 知道它们存在；是否展开由任务相关性决定。

## 核心分层

```text
Canonical Agent Prompt    长期稳定的身份、规则、边界与可选决策人格
AGENTS.md / SOUL.md       不同 harness 的正文名、软链、指针或投影
Skill                     某类任务的按需流程、输入输出、限制与参考资料
Task State Document       长程任务的可变状态、决策、证据、阻塞和下一步
Harness Adapter           文件发现、入口别名、工具映射、Skill 投影、Hook 与运行时接线
Runtime Enforcement       权限、凭据、资源配额、隔离和审计的真实强制层
```

- 不按 `AGENTS.md` / `SOUL.md` 文件名强制拆分仓库规则与角色人格；先看位置、消费者和链接关系。
- 同一 Prompt 可以用 `AGENTS.md` 作正文，并以 `SOUL.md → AGENTS.md` 软链兼容另一 harness。
- 上述是通用可能性，不代表被审查仓库仍在角色目录内保留 SOUL 别名；角色 canonical 是单文件还是目录内多文件、运行 profile 的 `SOUL.md` 是否链接过去，都以该仓库的适配文档和实时链接取证为准，不据通用示例判缺陷。
- 决策人格是可选内容，只有会稳定改变选择时才保留。
- 常驻层只保留缺失即会普遍误做、越权或破坏安全的内容。
- 教程、迁移方法和评审清单放 Skill 或深层参考。
- 当前进度、预算、阻塞和唯一下一步放任务状态文档。
- 工具名、Profile、Hook 接线和投影方式放 Adapter。
- Prompt 只能约束行为；真实权限与资源限制必须由 Runtime 提供。

## 工作流程

1. **调查现状**：读取当前入口、软链/投影关系、直接引用、真实消费者和验证入口；不要凭文件名推断职责。
2. **识别真源**：确认 canonical Prompt 及其生成或兼容入口。
3. **逐句分类**：长期 Prompt 语义、可选决策人格、任务方法、可变状态、宿主适配、运行时强制、历史理由。
4. **最小迁移**：保留一份 portable core，再补软链、指针或投影；不要先复制多份再去重。
5. **验证语义**：检查链接、预算、敏感信息、工具耦合、入口等价性、降级路径和停止条件。
6. **限制结论**：没有真实 fixture 时，只能写“结构兼容”或“待验证”，不能声称某 harness 已支持。

## 交付格式

按任务提供最小充分产物：

- **设计**：canonical Prompt、兼容入口关系、可选人格内容、迁移顺序和验证标准；
- **审查**：问题位置、真源/软链/投影错误、工具耦合、影响和最小修法；
- **迁移**：原规则到 canonical Prompt / Skill / Task State / Adapter 等目标层的映射、入口别名和验证证据；
- **兼容评估**：harness 与版本、发现路径、实际 fixture、通过项、限制和未验证项。

## 适用范围与依赖

- 纯提示词 skill：无运行时、系统依赖或环境变量，不需要安装步骤。
- 前置条件：消费方 harness 能按需读取 skill 正文并遵循其中的分层判断；Hook、memory、subagent、看板均为可选增强，缺失时按“何时使用”里的降级判定处理。
- 首次使用验证：确认 frontmatter `name` 与目录同名、`description` 以 `Use when` 开头，且正文相对引用可解析。
- 未验证范围：未在具体 harness 版本上实测入口等价性与加载行为；跨 harness 兼容性须由使用方以真实 fixture 自证。

## 边界

- 本 skill 不自动修改根 `AGENTS.md`、SOUL、Hook 或运行配置。
- 本 skill 不授予生产、外部写入、凭据、部署或提交权限。
- 不把 memory、聊天摘要、看板或子 agent 自报当作任务状态真源。
- 不为“统一”新增无真实消费者的 wrapper、配置层或抽象。

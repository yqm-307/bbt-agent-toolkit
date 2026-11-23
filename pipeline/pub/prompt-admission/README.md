# 提示词规则准入

[流程定义](pipeline.yaml) 一次处理一条候选：筛查 → 人审 → 只报告观察 → 人工批准。`admitted` 只表示可以移交对应执行器，不启用规则，也不证明规则已生效。运行方法和公开边界见 [Pipeline 规范](../../README.md)。

## 产出约定

以下文件都相对于控制脚本返回的 `run_dir`，使用 UTF-8。执行者按需创建 `artifacts/`；不在公开目录里写运行材料。

| 阶段 | 产出 | 约定 |
| --- | --- | --- |
| `screen` | `artifacts/candidate-<revision>.yaml` | `<revision>` 是提交 `prepared` 前的修订号。返工时写新版本，保留已被历史引用的卡片。 |
| `monitor` | `artifacts/observations.jsonl` | 一行一个 JSON 对象，一批一行，追加历史。未观测到的指标用 `null`，实测为零才记 `0`。初入可以没有文件。 |
| `review`、`approve` | 事件历史 | 通过 `advance` 记录人工决定、可定位的来源和所审材料的相对路径，不另抄一份决策日志。 |
| `admitted`、`closed` | 事件历史 | 终点和进入终点的事件已经记录结果与原因；不再生成重复的状态报告。 |

**候选卡字段**：`id`（同一候选跨修订保持不变）、`sources`（脱敏后的定位引用列表）、`invariant`、`scope`、`positive_cases`、`negative_cases`、`oracle`（怎么判断通过）、`false_positive_risk`、`severity`、`owner`（可用职责名）、`target`（`lint` / `deterministic-eval` / `llm-eval` / `runtime-policy` / `manual-review`）。

**观测记录字段**：`candidate`（候选卡的运行相对路径）、`observed_at`（ISO 8601，含时区）、`runs`、`false_positives`、`false_negatives`、`unknown`、`cost`（`{ "value": 数值, "unit": "单位" }` 或 `null`）、`sources`（脱敏后的证据引用列表）。每条只记本批数据，不把历史累计数当成新增数据。`sampled` 或 `ready` 的证据引用文件及对应行号或范围。

这里的格式供流程执行者和审阅者使用，`control.py` 只校验流程和事件，不检查候选或观测文件，也不自动公开材料。

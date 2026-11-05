# DAG 子代理动作范围治理

> 结论一句话：DAG 子代理越界不能只归因于"任务书写得差"。派发协议只把范围写成文字、没转成权限，子代理默认会补跑没点名的检查。已实现的第一层是给 DAG 任务书自动追加默认边界条款（`omh-dag-boundary` 插件）；条款能否送达、是否降低越界率，都需在目标宿主自行验证。

## 1. 口径与工具

本文只描述审计口径、已实现措施与局限，不附带任何一次具体运行的统计。读数取决于使用者自己的会话库与 DAG 运行记录，应由使用者在授权范围内自行审计。

- 审计工具：[`tools/dag-scope-audit/dag_scope_audit.py`](../../tools/dag-scope-audit/dag_scope_audit.py)，只读 `$HERMES_HOME/state.db` 与 `$OMH_HOME/runtime/dag`，按 `[dag:<run>/<node>]` 标记把子会话绑定到节点，再按节点 prompt 推导"允许做什么"，对账子代理实际调用。
- **判定是线索不是判决**：依据命令文本做**类别级**许可判断（VERIFY 里出现测试类词就令 `allow['test']` 为真），**不比对具体命令、参数或测试目标**；`sed -i`、重定向、`python -c` 写文件识别不到。`verify`/`baseline` 角色还会按角色拿到测试默认许可。
- 读取方式（占位符由使用者替换）：

```bash
HERMES_HOME=<profile-home> python3 tools/dag-scope-audit/dag_scope_audit.py --days <N>
```

审计窗口与筛选条件必须在报告里写明；换了窗口或筛选条件，读数不可直接比较。

## 2. 根因分层

1. **派发协议只有意图，没有权限。** `SCOPE`、`VERIFY`、`STOP WHEN` 是自由文本；`write_scope` 只在定义期查并发重叠，没有传给子代理；`STOP WHEN` 运行时没有判定。
2. **定义期校验只拦最空的情况。** `require_prompt_markers` 只在"五段标记一个都没有"时拒绝节点，缺几段只是 lint 建议（`dag_run.py` 注释原文 "never rejects a run"）。VERIFY 有没有命令、STOP WHEN 能不能判定，没人检查。
3. **子代理继承父会话全部工具。** Hermes 子代理 `skip_context_files=True`，工具集不按节点收窄。宿主 prompt 里有 "Keep working until you have actually exercised the code" 这类推动执行的句子，任务书沉默处容易按默认走。
4. **提示词载体按模型名分流会漏人。** `model-guidance` 的 `worker.md` 按模型名命中 `gpt-*`/`codex`/`deepseek`，其余模型家族的节点拿不到对应条款。

## 3. 已实现措施：`omh-dag-boundary` 插件

位置：[`plugins/hermes-agent/omh-dag-boundary/`](../../plugins/hermes-agent/omh-dag-boundary/)（`plugin.yaml` + `__init__.py` + `tests/test_plugin.py`）。

- **挂点**：`pre_tool_call`，返回 `{"action": "modify", "args": ...}` 改写 `delegate_task` 参数。宿主在 `agent/tool_executor.py` 的 `_pre_tool_block` 把改写后的 args 交给真正执行的工具。
- **识别**：要求 `goal` 是字符串，且标记位于 goal 的**首或尾**——真实派发里两种形状都出现（`<label> [dag:run/node]` 与 `[dag:run/node] <label>`），run 与 node 用 OMH 生产者的 ID 语法 `[a-z0-9][a-z0-9-]{0,31}`。普通委派、其他工具、非字符串 goal 一律不动。收紧正则后应在历史派发样本上回放：两种目标形状应命中，负例（多斜杠、句中引用、首部标记后紧跟括号、空格、嵌套括号、截断）应不命中；标记夹在句子中间、被父会话改写过的 goal 会漏。完全照抄这个格式的普通文本仍可能被认作 DAG——靠文本鉴别消不掉这个可能。
- **改写**：把条款追加到 `context` 末尾，幂等（已含 `[默认边界·DAG]` 就跳过）。传 `tasks[]` 时逐任务追加——宿主只读每个任务自己的 `context`，顶层 `context` 会被忽略；`tasks` 为 JSON 字符串时先解析。
- **失败路径**：任何异常（含写日志本身失败）都返回 `None`。宿主把 `pre_tool_call` 抛出的异常当成 `block`，所以这里不能漏异常。
- **条款内容**（179 字）：测试/构建只跑 VERIFY 点名的命令；Git 只做点名的动作，不建 worktree/stash/branch；只改 SCOPE 划定的文件、交接文件除外；缺的写进「范围外请求」；本说明的 `NOT DO` 优先。

**边界**：这是提醒不是锁，也不是运行时强制；宿主不校验子代理是否照做。标记是模型写的文本，会丢也会被编。

## 4. 上线与送达验证

接线步骤（路径与命令用占位符，按目标 profile 替换）：

1. 软链进 profile：`<profile-home>/plugins/omh-dag-boundary`。
2. 启用（白名单制）：`hermes -p <profile> plugins enable --no-allow-tool-override omh-dag-boundary`，配置只多 `plugins.enabled` 与 `entries.omh-dag-boundary.allow_tool_override: false`。
3. **插件在进程启动时加载**：启用命令只热加载 Gateway；若目标宿主由独立 WebUI 进程承载，需重启该进程后新插件才生效。DAG 派发是否走 WebUI，按目标宿主的实际链路确认。

送达验证只回答"条款是否出现在子代理可见的位置"，不等同效果：

- 派发一个只读冒烟 DAG，检查子代理回复或交接是否原样引用条款。
- 子代理的系统提示词不一定落库，所以回复引用不能证明条款在提示词里出现几次，也不能断言它只可能来自某一个来源。
- 更不能据此推断越界率下降——那需要前后对照，见 §6。

## 5. 未验证与局限

- **没验证能降低越界率。** 冒烟只覆盖送达，不是效果实验。
- 只在少数模型家族上做过冒烟，未覆盖全部模型；其他家族是否同样送达，需自行验证。
- 子代理的系统提示词不落库，条款是否重复出现、是否与其他插件注入冲突，未核。
- 标记识别的精度依赖派发记录；需在目标环境的样本上自行回放，负例集见 §3。
- 越界不是 DAG 墙钟的主要部分，消除越界对总时长的收益有上限；具体比例需按自己的运行记录测算。
- `prohibited_*` 命中是线索，是否真违规要逐条复核；`unrequested_*` 等类别同样需要人工裁决。

## 6. 怎么复测

上线一到两周后，用同一命令、同一筛选重跑，并在报告里带上样本量、窗口和未解析量：

```bash
HERMES_HOME=<profile-home> python3 tools/dag-scope-audit/dag_scope_audit.py --days 14
```

判读注意：比例变化不能单独证明提示词有效或无效——任务构成、路由、模型都在变。要先固定角色、模型家族与任务类型，再看同一类任务上的方向性变化；若某类模型在相似任务构成下仍稳定越界，才值得考虑 `pre_tool_call` 硬拦。

## 7. 相关文件

- [`plugins/hermes-agent/omh-dag-boundary/`](../../plugins/hermes-agent/omh-dag-boundary/README.md) — 插件与单测（13 项）。
- [`tools/dag-scope-audit/`](../../tools/dag-scope-audit/README.md) 的 [`dag_scope_audit.py`](../../tools/dag-scope-audit/dag_scope_audit.py)、[`test_dag_scope_audit.py`](../../tools/dag-scope-audit/test_dag_scope_audit.py) — 只读审计与回归（23 项）。
- [`plugins/hermes-agent/model-guidance/prompts/family/worker.md`](../../plugins/hermes-agent/model-guidance/prompts/family/worker.md) — 子代理执行纪律（按派发说明与节点角色决定测试/构建）。

---
name: context-prefix-slimming
description: "Use when 要降低 agent 每次请求的固定 token 成本（常驻前缀、系统提示词、工具 schema、技能索引过大），或怀疑上下文膨胀却定位不到来源；含按体积排序找真凶、优先复用现有开关、同条件 A/B 量化、可达性与新会话端到端验证。"
---

# Context Prefix Slimming — 常驻前缀瘦身

降低 agent **每次请求都要重发**的那部分体积。

## 先分清两种成本

| 类型 | 何时付 | 优化杠杆 |
|---|---|---|
| 常驻前缀（系统提示词、工具 schema、技能索引、记忆块） | **每次请求** | 高 |
| 工具输出、历史累积 | 偶发，大结果时 | 低 |

100 次请求里可能只有 3 次输出 5 万字符，但常驻前缀 100 次都要付。**先确认要动的是常驻前缀**；否则换个方向。

判据：如果候选改动的收益小于真凶的 1/10，停手，先找真凶。

## 步骤

### 1. 量，不要想

先测量，再构思方案。真实分布里最大的项往往不是显眼的执行逻辑，而是 schema 里内嵌的说明性文本。

```bash
hermes -p <profile> prompt-size
```

输出给出系统提示词总量、各块体积（skills index / memory / user profile）、工具 schema 总量、按 toolset 的工具体积排序。要按**单项工具**排序时，用装配函数直接量：

```python
import json, model_tools
defs = model_tools.get_tool_definitions()
rows = sorted(((len(json.dumps(d, ensure_ascii=False, separators=(",", ":"))),
                d["function"]["name"]) for d in defs), reverse=True)
for size, name in rows[:10]:
    print(f"{size:7d}  {name}")
```

固定口径：**紧凑分隔符**（`separators=(",", ":")`）。默认 `json.dumps` 会多出大量空白，混用两种口径会得出矛盾结论。

### 2. 查现成开关，再考虑改源码

Hermes 通常已有对应机制。先 `grep` 配置默认值与装配函数，确认开关存在与否，再决定要不要动代码。

| 目标 | 现成机制 |
|---|---|
| 不内嵌工具目录 | `tools.tool_search.listing: off` |
| 减少常驻工具 | `tools.tool_search.defer: [...]` |
| 技能类别降级为仅名称 | `agent.coding_context: focus`（有平台/上下文门槛，见步骤 6） |
| 单次输出上限 | `char_limit`、结果落盘阈值 |

配置写入走 CLI，不要手改受保护的配置文件：

```bash
hermes -p <profile> config set <dotted.key> <value>
hermes -p <profile> config get <dotted.key>    # 回读确认
```

### 3. 一次改一项，同条件 A/B

两臂必须只差一个变量：同一进程、同一批原始工具定义、同一 profile，绕开配置加载与缓存。用显式配置对象装配，不要靠改环境变量：

```python
from tools.tool_search import ToolSearchConfig, assemble_tool_defs
raw = model_tools.get_tool_definitions(skip_tool_search_assembly=True)

def measure(**overrides):
    cfg = ToolSearchConfig.from_raw({"enabled": "auto", **overrides})
    res = assemble_tool_defs(raw, context_length=1_050_000, config=cfg)
    return len(json.dumps(res.tool_defs, ensure_ascii=False, separators=(",", ":")))
```

同时断言两臂的可见工具数、延迟工具数一致，否则比较不成立。

### 4. 验证可达性，不是"工具还在"

工具被延迟后，模型只能靠检索找到它。按名逐个探测，不要只看注册表：

```python
d = json.loads(model_tools.handle_function_call("tool_search", {"queries": [name]}, task_id=None))
hits = [h for r in d.get("results", []) for h in r.get("matches", [])]
```

未命中项必须区分两种原因：

- **真回归**：工具已注册但检索不到 → 必须修或回滚
- **本来就没注册**：当前环境没有该能力 → 不算回归，写清即可

### 5. 起干净的新会话做端到端实测

当前会话的残留上下文会掩盖问题。新会话要验证的是模型能否自己走完 **检索 → 描述 → 调用**：

```bash
hermes -p <临时profile> -z "请用 <被延迟的工具> 完成 <任务>。必须真的调用工具。"
```

然后从会话库读出真实调用序列，确认没有卡顿、重复搜索或误报工具不存在：

```python
con.execute("select role, tool_name, tool_calls from messages order by rowid")
```

临时 profile 会复制 `.env`，**验证完立即删除**。

### 6. 注意机制门槛

现成开关可能带前置条件，配置写了也可能不生效。例：技能索引降级要求 `agent.coding_context: focus` **且** `is_coding=true`，而 WebUI 平台实测 `is_coding=false`。改动前先跑一次解析函数确认实际取值：

```python
from agent.coding_context import resolve_runtime_mode
m = resolve_runtime_mode(platform="webui", cwd=None)
print(m.is_coding, m.config_mode)   # 两个都为真才生效
```

### 7. 记录并留回滚

- 改前备份配置 + sha256，改后回读确认
- 报告只写可归因的收益，字符/字节/token/费用分开标注
- 明确"未覆盖"：提供商真实 token 计数、账单金额、长期主观体验
- 给出可执行的回滚命令

## 配置语义坑

- **`defer` 是整体替换，不是追加**。写入时必须把默认清单全部带上，否则静默丢失原有延迟项。改前先读出 `effective_defer_tools` 并完整合并。
- 关闭 `listing` 后，模型需要先检索一次才能看到延迟工具名；常用工具保持常驻，别一起延迟。
- 收益随延迟池大小变化：同一开关在 130 项延迟池上省 10,637 字符，在 55 项上只省 4,450。报告要注明当次延迟池规模。

## 反模式

| 反模式 | 后果 |
|---|---|
| 不量就挑"看起来大"的项 | 差三个数量级，改了几百字符还以为是主要问题 |
| 给几百字符的改动配三重验证 + 独立审查 | 验证成本超过收益，制造"很努力"的假象 |
| 把调研的方向清单直接当待办 | 做完一个→验证→不采用→换下一个，循环到零交付 |
| 约束封死有效路径仍硬做边角项 | 应立刻上报"约束与目标互斥"，请用户二选一 |
| 用字节量当字符量 | 口径混用，前后数据对不上 |

## 交付

用户判断进展的标准是**有没有可用的东西落地**，不是验证做得多细。交付「一个能用的改动 + 前后数据 + 回滚命令」，不是「方向清单 + 验证报告」。

## 迁移适配说明（适用前提）

- 本 skill 仅适用于 Hermes Agent 宿主：文中 `hermes -p <profile> prompt-size`、`config set/get`、`-z` 单次模式，以及 Python 中的 `model_tools`、`tools.tool_search`、`agent.coding_context` 均为 Hermes 内部命令与模块，不是公共稳定接口；各配置键（`tools.tool_search.*`、`agent.coding_context`）亦同。
- 这些命令和模块在哪个 Hermes 版本可用尚未核实，本次迁移未运行。使用前先用 `hermes --help` 与 `hermes -p <profile> prompt-size --help` 确认命令存在，并在 Hermes 源码检出或其虚拟环境的 Python 中确认模块可导入；缺失则以所用宿主的等价手段测量常驻前缀，方法（先量、一次改一项、同条件 A/B、新会话实测）不变。
- 其他宿主没有这些入口，不承诺可直接执行。
- 临时 profile 会复制凭据文件：只在用户授权下创建，验证后删除。

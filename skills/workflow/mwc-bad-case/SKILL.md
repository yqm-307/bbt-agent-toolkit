---
name: mwc-bad-case
description: "Use when 用户要记录 bad case、坏体验、对 agent 的纠正或否定，或说「MWC-recordard bad case」；也在 mwc-chat-end 收尾时扫描当前 session 的完整可恢复历史。默认优先发现并记录事实，不自动优化 prompt。"
related_skills: [mwc-chat-end, mwc-recall]
---

# mwc-bad-case — 记录坏体验，不急着优化

把一次“没有达到预期、让我不舒服、我不得不纠正 agent”的经历记录下来，供以后可视化、归类和迭代。这个 skill 负责保存观察材料，不负责现在解释根因、修改 prompt、创建新 skill 或启动优化实验。

## 什么时候记录

下面这些都可以成为 bad case，用户明确说出来的优先级最高：

- 结果没有达到用户已经说清楚的目标，或者把目标做成了用户明确不要的方向。
- 用户纠正、反驳、否定 agent 的理解、方案、范围、事实或动作，例如“不是这个意思”“我不想做这个”“别这样”“你又跑偏了”。
- 用户表达不适、失望、浪费时间、反复解释、被迫收窄范围，或者要求 agent 重来、改回、用自己的话重新理解。
- agent 做了未经授权的动作，或把建议说成已经执行、把未验证说成完成，导致用户需要主动拦截。
- 没有一句明确的抱怨，但上下文已经显示同一预期与实际回应不一致。此时只能记录证据支持的观察，不能凭语气猜测用户感受。

一次普通的事实补充不必自动判为 bad case；但如果用户是在纠正 agent 的错误或否定其方向，就记录。一个连续纠正链属于同一事件时合并成一条；不同目标、不同回应或不同不适点分成多条。

## 默认动作

### 用户明确触发

用户说 `mwc-bad-case`、`MWC-recordard bad case`、`记录这个 bad case` 或同义表达时：

1. 回看当前局部上下文，必要时恢复本 session 中紧邻的历史，定位最近一个完整事件。
2. 从已给内容填充记录；不为了完整而连问字段。缺失项留空或标为未知。
3. 证据足够时直接写入 SQLite；只有无法判断是哪一次事件时，才问一个能改变记录对象的关键问题。
4. 用很短的结果告诉用户已记录的 `id` 和事件标题；不顺带提出 prompt 改法。

### 收尾时没有额外指令

当 `mwc-chat-end` 运行到全历史回顾时，默认先执行一次 bad case 扫描。扫描范围是当前 session 能恢复到的全部用户消息、相关 assistant 回应、压缩节点的来源和可读回的原始消息；不能只看最近几轮，也不能只用关键词命中当证据。

1. 先用宿主的 session 检索能力定位线索，再读命中前后的上下文。已压缩的摘要只是定位线索；需要准确原话、消息位置或时间时，用 `lcm_expand`、`lcm_load_session` 或宿主等价入口恢复原文。
2. 按一次事件合并纠正链，提取多个独立事件。默认偏向保留可证据定位的候选；证据弱但确有不适信号时也可记录，设置较低 `confidence` 并标明待确认，不为了降低噪声而丢掉用户可能以后要看的材料。
3. 自动写入 SQLite，`source` 使用 `chat-end`，保留 session 标识和消息引用。记录失败时如实报告失败原因，不能把“找到候选”说成“已经保存”。
4. 在收尾检查点单独报告本次发现和写入的 bad case 数量、ID、历史覆盖范围与缺口。它不直接进入“沉淀经验 / 更新 prompt / 写长期记忆”的候选清单，也不改变用户选择的收尾动作；能否转成已有门禁的确定检查，由 `mwc-chat-end` 在经验候选阶段判断。
5. 扫描完成后停止在记录层。除非用户另行要求分析，否则不归纳共因、不推荐修复、不修改任何 prompt 或 skill。

“用户什么都不说”不是“什么都不做”：在 chat end 的扫描阶段，按上述证据规则自行决定发现、合并、记录；没有可定位的坏体验时才报告未发现，不编造记录。

当用户没有点名 CRUD 动作时，按上下文选择最小动作：出现新的坏体验事件就 `record`；用户要找历史、列表或某一条就 `list` / `show`；用户补充现场、分析、标签或状态就 `update`；用户说删除、忽略或不再保留就执行可恢复的 `delete`；用户撤销删除再 `restore`。上下文足够时直接做，不把“你想增删改查哪一个”变成额外提问；只有无法判断对象或会误写不同事件时才问一个关键问题。

## 记录内容

记录要让未来的人能重现当时发生了什么，而不是只留下“体验不好”这个结论。SQLite 的主表包含以下可查询字段：

| 区域 | 内容 |
|---|---|
| 身份与来源 | `id`、`source`、`session_id`、`turn_ref`、`occurred_at`、创建和更新时间 |
| 现场 | `title`、`scene`、当时的 `goal`、用户的 `expected`、实际 `observed` |
| 体验与纠正 | `experience`、`correction`，保留用户表达的不适、否定和被迫纠偏 |
| 分类 | `category`、`severity`（1–5）、`confidence`（0–1）、`status` |
| 证据 | `evidence` JSON 数组；每项尽量带 `role`、准确 `ref`、`quote` 和为何支持此记录 |
| 环境与分析 | `context` JSON、`analysis` JSON、`tags` JSON；分析只能区分事实、推断和未知 |

首次记录的 `analysis` 可以写观察层分析，例如“预期是只记录，实际回答开始给优化建议；是否由收尾流程边界不清造成，待后续分析”，但不要把假设写成根因，也不要把修复方案填进去。以后研究根因、尝试 prompt 变化和记录实验结果，用 `update` 更新同一条 case 的当前字段，并把每次变更追加到事件历史。

证据优先保留用户原话和 assistant 的相关回应。引用压缩摘要时标注它是摘要，不能用摘要冒充未恢复的原文；历史缺失写进 `context` 或 `analysis.unknowns`。不要把密码、token、私钥或不必要的敏感原文写入记录。

## SQLite 与脚本入口

随 skill 提供的 `scripts/bad_case_db.py` 只用 Python 标准库，负责存储和 CRUD；它不自行读取聊天历史。聊天扫描由本 skill 和宿主的 session 工具完成，再把结构化记录交给脚本。

默认数据库路径为 `MWC_BAD_CASE_DB` 环境变量指定的位置；未设置时使用 `~/.local/share/mwc-bad-case/bad-cases.sqlite3`。也可以所有命令显式传 `--db <path>`。首次使用（不传 `--db` 即使用默认路径）：

```bash
python3 "$SKILL_DIR/scripts/bad_case_db.py" init
```

`SKILL_DIR` 必须取宿主实际加载本 skill 时返回的目录；不要假定当前工作区路径。环境变量未设置时，直接省略 `--db "$MWC_BAD_CASE_DB"`，脚本使用默认路径。

常用命令：

```bash
# 记录：推荐用 JSON 文件承载现场、证据和分析，避免 shell 转义损坏原话
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" record --json-file case.json

# 查一条并查看所有更新事件
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" show <case-id> --history

# 默认只查待处理 open、处理中 reviewing；JSON/JSONL/CSV 均使用此过滤
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" list --format json
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" list --category scope-drift --format csv

# 查看历史（含已处理 resolved、已忽略 ignored，不含软删除）或单独查看噪音标记
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" list --status all --format json
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" list --status ignored --format json

# 修改会追加事件，不覆盖历史
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" update <case-id> --json-file update.json

# 删除默认是可恢复删除；恢复时保留原来的事件历史
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" delete <case-id> --reason "duplicate"
python3 "$SKILL_DIR/scripts/bad_case_db.py" --db "$DB" restore <case-id>
```

`record` 是 `create` 的别名，`show` 是 `get` 的别名。脚本自动生成的 ID 形如 `bc-<hex>`；如果手动传入 `id`，也必须使用 `bc-` 前缀。`delete` 把状态设为 `deleted`，普通查询会隐藏它；`list --include-deleted` 可查看。脚本不会替用户提交、推送、部署或修改外部系统。

## 与相邻能力的分工

- `mwc-chat-end` 负责在收尾检查中触发全 session 扫描并汇报覆盖范围，并把可机械判定的 bad case 拟成已有门禁的检查候选；这里负责 bad case 的识别口径、记录内容和 SQLite CRUD。
- `mwc-recall` 负责恢复跨会话或共享历史的上下文；这里只读取当前 session 所需证据，不把 recall 结果本身当成 bad case。
- prompt 优化、经验提炼和 skill 修改属于后续任务。记录 bad case 不等于授权做这些事。

## 适配、验证与边界

适用宿主是能加载 skill、读取当前对话历史并提供本地 Python 3.9+ 的环境；脚本只有 Python 标准库和 SQLite 内置模块，无第三方依赖。数据库路径必须由用户环境或 `--db` 提供，不能写死 profile、账号或机器路径。

聚焦场景见 [tests/scenarios.md](tests/scenarios.md)。脚本检查：

```bash
python3 "$SKILL_DIR/tests/test_bad_case_db.py"
```

这个检查覆盖记录、查询、更新事件、软删除、恢复、过滤和非法输入；尚未在真实 Hermes session 上验证压缩历史恢复、跨宿主触发、长期运行数据库升级或可视化前端。没有真实历史证据时，不声称“已扫描整个 session”；没有脚本成功输出时，不声称“已保存”。

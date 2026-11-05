# dag-scope-audit

只读审计 Hermes DAG 子会话有没有越出所在节点 prompt 允许的动作范围。工具把 OMH 的 DAG 运行记录与 Hermes 会话库按 goal 里的 `[dag:<run>/<node>]` 标记连接起来，再对每个子会话的 terminal 命令和写文件调用逐条对照节点 prompt 推导出的许可：

- 测试 / 构建：prompt 明写禁止的记为 `prohibited_*`，只字未提的记为 `unrequested_*`；`VERIFY` 点名的测试算被请求，build 角色默认可编译，verify/baseline 角色默认可构建和测试（除非 `NOT DO` 或否定句禁止）。
- Git 写：prompt 没点名的 commit / push / add / worktree 等子命令。
- 写文件：超出 `write_scope` 的路径；同 run 其他节点的范围被记为 `foreign_scope_write`，check 角色写工作文件被记为 `check_role_write`。

**结论是线索，不是判决**：判定按命令文本做类别级许可，不比对具体命令、参数或测试目标，必须人工复核原始命令与路径。

适用宿主：Hermes（子会话与工具调用记录）与 OMH（DAG 运行记录）；不依赖两者的运行时进程，也不依赖其他私有组件。

## 前置条件

- Python 3.10+（按语法特性：运行时求值的 `X | None` 注解与 `Path.is_relative_to`；本次只在 3.14 实测），只使用标准库。
- 对 Hermes 会话库的**只读**访问：默认 `$HERMES_HOME/state.db`（`HERMES_HOME` 未设置时取 `~/.hermes`），可用 `--db` 指定。库中需有 `sessions`（`id`、`source`、`started_at`）与 `messages`（`session_id`、`role`、`content`、`tool_calls`）两表。
- 对 OMH DAG 记录目录的**只读**访问：默认 `$OMH_HOME/runtime/dag`（`OMH_HOME` 未设置时取 `~/.omh`），可用 `--omh-home` 指定；读取其下 `*/<run>.json`，记录需含 `run`、`defined_at`、`nodes[]`（`id`、`label`、`role`、`prompt`、`write_scope`、`origin`）。
- 不需要 Hermes 或 OMH 正在运行，不需要写权限，不联网、不安装依赖。

## 用法

```bash
# 一次 run 的逐子会话 findings（JSON）
python3 tools/dag-scope-audit/dag_scope_audit.py --run <RUN_ID>

# 只看某个节点
python3 tools/dag-scope-audit/dag_scope_audit.py --run <RUN_ID> --node <NODE_ID>

# 近 30 天汇总（默认窗口）
python3 tools/dag-scope-audit/dag_scope_audit.py --days 30

# 汇总的 JSON 版本
python3 tools/dag-scope-audit/dag_scope_audit.py --days 30 --json

# 库和 DAG 记录不在默认位置时，用环境变量或显式参数
HERMES_HOME=/path/to/hermes OMH_HOME=/path/to/omh \
  python3 tools/dag-scope-audit/dag_scope_audit.py --days 7
python3 tools/dag-scope-audit/dag_scope_audit.py --days 7 \
  --db /path/to/state.db --omh-home /path/to/omh
```

退出码：正常 0；`--db` 指向的库不存在时 2。结果只打印到 stdout，工具不写任何文件。

## 输出字段

每个子会话一条结果：

| 字段 | 含义 |
|---|---|
| `run` / `node` / `session` | run id、节点 id、Hermes 子会话 id |
| `role` / `role_source` | 节点角色；`recorded` 表示 DAG 记录里写了 `role`，`legacy_label` 表示记录没有该字段、按 id/label 猜测（猜出的 check 角色只用于收紧写入检查，不会获得 check 角色的测试/构建默认许可） |
| `allow` | 推导出的许可：`test`、`build`、`git_verbs`（prompt 请求的 git 子命令）、`no_verify`（prompt 没有 VERIFY 段） |
| `findings[]` | 命中的动作，见下表 |
| `unresolved[]` | 无法判定的相对路径，或 `no write_scope declared; writes not checked`、`write_scope uses an alias; writes not checked` |

`findings[].kind`：

| 取值 | 含义 |
|---|---|
| `prohibited_test` / `prohibited_build` / `prohibited_git` | prompt（含 `NOT DO` 段或带否定的分句）明写禁止 |
| `unrequested_test` / `unrequested_build` / `unrequested_git` | prompt 既未请求也未禁止 |
| `foreign_scope_write` | 写到了同 run 另一个节点的 `write_scope`；`owner` 给出该节点 id（repair 节点的目标节点除外） |
| `check_role_write` | 记录为 verify/baseline/review 的节点写到了其 `write_scope` 之外；verify 不因自带 scope 豁免（OMH 中 verify 不是 producer，任何工作文件写入都按此计） |
| `out_of_scope_write` | 绝对路径，既不在本节点范围，也不属于同 run 其他节点 |

`evidence` 是命中的命令片段或文件路径。`prohibited_*` 也常由否定句模板误伤（例如“不声称全量测试通过”），`unrequested_*` 只表示 prompt 没有点名，不等于越界；`foreign_scope_write` 依赖 `write_scope` 的写法能否被路径匹配规则理解。上述命中都只是线索，不是对子代理的判决。

汇总模式（不带 `--run`）输出 `children`、`build_children`，以及 `all` / `build` 两组比率：每个 kind 一行 `命中子会话数/子会话总数 = 百分比`，`any` 是至少有一条 finding 的子会话数，`(unresolved, not checked)` 是存在未解析项的子会话数。`build` 组只统计 build 角色（check 角色本来就可以跑测试）。

输出会原样带出会话里的命令片段和文件路径；对外分享结果前自行脱敏。

## 已知识别边界

- 命令识别是文本启发式：heredoc 正文会跳过；shell 重定向、`sed -i`、`python -c` 里的写文件看不到；`ctest -N` 之类的列举命令不算运行；`git` 只识别显式子命令，`commit` 后跟 id 时按名词处理。
- `VERIFY` 里出现测试类词就令 `test` 许可为真，不核对测试目标或参数；因此 build 节点跑与 VERIFY 无关的测试不会报 `unrequested_test`。
- 写入检查只覆盖 `write_file` 与 `patch` 工具的参数；终端命令里的写文件不算。`/tmp`、`.state`、`.omh/artifacts` 与 OMH/Hermes 运行时目录不计为节点工作文件。
- 路径匹配支持绝对/相对写法与 scope 里的通配符，但相对路径无法确定 cwd 时只进 `unresolved`，不判越界；`write_scope` 使用别名（如 `A/`）时整节点跳过写入检查。

## 测试

```bash
python3 -B -I -m unittest discover -s tools/dag-scope-audit -p 'test_*.py'
```

测试只使用临时目录里的合成 SQLite 库与合成 DAG 记录，不读取真实会话数据。

## 未验证范围

- 只在 WSL 的 Python 3.14 上运行过单元测试与 `--help`；未在 macOS、Windows 原生 Python 或其他 3.10–3.13 解释器上实测。
- 迁移过程没有对真实 Hermes 会话库或真实 OMH 运行记录执行审计，因此未验证真实数据的 schema 变体、跨版本字段差异与大体量库上的耗时。
- 命令与路径识别规则只由现有单元测试覆盖，未用真实命令语料校准召回率与误报率。

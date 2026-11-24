# Pipeline 规范

Pipeline 是可持久化的流程图：**YAML 定义节点与连线，`control.py` 按事件推进，JSON 文件保存一次运行的进度。** 脚本不执行节点里的工作；实际操作由人或 agent 在已有权限内完成，再提交结果。

定义与运行使用扁平状态机。入口、事件和终点的设计参考 [Apache Commons SCXML](https://commons.apache.org/proper/commons-scxml/guide/scxml-documents.html) 和 [W3C SCXML](https://www.w3.org/TR/scxml/#BasicStateMachineNotation)。本仓使用下面的 YAML v1 格式，不支持 SCXML、调度、并行节点、条件表达式或自动执行。

## 目录与产出

`<name>` 是流程名称，与定义里的 `id` 一致；`<run-id>` 由发起人指定，在同一流程内不得复用。这两个名称都用小写字母开头的小写字母、数字和连字符。

| 路径（相对 `pipeline/`） | 放什么 |
| --- | --- |
| `pub/<name>/pipeline.yaml` | 可公开的流程定义。同目录的 `README.md` 可补充该流程的产出格式。 |
| `pub/<name>/data/` | 可提交的公开样例、测试资料或经人工确认可公开的交付件。 |
| `pri/<name>/pipeline.yaml` | 可选的私有流程定义。同名定义只能在 `pub`、`pri` 中择一；不会自动覆盖。 |
| `pri/<name>/data/` | 跨次复用的本地输入和数据。 |
| `pri/<name>/runs/<run-id>/state.json` | 每次运行的进度和事件证据，由控制脚本独占管理。 |
| `pri/<name>/runs/<run-id>/artifacts/` | 本次运行要保留的候选卡、报告等。由节点执行者按该流程的约定写入。 |
| `pri/<name>/runs/<run-id>/cache/` | 本次运行可重建的缓存与中间文件，不作为唯一证据来源。 |

运行即使使用公开定义，也始终写入 `pri`，脚本不会往 `pub` 写任何文件。`pri/` 整体由 Git 忽略；它不是凭据存储，也不是访问控制。流程执行者按需建数据和产出子目录，不在仓库其他位置落一套运行文件。证据用简短描述和相对路径（从 `run_dir` 起算），不塞入原始材料、不依赖本机绝对路径。对外公开时另做可公开的副本，经确认后再放入 `pub`；不复制整个运行目录，也不提交缓存、状态、原始样本或日志。

## 公开流程

- [提示词规则准入](pub/prompt-admission/README.md)：对单条候选做筛查、人审、观察和人工批准；只记录是否获准，不启用规则。

## YAML v1

```yaml
version: 1
id: example
initial: review
max_steps: 3

steps:
  review:
    instruction: 人工检查材料，补充后可重审，确认后结束。
    events:
      revise: review
      accept: done
  done:
    final: true
```

| 字段 | 规则 |
| --- | --- |
| 顶层 | 必填 `version: 1`、`id`、`initial`、`max_steps`、`steps`。`initial` 指向普通节点；`max_steps` 是 1–1000 的十进制整数。 |
| `steps` | 键是节点 ID。普通节点必填非空文本 `instruction` 和非空 `events`。说明写清做什么、何时能提交哪种事件；长说明可以用 `>-` 换行书写。 |
| `events` | 每行一个 `事件名: 目标节点`。可指回自身或任意已有节点。 |
| `final` | 写为 `final: true`，可附非空 `instruction`，不可声明 `events`。用不同终点区分成功、拒绝等结果。 |

- 定义是 UTF-8 编码的单个 YAML 文档。不接受重复键、未知字段、锚点、别名或显式标签。ID、事件名使用小写字母开头的小写字母、数字和连字符。标量按字段含义解释，不自动把 `on`、`no` 等事件名转成布尔值。
- 所有节点必须从入口可达，且每个节点都要有通往某个终点的路径；起点至少有一条能在步数上限内结束的路径。每次成功推进消耗一步，包含自环。最后一步到达终点仍为 `finished`；用完步数却未到终点为 `exhausted`，不能继续，也不算业务成功。
- 同一时刻只有一个当前节点。脚本只接受该节点列出的确切事件；不会自动选边。等待外部结果或人工决定时保持当前节点，不消耗步数。

## 操作

需要 Linux（包括 WSL 的 Linux 文件系统）、工具箱中可写的 `pipeline/pri/`（不存在时由 `start` 创建），以及装有 [PyYAML](https://pypi.org/project/PyYAML/) 的 Python 3.10+。用 `python3 -c 'import yaml; print(yaml.__version__)'` 确认所选解释器能导入 PyYAML，版本范围见 [`requirements.txt`](requirements.txt)。缺依赖时，在有安装权限的 Python 虚拟环境中运行 `python3 -m pip install -r pipeline/requirements.txt`。装好后，运行流程不联网。以下命令从工具箱根执行，示例只用合成证据。需要查看历史和回放时，先生成只读查看数据：

```sh
python3 pipeline/control.py validate pipeline/pub/prompt-admission/pipeline.yaml
RUN_ID="demo-$(date -u +%Y%m%d%H%M%S)"
python3 pipeline/control.py start prompt-admission "$RUN_ID"
python3 pipeline/control.py status prompt-admission "$RUN_ID"
python3 pipeline/control.py advance prompt-admission "$RUN_ID" --expect 0 --event prepared --evidence '合成演示：候选卡 DEMO-1 已准备'
python3 pipeline/control.py advance prompt-admission "$RUN_ID" --expect 1 --event revise --evidence '合成演示：审阅要求补反例'
mkdir -p pipeline/pri/prompt-admission/runs/"$RUN_ID"/cache
python3 pipeline/control.py status prompt-admission "$RUN_ID" --history --graph \
  > pipeline/pri/prompt-admission/runs/"$RUN_ID"/cache/view.json
# 在浏览器中打开 pipeline/viewer.html
```

| 命令 | 行为 |
| --- | --- |
| `validate YAML` | 只读检查指定 YAML 并输出节点、事件与目标；也可检查未归档的草稿。 |
| `start NAME RUN_ID` | 按名称找到唯一的流程定义，确认 `id` 与名称相同，创建新的私有运行目录并冻结 YAML 快照。 |
| `status NAME RUN_ID [--history] [--graph]` | 只读返回当前节点、可用事件、状态、修订号及定义 SHA‑256；`--history` 附事件历史，`--graph` 附完整节点和入口，供查看器使用。 |
| `advance NAME RUN_ID --expect REVISION --event EVENT --evidence TEXT` | 在文件锁内校验修订号和事件，记录非空证据，原子写入一次转换。修订号从 0 开始，自环也会加 1。若报错或遇到修订冲突，先查看 `status`，不要盲重试。 |

成功时 stdout 输出 JSON，退出码为 0；定义、状态或 I/O 错误写入 stderr，退出码为 1；参数解析错误为 2。三个运行命令都返回绝对路径 `run_dir`，以脚本所在的 `pipeline/` 为基准，与当前工作目录无关。受控定义和运行路径、`state.json` 不接受符号链接。等待中的运行仍为 `running`。只有 `status` 和 `validate` 是只读命令。

### 历史查看与回放

[`viewer.html`](viewer.html) 是零依赖、可离线打开的只读查看器。它不直接解析 `state.json` 或 YAML，避免浏览器端复制一套与 `control.py` 不同的解析规则。`status --history --graph` 生成的 JSON 可通过文件选择、拖放或粘贴载入查看器。

查看器支持流程图、当前节点、事件时间线和逐步回放。回放只移动内存中的游标，不修改状态，也不会调用 `advance`。游标回到最新位置且运行仍为 `running` 时，页面可以复制一条带占位证据的 CLI 命令；实际推进仍须回到命令行并重新核对 `revision`。

```sh
mkdir -p pipeline/pri/prompt-admission/runs/"$RUN_ID"/cache
python3 pipeline/control.py status prompt-admission "$RUN_ID" --history --graph \
  > pipeline/pri/prompt-admission/runs/"$RUN_ID"/cache/view.json
# 在浏览器中打开 pipeline/viewer.html
```

页面载入的数据只保存在当前页面内存中，关闭页面即丢弃。不要把 `view.json`、原始证据或运行目录复制到 `pub`。

## 状态和维护

- **运行态只走脚本。** 不直接创建、读写、补丁修改或复制 `state.json` 来改变流程位置。每次推进只记录可定位的最小证据（例如产物路径、审阅记录编号、失败原因），不要记录真实凭据或原始私有材料。
- `state.json` 由脚本管理，保存启动时的 YAML 快照及事件、证据和时间，当前节点从历史推导。状态更新用同目录原子替换；并行提交同一修订号最多接受一次。脚本入口和文件锁约束协作调用；两者不提供对同一系统账号的防篡改隔离，也不验证证据真假或人物身份。
- YAML 是源码，可按普通代码变更维护。改完先 `validate`，再开新运行试走受影响的分支、回环和终点。已有运行仍使用启动时的定义。旧版 YAML 运行不自动迁移；停掉推进后，可将整个运行目录原样移到 `pri/<name>/runs/<run-id>/` 的空闲位置，再用 `status <name> <run-id>` 核对。XML 原型创建的运行仍须用旧脚本续跑，或新开 YAML 运行。不要编辑快照。
- 当前支持一条流程中一次一步，由人或 agent 依据可观察结果选择事件。需要并行节点、表达式、调度或跨机共享状态时，先重新评估是否适合继续用这套文件机制。

## 验证

从仓库根运行 `python3 -B -m unittest discover -s pipeline/tests -v`。测试通过真实命令行和隔离的临时目录验证流程推进、快照、并发、目录约定及 `status --graph` 输出，不写入仓库的 `pri/`。查看器的布局和浏览器交互需要在 Chromium 或 Firefox 中手工检查。

未验证 macOS、Windows 原生环境、网络文件系统、断电恢复和不同宿主的 skill 自动触发。脚本、示例和测试均不依赖真实 bad case、外部 eval 平台或 CI。

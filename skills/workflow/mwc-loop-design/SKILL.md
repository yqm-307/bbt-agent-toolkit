---
name: mwc-loop-design
description: "Use when 用户不知道如何设计能自我迭代的 loop、loop DAG 或并行反馈流程，或要把性能、调研、实验目标写成不可执行的 Loop DSL 并检查语法、环、退出和阻塞条件；提供设计方法、代码式描述和静态检查，不执行 loop。"
related_skills: [mwc-sharpen, mwc-next-step]
---

# mwc-loop-design — 用不可执行 DSL 设计可收敛的 loop

帮助用户把一个目标设计成可交给其他工作流执行的 loop 描述。输出包含设计判断、Loop DSL 和静态检查结果；DSL 只描述节点、数据、并发、反馈、回流、退出和阻塞，不执行节点，也不直接启动 DAG、OMH 或任何外部工具。

## 先判断是不是需要 loop

触发在用户没有思路时：例如“不知道怎么让它自己迭代”“帮我设计一个 loop DAG”“调研、实验和评估怎么并行”“怎样保证循环不会无限跑”。普通的一次性修改、已经明确的执行计划或只需要一个下一步时，不强行套 loop。

目标、已有 plan、标准和权限保持不变。缺少会改变目标或关键边界的信息时，只问一个关键问题；可以合理默认的细节写成待验证条件，不用问卷把设计工作退回给用户。

## 优质 loop 的形式化检查

把一个 loop 先看成下面的结构，而不是一串“继续优化”的动作：

```text
L = (G, I, S, D, A, F, P, X, B, M, E)

G  目标：要改善什么，怎样观察改善
I  不变量：正确性、质量、权限、预算等不能被牺牲的条件
S  状态：下一轮必须继承的证据、假设、已试路径和未决问题
D  发现/发散：从哪里产生候选方向
A  尝试：如何用最小代价验证一个候选
F  反馈：哪些结果区分有效、无效和未知
P  减枝：怎样保留、改写、排除或暂停候选
X  退出：达到目标或完成明确的收敛条件
B  阻塞：没有反馈、预算耗尽、权限不足或无法安全推进时暂停
M  记忆：下一轮怎样拿到 S
E  边：节点如何回流、汇合和传递条件
```

最低有效条件可以写成：

```text
valid(L) = G ∧ reachable(entry) ∧ F ∧ P ∧ X
           ∧ ∀ cycle C: exit(C) ∨ block(C)
```

其中 `exit(C)` 或 `block(C)` 必须落在这个环里的节点上。只在 loop 根部写一个“最终达标就退出”，却没有给局部验证/修复环安排退出或阻塞条件，仍然是不完整的 loop。

更好的 loop 还应满足：

- `G` 是可观察结果，`X` 是可判断条件；“感觉更好”“继续看看”不能充当退出条件。
- `D` 允许发散，但 `P` 必须说明候选怎样按目标相关性、证据、验证成本和不变量减枝；无关、重复、已被证据否定或超预算的候选退出当前分支。
- `F` 必须改变下一步：有效时保留，无效时改假设或排除路径，未知时补观测；原样重试不算反馈回路。
- `B` 与成功退出分开。阻塞时说明缺什么，以及什么条件满足后可以重新进入；阻塞不是把失败伪装成完成。
- 并发分支要有明确的 `join` 或汇合节点，写清结果在哪里被比较和裁剪。`parallel` 只表达可并发，不代表已经执行。
- `S`/`M` 让下一轮记得结论、依据和已试路径，避免每轮重新发现同一个问题。

## 设计步骤

1. 写 `goal` 和 `invariant`，把目标、不可牺牲的标准和资源边界分开。
2. 选最小节点：发现、尝试、观察/评估、汇合。只有确实改变决策的节点才保留。
3. 指明 `entry`。有两条能同时推进的证据链就把多个入口或并行节点写清楚；不要用“并行”掩盖它们没有共享状态或汇合位置。
4. 给每条边写触发条件，并给每个环内的局部验证节点写 `exit when` 或 `block when`。
5. 写反馈分支和减枝规则：保留、改假设、排除、等待分别回到哪里。
6. 用检查器校验语法、引用、可达性、并发汇合和每个环的退出/阻塞条件，再把 DSL 交给 DAG 或 OMH 工作流解释。检查器只检查描述，永远不执行描述。

## Loop DSL

文件使用 `.loop` 后缀。语法刻意保持简单：每条声明独占一行并以 `;` 结束；字符串使用双引号；条件是不可执行的标签，只允许标识符以及 `and`、`or`、`not`；`does` 是给后续执行器看的意图，不是 Python、Shell 或 OMH 调度语句。

```text
loop NAME {
  goal "可观察的目标";
  invariant "不能破坏的标准";
  entry node_a, node_b;
  exit when target_met;
  block when no_signal or budget_exhausted;

  node node_a [kind=discover, run=parallel] {
    does "发现并筛选候选";
    reads current_state;
    emits hypotheses, evidence;
    exit when enough_evidence;
    block when source_unavailable;
  }

  node node_b [kind=experiment, run=parallel] {
    does "用固定条件验证一个候选";
    reads hypotheses, baseline;
    emits result;
  }

  node judge [kind=judge, run=gate] {
    does "比较反馈并决定保留、改写、排除或等待";
    reads evidence, result;
    emits decision, next_state;
    exit when target_met;
    block when no_signal;
  }

  join judge <- node_a, node_b;
  edge node_a -> judge when evidence_ready;
  edge node_b -> judge when result_ready;
  edge judge -> node_a when new_hypothesis;
  edge judge -> node_b when candidate_to_test;
}
```

节点 `kind` 可用 `discover`、`experiment`、`observe`、`judge`、`act`、`wait`、`gate`；`run` 可用 `serial`、`parallel`、`gate`。`join target <- a, b` 表示 `target` 要汇合多个分支，检查器会要求相应的 `a -> target`、`b -> target` 边存在。

完整的性能优化例子见 [references/cpu-optimization.loop](references/cpu-optimization.loop)。它让调研、实验和评估形成并发证据流，经 `feedback` 汇合后裁剪候选，再回流到下一轮；`target_met` 退出，`no_signal` 或 `budget_exhausted` 阻塞。

## 检查器

随 skill 提供的 `scripts/check_loop.py` 是静态检查工具，只读 `.loop` 文件，不运行 `does`，不执行边上的条件，也不派发任务：

```bash
python3 "$SKILL_DIR/scripts/check_loop.py" path/to/cpu-optimization.loop
python3 "$SKILL_DIR/scripts/check_loop.py" path/to/cpu-optimization.loop --format json
python3 "$SKILL_DIR/scripts/check_loop.py" path/to/cpu-optimization.loop --strict
```

它会检查：

- DSL 语法、字符串、属性、条件和数据名；
- `goal`、`entry`、根级 `exit`、节点 `kind/run/does`；
- 边、入口和 `join` 的节点引用；
- 从入口的可达性；
- 是否存在回环，以及每个回环内是否有 `exit when` 或 `block when`；
- 并行分支是否声明 `join`，是否有 `judge/observe` 反馈节点；
- `invariant`、阻塞条件和输出声明缺失时的 warning。

返回码为 0 表示没有 error；1 表示语法或结构错误，或 `--strict` 下存在 warning；2 表示文件读取或命令行错误。JSON 输出适合后续 DAG/OMH 适配器读取，但适配器仍需自行决定授权、调度和执行。

## 交给 DAG 或 OMH 的边界

Loop DSL 是设计契约：它表达“哪些节点可以存在、哪些结果触发回流、什么条件结束或阻塞”。DAG/OMH 等工作流可以把节点映射成任务、把 `join` 映射成汇合门、把 `exit/block` 映射成停止或等待门；映射过程必须另外保留用户目标、权限、不变量和证据要求。

本 skill 不代替 DAG/OMH 的执行规则，不假装已经并行、不启动 agent、不写外部状态。若用户只想先设计，就交付 DSL、检查结果和简短 ASCII 图；若用户后来明确要求执行，再由相应工作流读取并解释这份 DSL。

## 验证与边界

适用宿主是能加载 skill 并提供 Python 3.9+ 的环境；检查器只使用 Python 标准库，不需要第三方服务。脚本测试见 [tests/test_check_loop.py](tests/test_check_loop.py)，示例见 [references/cpu-optimization.loop](references/cpu-optimization.loop)：

```bash
python3 "$SKILL_DIR/tests/test_check_loop.py"
```

当前 11 项脚本测试在仓库内及独立目录均通过，覆盖有效的并发反馈 loop、空白/纯注释输入拒绝、缺少根退出、非法条件、环及局部子环没有退出/阻塞、join 缺边、不可达节点和 JSON CLI 输出。独立目录验证不代表已验证其他系统或 Python 3.9。尚未验证真实 DAG/OMH 适配器、模型是否稳定生成该 DSL、跨宿主触发或把 DSL 映射成实际调度；这些都不能由静态检查结果代替。

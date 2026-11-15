# mwc-loop-design 聚焦场景

以下是输入与人工判定要求；脚本测试另见 `tests/test_check_loop.py`。这些场景尚未作为真实模型评测运行。

## 1. 性能优化的并行 loop

输入：

> 我的目标是降低 CPU 消耗。我想让一路持续调研，一路持续测试实验，还有一路持续评估，结果汇合后再决定下一轮怎么走。帮我用 mwc-loop-design 写成可以交给 DAG/OMH 的描述，但先不要执行。

应满足：输出不可执行的 `.loop` 设计；至少有 research、experiment、evaluate/feedback 节点；调研和实验可并行；有 `join` 或等价汇合；反馈会改变下一轮候选；根部有目标退出；环内有局部 `exit when` 或 `block when`；不声称已经并行或已经降低 CPU。

## 2. 发散后减枝

输入：

> 我想改善一个慢服务，但可能有缓存、数据库、序列化和线程调度四个方向。怎么设计 loop 才不会把四个方向无限展开？

应满足：把候选产生、证据收集、验证成本和选择规则写进 `discover` / `judge` / `experiment` 的关系；明确无关、重复、无证据或超预算候选如何退出当前分支；不能只写“持续寻找优化点”。

## 3. 环没有局部出口

输入 DSL：

```text
loop repair {
  goal "验证修复";
  entry test;
  exit when done;
  node test [kind=experiment] {
    does "反复测试";
    emits result;
  }
  edge test -> test when retry;
}
```

应满足：检查器报告 `CYCLE_NO_STOP`；根部的 `exit when done` 不能替代环内的 `exit when` 或 `block when`。修复后的建议至少补一个可观察的局部退出或阻塞条件。

## 4. 并发汇合缺边

输入 DSL 声明 `join evaluate <- research, experiment;`，但只存在 `research -> evaluate`。

应满足：检查器报告 `JOIN_EDGE_MISSING`，指出缺少 `experiment -> evaluate`；不把 `join` 当成已经执行的调度器，也不自动补写用户的设计。

## 5. 只有一次修复的任务

输入：

> 帮我把这段说明里的错字改掉，并检查一遍。

应满足：不因出现“检查”就强行创建 loop；说明一次性修改→核对已经足够，必要时给一条无回边的路径；如果用户明确要求写 DSL，检查器可以把无回边报告为 `NO_CYCLE` warning，而不是伪造持续迭代。

## 6. 缺少关键目标

输入：

> 我想设计一个能自我迭代的 loop，帮我写 DSL。

上下文没有目标、标准、输入源或权限边界。

应满足：只询问会改变设计的关键问题，优先问“要改善的可观察结果是什么”；不编造通用节点、指标或退出条件，不为了生成代码样例而假装目标已经明确。

## 共同判定

关注设计能否回答：目标是什么、状态从哪里来、如何发散、如何减枝、反馈如何改变下一步、并发在哪里汇合、每个环怎样退出或阻塞。DSL 只是描述语言，不能触发外部动作；检查器只报告语法和结构问题，不能把静态通过说成行为完成。

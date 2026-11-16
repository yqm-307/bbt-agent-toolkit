# 审查委托信封（派发侧模板）

正式审查派发前填写本模板，整块粘进 `delegate_task` 的 `context`。缺必填字段不是"简短委托"，而是不合格委托：审查者应按 `NEEDS_CONTEXT` 返回，不自行补全目标或范围。

## 模板

```yaml
role: reviewer
# 附 reviewer 身份契约（agents/reviewer/AGENTS.md）正文；子代理通常不继承角色身份
review_contract: <目标仓定义的提交审查契约标识；无则省略>
review_package: <审查包绝对路径>
candidate: <完整基线 SHA / 候选指纹>
diff: <diff 文件路径或 git 命令>
reuse: <上轮报告路径 + 问题 ID 对账；无则写 none>
scope:
  read: <允许读取的文件/目录清单>
  forbid: 修改受审内容、commit、push、部署、读 secret
budget: <工具调用上限 / 时间上限>
report: <报告落盘路径>
verdict_enum: 可提交 | 条件提交 | 不建议提交 | BLOCKED
output_schema: <JSON Schema 对象，由调用方填入 delegate_task.output_schema>
```

## 字段规则

- `role`：必须附角色正文。以 Hermes 为例，原生子代理只继承工作区 `AGENTS.md`，不继承派发方的角色身份或 SOUL。
- `review_contract` / `review_package`：两者同时出现才构成提交审查入口；缺一按普通意见处理，不出"可提交"结论。
- `candidate`：不接受分支名、`HEAD` 或"最新候选"这类会漂移的描述；复审必须给上轮报告路径与问题 ID，否则旧结论不可对账。
- `scope.forbid`：只读是硬边界，不是礼貌用语；写清禁止项，审查者不得因"顺手修一下"越过。
- `verdict_enum`：用目标仓审查政策的枚举；无政策时用 [review-methods.md](review-methods.md) §11 的四值，不另造 `ship/no_ship`、`pass/fail` 等平行枚举。
- `report`：先落盘再回传路径；没有报告文件的结果不算审查完成。

## 派发后自检

1. 信封里的每个路径都真实存在且可读（审查者在隔离 profile / 子代理上下文里同样可读）。
2. `candidate` 与 `diff` 指向同一版本，没有在派发后又改动候选。
3. 若给出 `output_schema`，`verdict`、`evidence`、`uncovered` 三个字段可机器校验，避免结论含糊。

## 与运行时门禁的关系

本模板是派发方的填写标准，不构成运行时强制。要让缺信封的委托无法发出，需在 `delegate_task` 前加 `pre_tool_call` 钩子拦截；未接该门禁前，本模板靠派发方自律执行。

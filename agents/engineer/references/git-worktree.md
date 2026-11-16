# 在 worktree 或分支上提交

linked worktree 与主仓共享对象库和分支引用，但各有独立的工作树与索引。在 worktree 内 `git add` + `git commit` 会推进它当前 checkout 的分支，这是正确做法。

## 红线

- 不切到主仓目录（通常 checkout 着 `main`）为 worktree 里的文件提交——会进错分支。
- 不嵌套新建 worktree 去提交已有 worktree 的工作。
- 并行任务各用一个分支；同一分支不能被两个 worktree 同时 checkout。
- 提交、推送、开 PR、合并分别需要授权；有提交授权不等于可以推送。

## 安全提交流程

```bash
git branch --show-current          # 当前分支就是目标分支
git status --short                 # 只含本任务文件
git add <paths>                    # 精确暂存，不混无关变更
git diff --cached --check          # 暂存区空白错误
git diff --cached --stat           # 回读暂存范围
git commit -m '<按目标仓约定的标题>'
git log --oneline --decorate -3    # 新提交在目标分支上
git status --short --branch        # 工作树干净
```

获准推送时显式写分支：`git push -u origin <branch>`。开 PR 后用平台工具回读编号、状态和 head SHA，不采信命令自报。

## 整理未提交变更

- 先完整盘点：未暂存、已暂存、未跟踪、本地领先远端的提交分别列出。
- 按可独立理解与回滚的主题分组提交；每组暂存后回读范围。
- 日志、PID、会话 token、端口文件等运行态产物不提交；需要忽略时在根 `.gitignore` 加稳定规则，并用 `git check-ignore -v <实际文件>` 验证（目录模式要带尾斜杠，否则对不存在的路径会误报未忽略）。
- 迁移类变更：新路径已被跟踪，旧路径在活动代码、配置、文档里没有残留引用。

## 盘点进行中的 worktree

不能只看主工作树的 `git status`。对 `git worktree list` 里的每个非主 worktree 看 `status`、`log main..HEAD` 和未提交 diff：有未合并提交或未提交改动就是进行中，不清理；`prunable` 只说明记录的路径可能失效，不证明任务完成。

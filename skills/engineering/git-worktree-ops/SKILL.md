---
name: git-worktree-ops
description: "Use when committing or pushing from a linked worktree, hardening a repo's .gitignore, inventorying in-progress worktrees, or turning uncommitted changes into reviewable commit groups."
version: "1.0.0"
metadata:
  hermes:
    tags: [git, workflow, hygiene]
---

# Git Worktree Ops（worktree 内提交与仓库卫生）

与 using-git-worktrees（负责创建/隔离）互补：本技能负责已在 worktree 内时的**提交、推送与 .gitignore 卫生**。

## 适用条件与依赖

- `git worktree` 需要 git ≥ 2.5；创建/列举/改忽略规则的命令与平台无关。
- 第 1 节的 PR 部分需要 `gh` CLI 且已登录能访问该远端；没有 `gh` 时只是少了建 PR 的能力，其余照常可用。
- 不需要额外的配置文件或环境变量。
- 文中的目录（`.worktrees/`、`web/`、`internal/static/`）和分支名（`feat/<topic>`）是**占位示例**，按目标仓库的实际布局替换，不要原样套用。
- 验证记录：忽略规则陷阱与 worktree 行为在 git 2.53.0 / gh 2.46.0 的 Linux 环境实测过（见各节）；未在 Windows 原生 shell 与非 GitHub 远端（GitLab 等）实测，相关流程属未验证范围。

## 1. worktree 内提交的正确方式

**核心语义：** linked worktree 与主仓**共享同一个 .git 对象库**，但每个 worktree 有独立的工作树和索引。因此在 worktree 里执行 `git add` + `git commit`，提交直接推进**当前 checkout 的分支**（如 `feat/<topic>`），对象与分支引用写入共享对象库——这是标准且正确的做法。

**红线：**
- 绝不切到主仓目录（通常 checkout 的是 `main`）为 worktree 的文件 add/commit——会提交到错误分支。
- 绝不嵌套创建新 worktree 来提交已有 worktree 的工作。
- 并行任务各自用不同分支：同一分支不能被两个 worktree 同时 checkout（git 会拒绝并指出占用它的路径，实测如此）。索引彼此独立，但对象库与分支引用共享，所以并发提交只在分支不冲突时才互不干扰。

**安全提交流程：**
```bash
git branch --show-current          # 1. 确认当前分支就是目标分支
git status --short                 # 2. 确认只含本任务文件
git add <paths>                    # 3. 精准暂存，禁混无关变更
git diff --cached --check          # 4. 暂存区空白错误检查
git diff --cached --stat           # 5. 确认暂存范围
git commit -m '<type>: <summary>'  # 6. 遵循仓库既有 commit 约定
git log --oneline --decorate -4    # 7. 确认新提交在目标分支上
git status --short --branch        # 8. 工作树干净
```
推送显式指定分支：`git push origin <branch>`（不要依赖当前分支猜测）。

**push + 建 PR 均可在 worktree 内完成，无需回主仓：**
```bash
git push -u origin <branch>          # worktree 内推送当前分支并建立跟踪
gh pr create --base main --head <branch> \
  --title 'feat: ...' \
  --body-file - <<'EOF'
## 概要
...PR 正文（含验证证据、安全说明、已知非阻塞项）...
EOF
gh pr view <n> --json number,title,url,state,headRefName,headRefOid \
  --jq '{number,title,url,state,sha:.headRefOid}'   # 回读核验 PR 真实创建
```
- 分支推送后远端会提示对应的 compare/PR 链接；用 `gh pr create --head` 显式指定 base/head，不用交互。
- PR 正文自包含：概要、真实验证结果、安全/部署说明、已知非阻塞项。
- 创建后必须用 `gh pr view` 回读 URL/state/head SHA 核验（`git ls-remote` 可交叉确认分支已推送），不采信自报。
- 用户说"帮我提交"但本地只有 commit、未推送时，先问清"仅推送"还是"推送并建 PR"，再动手。

## 2. .gitignore 加固清单

下面的目录是**单仓示例**（Go 服务端 + React 前端 + Docker 部署）：规则类别通用，路径按自己的实际布局替换。

基线（worktree 场景）：
```
.worktrees/          # 若采用在仓内集中存放 linked worktree 的约定，必须忽略它本身
web/dist/
web/node_modules/
```
把 worktree 放在仓内固定目录（如 `.worktrees/`）是常见约定；实测在仓根 `.gitignore` 写入 `.worktrees/` 后，该目录下的 worktree 不会被主工作树记为未跟踪。若选择放在仓外，就不需要这条规则。

常见缺口——检查时逐项确认：
```
# E2E/浏览器测试产物（否则每次跑测试都污染 git status）
web/test-results/
web/playwright-report/
web/blob-report/
# 凭据（.dockerignore 有了不代表 .gitignore 也有——两处都要）
.env
.env.*
*.pem
*.key
secrets/
# 测试/工具
coverage/
coverage.out
tmp/
*.log
.DS_Store
.idea/
.vscode/
```
注意：
- `.dockerignore` 与 `.gitignore` 是**两套独立规则**，凭据类必须两边都覆盖。
- 构建期需要存在但内容可空的占位文件（如 Go 的 `internal/static/dist/placeholder.txt`，供 `go:embed` 使用）**必须保持 git 跟踪**，保证干净 clone 上 `go build ./...` 可用；不要因为它是"占位"就忽略所在目录。
- 只靠目录内部的 `.gitignore`（内容为 `*`）实现忽略是**脆弱机制**（依赖未跟踪文件存在，clone 或清理后就失效），应在根 `.gitignore` 显式补一条。

## 3. 验证忽略规则：check-ignore 陷阱

**陷阱：** `git check-ignore -q web/test-results` 对**不存在的目录路径**（无尾斜杠）会返回 NOT IGNORED，即使模式 `web/test-results/` 确实匹配——git 无法判断它是文件还是目录，而尾部 `/` 模式只匹配目录。实测：同一仓库里无尾斜杠返回退出码 1，带尾斜杠正常命中并给出 `.gitignore` 行号。

**正确验证方式：**
```bash
git check-ignore -v web/test-results/    # 目录模式带尾斜杠
# 或模拟真实产物：
mkdir -p web/test-results web/playwright-report coverage
touch web/test-results/a.txt web/playwright-report/index.html coverage/out.txt
git status --short                        # 应只显示真实修改，不显示产物
rm -rf web/test-results web/playwright-report coverage
# 确认已有跟踪文件不受影响：
git ls-files internal/static/dist/        # placeholder 仍被跟踪
```

## 4. 盘点进行中 worktree（任务续接/仓库状态检查）

当用户问“有没有进行中的任务”或仓库存在多个 worktree 时，不能只看主工作树的 `git status`，也不能把 `prunable` 当作“可安全删除”或“已完成”的结论。采用只读盘点：

```bash
# 主仓：当前残留与所有 linked worktree
 git status --short --branch
 git worktree list

# 对每个非主 worktree（包括 prunable）分别检查
 git -C <worktree> status --short --branch
 git -C <worktree> log --oneline main..HEAD
 git -C <worktree> diff --stat main...HEAD
 git -C <worktree> diff --stat              # 未提交改动
```

判读规则：
- **分支有未合并提交或未提交代码**：标为进行中/待收口；报告分支、路径、改动文件和验证状态，勿清理。
- **仅 `prunable`**：表示 Git 记录的 worktree 路径可能失效，不证明任务完成；先确认目录可达、分支与改动后才提议 `git worktree prune`。
- **主仓未跟踪 build 目录或计划文件**：单独列为残留/待分类，不归因给某个 worktree，也不擅自删除。
- 若存在与任务名相符的计划文件，读取其目标与 checklist；计划未打勾不是实现状态的唯一证据，必须同代码和测试记录交叉判断。

交付时区分：`明确进行中`、`已收口但待清理`、`未分类残留`、`仅可选后续工作`。不要把“用户尚未授权启动”的选项汇报为正在执行。

## 5. 整理未提交变更并归档（非 worktree 同样适用）

用户要求“整理并归档本地未 commit 变更”时，不要把全部变更粗暴塞入一个提交，也不要将暂存、提交和推送混为一件事。

1. **定位仓库。** 先用显式仓库路径执行 `git -C <repo> status`；若当前 shell 的 cwd/环境异常，不能据此断言“不是 git 仓库”。
2. **完整盘点。** 并行读取 `git status`、`git diff --stat`、`git diff --cached --stat`、`git status --porcelain --untracked-files=all` 与 `git log --oneline @{upstream}..HEAD`。分别报告：未暂存、已暂存、未跟踪、以及既有本地未推送提交。
3. **按原子主题分组。** 将文档、迁移/配置、独立功能、生成物或运行态残留分开；每组提交须可独立理解和回滚。先逐个 `git add <精确文件列表>`，每组都用 `git diff --cached --stat` 回读范围。
4. **运行态与敏感产物。** 对未跟踪目录先看文件名和最小必要内容，识别端口、PID、日志、会话 token、URL key 等。此类运行态产物不得提交；在根 `.gitignore` 添加稳定的目录规则。用 `git check-ignore -v <实际文件>` 和 `git status --short` 验证规则确实生效，且不误伤已跟踪文件。
5. **验证和独立审查。** 运行仓库规定的 lint/test 与 `git diff --cached --check`；仓库要求独立审查时，在提交前由未参与实现的人审查暂存 diff 的分组、跨文件迁移引用、敏感信息及功能代码。主执行者自检不替代独立审查。
6. **提交与推送分离。** review 通过后按组提交；提交完成后再次检查工作树。只有用户明确要求推送，或已确认“归档”包含远端同步时，才 push。若本地已有领先远端的提交，要单独说明数量和推送影响，不能自行推送。

**迁移类变更的额外检查：** 新路径必须已被 Git 跟踪；旧路径删除后，在活动代码/配置/文档范围内检索旧引用，历史 plans/decisions 可按仓库规则排除。执行仓库的迁移 lint，不能只凭目录存在判断成功。

## 6. 验证清单（完成前）

- [ ] `git diff --check` 通过
- [ ] `git diff --cached --check` 通过；每组暂存范围已回读
- [ ] 新忽略规则对**真实产物文件**生效（`git check-ignore -v <实际文件>`；`git status` 不再显示它）
- [ ] 构建期占位文件（如 `go:embed` 目标）仍被跟踪
- [ ] 无非忽略的未跟踪文件：`git ls-files --others --exclude-standard` 为空（若用户要求完整收口）
- [ ] 迁移的新路径受跟踪、活动范围无旧引用、仓库 lint/test 通过
- [ ] 仓库要求的独立审查已完成（若适用），阻断问题已修复
- [ ] 提交落在目标 worktree 分支上（`git log` + `git status --branch` 确认）
- [ ] 推送状态已明确告知或按授权完成

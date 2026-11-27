---
name: git-worktree-ops
description: "Use when committing or pushing from a linked worktree, closing out a branch through PR, CI and merge, hardening a repo's .gitignore, inventorying in-progress worktrees, or turning uncommitted changes into reviewable commit groups."
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

## 0. 收口与盘点：先用现成命令

`scripts/git_closeout.py`（Python 3.10+，只用标准库；`ship` 需要已登录的 `gh`）把第 1 节的推送/PR 与第 4 节的盘点做成了命令，固定流程不再逐步手敲：

```bash
python3 "$SKILL_DIR/scripts/git_closeout.py" census <repo>... [--fetch] [--json]   # 只读盘点
python3 "$SKILL_DIR/scripts/git_closeout.py" sync                                   # 把本地基线安全快进到 origin/<base>
python3 "$SKILL_DIR/scripts/git_closeout.py" ship [--title T] [--body-file F]       # 在功能分支的工作区里运行
```

- `census`：列出每个 worktree 与本地分支是「进行中 / 已合并可清理 / 无独有提交」，以及基线是否落后、能否快进。squash 合并要靠 `gh` 里指向同一基线的 PR 记录识别，`--no-gh` 或 gh 读取失败时会显示为未合并。基线、默认分支与 main/master 不列为可清理。
- `ship`：推送 → 开或复用 PR（只复用同仓、指向本基线的 PR）→ 等 CI → 合并（默认 squash，`--match-head-commit` 锁定刚验证的提交）→ 确认合并提交已在 `origin/<基线>` → 快进本地基线 → 清理 worktree、本地与远端分支。清理只删仍停在已合并 head 上的对象：worktree 已切走、分支或远端已推进时保留并说明。工作区不干净、没有新提交、在长期分支上、CI 失败或超时、PR 是草稿、分支保护拦截（`BLOCKED`/`BEHIND`/`DIRTY`）时停下并以退出码 2 说明原因；不强推、不强删、不绕过保护。`--no-merge` 停在合并前，`--keep-worktree` 不清理。
- 用户一句「收口」「提 PR，CI 绿了合掉」就是对整条链的授权，不逐步再问；仓库规范写明不自行合并时，用 `--no-merge` 停在合并前再问。基线工作区有别人的未提交改动时只报告、不快进。
- 例外：基线工作区的未提交改动正是刚合入远端的内容时（如先拆到 worktree 提交并 ship 的本地积压），先证明再快进：`HEAD` 是 `origin/<基线>` 的祖先；`git diff --binary HEAD` 导出的补丁，在用 `git read-tree origin/<基线>` 初始化的临时 `GIT_INDEX_FILE` 上能通过 `git apply --cached --reverse --check`；没有进程占用工作区。三项都成立才 `git stash push` → `git merge --ff-only origin/<基线>` → 成功后 `git stash drop`；任一项不成立仍只报告、不快进。未跟踪文件不在这项检查里，保持原样。
- `sync`：对应「把 main 更新到最新」。基线工作区干净就快进；有未提交改动时停下并说明，只有改动经覆盖证明正好是刚合入远端的内容（如 ship 拆出去的本地积压）才 stash 快进再 drop——证明用 `git diff --binary HEAD` 在 read-tree origin/<base> 的临时索引上反向 apply。基线有未推送提交、无法快进时都停下（退出码 2）。未跟踪文件不参与覆盖证明，保持原样。同步前先 `census` 盘点：有未提交改动的 other worktree 不在 sync 范围内，只报告。
  竞态上限：证明到 stash push 之间没有占用检查，窗口内若有进程新写入改动，会被 stash 捕获并随 drop 丢失——sync 只在没有活跃任务写基线工作区时使用；窗口本身毫秒级，无法靠检查闭合。
- 输出 JSON 里的 PR 链接、合并 SHA、CI 结果（`pass`；`none` 表示宽限期内一直没观察到检查，不等于检查通过）就是交付证据，原样转述，不另写「已验证」。

回归：`python3 -B -m unittest discover -s tests`（在本 skill 目录执行；真实 git + 本地裸远端 + `tests/gh_stub.py` 替身）。真实 GitHub 上的 `ship` 以首次实跑记录为准。

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
仓库要求审查票时，推送前（包括运行 `ship` 前）核对票据的基线、目标提交和覆盖范围是否与实际审查证据一致。覆盖不足时先补审，不将定向复审填为全量通过。

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
- **含 submodule 的 worktree**：`git worktree remove` 会报 `working trees containing submodules cannot be moved or removed`（即使工作树干净）。确认无未提交改动后，直接 `rm -rf <worktree目录>` 再在所属仓 `git worktree prune` 清理登记；submodule 内容只是检出，无独有数据。
- **主仓未跟踪 build 目录或计划文件**：单独列为残留/待分类，不归因给某个 worktree，也不擅自删除。
- 若存在与任务名相符的计划文件，读取其目标与 checklist；计划未打勾不是实现状态的唯一证据，必须同代码和测试记录交叉判断。

- 交付时区分：`明确进行中`、`已收口但待清理`、`未分类残留`、`仅可选后续工作`。不要把“用户尚未授权启动”的选项汇报为正在执行。

### 含未提交改动的 worktree：删除前恢复验证

盘点阶段不清理。获准收口后，记录并保全该 worktree 的 `HEAD`，用 `git diff --binary --full-index HEAD --` 导出已跟踪文件的净变化。用 `git read-tree` 从该基线初始化临时 `GIT_INDEX_FILE`，以 `git apply --cached` 回放，对照原工作树核对路径（含删除）、blob 内容与 Git 文件模式。将补丁、基线 SHA 和核对清单保存在待删目录之外；另行盘点并验证需保留的暂存状态、未跟踪文件和忽略文件。

删除前复查没有新增未保全的改动、依赖子仓干净且无未保全的独有提交、没有进程占用目录。普通 worktree 收口至干净后才用 `git worktree remove`；若命令拒绝，不擅自强删。含 submodule 的清理同样受上述门槛约束，不得仅凭父仓干净就删除。已确认收口且干净的 worktree 可跳过补丁回放；仅有远端引用不算收口。

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

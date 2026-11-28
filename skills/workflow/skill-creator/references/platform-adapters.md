# 平台差异与降级路径

上游 skill-creator 面向 Claude Code / Claude.ai / Cowork 三种环境，能力不同。移植到 Hermes 后由宿主能力决定走哪条路径，不要假装不存在的工具可用。

## 能力矩阵

| 能力 | 有子代理（如 Hermes / Claude Code / Cowork） | 无子代理（如 Claude.ai 对话环境） |
|---|---|---|
| 测试用例执行 | 每条用例与 baseline 并行派子代理 | 串行，自己按 skill 指令逐条完成任务 |
| baseline 对照 | 有 | 跳过（自己写了 skill 又自己跑，对照意义不成立） |
| 定量 benchmark | 有 | 跳过，只看定性反馈 |
| viewer | 起服务或用 `--static` | 直接在对话里贴结果 |
| 盲对比 | 可用 | 不可用 |
| description 优化 | 取决于能否非交互调用模型（`claude -p` 或等价 CLI） | 通常不可用 |

## 所在仓库的门禁

上游 skill-creator 是通用框架，不含具体仓库的约定。新建或修改 skill 时额外遵守所在仓库的规范，常见检查项：

### 目录与索引

- 所在仓库通常检查 skill 引用可解析、frontmatter `name` 唯一且与目录同名；如仓库有索引生成物（如 `skills/INDEX.md`），新增 skill 后按其命令重生成。
- 本仓库（bbt-agent-toolkit）的引用检查：`python3 tools/prompt-health/prompt_health.py`，reference_errors 须为 0。

### SKILL.md 体量

- 官方建议 500 行以内（组织建议）；个别仓库对 `AGENTS.md` 有跨 harness 字节预算，那不是 SKILL.md 的门禁。

### 完整验证序列

按所在仓库的验证入口执行（lint、提交前预检、空白检查），FAIL 为 0 才可继续。

## Claude.ai 式环境的降级

核心流程不变（起草 → 测试 → 评审 → 改进 → 重复），只改机制：

- **跑用例**：无子代理则无并行。逐条读 skill 的 SKILL.md，按指令自己完成测试 prompt；一次一条。严格性弱于独立子代理（既写了 skill 又跑它，上下文全知），但作为健全性检查有用，人工评审环节可补足
- **看结果**：开不了浏览器就跳过 viewer，把 prompt 与产出直接摆进对话。产出是用户需要看的文件（`.docx`、`.xlsx`）就存到文件系统并告知路径，让他自己下载查看，并就地问「这样行吗？想改哪儿？」
- **benchmark**：跳过。它依赖 baseline 对比，无子代理时对比不成立
- **description 优化**：本节依赖 `claude -p` 这类非交互调用，只有相应 CLI 可用时才跑，否则跳过
- **盲对比**：需要子代理，跳过
- **打包**：`package_skill.py` 只要 Python 和文件系统就能跑，任何环境都可打包，让用户下载 `.skill`

## 更新已有 skill（而非新建）时的额外约束

- **保留原名**：用该 skill 已有的目录名与 frontmatter `name`，不做 `-v2` 之类的改名。已装的是 `research-helper`，产出就是 `research-helper.skill`
- **改前先复制到可写位置**：已安装路径可能只读，先 `cp -r` 到临时目录再改、再打包
- **手工打包先在临时目录暂存**，再复制到输出目录——直接写入可能因权限失败

## 无浏览器环境的反馈回收

没有常驻服务时，viewer 的「提交全部评审」会把 `feedback.json` 下载成文件，而不是回传到服务器。你需要主动去下载目录取最新那份（可能有 `feedback.json (1)` 这类重名版本），复制进 workspace 供下一轮读取；必要时先申请访问权限。

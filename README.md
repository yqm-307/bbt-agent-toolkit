# bbt-agent-toolkit

可独立复用的 Agent 技能、提示词优化方法、插件与辅助工具。

## 范围

收录通用能力及其使用说明、测试和来源；不收录个人角色与偏好、私有运维资料、机器配置、账号信息或实际部署记录。公开内容必须在没有私有仓库的前提下可理解、可使用，不承诺兼容未经验证的宿主或版本。

## 目录约定

```text
bbt-agent-toolkit/
├── README.md                 # 项目介绍、范围和使用导航
├── AGENTS.md                 # 唯一协作规则入口，含提交规范
├── .gitignore
├── skills/<domain>/<skill-name>/ # 按能力域分类，每个 skill 独立成包
├── plugins/<host>/<name>/    # 按宿主隔离的插件源码、说明与测试
├── tools/<tool-name>/        # 可独立运行的辅助工具、说明与测试
├── docs/guides/              # 跨组件使用指南
├── docs/knowledge/           # 跨组件知识与原理
└── docs/decisions/           # 架构与维护取舍
```

已收录 skill 分类：

| 能力域 | Skill |
|---|---|
| `coding-style` | `clean-code`、`coding-format`、`coding-documentation` |
| `assurance` | `test-case-design` |
| `engineering` | `context-prefix-slimming`、`git-worktree-ops` |
| `knowledge` | `decision-matrix` |
| `prompt-opt` | `prompt-denoise` |
| `workflow` | `chinese-documentation`、`harness-neutral-agent-prompts`、`mwc-bro`、`mwc-chat-end`、`mwc-in-your-own-words`、`mwc-ketchup`、`mwc-recall`、`mwc-sharpen`、`mwc-teach` |

分类仅用于导航，不改变 skill 名称；`mwc-*` 直接放在 `workflow/` 下，不额外增加族目录。

目录按实际内容创建；上图是结构约定，不表示所有能力已交付。组件专属的参考资料、脚本、模板和测试随组件保存，不在根目录重复归档；只有跨组件验证才放根 `tests/`。已收录 17 个 skill（见上表）；部分资产许可待定，不代表可公开发布。下列验证状态只记录实际执行过的检查，未列出的检查均未执行；未建立统一验证命令或 CI。

- `clean-code`：`scripts/check_examples.py` 在 WSL2（g++ 15.2.0、Python 3.14.9）实跑通过（3 个 C++17 示例与本地链接检查，退出码 0）；未在其他平台验证。
- `coding-format`：`scripts/validate.py` 未运行。
- `coding-documentation`：`scripts/validate.py` 未运行。
- `decision-matrix`：`scripts/check_fixtures.py` 未运行。
- `git-worktree-ops`：无可执行入口；`.gitignore` 尾斜杠与同分支多 worktree 两条行为断言在临时仓中实测，未执行 push 与 `gh pr create`。
- `prompt-denoise`：`tests/` 离线单元测试 11 项通过（Python 3.14.9、3.11）；`scripts/extract_inventory.py` 在两份真实提示词上实跑（一份 241 句；一份带 `--follow` 共 10 个文件、2162 句，触发清单过大提示）。完整流程在 Hermes 中对一份 241 句的角色提示词实跑一次：三路子代理并行产出 39 条发现，`--verify` 查出 1 条编号错误，合并为 26 处建议；未做改前改后的行为对比。未在 macOS、Windows 或 Python 3.10、3.12、3.13 上实测。
- `mwc-chat-end`：`scripts/session_archive.py self-test` 实跑通过（Python 3.14.9）；WebApp 侧 `check` 在真实会话上运行，`hermes sessions archive` 的 `--include-open` 归档在一次性会话上实测并读回，当前会话做过归档→读回→恢复往返；压缩轮换后的回退路径与 WebUI 分支只有自检覆盖，真实 WebUI `check` / `archive` 未运行。
- 无可执行入口的提示词类 skill（`chinese-documentation`、`context-prefix-slimming`、`harness-neutral-agent-prompts`、`mwc-bro`、`mwc-in-your-own-words`、`mwc-ketchup`、`mwc-recall`、`mwc-sharpen`、`mwc-teach`、`test-case-design`）：只做了 frontmatter 与相对链接检查，提示词效果未在宿主中实测。
- [mm-disclosure 插件](plugins/hermes-agent/mm-disclosure/README.md)：离线单元测试 15 项通过；`hermes plugins doctor --ci` 通过（0.3.0，3 个 hook）。未验证宿主实际加载与新会话首轮注入，未对真实 Hindsight 服务端做端到端测试。
- [custom-prompt-inject 插件](plugins/hermes-agent/custom-prompt-inject/README.md)：按 JSON 条件把自定义提示词注入 system prompt 或 user context；本地离线测试结果以组件 README 为准，未验证宿主实际加载与 WebUI/CLI/gateway 端到端送达。
- [omh-dag-boundary 插件](plugins/hermes-agent/omh-dag-boundary/README.md)：离线单元测试 13 项通过。未验证宿主 `pre_tool_call` 改写行为、真实 OMH 派发链路与宿主版本兼容性。
- [prompt-health 工具](tools/prompt-health/README.md)：本次迁移未改动、未重新运行检查，因此此处不给出验证结论。
- [dag-scope-audit 工具](tools/dag-scope-audit/README.md)：离线单元测试 23 项通过；`--help` 正常退出，`--db` 指向不存在的文件时报错并退出 2。未在真实会话库或真实 OMH 运行记录上执行；未在 macOS、Windows 或 Python 3.10–3.13 上实测。
- [dag-subagent-scope-control.md](docs/knowledge/dag-subagent-scope-control.md)（知识文档）：文内相对链接、仓库路径与引用的测试数（插件 13 项、工具 23 项）已核对；文档只描述通用方法与限制，不含本机运行样本。

## 使用与贡献

选择需要的组件，按其说明接入目标宿主；不提供默认启用全部能力的安装方式，不自动改写用户配置。宿主相关的工具与前置条件必须由组件说明。

目录、验证、迁移和 Git 提交规则见 [AGENTS.md](AGENTS.md)。

## 许可证状态

仓库整体许可证尚未选定；公开可见不等于已授予整体再分发许可。引入第三方内容前须核实授权、保留适用的许可证与署名，并注明来源及本地修改；不得用未来的根许可证覆盖第三方原有条款。

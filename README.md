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

首批 skill 分类：

| 能力域 | Skill |
|---|---|
| `coding-style` | `clean-code`、`coding-format`、`coding-documentation` |
| `assurance` | `test-case-design` |
| `engineering` | `context-prefix-slimming` |
| `knowledge` | `decision-matrix` |
| `workflow` | `chinese-documentation`、`mwc-bro`、`mwc-in-your-own-words`、`mwc-sharpen`、`mwc-teach` |

分类仅用于导航，不改变 skill 名称；`mwc-*` 直接放在 `workflow/` 下，不额外增加族目录。

目录按实际内容创建；上图是结构约定，不表示所有能力已交付。组件专属的参考资料、脚本、模板和测试随组件保存，不在根目录重复归档；只有跨组件验证才放根 `tests/`。首批 11 个 skill 已收录：本批迁移**未运行任何测试或验证脚本**，也未在新机器验证；部分资产许可待定，不代表可公开发布。已收录 [model-guidance 插件](plugins/hermes-agent/model-guidance/README.md)、[mm-disclosure 插件](plugins/hermes-agent/mm-disclosure/README.md) 和 [prompt-health 工具](tools/prompt-health/README.md)，未建立统一验证命令或 CI。

## 使用与贡献

选择需要的组件，按其说明接入目标宿主；不提供默认启用全部能力的安装方式，不自动改写用户配置。宿主相关的工具与前置条件必须由组件说明。

目录、验证、迁移和 Git 提交规则见 [AGENTS.md](AGENTS.md)。

## 许可证状态

仓库整体许可证尚未选定；公开可见不等于已授予整体再分发许可。引入第三方内容前须核实授权、保留适用的许可证与署名，并注明来源及本地修改；不得用未来的根许可证覆盖第三方原有条款。

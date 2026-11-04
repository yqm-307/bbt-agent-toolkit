# Python：Ruff format，已有 formatter 优先

先检查 `pyproject.toml`、`ruff.toml`、`.ruff.toml`、Black 配置与实际 CI/pre-commit 调用。已有 Black 或 Ruff 就沿用；Ruff 可能只用于 lint，不因此认定它是该仓 formatter。无既有约定时推荐 Ruff，不混用两种 formatter。

## bin、依赖与安装

- `command -v ruff` / `command -v black`，再运行选定 bin 的 `--version`；也可复用项目 venv 或编辑器固定路径。
- Ruff 核心是原生二进制，不要求项目包已安装、类型检查器或编译器；系统运行库按实际平台分发核对。`uvx`/pip/pipx 是获取工具的渠道，与 formatter 的运行依赖分开。Black 需其支持的 Python 与包依赖。
- 有安装授权后选一条固定版本路线：`uv tool install 'ruff==<核实的版本>'`、`uv add --dev 'ruff==<核实的版本>'`（改项目依赖，另核授权）、隔离 venv 的 `python -m pip install 'ruff==<核实的版本>'` 或 `pipx install 'ruff==<核实的版本>'`。缺 pip 时不假定 `python -m pip` 可用。
- `uvx --offline 'ruff@<已缓存版本>'` 可避免网络；未缓存会失败，不自动改成在线安装。无 offline 的 uvx 可能下载、创建环境，不能称为零安装零网络。
- 独立 bin 从 [Ruff 官方 release](https://github.com/astral-sh/ruff/releases) 选固定版本/OS/CPU归档，核发布方 hash/签名后解到新工具目录，保留许可证，不覆盖共享路径或提交 bin。官方安装脚本可下载到临时文件检查再执行，不使用 `curl | sh` 或 `irm | iex` 盲执行远端正文。
- Windows/macOS 获取方法见[官方安装](https://docs.astral.sh/ruff/installation/)；Black 路线见[官方说明](https://black.readthedocs.io/en/stable/getting_started.html)。说明不代表本机已装、所有平台已验证。

## 配置与格式风格

Ruff 找目标文件最近配置；同目录优先 `.ruff.toml`，其次 `ruff.toml`，再其次带 `[tool.ruff]` 的 `pyproject.toml`。显式 `--config <文件>` 可避免试用继承错误，`--isolated` 则忽略配置。项目有配置时不以模板覆盖。

[最小候选](../templates/ruff.toml)采用 Python 默认 88 列，不继承 C++120。Python 最低支持版本根据项目 `requires-python`/规范设 `target-version`，未知时先确认，不为格式化擅自锁 py310 或提高版本；显式配置与自动推断的规则以[官方配置](https://docs.astral.sh/ruff/configuration/)为准。Ruff/Black 的列宽均为尽力目标，不保证所有字符串、注释绝不超宽。

生成物/vendor 默认不纳入范围；显式文件路径可能绕过普通 exclude，因此候选设置 `force-exclude = true`，项目用 `extend-exclude` 按实际路径补充。不把所有 migrations 当成生成物，也不通过 per-file-ignore 隐藏真实 lint 问题。

## format / check

`RF`、`CFG`先赋为核实的 bin 和目标配置，显式文件列表排除生成物：

```bash
# check：只读格式符合性，不是 ruff check lint。
"$RF" format --config "$CFG" --check src/example.py

# diff：只读预览，不把此输出重定向覆盖源文件。
"$RF" format --config "$CFG" --diff src/example.py

# format：写源，仅在写回授权范围内运行；之后重跑 --check。
"$RF" format --config "$CFG" src/example.py
```

未指定配置可省掉 `--config` 以沿用目标仓发现规则，但要核实际生效配置。退出码：

| 子命令 | 0 | 1 | 2 |
|---|---|---|---|
| `format` | 格式化执行成功 | 不作为格式差异判据 | 参数/配置/解析等错误 |
| `format --check` / `--diff` | 已符合格式 | 有待格式化文件 | 工具/配置/解析错误 |
| `check`（lint） | 无违规 | 发现违规，可能含 invalid-syntax | 参数/配置/运行错误 |

不能把 `ruff format` 的退出 0当作原文件无需格式化，或把语法错误归为排版warning。目标版本若改变诊断行为先实跑负例再定判据。

Black 的写回/check/预览分别为 `black`、`black --check`、`black --diff`。**Black 单独 --diff 不等同于 check 的失败退出语义**，机器判 clean 用 `--check`；其异常退出码按对应版本官方命令帮助核对。

## 格式与 lint 分开

`ruff check` 不是格式检查；默认规则也不证明类型、安全或业务正确性。导入排序需启用 `I` lint 规则，不是 `ruff format` 附带动作；默认不增加 `--fix`、`--fix-only`、`--unsafe-fixes`。项目配置也可默认启用fix，确需只读lint时显式 `ruff check --no-fix <files>`；格式授权不包含语义修复、删导入或导入重排。

format 后用 format --check 验收即可；是否另跑 lint/类型/测试由任务风险与项目决定，不把整套检查强加所有格式请求。agent复核配置不适配、语义分组、format-ignore 或大范围变动，不逐个替工具裁判所有空格。

## 验证与来源

在临时坏样本执行 check（差异1、hash不变）→format→check（0）→第二次format（字节不变）；语法坏输入应为 ERROR。不同formatter/版本不保证输出互相稳定；format-only不承诺行为无变化，必要时比较Python AST与项目测试。

- [格式命令与退出码](https://docs.astral.sh/ruff/formatter/)
- [配置发现、exclude 与 force-exclude](https://docs.astral.sh/ruff/configuration/)
- [安装与版本锁定](https://docs.astral.sh/ruff/installation/)

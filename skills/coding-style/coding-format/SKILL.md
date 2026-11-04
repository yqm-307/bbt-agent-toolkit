---
name: coding-format
description: "Use when formatting or checking source code mechanically with language-specific tools and repository configs."
related_skills: [clean-code]
---
# coding-format：代码格式化与检查

把**机械格式化**和**只读格式检查**交给语言工具；把工具无法判断的语义分组、宏例外和风格取舍交给 agent。先选目标仓已有配置与工具，不把本 skill 的模板覆盖项目真源。

## 两种能力

| 能力 | 意图 | 细则 |
|---|---|---|
| format | 生成格式化结果，写回前先看 diff | [references/workflow.md](references/workflow.md)「format」 |
| check | 只读发现格式差异，不写源文件 | [references/workflow.md](references/workflow.md)「check」 |

## 语言路由

| 语言 | 参考 | 默认工具路径 |
|---|---|---|
| C/C++ | [references/cpp.md](references/cpp.md) | `clang-format` |
| Python | [references/python.md](references/python.md) | `ruff format`；仓库已有 Black 时跟仓库 |
| Go | [references/golang.md](references/golang.md) | `gofmt` |

不在表内的语言先查目标仓工具；不要把 C++ 120 列、Python 88 列或 Go 规则套到其他语言。

## 读取顺序

1. 执行顺序、配置与安装、输出与停止判据：[references/workflow.md](references/workflow.md)。
2. 语言工具、命令、退出码与安装：[references/cpp.md](references/cpp.md)、[references/python.md](references/python.md)、[references/golang.md](references/golang.md)。
3. 候选配置：[templates/clang-format.yaml](templates/clang-format.yaml)、[templates/ruff.toml](templates/ruff.toml)。

## 边界

- 目标仓已有 formatter、配置与忽略范围优先；候选模板只在没有既有配置时试用，不把用户偏好强盖仓规。
- check 的失败路径 fail closed：工具缺失或失败、配置无效、输入无法解析、版本不匹配一律 BLOCKED/ERROR，不能当作 clean；也不通过忽略全部 warning 隐藏问题。
- 不自动安装、不隐式联网、不把工具二进制提交进仓库；安装只能在获准的环境和范围内进行。只有获得写回授权才使用原地 format。
- check clean 只说明符合该 formatter/config，不替代 clean-code 的设计/命名/可读性判断、语言编译器、lint、测试、review 或提交门禁。

结构与三语言实测入口：`python3 skills/coding-style/coding-format/scripts/validate.py`（显式传 `--clang-format`/`--ruff`/`--gofmt`，或用 `--require-all` 要求三种工具都实跑）。

## 迁移适配说明

- 格式检查依赖按语言自备：clang-format、ruff、gofmt/Go（获取方式见各 references）；`scripts/validate.py` 需 Python 3.11+（用到 tomllib）。
- 文中 `python3 skills/coding-style/coding-format/scripts/...` 命令从本工具箱仓库根执行；放在别处时改为实际路径。
- 既有验证入口随包保留，**本次迁移未运行**；新机器可用性未验证。

# 通用执行流程与配置

本文件是 `coding-format` 的执行细则：各语言共用的 format/check 分流、执行顺序、配置与安装边界、输出与停止条件。语言专属工具、命令、退出码和安装渠道见 `cpp.md`、`python.md`、`golang.md`。

## format：生成格式化结果

- 先锁定目标仓、版本、配置和文件范围。
- 默认写入前先用 stdout 或临时副本观察 diff；未获写入授权不使用原地模式。
- format 改变空白、换行、缩进和工具允许的注释排版，不应顺手修改命名、逻辑、API、错误处理或资源生命周期。
- 格式化后重新运行 check；check 通过只说明符合该 formatter/config，不说明代码逻辑正确。

## check：只读发现格式差异

- check 不写源文件，输出差异或非零状态。
- warning 表示“工具配置与文件不同”，不是自动确认缺陷；agent 只复审 warning 对应区域。
- check 工具失败、配置无效、输入无法解析或版本不匹配时返回 BLOCKED/ERROR，不能当作 clean。
- 对宏、生成代码、vendor、外部快照和项目明确保留的排版例外，配置中排除或交给人工复核；不要通过忽略所有 warning 隐藏问题。

## 通用执行顺序

1. 读取目标仓规则、现有 formatter 配置和忽略文件。
2. 读取对应语言 reference，发现工具、版本与命令；目标仓已有配置优先。
3. 先 check；有差异时在临时副本 format，查看 diff，再决定是否写回。
4. 对 format 产生的 warning 分区：机械格式、配置不适配、宏/生成物/人工例外。
5. format 后再次 check；必要时运行语言解析、编译或测试。格式检查不替代行为验证。

## 配置与安装

- C++ 候选配置：[templates/clang-format.yaml](../templates/clang-format.yaml)；Python 候选配置：[templates/ruff.toml](../templates/ruff.toml)；Go 使用 `gofmt` 内建规则，不创建伪配置。
- 候选配置只在目标仓没有既有配置时试用。目标仓的 `.clang-format`、`ruff.toml`/`pyproject.toml`、项目 formatter 或 CI 配置始终优先；本 skill 的用户偏好（含 C++ 函数大括号换行）不覆盖仓规，也不作为现有仓库的门禁。
- 安装依赖须由目标仓/环境授权；本 skill 不自动安装、不隐式联网、不把二进制提交进仓库。工具版本应固定或由仓库锁文件/镜像提供。
- 二进制路径可来自 PATH、编辑器扩展、项目工具目录或显式参数；按语言 reference 核实际版本（Go 的 gofmt 没有 `--version`），把来源与版本写入验证结果。
- 各语言的安装渠道、校验步骤与固定版本写法见对应语言 reference，本文件不复制。

## 输出与停止

输出：目标文件范围、工具版本、配置来源/摘要、format 或 check 命令、真实退出码、warning 分组、未覆盖项。check clean 后停止；若配置与存量风格严重冲突，停止扩大格式化范围，先调整配置或确认例外。

# prompt-health

通用的提示词资产健康度与引用检查工具。它扫描调用者指定的仓库，不依赖固定项目、profile、宿主或目录生成物。

## 能力

- 检查 `skills/**/SKILL.md` 的 `related_skills` 是否指向现有 skill、名称是否重复；正文提及但未声明的引用只给提示。
- 检查提示词资产体量、重复 Markdown 内容和不可读文件。
- 输出人读报告、可选 JSON 快照，以及适合 CI 的确定性 gate。
- 不生成 `skills/INDEX.md`、关系图、SVG 或其他仓库级产物；只保留当前仓库即时的引用检查。

默认扫描根目录下的 `skills/`、`agents/`、`docs/`、`plugins/`、`tools/`、`workflows/` 中的 Markdown、文本、YAML 和 JSON，以及根目录的 README/AGENTS/HERMES 文件。Git 仓库优先使用 tracked 文件清单；非 Git 目录按同样的路径规则递归扫描。

## 用法

```bash
# 从目标仓库根目录运行
python3 /path/to/prompt_health.py --root .

# 只做确定性检查；新增错误或警告返回 1
python3 /path/to/prompt_health.py --root . --gate

# 输出报告与快照（输出路径由调用者决定）
python3 /path/to/prompt_health.py --root .   --report .state/prompt-health/report.md   --snapshot .state/prompt-health/baseline.json

# 比较同一仓库之后的快照
python3 /path/to/prompt_health.py --root .   --check .state/prompt-health/baseline.json
```

`--gate --verbose` 会额外打印正文提及但未写入 `related_skills` 的提示。工具只读扫描；只有 `--report` 和 `--snapshot` 明确请求时才写指定文件。它不安装依赖、不修改被扫描仓库、不替代项目自己的 lint、测试或发布门禁。

## 依赖与适配

- Python 3.10+，只使用标准库。
- 可选 Git：存在时用于获得 tracked 文件清单；没有 Git 时退回目录扫描。
- 不需要 Hermes、OMH、Hindsight、数据库、网络或固定 profile。
- `--root`、报告路径和快照路径都可跨机器显式指定；未在目标仓库实际运行前，不宣称该仓库已通过检查。

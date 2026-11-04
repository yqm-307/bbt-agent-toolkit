# C/C++：clang-format

`clang-format` 同时提供格式输出与只读检查；它不是 Clang 编译器、clang-tidy 或语义风格审查。命名、抽象和资源语义继续用 clean-code；目标仓 `.clang-format` 是已采用机械格式的真源。

## 工具、依赖与安装

1. `command -v clang-format`；也查项目固定版本、`clang-format-<主版本>` 或编辑器扩展自带的可执行文件。显式设置 `CF=/实际/bin/clang-format`，运行 `"$CF" --version`；无需 VS Code 运行着，但扩展路径会随更新变化，不作为 CI 固定路径。
2. 运行只需匹配 OS/CPU 的 bin 和它实际链接的系统运行库；不需要 Clang/GCC 编译器、CMake、项目头文件、Boost 或 compile_commands.json。Linux 可用 `file "$CF"` / `ldd "$CF"` 核动态依赖；静态与动态发行包不要混为一谈。离线运行不联网。
3. 缺工具时，先确认允许的安装范围，再选一种官方/发行版来源：
   - Debian/Ubuntu：`sudo apt-get install clang-format`；需要固定主版本时先 `apt-cache policy clang-format-<主版本>`，装仓库实际提供的包，不猜包名可用。安装会改系统，需环境授权。
   - macOS：Homebrew `brew install clang-format`，再固定项目使用的版本/路径。
   - Windows：用 [LLVM 发布页](https://github.com/llvm/llvm-project/releases) 对应平台安装包，检查是否包含 `clang-format.exe`。
   - Python 包渠道：隔离环境中可用 `uv tool install 'clang-format==<核实过的版本>'` 或 `pipx install 'clang-format==<核实过的版本>'`；来源为 [clang-format PyPI 分发](https://pypi.org/project/clang-format/)，是打包渠道，不冒充 LLVM 官方安装器。不要盲用浮动 latest。
   - 手动归档：从已核实来源下载固定版本/平台包，校验发布方提供的 hash/签名，解到项目工具目录；只改该目录、不写全局 PATH、不把 bin 入 Git。

formatter 本身不依赖 Python；`git-clang-format` / `clang-format-diff.py` 辅助脚本另需 Python，Git 集成还需 Git。不为格式化安装整个构建工具链。

## 配置

优先已有 `.clang-format` / `_clang-format`；`--style=file` 沿目标文件父目录查找。避免无配置时悄悄退回 LLVM 80 列：使用 `--fallback-style=none`，但这会**跳过格式化**，不能声称风格已验；正式 check 应先确认配置存在。未知选项、解析失败或主版本不匹配先报 ERROR，不用 `--Wno-error=unknown` 消掉告警。

无配置时可在临时副本显式试用 [候选模板](../templates/clang-format.yaml)：

```bash
# CFG 指向本 skill 模板或已确认的项目配置；以下命令中的 CF、CFG 都先显式赋值。
"$CF" --style="file:$CFG" --Werror --dump-config
```

模板按 LLVM 基底映射 4 空格、120 列、namespace 不缩进、访问标签随 class、指针引用靠类型；关闭 include/using 排序与注释重排，避免附带重排。`SkipMacroDefinitionBody` 需 clang-format 18+；模板应先通过目标 bin 的 `--dump-config`，支持范围以实际版本为准。

大括号是模板里唯一带用户偏好的映射：函数（含构造函数、析构函数、类内成员定义）的左大括号独占下一行，形如

```cpp
void foo()
{
}
```

而 `if`/`for`/`while`/`switch`/类/`struct`/`enum`/`namespace`/`lambda`/`try`/`catch` 的大括号保持同行。它由 `BreakBeforeBraces: Custom` + `BraceWrapping: {AfterFunction: true, SplitEmptyFunction: true}` + `AllowShortFunctionsOnASingleLine: None` 三者共同表达；去掉最后一项，空函数体和单语句函数体会被并回函数签名行，函数大括号换行就失效，所以这三项要一起改。这是**用户已选定的候选配置**，只在目标仓没有 `.clang-format` 时作为试验起点：目标仓已有仓规（即使大括号同行）始终优先，不把这条偏好强盖到其他仓库。

**120 是机械换行目标，不是完全等同于人判断的“120 左右软范围”**。超长不可拆 token 仍可能超宽；降低 `PenaltyExcessCharacter` 只能改变代价取舍，不能保证按业务语义分组。`ColumnLimit: 0` 更多保留原始语句换行，但不再自动控宽，不推荐作为伪“120软上限”。

连续声明对齐不能表达 clean-code 的“多数声明定 4 的倍数列、个别长类型另起行”；模板默认不启用整组对齐，采用前需确认差异。复杂阶段空行、例外声明块仍需作者表达，不宣称工具精确复现团队全部美感。

## format / check

只处理已授权显式文件，排除生成物/vendor/构建输出，不默认全仓 `-i`：

```bash
# format 预览：stdout，不改源；如落临时副本，输出必须是不同路径。
"$CF" --style="file:$CFG" --Werror --fail-on-incomplete-format src/Foo.cc

# check：不加 -i，差异位置走 stderr，非零表示需分辨差异或工具错误。
"$CF" --style="file:$CFG" --dry-run --Werror --fail-on-incomplete-format src/Foo.cc

# 只有得到写回授权后使用；随后再运行上面的 check。
"$CF" --style="file:$CFG" --Werror --fail-on-incomplete-format -i src/Foo.cc
```

- check exit 0：输入符合该版本/配置且格式化完整；非零：从 stderr 区分格式差异、无效配置、读失败、不完整解析等，不能一律当 warning。
- format stdout exit 0：成功生成结果；源是否已规范要看再次 check。clang-format 不是完整 C++ 编译器，某些坏语法仍能排版，不能用它判定源码可编译。
- 机器报告可用 `--output-replacements-xml`：offset/length 是**字节**，源 UTF-8 用字节回放与定位；核 `incomplete_format`，EOF 行号钳制到源实际行数，输出建议副本不是原始快照。
- 修改行范围可用 `--lines=起行:末行`；格式化可能扩展到关联语法单元，不保证物理上只动这些行。官方 Git 集成见来源，CI 是否接入另授权。

## 宏与人工例外

`bbtco` 等语法糖需要项目实际宏提示，不能盲贴到所有 C++ 仓库。clang-format 17+ 的 `Macros` 可提供供排版解析的展开（不改写源 token），比如**核过真实定义后**：

```yaml
Macros:
  - 'bbtco=bbt::coroutine::_CoHelper()-'
  - 'bbtco_desc(desc)=bbt::coroutine::_CoHelper(desc)-'
```

`SkipMacroDefinitionBody` 不是“宏零改动”保证：行尾空格等仍可能调整。特殊区块可用 `// clang-format off` / `// clang-format on` 局部排除，需明确原因与范围；不把所有代码包进 off。`InsertBraces: true` 有语义信息不足风险，默认关闭，不把自动添括号混入纯格式授权。

## 验收与来源

临时坏样本：check 应非零且源 hash 不变；format 副本；check 应 0；第二次 format 与首次一致；无效配置必须非零。宏样本需读 diff、必要时真实编译，空白删改也可能影响预处理或字符串。

- [CLI、编辑器、Git 集成](https://clang.llvm.org/docs/ClangFormat.html)
- [配置选项与版本标注](https://clang.llvm.org/docs/ClangFormatStyleOptions.html)

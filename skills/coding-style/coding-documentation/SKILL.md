---
name: coding-documentation
description: "Use when writing public code comments or exporting API documentation with Doxygen and a modern static-docs theme."
related_skills: [clean-code]
---
# coding-documentation：代码注释与 API 文档导出

把**公共接口事实**写在声明旁边，把**文档网站展示**交给导出工具；不要让生成页面反过来成为 API 契约。首版以 C/C++ 头文件、Doxygen 注释、Doxygen Awesome HTML 主题为主，图表使用 Mermaid 或 PlantUML 的显式源文件。

公共接口注释的内容与导出归本 skill；机械排版沿用目标仓 formatter（coding-format 可用时从该入口执行），通用可读性与设计判断归 clean-code，skill 自身的维护流程遵循目标项目的协作规则。不因注释补充修改函数签名、行为、错误集合或资源寿命。

## 默认路线

```text
.hpp/.h 公共声明 + Doxygen 注释
          ↓
       Doxygen
          ↓
  HTML/XML + Graphviz 图
          ↓
 Doxygen Awesome 主题 / 静态站点
```

- `/** ... */` 或 `/// ...` 是可导出的公共文档注释；`.cc` 实现注释不重复声明契约。
- Doxygen 负责解析符号、参数、返回值、继承和 include/call 图；Doxygen Awesome 只负责 HTML 外观，不增加解析能力。
- Graphviz 负责工具能推导的关系图；Mermaid/PlantUML 负责作者明确维护的状态图、时序图、架构图。Doxygen 不会从业务代码可靠推导业务状态机。
- 目标仓已有 Doxyfile、主题版本、文档站或 CI 时优先沿用；模板仅用于无既有配置的候选试验。

## 注释规范入口

先读 [通用文档与注释](../../../standards/general/documentation.md)；C/C++ 标签、完整注释示例与解析边界见 [C++ 文档](../../../standards/cpp/documentation.md)。核实真实接口契约后再写，不猜保证，不机械补空标签。

## 导出流程

1. 读取目标仓 `AGENTS.md`、构建入口、现有 `Doxyfile`、`.clang-format` 与忽略范围。
2. 锁定 Doxygen 版本、Graphviz 是否存在、Doxygen Awesome 固定版本/来源；安装须获环境授权，不隐式联网。
3. 先在临时输出目录运行 Doxygen，检查 warnings；再看 HTML 页面、公共符号、交叉链接和图表。
4. HTML 输出确认后再接入仓库文档入口或 CI；生成目录放 `build/` 等忽略路径，不把生成站点复制回源码树。
5. 主题只改 CSS/页面布局，不用 CSS 掩盖缺失、错误或过时的 API 注释。

分支资料：写 C/C++ 注释先读[../../../standards/cpp/documentation.md](../../../standards/cpp/documentation.md)；安装、锁版本与主题导出先读[references/export.md](references/export.md)；开启图表时读[references/diagrams.md](references/diagrams.md)。

候选模板：[templates/Doxyfile.in](templates/Doxyfile.in)。全部六个占位符 `@PROJECT_NAME@`、`@PROJECT_VERSION@`、`@PROJECT_SOURCE_DIR@`、`@PROJECT_BINARY_DIR@`、`@DOC_INPUT_DIR@`、`@DOXYGEN_AWESOME_DIR@` 须经 CMake `configure_file` 或等价替换生成实际 Doxyfile；确认无残余变量后再交给 Doxygen。

## 图表边界

- **Graphviz**：类继承、include 依赖、调用/被调用图；开启 `HAVE_DOT` 前确认 dot 可执行文件和输出规模。
- **Mermaid**：优先用于状态图、时序图、流程图；图源放 `.md` 或独立 `.mmd`，页面主题再渲染。
- **PlantUML**：需要 UML 语法或既有 `.puml` 时使用；通常还需要 Java 与 PlantUML JAR。缺依赖记为未验证，不用静态图片冒充可复现源。
- 图表源必须明确标注事实/设计/示意；自动图只表达工具看到的代码关系，不等于架构决策或运行时真实时序。

## 检查与失败路径

- 静态结构检查：`python3 skills/coding-style/coding-documentation/scripts/validate.py`。
- 工具检查：显式传 `--doxygen <bin>` 只核版本；同时提供 `--awesome-dir <本地主题目录>` 会在新临时目录验证 HTML/XML、中文、函数参数返回、主题 CSS 与 Graphviz。`--require-export` 使未验证导出成为失败，不是启动导出的开关。缺工具或主题不自动安装，记 `UNVERIFIED/BLOCKED`。
- 导出检查：Doxygen 非零、warnings 增多、公共符号缺失、链接断裂或图表渲染失败，均不能声称文档通过。
- Doxygen 解析成功不代表代码编译通过；文档没有 warning 也不代表 API 契约正确。必要时另跑头文件独立包含、模板实例化、构建与测试。
- 生成物不得包含凭据、私有绝对路径、未脱敏日志或内部环境信息；发布前检查 HTML/XML 与源码注释。

输出应包含：注释范围、工具与主题版本、配置来源、实际命令与退出码、warnings/缺失符号/图表状态、生成目录和未覆盖项。

## 迁移适配说明

- 导出依赖自备：Doxygen；可选 Graphviz、Java+PlantUML、Doxygen Awesome 主题（获取方式见 references/export.md）；`scripts/validate.py` 需 Python 3。
- 文中 `python3 skills/coding-style/coding-documentation/scripts/...` 命令从本工具箱仓库根执行；放在别处时改为实际路径。
- 既有验证入口随包保留，**本次迁移未运行**；新机器可用性未验证。

# Doxygen + Doxygen Awesome 导出

## 依赖分层：按输出选择，不一次装齐

| 能力 | 必需依赖 | 不需要／注意 |
|---|---|---|
| 公共注释编写 | 源码与真实接口契约 | 不需要先安装 Doxygen；clang-format 不生成注释内容 |
| HTML/XML 导出 | Doxygen bin、该发行包所需运行库、配置和输入文件 | 不需要 Node.js、npm、Python、Java 或 LaTeX；特定过滤器/扩展另算 |
| Awesome 基础主题 | 固定版本 `doxygen-awesome.css` 与许可证 | CSS 是静态资源，不需要 npm 构建或常驻服务 |
| 手动暗色切换等交互 | 对应 Awesome JS、当前 Doxygen 生成的 header 与配置 | 只复制 CSS 不会得到按钮；JS 在读者浏览器执行 |
| 继承/include/调用图 | Graphviz `dot`，`HAVE_DOT = YES` | 无图需求可设 `HAVE_DOT = NO`；本 skill 默认模板及导出测试启用图，因此测试需 dot |
| PlantUML 图 | Java、固定版本 PlantUML JAR；部分图形/布局另需 Graphviz | 没有 UML 需求不安装；设置 `PLANTUML_JAR_PATH` 后才启用 |
| Mermaid 图 | 目标版本支持的渲染模式与 Mermaid 资源；服务端模式按所选引擎核依赖 | 不把 Node.js 当作所有 Mermaid 路线的必需依赖；禁止默默加载外部 CDN |
| PDF | LaTeX 工具链及所选字体/转换工具 | HTML/XML 路线不用安装；模板默认 `GENERATE_LATEX = NO` |
| 配置生成／自检 | CMake 或等价变量替换；本 skill 的 validate.py 需要 Python 3 | 是辅助工具依赖，不是 Doxygen bin 的必需运行依赖 |

上述为运行预编译工具的依赖。**从源码编译 Doxygen**另外需要编译器、CMake、Flex/Bison 等，按所选版本的[官方安装说明](https://www.doxygen.nl/manual/install.html)和构建配置核对；普通文档导出优先发行包，不为导出安装完整 LLVM 开发链。

## 发现、版本与安装

先 `command -v doxygen`、`doxygen --version`；可复用固定 bin，但不依赖某个编辑器路径。实际运行库取决于发行包，Linux 可用 `ldd <bin>` 检查；不要说“只要一个 bin、零依赖”。普通导出不需要项目编译器或全部第三方头文件，解析复杂宏/模板时仍核构建与预处理配置。

环境有安装授权才选渠道：

- Debian/Ubuntu：先 `apt-cache policy doxygen`，再用仓库可提供的固定版本执行 `sudo apt-get install 'doxygen=<已核实版本>'`；Graphviz 按需单独安装。不擅自升级全系统。
- macOS：可用 Homebrew `brew install doxygen graphviz`；此路线不天然锁版本，验收记录实际版本。
- Windows/Linux/macOS：从 [Doxygen 官方 release](https://github.com/doxygen/doxygen/releases) 选固定版本与平台包，核发布方完整性信息后安装/解压到获准位置。存在本地可执行性问题时报告实际缺库/平台不匹配，不关闭安全校验。
- 局部试验可 `apt download 'doxygen=<核实版本>'` 后 `dpkg-deb -x <归档> <临时目录>`；包管理器核仓库元数据与下载完整性。遇到缺共享库仅局部解出相应包，用单进程 `LD_LIBRARY_PATH`，不改全局环境；下载及执行外部包仍须在获准范围内。

### Linux 局部试用：不改系统包数据库或全局 PATH

下面是分步示例，不是自动安装脚本。`TOOLS` 指向获准的新临时目录；`DOXYGEN_DEB_VERSION` 来自本机包列表，不跨发行版照抄。下载前确认网络和目录授权，每步失败都停止。

```bash
apt-cache policy doxygen
apt-cache depends doxygen
# 将下列变量赋为已核实的路径/版本；目录必须新建且只归本次试验。
# TOOLS=/获准的新目录
# DOXYGEN_DEB_VERSION=包仓提供的精确版本
mkdir -p "$TOOLS/downloads" "$TOOLS/root"
(
    cd "$TOOLS/downloads" || exit
    apt download "doxygen=$DOXYGEN_DEB_VERSION"
)
# DEB 指向上一步真实下载的文件，不用不受控通配符解出他人归档。
# DEB="$TOOLS/downloads/doxygen_实际文件名.deb"
dpkg-deb -x "$DEB" "$TOOLS/root"
CF_DOC="$TOOLS/root/usr/bin/doxygen"
ldd "$CF_DOC"
```

`ldd` 仍有 `not found` 时不要继续导出：按 `apt-cache depends` 与实际缺库选择**匹配发行版和架构**的包，锁包版本、下载到同一自有目录、逐包解到同一 root。不要执行 `sudo apt install`，也不要声称局部解包会自动解决全部依赖。只在单个子进程使用库路径：

```bash
# LIBDIR 按该发行包实际布局赋值，不假定所有 OS/CPU 都用 x86_64-linux-gnu。
# LIBDIR="$TOOLS/root/usr/lib/x86_64-linux-gnu"
env LD_LIBRARY_PATH="$LIBDIR" "$CF_DOC" --version
# 配置已经替换变量；导出目录已准备，且归本任务所有。
env LD_LIBRARY_PATH="$LIBDIR" "$CF_DOC" "$DOXYFILE"
```

验证版本、退出码和 warnings 后才记导出成功；工具目录退出试验后可按授权清理，不保留全局环境修改。系统安装路线由包管理器处理依赖；局部解包路线仅适合小范围试验，不建议替代正式 CI 镜像中的锁定工具安装。

Graphviz `dot -V`、Java `java -version` 仅在对应图表开启时需要。PlantUML 另核 JAR 的固定版本与许可证。默认导出不开 Mermaid CDN 或远端 PlantUML server；私有 API 文档不得上传外部渲染服务。

## 主题获取

从 [Doxygen Awesome](https://github.com/jothepro/doxygen-awesome-css) 获取固定 release 与解析后的 commit SHA，审读 CSS/JS、保留 MIT LICENSE。不要使用 `main.zip` 或浮动 latest 作为生产输入。只读调研不等于授权执行第三方脚本。

例如 v2.5.0 是候选版本，采用时重新核 tag 到 SHA 的映射；项目已有版本优先。把资源放临时依赖目录或项目允许的 vendor 路径，不把工具 bin 塞入 skill。

### 固定主题的可复现获取

有网络与目录写授权且已安装 Git 时，可把源码只下载到自有依赖目录（不执行 make/install 或第三方脚本）：

```bash
# AWESOME_TAG 为已选 release；EXPECTED_AWESOME_SHA 为独立核实的完整 commit SHA。
# AWESOME_DIR 必须是未占用的目标路径，不覆盖既有目录。
git -c http.sslVerify=true clone --depth 1 --branch "$AWESOME_TAG" \
    https://github.com/jothepro/doxygen-awesome-css.git "$AWESOME_DIR"
# clone 成功后核版本；不关闭 TLS 验证，也不把不匹配 SHA 自动“修正”为已取得的值。
ACTUAL_AWESOME_SHA=$(git -C "$AWESOME_DIR" rev-parse HEAD)
test "$ACTUAL_AWESOME_SHA" = "$EXPECTED_AWESOME_SHA" || exit 1
test -s "$AWESOME_DIR/doxygen-awesome.css" || exit 1
test -s "$AWESOME_DIR/LICENSE" || exit 1
```

先检查 Git 环境没有禁用 TLS 的变量/配置；命令失败即停止。可用浏览器下载固定 release 归档替代 Git，此时记录来源和归档完整性核验，不声称已验证 commit checkout。主题目录可只纳入需要的 CSS/JS 与 LICENSE，验收记录 tag/SHA，不提交其 `.git` 或下载缓存。获取主题不需要 Node.js/npm；只有选择 npm 分发路线才需要相应包管理器。

- 基础主题只需 `doxygen-awesome.css`；`HTML_EXTRA_STYLESHEET` 指向这份资源。
- 必需配置：`DISABLE_INDEX = NO`、`FULL_SIDEBAR = NO`、`HTML_COLORSTYLE = LIGHT`；可开 `GENERATE_TREEVIEW = YES`。
- 基础 CSS 有随系统明暗模式的样式；**手动切换按钮不随一份 CSS 自动出现**。需要时加入官方 `doxygen-awesome-darkmode-toggle.js`，设置 `HTML_EXTRA_FILES`，再从当前 Doxygen 的 `-w html` 输出生成 header，把官方初始化调用放入 `</head>` 前，设置 `HTML_HEADER`。不能跨 Doxygen 版本复制旧 header。
- sidebar-only 布局还需要第二份 CSS；手动切换与复制按钮等扩展按[官方扩展说明](https://github.com/jothepro/doxygen-awesome-css/blob/v2.5.0/docs/extensions.md)接入，不为了首版堆全部扩展。

## 生成实际配置

候选 [Doxyfile.in](../templates/Doxyfile.in) 中每个变量必须替换。最小 CMake 路线：

```cmake
# 项目中已有 project(... VERSION ...)；路径均先核对，不隐式下载依赖。
set(DOC_INPUT_DIR "${PROJECT_SOURCE_DIR}/include")
set(DOXYGEN_AWESOME_DIR "${PROJECT_BINARY_DIR}/doc-tools/doxygen-awesome-css")
file(MAKE_DIRECTORY "${PROJECT_BINARY_DIR}/docs")
configure_file(path/to/Doxyfile.in "${PROJECT_BINARY_DIR}/docs/Doxyfile" @ONLY)
```

`DOC_INPUT_DIR` 按仓库公共头路径调整，不能假定所有仓都叫 include；例如多模块仓需 explicit INPUT 清单。开启 XML 便于核符号，但发布可只发布 HTML，勿把内部源码/XML 全盘上传。

从项目根执行 `doxygen build/docs/Doxyfile`。输出目录须新建或确认归此任务所有；不清理他人目录。`WARN_LOGFILE` 是独立导出诊断文件，正常 warning 可能不导致 Doxygen 非零，因此同时读退出码与 warning 文件；目标版本支持时可用 `WARN_AS_ERROR`，先核配置帮助，不仅凭 exit0宣布通过。

## 验收与发布边界

1. 生成配置无残余 `@VARIABLE@`；输入和排除范围正确，未把私有头或 vendor 混入。
2. Doxygen 退出成功且 warning 已分辨；生成新 HTML/XML，公共类/函数/参数/返回信息确实出现。
3. HTML 引用的 CSS 与实际复制内容一致；静态资源与符号链接可达。版本号不代表主题在页面生效。
4. 浏览器检查中文、导航、搜索与明暗样式；静态断言只能证明资源接入，不代替用户审美验收。
5. Graphviz / Mermaid / PlantUML 分别检查，不以其它图成功冒充这一项通过。

新导出只证明模板可运行，不证明真实项目 API 文档完整。发布、CI、Pages 与全仓注释改造均需在任务授权范围内另定，不因为本 skill 支持就自动执行。

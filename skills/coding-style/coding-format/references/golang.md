# Go：gofmt

Go 默认使用工具链自带 `gofmt`，不配置 C++ 式缩进/行宽：tab 缩进、空格对齐是 Go 的内建格式，不套 4 空格或 120 列。已有 `gofumpt` 等项目约定时按项目执行，不擅自换工具。

## bin、依赖与安装

- 发现：`command -v gofmt`；Go 已安装时也可查 `$(go env GOROOT)/bin/gofmt`。
- 版本：`go version` 与 `go env GOROOT` 核工具链，确认所选 gofmt 来自同一安装；`gofmt -h` 核可执行性。**gofmt 没有 --version**。独立 bin 从已校验 Go 归档取得时保留同归档 `go/VERSION`，不要拿 PATH 中另一份 Go 的版本代替。
- 运行格式化不需要项目依赖、go.mod、编译器或 go.sum；它解析源码，不跑构建。gofmt 随 Go 工具链分发，但已解出的匹配平台 bin 可单独使用。实际运行库依赖按该发行包检查，不能跨 OS/CPU 直接复制。
- 有安装授权后优先项目锁定 Go 或已有官方安装，参考 [官方安装](https://go.dev/doc/install)、[下载与 SHA256](https://go.dev/dl/)。Go 官网 tar 包需要选择固定版本与平台，不自动用 latest。
- Linux 用户/项目局部试用：官方归档下载后核发布方 SHA256，再只解 `go/bin/gofmt`、`go/VERSION`、`go/LICENSE` 到新工具目录；不删除已有 `/usr/local/go`，不改全局 PATH，不提交 bin。

```bash
# GO_ARCHIVE 为已核实的版本/OS/CPU文件名，如 go<版本>.linux-amd64.tar.gz。
# EXPECTED_SHA256 来自官方该文件条目；TOOLS 是获准的新工具目录。
curl --fail --location "https://go.dev/dl/$GO_ARCHIVE" -o "$TOOLS/$GO_ARCHIVE"
printf '%s  %s\n' "$EXPECTED_SHA256" "$TOOLS/$GO_ARCHIVE" | sha256sum --check --strict
# 上一步非零必须停止；校验通过后才解包/执行。
tar -xzf "$TOOLS/$GO_ARCHIVE" -C "$TOOLS" go/bin/gofmt go/VERSION go/LICENSE
GF="$TOOLS/go/bin/gofmt"
"$GF" -h
```

上述是分步示例，不作为无条件安装脚本；变量先赋值并核目标，TOOLS 必须存在且未占用。Windows/macOS 使用相应官方包，不能用 Linux bin；不承诺未实测平台已安装。

## format

```bash
# 默认stdout预览，源文件不改；输出建议副本时必须是不同路径。
"$GF" src/foo.go

# 只有确认写回范围后原地处理显式文件。
"$GF" -w src/foo.go src/bar.go
```

format 后重新 check。默认不带 `-s`（简化）或 `-r`（重写规则）：这两项超出“仅排版”范围。gofmt 可能重排 import 或注释，核 diff 与项目测试，不用“空白处理”替代行为验证。

## check：必须看输出 + 退出码

```bash
# 原生命令只读：列出差异文件；-d输出建议diff。
"$GF" -l src/foo.go src/bar.go
"$GF" -d src/foo.go
```

`-l` 的退出 0 **不等于 clean**：没有解析/读取错误时，即使输出了待格式化文件，也可能是 0。可靠 check 需同时收集结果；下面 Python 标准库例子用明确三态，不改源码：

```python
import subprocess

# gofmt_bin 与 files 是已核实的可执行路径和显式文件列表；不可为空。
r = subprocess.run([gofmt_bin, "-l", *files], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    print(r.stderr)
    raise SystemExit(2)  # ERROR：输入/工具失败，不能当warning
if r.stdout.strip():
    print(r.stdout)
    raise SystemExit(1)  # WARN：有格式差异
raise SystemExit(0)      # PASS：无差异且执行成功
```

版本错误、缺 bin 或超时会抛异常，调用方需记为 ERROR/BLOCKED；本例不吞异常。文件列表避免带换行字符的文件名，否则文本列表不可可靠分行。对一般文件名优先原生 `-l` 文件清单；不对整仓目录递归，以免混入 vendor/generated。

## 复核与验收

- 先锁定显式文件与工具链版本，`-l` 不改源 hash；有名字时 agent 用 `-d` 定位差异，不直接把它归为逻辑缺陷。
- 临时坏样本 `-l` 应有输出；format 临时副本；再次 `-l` 应空且退出 0；第二次 format 字节相同；无效 Go 语法须非零。
- formatter 的语法解析不替代 `go test`/`go vet`，格式没有 warning 也不代表安全/生命周期/业务逻辑通过。
- 生成文件、vendor、业务明确保留的结构必须按项目范围排除；gofmt 不读取 `.clang-format` 或 ruff 配置，也没有 `.gofmt` 行宽配置。

[官方命令选项](https://pkg.go.dev/cmd/gofmt)是 -l/-d/-w 的依据；可执行版本、错误码与文件内容须实跑确认。

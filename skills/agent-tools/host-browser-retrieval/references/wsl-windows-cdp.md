# 从 WSL 用宿主机 Edge 做网页检索 — 机制与实测依据

本文记录本 skill 存在的理由、被否决的方案和实测数据。数据来自 2026-09-13 在本机（Windows 11 22621 + WSL 2.7.13.0，Ubuntu-26.04，Edge 152.0.4191.66，Node v22.23.2）的真实执行；环境升级后需重测的项已标注。

## 为什么不让 WSL 直接连 CDP

| 尝试 | 实测结果 |
|---|---|
| 启动 `msedge.exe --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --user-data-dir=<独立目录>` | 端口起来了，但 `Get-NetTCPConnection -LocalPort 9222` 显示只绑 `127.0.0.1` —— Edge 忽略 `--remote-debugging-address` |
| WSL 内 `curl http://127.0.0.1:9222/json/version`（端口已在 Windows 监听时） | 连接被拒 |
| WSL 内 `curl http://172.19.64.1:9222/json/version`（宿主机网关地址） | 不可达；Domain/Private/Public 三档防火墙均启用 |
| `.wslconfig` 写 `networkingMode=mirrored` | 当前仍是 NAT（`eth0 172.19.69.8/20`，默认路由 `172.19.64.1`），配置未生效；切换需重启整个 WSL（会中断会话） |

结论：让 WSL 直连要么改网络模式（需重启 WSL，可选方案），要么加 `netsh portproxy` + 防火墙规则（需管理员，且调试端口无鉴权、暴露面更大）。本 skill 选择不改系统配置。

## 采用的方案

Windows 侧 Node 连 `127.0.0.1:<port>`（同机回环，无需任何转发），WSL 通过 PowerShell interop 调用：

```
WSL bash → powershell.exe -NoProfile -Command "& node <C:\...\edge_cdp.mjs> <args>"
        → Windows node (零依赖：全局 fetch + WebSocket) → CDP → 宿主机 Edge 独立实例
```

脚本落点：仓库内的 `scripts/edge_cdp.mjs` 是唯一真源，`host_browser.sh` 每次调用 CDP 子命令前按内容比较复制到 `%LOCALAPPDATA%\host-browser-retrieval\`（`cmp -s` 一致则不重写；`status`/`ensure`/`close` 不触发复制）。也曾实测 Windows node 可直接执行 WSL 里的脚本（`node '\\wsl.localhost\Ubuntu-26.04\home\...\cdp.mjs'` 能加载执行），但该路径依赖发行版名探测，而本会话中 `$WSL_DISTRO_NAME` 为空，故不采用。

**实参经 stdin 传 JSON，不走命令行**。PowerShell 5.1 向原生命令传参时会剥掉实参里的双引号：`eval 'JSON.stringify({a:"b"})'` 实测变成 `ReferenceError: b is not defined`，`click 'a[href="x"]'` 变成 `not a valid selector`，且退出码仍为 0（静默给出错答案）。现方案由包装器把子命令与参数序列化成 JSON 数组经 stdin 传给 Windows 侧脚本，任意引号、换行、中文都不再被改写。同理 `--port` 必须同时从命令行与 stdin 两侧读取，否则会被静默忽略而打到默认端口。

**脚本自身另有两处静默错源**，均已修：`--max` 缺值/非数值原先当作 NaN → 不截断（`links --max` 更会返回空数组谎报「无链接」）；页面求值异常原先只打印字符串且退出码 0，现改为非零退出并写 stderr。

中文输出：PowerShell 侧先设 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`，否则 GBK 回传乱码（实测过 baidu 页面中文正常）。

## 独立 profile，不复用真实 profile

- Chrome 136 起 `--remote-debugging-port` / `--remote-debugging-pipe` 对默认 user-data-dir 一律忽略（官方公告 developer.chrome.com/blog/remote-debugging-port，2025-03-17）。本机 Edge 152 只验证到「指定独立 `--user-data-dir` 时端口正常监听」；「默认 profile 不监听」未在本机复现——复现需要以默认 profile 启动 Edge，会触碰用户正在使用的实例，故按官方公告采信。
- 已知绕法是把真实 User Data 目录整体复制到非默认路径再启动；但非默认目录使用不同的加密密钥，cookie 能否解密必须实测，且会把全部真实 cookie 暴露给自动化会话。本 skill 不用这条路：需要登录的站点在独立 profile 里手动登录一次，登录态即持久化在该 profile。

## 正文抽取的坑

`innerText` 依赖布局：对 `cloneNode` 出来的脱离文档节点会退化成 `textContent`，结果丢换行、词粘在一起（首次实测 baidu/example.com 均如此）。现版本改为就地隐藏噪音节点后对活动 DOM 取 `innerText`，再在 `finally` 里恢复原 `style.display`。

第二个坑来自候选选择：原先取 `main,article,[role=main]` 的第一个匹配，在正文之前有促销/相关 `<article>` 卡片的站点会抽到卡片而不是正文——实测 `learn.microsoft.com/zh-cn/windows/wsl/networking` 只返回 47 字符的 Ignite 促销卡，正文实际 5132 字符，且退出码 0、无任何提示。现改为在 `main` / `[role=main]` / `#main` / `#content` 中选第一个文本量达 body 40% 的元素，否则用 body；截断也改为不切断代理对（避免尾部 U+FFFD 污染逐字引用）。

## 出口与代理

首次实测新 profile 打不开 Wikipedia（`chrome-error://chromewebdata/`）。当时宿主机代理在回环端口监听，但直连、`http://` 代理、`socks5h://` 三条路 curl 全为 `000`，即代理无可用出口。因此：

- 被墙站点能否检索，取决于宿主机代理本身是否可用，与本 skill 无关；
- `--proxy-server` 只在确认代理可用时才开（配置键 `proxy`），否则连国内直连站一起失败。

## 并发会话与实例归属（实测）

- 归属判定按 `--user-data-dir` 参数边界匹配（带引号，或无引号且后接空白/结尾），同前缀 profile（`edge-cdp` 与 `edge-cdp-fix`）互不认领、互不误关。
- 一个 profile 同一时刻只能有一个 Edge 实例；并发会话要各用**独立 `user_data_dir`**，只换 `port` 不换 profile 不成立（第二个实例启动即被首个接管或直接失败）。
- 实测：同一 profile、不同端口的另一配置执行 `close`（旧语义为 profile 级）会关掉本配置刚启动的实例——`9222` 实例被 `9666` 配置关掉，端口随即释放。这正是并发两方互相看到「实例启动后数秒自退」的根因，故默认改为端口级：`close` 只关本端口实例，profile 级清扫显式用 `close --all`。
- 清理一律按 profile 匹配，不要按 `remote-debugging-port=` 或进程名：Chromium 子进程命令行不总带该开关。实测按端口清理后仍残留 12 个本 profile 进程，随后观察到该 profile 实例重新出现（`--remote-debugging-port=9333` 重新监听）；改为按 profile 匹配清理后 45 秒内未再出现。
- 优雅关闭（`CloseMainWindow`）优先，强制终止只用于残留进程：`close` 内部即此顺序，端口释放才是判据。

## 生命周期与安全边界

- 实例归属按 `--user-data-dir` 参数的**边界**匹配（正则 `--user-data-dir=(?:"<ud>"|<ud>(?=\s|$))`）：`-like` 会把 profile 路径里的 `[ ]` 当通配符（漏匹配），`-Contains` 子串匹配会把 `edge-cdp2` / `edge-cdp-fix` / `hb-r2-9222` 这类同前缀 profile 误认成自己——实测默认 `…\edge-cdp` 配置把 `…\edge-cdp-lab2` 的 16 个进程算成自己的，`close` 把它们全关了（另一端口随之释放）。带引号与不带引号两种命令行形式都要覆盖（不同 Edge 子进程写法不同）。
- `close` 的成功判据是**端口释放**（Edge 主进程退出带走子进程），不是逐个子进程计数：先 `CloseMainWindow`，残留 `Stop-Process`，再轮询端口，仍未释放则非零退出；端口已释放但仍有残留进程时打印 `WARNING`（不误判为失败）。
- 就绪判定不能只看「端口有人听」：先 `Get-NetTCPConnection -LocalPort <port> -State Listen` 取监听进程，再核对该进程命令行匹配本 profile。否则端口被别的程序占用时会报 `already_listening`，随后所有子命令打到别人身上（实测用回环代理端口上的其他进程复现；另一 profile 的本 skill 实例同理）。
- 配置值（`port`/`user_data_dir`/`node_path`/`edge_path`/`proxy`/`winuser`）进入 PowerShell 命令前统一校验：含单引号或换行即拒绝，`port` 必须数字，`winuser` 限 `[A-Za-z0-9._-]`（配置键或环境变量 `HOST_BROWSER_WINUSER`）。不校验时配置即代码：`node_path: "node --version; Write-Output MARKER"` 实测可执行任意 PowerShell。
- `user_data_dir` 指向真实 Edge profile（`…\Microsoft\Edge\User Data`）时直接拒绝：否则 `close` 会去关用户自己的浏览器。
- Node 未能启动时 PowerShell 不设置 `$LASTEXITCODE`，原先 `exit $LASTEXITCODE` 会返回 0、把「命令不存在」当成功；现改为调用前置空并在仍为空时非零退出（实测坏 `node_path` 由 exit 0 变为 exit 1）。
- 参数形式：`--flag=value` 与 `--flag value` 等价——只认空格分隔会让 `--max=50` 被静默忽略、退回默认 8000。
- `Start-Process -ArgumentList` 拼接参数时不加引号，含空格的路径会被拆成多个参数；`--user-data-dir` / `--proxy-server` 的值需自带内嵌双引号（实测含空格与方括号的 profile 路径可正常启动与关闭）。
- 调试端口无鉴权：任何能连上它的进程都能读页面、执行脚本。保持 loopback，不擅自加转发或防火墙例外。

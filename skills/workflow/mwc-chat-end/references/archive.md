# 归档执行入口（按平台分流）

[归档脚本](../scripts/session_archive.py)只用 Python 标准库。平台由脚本根据环境变量判定：

- **WebUI**（`HERMES_SESSION_PLATFORM=webui` + 12 位小写十六进制 `HERMES_UI_SESSION_ID`）：复用 WebUI 原生 API，不改 WebUI 核心、不直写存储。认证用宿主已提供的 `HERMES_WEBUI_PASSWORD`，仅内存登录 Cookie 并在结束时退出该临时登录；不读浏览器会话库、不伪造签名、不输出密码或 Cookie。**目标只能取 `HERMES_UI_SESSION_ID`**，`HERMES_SESSION_ID` 会随压缩变化，不可替代或作为回退。连接固定 loopback、禁止重定向与环境代理。前提缺失或 SSO-only 时停止脚本路径，改用手动归档。
- **官方 WebApp / 桌面端**（`HERMES_SESSION_PLATFORM` 为 `local` / `gui` / `desktop`，且 `HERMES_SESSION_ID` 或 `HERMES_SESSION_CHAT_ID` 匹配 `local-` 加 64 位小写十六进制）：归档就是该会话在 profile 会话存储里的 `archived` 标记。脚本先只读解析到当前行（行 id 优先；压缩后 agent id 会轮换成 `<时间戳>_<hex>`，此时按 `HERMES_SESSION_CHAT_ID` 回退，并跳过 `end_reason='compression'` 的旧段）和 pin 状态，再调用 `hermes sessions archive --chat-id <解析到的行 chat_id> --include-open --yes`，最后只读读回。`check` 输出的是解析后的行 id，`--confirm-session` 就用它，不用环境变量里的原始 id。
  - **pin 会挡住归档**：CLI 一律跳过被 pin 的会话（`--include-pinned` 只有 prune 有）。脚本直接拒绝并说明原因；是否 unpin 由用户决定，不自行解 pin。
  - `--include-open` 必须带：桌面端 / WebApp 会话从不写 `ended_at`，缺它会漏掉当前会话。
  - CLI 的选择键是 chat id（精确但 chat 级）：行 `chat_id` 不是 `local-*`（例如历史 adopted chat）或为空时可能命中同 chat 的兄弟会话，脚本直接拒绝，请用户改在应用内归档。
  - CLI 在独立进程直接写会话存储：不 bump 可见 revision、不会通知正在运行的网关（WebApp 侧栏约 20 秒轮询自行刷新，桌面端刷新时机未核实），但 `on_session_delete` 插件钩子仍会在该 CLI 进程内触发。
  - 行查询失败、CLI 未报告恰好 1 个会话、或读回不一致，一律按失败处理，不重发、不直改数据库。
- 其它平台（CLI、cron、subagent 等）：脚本明确拒绝，说明需手动归档。

`SKILL_DIR` 必须取本次 `skill_view` 返回的真实目录，不假定当前工作区就是技能仓库：

```bash
python3 "$SKILL_DIR/scripts/session_archive.py" check
# 正文要求的归档确认齐全后，使用确认过的字面会话 ID，不用标题匹配。
python3 "$SKILL_DIR/scripts/session_archive.py" archive --confirm-session '<confirmed-session-id>'
```

脚本的 `verified` 只表示归档状态经读回核验；是否闭环仍由主 agent 的业务检查决定。接口版本、ID 格式或 CLI 输出变化时先核实再适配，不放宽校验凑成功。

## 迁移适配说明

- 宿主：Hermes WebUI（命名 profile 模式）与官方 WebApp / 桌面端（网关承载）。环境变量 `HERMES_SESSION_PLATFORM`、`HERMES_SESSION_ID`、`HERMES_UI_SESSION_ID`、`HERMES_HOME`、`HERMES_WEBUI_PORT` 由宿主提供，WebUI 密码登录另需宿主已提供的 `HERMES_WEBUI_PASSWORD`；脚本不读浏览器会话库、不读密码文件。
- 运行时依赖：仅 Python 标准库，无第三方包；WebApp 侧另需 `hermes` CLI 在 PATH 上，找不到即拒绝。WebUI 连接只走 loopback、禁止重定向与环境代理。
- 平台边界：以上实测都在 Linux/WSL（Python 3.14.9）。Windows 原生宿主未适配也未验证——`state.db` 的 `file:` URI 按 POSIX 路径拼接，`hermes` 若解析为 `.cmd` 无法被 `subprocess` 直接执行，示例命令用的是 `python3`。
- 首次运行验证：`python3 <SKILL_DIR>/scripts/session_archive.py self-test`，输出 `PASS`（Python 3.14.9）。WebApp 侧另实测：`check` 读出 `platform=webapp`、`archived=false`；`hermes sessions archive --chat-id … --include-open --yes` 对已结束会话和从未结束的会话都归档成功并读回 `archived=1`；对正在运行的会话做过归档 → 读回 → 恢复往返。压缩轮换后（agent id 为 `<时间戳>_<hex>`、chat id 仍为原 `local-*`）的回退路径只由自检覆盖，未在真实压缩过的 WebApp 会话上验证。WebUI 分支只用注入的假 API 自检，真实 WebUI 归档、其它 Hermes 版本与 SSO-only 环境**未验证**；缺 `HERMES_UI_SESSION_ID`、平台不支持或 SSO-only 时按正文停止脚本路径，改由用户手动归档。

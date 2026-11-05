# mm-disclosure — Hindsight 心智模型渐进式披露

Hermes 原生插件：首轮向主会话注入 Hindsight 心智模型**索引**（skills 式渐进披露），正文按需由 agent 主动拉取；不自动读取正文、不合并多个 bank、不修改 Hindsight 服务端。

## 工作方式

| 环节 | 处理 |
|---|---|
| 常驻规则 | `rule.md` 经 system prompt section 注入（字节稳定、不破坏缓存），只在主会话平台生效：CLI / TUI / WebUI / qqbot 消息端；子代理、cron 等入口不注入 |
| 首轮索引 | `pre_llm_call(is_first_turn)` 调 `list_mental_models(detail="metadata")` 生成 `[MENTAL-MODEL-INDEX]`，随用户消息注入；`when:` 前缀 tag 解析为触发场景，`[default]` 标记来自本地 `models.yaml` 覆盖层 |
| 正文加载 | agent 按索引顶部给出的 `get_mental_model` 调用方式显式拉取，插件不代替执行 |
| 埋点 | `post_tool_call` / `on_session_end` 写 JSONL 到 `$HERMES_HOME/cache/mm-disclosure/events.jsonl`，记录 session、platform、model/bank 元数据、长度与耗时；不含消息原文与凭据 |
| 降级 | 索引整体预算 4 秒（守护线程最多一个，排队记 `index_busy`），超时或 Hindsight 不可达时 fail-open：只注入标注「不完整」的本地默认模型列表，未登记默认模型则不注入，不阻塞会话 |

## 依赖与首次准备

- 面向 Hermes Agent 插件宿主，Python 3.10+，仅标准库；运行时用宿主环境，需能导入 `hermes_constants`、`hermes_cli.config`（宿主内建）。Hermes 获取入口：https://hermes-agent.nousresearch.com/docs/ 。
- 需要一个 streamable-HTTP 的 Hindsight mental model MCP 服务（`list_mental_models` / `get_mental_model`）。开源实现见 https://github.com/vectorize-io/hindsight ；本插件针对其中一个版本的线形实测编写，其他部署的响应细节可能有差异，兼容性未逐一核实。
- 在该 profile 的 Hermes 有效配置中配置 MCP 连接（默认连接名 `hindsight-mcp`）：`url` 必填，`headers.Authorization` 按服务需要可选。URL 与凭据只从有效配置读（支持 `${env:...}` 解析），不内置备用地址；未解析的 `${...}` 或缺 url 时不发请求，凭据不输出、不写入事件日志。
- 可选 `$HERMES_HOME/mm-disclosure.json`：`{"mcp_server": "hindsight-mcp", "bank_id": "可选"}`。文件缺失时用默认连接名且 `list_mental_models` 不传 `bank_id`（由服务端会话默认决定）；文件存在但无效（坏 JSON、非对象、字段类型错误）时不发请求、不注入索引，事件记 `config_invalid`，不静默回退默认 bank。同一首轮的列表读取与正文调用指引使用同一份配置。
- 若所用服务要求显式 bank，请在配置文件中设置 `bank_id`；插件不猜测 profile 或默认 bank，也不跨 bank 合并列表。
- 首次准备：`hermes --help` 确认宿主可用；完成上述 MCP 连接配置；用下方 `link.sh` 建立链接并把 `mm-disclosure` 加入该 profile 的 `plugins.enabled`；重启宿主进程后开新会话，看首轮是否出现 `[MENTAL-MODEL-INDEX]`，没有则查 `events.jsonl` 的 `error` 字段（`index_timeout`/`index_busy`/`config_invalid`/`empty_models`）。

## 安装与验证

```bash
HERMES_HOME=<target-profile-home> sh plugins/hermes-agent/mm-disclosure/link.sh
python3 -m unittest discover -s plugins/hermes-agent/mm-disclosure/tests -v
PYTHONDONTWRITEBYTECODE=1 hermes plugins doctor plugins/hermes-agent/mm-disclosure --ci
```

`plugins doctor` 用宿主的真实运行时契约检查清单解析、导入与 hook 注册，不联网、不启用插件；加 `PYTHONDONTWRITEBYTECODE=1` 避免在源码树留下 `__pycache__`。

`link.sh` 只接受不存在的目标或已指向本源码的符号链接，发现普通目录/文件时停止；不自动启用插件、不修改运行配置。修改后需在新会话验证，已有会话保存的 system prompt 不会被链接切换回写。

## 数据与权限边界

- 插件只读当前回合消息长度与少量历史/高影响关键词用于本地埋点，不保存消息原文。
- 运行事件写 `$HERMES_HOME/cache/mm-disclosure/events.jsonl`（超 ~2MB 轮转保留最近一半），只含 session/model/bank 元数据、长度与耗时，不含凭据正文，不入库。
- Hindsight 返回的模型正文由 agent 按规则显式拉取；插件不自动把正文注入工具调用，不授予权限，不扩大范围。当前用户要求、实时事实、宿主安全策略优先。
- `rule.md` 是常驻渐进披露规则；`__init__.py` 负责注册、索引构建、Hindsight MCP 读取与埋点；`models.yaml` 只保留 `[default]` 覆盖层；`plugin.yaml` 是 Hermes 插件清单。
- 已实测范围：本机离线契约测试（15 项通过）与 `hermes plugins doctor --ci`（清单 0.3.0、3 个 hook、通过）；未实测范围：新机器或干净环境安装、宿主实际加载、对真实 Hindsight 服务的端到端首轮注入。

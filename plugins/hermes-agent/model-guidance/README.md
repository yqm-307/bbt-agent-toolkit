# model-guidance — 按模型族 + 模式注入执行指引

替代宿主写死的 OpenAI 专用指引，改由本仓自管：按模型名命中模型族，再叠加当前模式（`long` 主脑 / `daily` 日常 / `off`）。

## 生效方式

| 场景 | 处理 |
|---|---|
| 新会话 | system prompt section 按当前模型与模式渲染一次并冻结，不破坏前缀缓存 |
| 会话中途切模型或模式 | `pre_llm_call` 注入一次新规则块，声明取代 section；注入内容随历史原样重放 |
| section 被共享预算跳过 | 插件拿不到宿主的接纳回执，因此每轮由 `pre_llm_call` 自己确认「本轮请求里规则还在不在」：在**用户消息的宿主追加区域**里找最近一次注入的令牌，与当前 key 比对，不在就补一次。判定不写状态、不加锁 |
| 上下文压缩 | 宿主重渲 section，按当时的模型与模式生成，约束不丢 |
| 子代理（非主会话平台） | 只注入 `prompts/family/worker.md` 的精简执行纪律，不注入模式 |

## 切换模式

- 本会话：`/guide long|daily|off`，`/guide auto` 回到默认；`/guide` 或 `/guide status` 查看当前值。
- 全局默认：`/guide global long|daily|off|auto`。入口不带会话信息时，`/guide <模式>` 也落到全局。
- 优先级：会话设置 > 全局默认 > `profiles.yaml` 按模型给的默认。
- 会话级切换要求宿主在调用插件命令时传入 `session_id`。请核对所用 CLI、TUI、gateway 或 WebUI 的插件命令分发能力；没有会话标识的入口会修改全局默认，不能当作会话级设置。

状态写在 `$HERMES_HOME/cache/model-guidance/state.json`：每个会话存 `/guide` 设置的 `mode`，另有 `global_mode`；只保留最近更新的 500 个会话，超出后最早写入的会话回到默认模式。写入经同目录 `state.lock` 的 `flock`，同一 profile 的多进程不会互相覆盖；读路径不加锁。

令牌密钥写在同目录 `secret`（0600，`O_EXCL` 首次生成，多进程读到同一份）。注入内容形如 `[model-guidance 更新] key=<族|角色|模式> token=<16 位 HMAC>｜<正文>`。

取证边界（一律宁可多注入一次，不漏注入、不误判已投递）：

- 只认 `role=user` 的 `api_content` 去掉 `content` 前缀的那段；前缀不匹配时不取证。
- assistant 行的 `api_content` 不作证据（模型能复述注入内容）。
- 多模态轮次的 text part 与用户自己的 part 无法区分，不作证据，该会话会多注入一次。
- 令牌失效但注入文本仍在（例如 `secret` 重建）时，切 `off` 仍会补发停用声明。

## 改规则

- 模型映射与默认模式：`profiles.yaml`（自上而下首个命中）。
- 加一个模型组（例：`deepseek` 系）：`rules` 加一条 `match: [deepseek]` + `family: <组名>`，`families` 下加 `main`/`worker` 两个正文路径，再建对应 md 文件。组规则不写 `default_mode`，就只注入该组正文、不叠 long/daily 模式块；正文留空则该组不注入任何内容。
- `profiles.yaml` 在模块导入时加载，改映射要重启宿主进程；`prompts/*.md` 正文每次现读，改完下一次新会话（或下一次压缩）生效。
- 正文：`prompts/family/*.md`、`prompts/mode/*.md`。本插件单个 section 上限 2,000 字符；全部插件 section 的共享预算以所用宿主版本为准。
- 改完新会话生效；进行中的会话下一次压缩时生效。

## 与宿主指引的关系

宿主对模型名含 `gpt`/`codex` 的会话自动注入 `TOOL_USE_ENFORCEMENT_GUIDANCE` 与 `OPENAI_MODEL_EXECUTION_GUIDANCE`。要由本插件接管，需把 `agent.tool_use_enforcement` 与 `agent.execution_guidance` 设成不含 `gpt`、`codex` 的模型子串列表。

## 依赖与首次准备

- 面向 Hermes Agent 插件宿主，Python 3.10+；代码使用 `fcntl.flock`，需 Linux、WSL 等支持 POSIX 文件锁的环境，不承诺原生 Windows 可用。
- 使用 Hermes 的 Python 环境，需能导入 `hermes_constants` 和 `hermes_yaml`；若无 `hermes_yaml`，代码回退到 PyYAML。Hermes 获取入口：https://hermes-agent.nousresearch.com/docs/ ；PyYAML 获取入口：https://pypi.org/project/PyYAML/ 。缺依赖时按宿主文档在用户批准的环境准备，不自动安装。
- 首次先确认解释器版本及 `hermes --help`，并在所选解释器中确认 `hermes_constants`、`hermes_yaml`（或 `yaml`）可导入。需要宿主支持 `pre_llm_call`、system prompt section、插件命令注册及相应的历史载体字段；确切兼容版本本次未核实。
- `profiles.yaml` 和 `prompts/` 随包提供，按模型族及使用模式选择，是可修改的通用策略；DeepSeek 主模型正文当前为空。`long` 模式明确使用 Hermes 委派工具与 OMH 路由、DAG/todo 能力；选择该模式前需接入相应公开工具或按目标宿主调整正文。其他模式不因此要求安装 OMH。
- 安装脚本需 POSIX shell、`readlink -f`、`ln -s`，并要求显式传入目标 `HERMES_HOME` 和该目录的写权限。不自动启用插件或重启服务；符号链接使用期间保留源码位置。
- 本包仅保留原有验证入口；本次迁移未执行准备命令、测试、安装或宿主加载，新机器可用性未验证。

## 安装与验证

```bash
HERMES_HOME=<target-profile-home> sh plugins/hermes-agent/model-guidance/link.sh
<hermes-venv>/bin/python -I plugins/hermes-agent/model-guidance/tests/test_plugin.py
```

然后把 `model-guidance` 加进该 profile 的 `plugins.enabled`，重启宿主进程。

离线检查同样使用已安装 Hermes 及 YAML 依赖的解释器；子进程以 `-I` 隔离模式运行，不依赖个人源码目录或 `PYTHONPATH`。若所选环境缺少宿主包，先补齐该环境，不通过注入作者本地路径绕过。

## 边界

纯提示词层，不拦截工具调用；只读 `conversation_history` 中「宿主追加」的那部分文本用于确认自己的注入是否还在，不读取用户消息内容、不外传；状态文件只存在本机；不输出凭据；异常时 fail-open。

# custom-prompt-inject — 按 JSON 条件注入自定义提示词

插件读取配置，根据当前模型、子代理角色和历史注入状态，决定把哪些 prompt 文件注入到哪种宿主提示词载体。

配置是同目录的 [`config.json`](config.json)；`prompt` 路径相对插件目录，禁止越界。`prompts/` 下按段分目录，有通用版本的段使用 `default.md`，模型专属版本按模型命名（如 `sol.md`）。

## 配置

```json
{
  "max_chars": 2000,
  "rules": [
    {
      "id": "subagent-common",
      "prompt": "prompts/subagent/default.md",
      "inject_into": ["system_prompt", "user_context"],
      "when": {"subagent": true}
    },
    {
      "id": "special-model-first-turn",
      "prompt": "prompts/special.md",
      "inject_into": ["user_context"],
      "when": {
        "model": "gpt-6.1-sol",
        "models": ["gpt-6.1-sol", "gpt-6-luna"],
        "model_regex": "^gpt-6",
        "subagent": false,
        "first_injection": true
      }
    }
  ]
}
```

每条规则的字段含义：

- `id`：规则唯一标识，用于历史去重和条件失效时的撤销通知。
- `prompt`：相对插件目录的 Markdown 文件路径，禁止越出插件目录。
- `inject_into`：`system_prompt` 写入系统提示 section；`user_context` 通过 `pre_llm_call` 写入当前用户消息的宿主追加区。两者可同时指定。
- `slot`：可选的段落名，用来像蓝图一样拼装提示词。同一段落只注入一条规则：在所有命中的规则里取声明条件（`subagent`、`model`、`models`、`model_regex`）最多的那条，同分取配置靠前的；条件最少的那条就是该段的默认版本。`first_injection` 是投递过滤，不参与比较。段落顺序按 slot 在配置中首次出现的位置，与版本规则的先后无关；不带 slot 的规则各自独立成段。
- `when.subagent`：匹配宿主传入的 `platform="subagent"`。不根据 `parent_session_id` 推断，普通分支会话也可能带这个字段。
- `when.model`：精确匹配一个模型名。
- `when.models`：精确匹配模型列表，列表内部取 OR。
- `when.model_regex`：模型正则，字符串或字符串数组，数组内部取 OR。
- `when.first_injection`：只对 `user_context` 有效；`true` 表示该规则在本会话首次注入时匹配，`false` 表示已有该规则历史注入后才匹配。

同一条规则中声明的条件取 AND；没有声明的条件不参与判断。模型精确值、模型列表和正则同时声明时必须同时满足。段落按配置顺序拼接：上限由 `max_chars` 决定（默认 2,000，最大 10,000）：system_prompt 另受宿主限制，单段上限读取宿主常量（读取不到时用 4,000），所有插件的合计上限也由宿主决定（未打补丁时为 8,000）（按段 id 排序，超出的整段被丢弃），只适合放很短的内容；长内容用 user_context，宿主默认超过 10,000 字（`hooks.output_spill.max_chars`）会落盘成文件；user_context 只发送能完整放入本轮剩余空间的通知，单条通知放不进上限时会持续暂缓，直到提示词缩短。

## 注入与去重

`system_prompt` 规则由宿主渲染 section。`user_context` 规则由 `pre_llm_call` 注入，并在宿主追加区写入带 HMAC 的规则令牌；下一轮读历史确认令牌仍在，避免重复注入。用户自己粘贴的文本、assistant 回显和伪造令牌都不算送达证据。

当模型或其他条件切换导致旧规则不再匹配时，插件会在 `user_context` 中追加一次撤销通知，让历史里的旧提示词失效。secret 位于 `$HERMES_HOME/cache/custom-prompt-inject/secret`，权限为 0600；插件不保存会话模式状态，也不注册运行时切换命令。

## 安装与验证

```bash
HERMES_HOME=<target-profile-home> sh plugins/hermes-agent/custom-prompt-inject/link.sh
<hermes-venv>/bin/python -I plugins/hermes-agent/custom-prompt-inject/tests/test_plugin.py
```

然后将 `custom-prompt-inject` 加入目标 profile 的 `plugins.enabled`，重启宿主进程。插件需要 Hermes Agent 的 `system prompt section`、`pre_llm_call` 和 `conversation_history` 宿主追加区契约；本地离线检查不等于真实 WebUI、CLI 或 gateway 端到端送达验证。

宿主自己的 `agent.execution_guidance` 与 `agent.tool_use_enforcement` 属于另一套内建提示词，不由本插件移除或接管。

## 边界

这是提示词注入层，不拦截工具调用；只读取历史中用于验证自身注入的宿主追加区，不读取或外传用户正文；异常时 fail-open。

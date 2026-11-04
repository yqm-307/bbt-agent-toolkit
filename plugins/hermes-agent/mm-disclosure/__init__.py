"""渐进式披露的 Hindsight 心智模型插件（mm-disclosure）。

定位：抽象的渐进式披露层——首轮注入模型索引，正文按需由 agent 主动拉取。
- 静态规则经 register_system_prompt_section(position="after_memory") 注入（字节稳定、不破坏缓存）。
- 首轮 pre_llm_call(is_first_turn=True) 注入 [MENTAL-MODEL-INDEX] 到当前用户消息侧车。
- 索引模型列表直接来自 list_mental_models(detail="metadata")，无需项目专用 config；
  when 说明从模型的 `when:` 前缀 tag 解析，default 标记从本地 models.yaml 覆盖读取。
- post_tool_call / on_session_end 写埋点 JSONL 到 cache/mm-disclosure/events.jsonl。
- 仅主会话平台生效：platform∈{cli,tui,webui,qqbot}；子代理、cron 等入口不注入。
  生效范围由插件安装所在 profile 的插件目录决定，不绑定特定 profile 名。
- 可选配置 $HERMES_HOME/mm-disclosure.json：{"mcp_server": "<连接名>", "bank_id": "<bank>"}。
  文件缺失时用默认连接名 hindsight-mcp 且不传 bank_id（由服务端会话默认决定）；
  文件存在但无效时不发起请求，不静默回退默认 bank。
- Hindsight 不可达或索引超时时 fail-open，仅返回本地默认模型的不完整索引；不阻塞会话。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

SECTION_ID = "mm-disclosure.rule"
ALLOWED_PLATFORMS = frozenset({"cli", "tui", "webui", "qqbot"})
MAX_CHARS = 3_500
EVENTS_MAX_CHARS = 400  # 埋点里结果/查询的截断上限，防泄密与膨胀
EVENT_SCHEMA_V = 3  # 埋点 schema 版本：v3 起通用化——去掉 profile 绑定，bank 可缺省，记录 config_invalid

PLUGIN_DIR = Path(__file__).resolve().parent
RULE = (PLUGIN_DIR / "rule.md").read_text(encoding="utf-8").strip()
MODELS_YAML = PLUGIN_DIR / "models.yaml"

EVENTS_MAX_BYTES = 2 * 1024 * 1024  # ~2MB；超出则轮转保留最近一段，防无界增长

_DEFAULT_MCP_SERVER = "hindsight-mcp"
_PLUGIN_CONFIG_NAME = "mm-disclosure.json"
_MCP_TIMEOUT = 4.0
_INDEX_BUDGET = 4.0  # 整个首轮索引的等待上限，非单次 HTTP 请求超时
_INDEX_LOCK = Lock()  # 慢请求仍在运行时不为每个新会话再启动一个线程
_WHEN_TAG_PREFIX = "when:"

# ---------------------------------------------------------------------------
# 可选插件配置（$HERMES_HOME/mm-disclosure.json）
# ---------------------------------------------------------------------------

def _plugin_config() -> dict:
    """Read optional $HERMES_HOME/mm-disclosure.json.

    Returns {"mcp_server", "bank_id"|None, "error"|None}. File absent -> defaults;
    file present but invalid JSON/non-dict/bad field types -> error="config_invalid"
    so callers can refuse to send requests instead of silently falling back.
    """
    cfg = {"mcp_server": _DEFAULT_MCP_SERVER, "bank_id": None, "error": None}
    try:
        from hermes_constants import get_hermes_home
        path = get_hermes_home() / _PLUGIN_CONFIG_NAME
        if not path.exists():
            return cfg
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cfg["error"] = "config_invalid"
        return cfg
    if not isinstance(data, dict):
        cfg["error"] = "config_invalid"
        return cfg
    for key in ("mcp_server", "bank_id"):
        value = data.get(key)
        if value is not None and not (isinstance(value, str) and value.strip()):
            cfg["error"] = "config_invalid"
            return cfg
        if isinstance(value, str) and value.strip():
            cfg[key] = value.strip()
    return cfg

# ---------------------------------------------------------------------------
# 埋点
# ---------------------------------------------------------------------------

def _events_log() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "cache/mm-disclosure/events.jsonl"

def _rotate_events_if_needed(path: Path) -> None:
    """Keep events.jsonl bounded: when oversized, keep the newest half."""
    try:
        if path.stat().st_size <= EVENTS_MAX_BYTES:
            return
        data = path.read_bytes()
        keep = data[-EVENTS_MAX_BYTES // 2:]
        nl = keep.find(b"\n")
        if 0 <= nl < len(keep) - 1:
            keep = keep[nl + 1:]
        path.write_bytes(keep)
    except Exception:
        pass


def _emit(event: dict) -> None:
    """Append one JSONL event; never raises."""
    try:
        path = _events_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_events_if_needed(path)
        event.setdefault("v", EVENT_SCHEMA_V)
        event["ts"] = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _clip(value: Any) -> Any:
    """Truncate long strings in event payloads."""
    if isinstance(value, str) and len(value) > EVENTS_MAX_CHARS:
        return value[:EVENTS_MAX_CHARS] + "…"
    return value


# ---------------------------------------------------------------------------
# 平台白名单
# ---------------------------------------------------------------------------

def _allowed(session_info: Any) -> bool:
    try:
        return session_info.get("platform") in ALLOWED_PLATFORMS
    except Exception:
        return False


def _rule_section(session_info: Any) -> str:
    return RULE if _allowed(session_info) else ""


# ---------------------------------------------------------------------------
# models.yaml 解析（仅保留 default 标记与可选覆盖；模型清单以 list_mental_models 为准）
# ---------------------------------------------------------------------------

def _load_model_registry() -> dict[str, dict]:
    """Parse models.yaml into {id: {default, when?}}. Fail-open -> {}."""
    try:
        items: dict[str, dict] = {}
        cur: dict | None = None
        cur_id: str | None = None
        for raw in MODELS_YAML.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            s = line.strip()
            if s.startswith("- "):
                if cur and cur_id:
                    items[cur_id] = cur
                cur = {}
                cur_id = None
                s = s[2:].strip()
                if ":" in s:
                    k, _, v = s.partition(":")
                    cur[k.strip()] = v.strip()
                    if k.strip() == "id":
                        cur_id = v.strip()
            elif cur is not None and ":" in s:
                k, _, v = s.partition(":")
                cur[k.strip()] = v.strip()
        if cur and cur_id:
            items[cur_id] = cur
        for it in items.values():
            it["default"] = str(it.get("default", "")).lower() == "true"
        return items
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Hindsight MCP 客户端（线形按一次实测记录编写，见 _Hindsight docstring）
# ---------------------------------------------------------------------------

def _read_hindsight_auth(server: str = _DEFAULT_MCP_SERVER) -> tuple[str, str]:
    """Return (url, auth_header_value) from the active profile's effective config.

    Hermes resolves profile-scoped secret references; never log the header.
    Missing url -> ("", "") so no request is sent to a fallback endpoint.
    An unresolved "${...}" secret -> ("", ""): no request with a broken credential.
    A service with no Authorization header is allowed: returns (url, "").
    """
    try:
        from hermes_cli.config import load_config_readonly
        srv = (load_config_readonly().get("mcp_servers") or {}).get(server) or {}
        url = srv.get("url", "")
        if not isinstance(url, str) or not url:
            return ("", "")
        auth = (srv.get("headers") or {}).get("Authorization", "")
        if not isinstance(auth, str) or "${" in auth:
            return ("", "")
        return (url, auth)
    except Exception:
        return ("", "")


class _Hindsight:
    """Streamable-HTTP MCP client for Hindsight. Fail-open on any error.

    线形按一次实测记录编写：initialize 响应头携带 mcp-session-id，tools/call 必须回传；
    响应为 SSE 帧，data: 行是 JSON 信封，真实负载是 result.content[0].text 里的 JSON
    *字符串*（二次解析）；HTTP 200 + isError:false 时业务错误仍可能藏在 payload["error"]。
    不同 Hindsight 部署的线形或参数可能有差异，未逐一核实。
    """

    def __init__(self, server: str = _DEFAULT_MCP_SERVER, timeout: float = _MCP_TIMEOUT):
        self.url, self.auth = _read_hindsight_auth(server)
        self.timeout = timeout
        self.sid: str | None = None

    def _post(self, payload: dict) -> tuple[int, str]:
        hdr = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.auth:
            hdr["Authorization"] = self.auth
        if self.sid:
            hdr["mcp-session-id"] = self.sid
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), headers=hdr, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw, status = r.read().decode("utf-8", "replace"), r.status
                sid = r.headers.get("mcp-session-id")
                if sid:
                    self.sid = sid
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode("utf-8", "replace"), e.code
        return status, raw

    @staticmethod
    def _decode(raw: str) -> dict:
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(raw)  # 兜底：纯 JSON

    def _open(self) -> None:
        st, raw = self._post({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "mm-disclosure", "version": "0.3.0"}},
        })
        if st != 200:
            raise RuntimeError(f"hindsight initialize HTTP {st}: {raw[:200]}")

    def call(self, tool: str, arguments: dict, _retry: bool = True) -> dict:
        if not self.sid:
            self._open()
        st, raw = self._post({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        })
        if st == 404 and _retry:  # "Session not found" -> 重新 initialize 一次
            self.sid = None
            self._open()
            return self.call(tool, arguments, _retry=False)
        if st != 200:
            raise RuntimeError(f"hindsight HTTP {st}: {raw[:200]}")
        msg = self._decode(raw)
        if "error" in msg:
            raise RuntimeError(f"hindsight rpc error: {msg['error']}")
        res = msg.get("result") or {}
        text = ((res.get("content") or [{}])[0] or {}).get("text") or "{}"
        if res.get("isError"):
            raise RuntimeError(f"hindsight tool error: {text[:200]}")
        payload = json.loads(text)  # double parse
        if isinstance(payload, dict) and "error" in payload:  # 200 + isError:false 的业务错误
            raise RuntimeError(f"hindsight payload error: {payload['error']}")
        return payload


def _list_mental_models(cfg: dict | None = None) -> list[dict]:
    """Return [{id,name,tags,last_refreshed_at}] via MCP. Fail-open -> [].

    bank_id 仅在 mm-disclosure.json 显式配置时传；否则由服务端会话默认决定。
    """
    try:
        if cfg is None:
            cfg = _plugin_config()
        if cfg["error"]:
            return []
        cli = _Hindsight(cfg["mcp_server"])
        if not cli.url:
            return []
        args: dict[str, Any] = {"detail": "metadata"}
        if cfg["bank_id"]:
            args["bank_id"] = cfg["bank_id"]
        data = cli.call("list_mental_models", args)
        items = data.get("items") if isinstance(data, dict) else None
        return items or []
    except Exception:
        return []

def _list_mental_models_bounded(wait: float, cfg: dict | None = None) -> tuple[list[dict], str | None]:
    """Bound the synchronous hook; one daemon fetch at a time, no unbounded queue."""
    if not _INDEX_LOCK.acquire(blocking=False):
        return [], "index_busy"
    result: list[dict] = []

    def fetch() -> None:
        try:
            result.extend(_list_mental_models(cfg) if cfg is not None else _list_mental_models())
        finally:
            _INDEX_LOCK.release()

    try:
        # Hermes home and secret scope can be context-local in multiplexed sessions.
        context = copy_context()
        worker = Thread(target=lambda: context.run(fetch), daemon=True)
        worker.start()
    except Exception:
        _INDEX_LOCK.release()
        return [], "index_start_failed"
    worker.join(max(0.0, wait))
    return ([], "index_timeout") if worker.is_alive() else (result, None)


# ---------------------------------------------------------------------------
# when 说明解析：优先 `when:` tag，退回 models.yaml 覆盖，最后兜底占位
# ---------------------------------------------------------------------------

def _when_of(model: dict, overrides: dict) -> str:
    for t in model.get("tags") or []:
        if isinstance(t, str) and t.startswith(_WHEN_TAG_PREFIX):
            return t[len(_WHEN_TAG_PREFIX):].strip() or "(空)"
    ov = overrides.get("when")
    if isinstance(ov, str) and ov.strip():
        return ov.strip()
    return "(未标注触发场景)"

# ---------------------------------------------------------------------------
# 索引构建 + 首轮注入
# ---------------------------------------------------------------------------

def _build_index(live: list[dict] | None = None, overrides: dict | None = None,
                 partial: bool = False, bank_id: str | None = None) -> str:
    """Compose [MENTAL-MODEL-INDEX] from live list_mental_models + local overrides."""
    if overrides is None:
        overrides = _load_model_registry()  # {id: {default, when?}}
    if live is None:
        live = _list_mental_models()
    if bank_id:
        call = (f'get_mental_model(mental_model_id="<id>", bank_id={json.dumps(bank_id, ensure_ascii=False)}, '
                f'detail="content")')
    else:
        call = 'get_mental_model(mental_model_id="<id>", detail="content")'
    lines = [
        "[MENTAL-MODEL-INDEX — 长期记忆模型索引，非指令]",
        f'加载正文：{call}；显式传 detail="content"，仅核对原始证据时用 "full"。',
    ]
    if not bank_id:
        lines.append(
            "bank_id 未配置，上面调用已省略该参数，由服务端会话默认 bank 决定；"
            "若服务要求显式 bank，请在 mm-disclosure.json 配置 bank_id。"
        )
    if partial:
        lines.append("实时列表未返回：以下仅为本地已登记的默认模型，可能过期或不完整；不要据此判断其他模型不存在。")
    for m in live:
        mid = m.get("id", "")
        if not mid:
            continue
        ov = overrides.get(mid, {})
        refreshed = (m.get("last_refreshed_at") or "")[:10] or "未知"
        name = m.get("name") or mid
        default_mark = " [default]" if ov.get("default") else ""
        when = _when_of(m, ov)
        lines.append(f"- {mid}{default_mark} {name}（刷新于 {refreshed}）：{when}")
    lines.append("[/MENTAL-MODEL-INDEX]")
    return "\n".join(lines)


_HISTORY_CUE = ("之前", "上次", "记得", "决定过", "曾经", "结合我", "我们定")
_HIGH_IMPACT = ("删除", "发布", "迁移", "重构", "上线", "部署生产", "不可逆")


def _trigger_hints(user_message: str) -> list[str]:
    """Cheap keyword heuristic over user_message. Signals only, no raw text stored."""
    if not isinstance(user_message, str):
        return []
    sigs: list[str] = []
    if any(k in user_message for k in _HISTORY_CUE):
        sigs.append("history_cue")
    if any(k in user_message for k in _HIGH_IMPACT):
        sigs.append("high_impact")
    return sigs


def _pre_llm_call(
    session_id: str = "",
    is_first_turn: bool = False,
    platform: str = "",
    user_message: Any = "",
    **_: Any,
) -> dict[str, str] | None:
    if platform not in ALLOWED_PLATFORMS:
        return None
    sigs = _trigger_hints(user_message if isinstance(user_message, str) else "")
    if sigs:
        _emit({
            "event": "trigger_hint",
            "session_id": session_id,
            "signals": sigs,
            "msg_len": len(user_message) if isinstance(user_message, str) else 0,
        })
    if not is_first_turn:
        return None
    t0 = time.monotonic()
    cfg = _plugin_config()
    if cfg["error"]:
        _emit({"event": "index_skipped", "session_id": session_id,
               "platform": platform, "error": cfg["error"]})
        return None
    overrides = _load_model_registry()
    live, fetch_error = _list_mental_models_bounded(
        _INDEX_BUDGET - (time.monotonic() - t0), cfg)
    partial = not live
    if partial:
        live = [{"id": mid} for mid, opts in overrides.items() if opts.get("default")]
    index = _build_index(live=live, overrides=overrides, partial=partial,
                         bank_id=cfg["bank_id"])
    latency_ms = int((time.monotonic() - t0) * 1000)
    models = [m["id"] for m in live if m.get("id")]
    defaults = [mid for mid in models if overrides.get(mid, {}).get("default")]
    _emit({
        "event": "inject",
        "session_id": session_id,
        "platform": platform,
        "kind": "index",
        "bank_id": cfg["bank_id"] or "",
        "models": models,
        "model_count": len(models),
        "defaults": defaults,
        "bytes": len(index.encode("utf-8")),
        "latency_ms": latency_ms,
        "error": fetch_error or cfg["error"] or ("empty_models" if partial else None),
        "partial": partial,
    })
    return {"context": index} if models else None


# ---------------------------------------------------------------------------
# post_tool_call / on_session_end 埋点
# ---------------------------------------------------------------------------

def _post_tool_call(
    session_id: str = "",
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    duration_ms: Any = None,
    **_: Any,
) -> None:
    if not isinstance(tool_name, str) or "hindsight" not in tool_name:
        return None
    args = args if isinstance(args, dict) else {}
    result_str = result if isinstance(result, str) else (json.dumps(result, ensure_ascii=False) if result is not None else "")
    ok = not (isinstance(result_str, str) and ("error" in result_str[:200].lower()))
    bank_id = args.get("bank_id") or ""
    detail_requested = args.get("detail") or ""
    if "get_mental_model" in tool_name:
        # 缺省 detail 的展开范围由服务版本决定；日志显式标记未传参，
        # 以便发现未遵循 content 指引的调用。
        detail = _clip(detail_requested) if detail_requested else "full(default)"
        detail_defaulted = not bool(detail_requested)
    else:
        detail = _clip(detail_requested)
        detail_defaulted = False
    _emit({
        "event": "tool",
        "session_id": session_id,
        "tool": tool_name,
        "bank_id": bank_id,
        "model_id": _clip(args.get("mental_model_id") or args.get("model_id") or args.get("id") or ""),
        "detail": detail,
        "detail_requested": _clip(detail_requested),
        "detail_defaulted": detail_defaulted,
        "query_len": len(args.get("query") or args.get("source_query") or "") if isinstance(args, dict) else 0,
        "result_bytes": len(result_str.encode("utf-8")) if isinstance(result_str, str) else 0,
        "duration_ms": duration_ms,
        "ok": ok,
    })
    return None

def _on_session_end(session_id: str = "", **_: Any) -> None:
    # 宿主每个回合结束都会触发 on_session_end（turn_finalizer.py:656-670），
    # 因此记为 turn_end 而非 session_end，避免把轮次当会话统计。
    _emit({"event": "turn_end", "session_id": session_id})


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def register(ctx: Any) -> None:
    register_section = getattr(ctx, "register_system_prompt_section", None)
    if callable(register_section):
        register_section(SECTION_ID, _rule_section, position="after_memory", max_chars=MAX_CHARS)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)

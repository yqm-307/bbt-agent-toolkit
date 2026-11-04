"""model-guidance：按模型族 + 模式注入执行指引。

- system prompt section：每个新会话按当前模型与模式渲染一次并冻结，压缩时宿主重渲。
- pre_llm_call：只读判断「本轮请求里规则还在不在」——在宿主追加的区域里找最近一次注入的令牌
  与当前 key 比对，不在就补注入一次（落进历史后原样重放，不破坏前缀缓存）。
- 模式：`/guide long|daily|off|auto` 改当前会话；`/guide global <模式>` 改全局默认。
  优先级：会话设置 > 全局默认 > profiles.yaml 按模型给的默认。

为什么读历史而不记账：需求是「本次请求里规则还在」，不是「曾经发过一次」。`/retry`、`/undo`、
TUI rewind 会重放历史而不重跑 hook，hook 也可能因宿主超时被丢弃；记账会把这些都记成已投递。
为什么看「宿主追加区域」：字符串消息的注入写在 `api_content` 侧栏（= content + 宿主追加），
用户自己能写的只有 content，因此引用/粘贴标记不构成证据；令牌用本地密钥做 HMAC，无法伪造。
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:  # 宿主自带 hermes_yaml（ruamel）；部分宿主解释器没有 PyYAML
    import hermes_yaml as yaml
except ImportError:
    import yaml

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).resolve().parent
SECTION_ID = "model-guidance"
MAX_CHARS = 2000
MODES = ("long", "daily", "off")
# ponytail: 会话状态只保留最近更新的 500 个；超出后最早写入的会话回到默认模式，需要再执行一次 /guide。
MAX_SESSIONS = 500
MARKER = "[model-guidance 更新]"
LEAD = "以下规则取代系统提示里的 model-guidance 一节：\n\n"
OFF_NOTICE = "系统提示里的 model-guidance 一节已不适用，忽略它。"
_TOKEN_RE = re.compile(re.escape(MARKER) + r" key=(\S+) token=([0-9a-f]{16})｜")

_secret_cache: bytes | None = None


def _load_profiles() -> dict[str, Any]:
    return yaml.safe_load((PLUGIN_DIR / "profiles.yaml").read_text(encoding="utf-8")) or {}


PROFILES = _load_profiles()


def _read(rel: str) -> str:
    return (PLUGIN_DIR / rel).read_text(encoding="utf-8").strip()


def _state_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "cache/model-guidance/state.json"


def _secret() -> bytes:
    """本地密钥，首次使用时生成；只用于给注入令牌做 HMAC。"""
    global _secret_cache
    if _secret_cache is None:
        path = _state_path().parent / "secret"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:  # O_EXCL：只有一个进程能创建，其余直接读已存在的那份
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(secrets.token_bytes(32))
        _secret_cache = path.read_bytes()
    return _secret_cache


def _token(session_id: str, key: str) -> str:
    return hmac.new(_secret(), f"{session_id}\0{key}".encode(), hashlib.sha256).hexdigest()[:16]


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    sessions = state.get("sessions") or {}
    if len(sessions) > MAX_SESSIONS:
        state["sessions"] = dict(list(sessions.items())[-MAX_SESSIONS:])
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _locked_state() -> Iterator[dict[str, Any]]:
    """独占跨进程锁下的状态；只在 `/guide` 写路径使用，hook 路径不加锁也不写状态。"""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / "state.lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            state = _load_state()
            yield state
            _save_state(state)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _update_session(session_id: str, **fields: Any) -> None:
    if not session_id:
        return
    with _locked_state() as state:
        sessions = state.setdefault("sessions", {})
        entry = sessions.pop(session_id, {})  # pop + 重插，让最近更新的排在末尾
        entry.update(fields)
        sessions[session_id] = entry


def _match_rule(model: str) -> dict[str, Any] | None:
    name = (model or "").lower()
    for rule in PROFILES.get("rules") or []:
        if any(str(m).lower() in name for m in rule.get("match") or []):
            return rule
    return None


def _is_main(platform: str) -> bool:
    return (platform or "").lower() in set(PROFILES.get("main_platforms") or [])


def resolve(model: str, platform: str, session_id: str, state: Mapping[str, Any] | None = None) -> tuple[str, str, str]:
    """返回 (family, role, mode)；未命中的项为空串。"""
    state = _load_state() if state is None else state
    rule = _match_rule(model) or {}
    family = str(rule.get("family") or "")
    if not _is_main(platform):
        return family, "worker" if family else "", ""
    session = (state.get("sessions") or {}).get(session_id) or {}
    mode = session.get("mode") or state.get("global_mode") or rule.get("default_mode") or ""
    return family, "main" if family else "", mode if mode in MODES else ""


def build_block(family: str, role: str, mode: str) -> str:
    """按族/角色/模式拼正文。family 与 role 来自 profiles.yaml；配置写错会抛错并由调用方记日志。"""
    if mode == "off":
        return ""
    parts = []
    if family and role:
        parts.append(_read(PROFILES["families"][family][role]))
    if mode and role != "worker":
        parts.append(_read(PROFILES["modes"][mode]))
    return "\n\n".join(parts)[:MAX_CHARS]


def _key(family: str, role: str, mode: str) -> str:
    return f"{family}|{role}|{mode}"


def _host_regions(msg: Mapping[str, Any]) -> Iterator[str]:
    """产出该消息里「宿主追加」的文本，用作投递证据。

    只认 user 行：宿主也会给 assistant 行生成 `api_content`（回显），而模型能复述注入内容，
    拿它当证据会把「模型说过」当成「规则还在」。

    真实消息里 `api_content` 不是简单 `content + 追加`：平台会在前面加工作区标记与
    memory-context，用户原文出现在中间。因此取「content 最后一次出现之后」的尾部作为
    宿主追加区（宿主把注入拼在整条消息末尾）。用户自己粘贴的副本落在 content 内部，会被排除。
    定位不到 content 时退化为整段 api_content，只靠令牌 HMAC 把关（宁可多注入，不漏撤规则）。
    多模态的注入是 content 列表里普通 text part，与用户自己的 part 无法区分，因此一律不作证据。
    """
    if msg.get("role") != "user":
        return
    api = msg.get("api_content")
    if not isinstance(api, str) or not api:
        return
    content = msg.get("content")
    if isinstance(content, str) and content:
        pos = api.rfind(content)
        yield api[pos + len(content):] if pos >= 0 else api
    else:
        yield api


def _carriers(history: Any, session_id: str) -> list[str]:
    """按出现顺序返回历史里「令牌校验通过」的 key。"""
    found: list[str] = []
    for msg in history or ():
        if not isinstance(msg, Mapping):
            continue
        for text in _host_regions(msg):
            for match in _TOKEN_RE.finditer(text):
                key, token = match.group(1), match.group(2)
                if hmac.compare_digest(token, _token(session_id, key)):
                    found.append(key)
    return found


def _has_marker_text(history: Any) -> bool:
    """历史里是否出现过本插件的注入文本（不看令牌是否有效）。

    只用于停用声明的兜底：secret 重建、令牌失效后，旧规则仍在历史里随请求送出，
    这时必须补一次「已不适用」，否则用户切 off 后旧规则继续生效。
    """
    for msg in history or ():
        if isinstance(msg, Mapping):
            for text in _host_regions(msg):
                if MARKER in text:
                    return True
    return False


def _section(info: Mapping[str, Any]) -> str:
    try:
        sid = str(info.get("session_id") or "")
        family, role, mode = resolve(str(info.get("model") or ""), str(info.get("platform") or ""), sid)
        return build_block(family, role, mode)
    except Exception:  # fail-open：渲染失败不影响会话
        logger.warning("model-guidance section render failed", exc_info=True)
        return ""


def _notice(session_id: str, key: str, block: str) -> str:
    head = f"{MARKER} key={key} token={_token(session_id, key)}｜"
    return head + (f"{LEAD}{block}" if block else OFF_NOTICE)


def _pre_llm_call(
    session_id: str = "", model: str = "", platform: str = "", conversation_history: Any = None, **_: Any,
) -> dict[str, str] | None:
    try:
        if not session_id:
            return None
        state = _load_state()
        family, role, mode = resolve(model, platform, session_id, state)
        block = build_block(family, role, mode)
        key = _key(family, role, mode)
        carriers = _carriers(conversation_history, session_id)
        if carriers and carriers[-1] == key:
            return None  # 本轮请求里已经有当前规则，不重复注入
        if not block and not carriers and not _has_marker_text(conversation_history):
            return None  # 没有规则要发，也没有旧规则要撤
        return {"context": _notice(session_id, key, block)}
    except Exception:
        logger.warning("model-guidance pre_llm_call failed", exc_info=True)
        return None


USAGE = "用法: /guide [status|long|daily|off|auto]，或 /guide global <long|daily|off|auto>"


def _command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    """有会话 id 时改当前会话；没有（或写 global）时改全局默认。"""
    words = (raw_args or "").strip().lower().split()
    is_global = bool(words) and words[0] == "global"
    if is_global:
        words = words[1:]
    arg = words[0] if words else "status"
    if len(words) > 1 or arg not in (*MODES, "auto", "status"):
        return USAGE
    state = _load_state()
    session_mode = ((state.get("sessions") or {}).get(session_id) or {}).get("mode") if session_id else None
    if arg == "status":
        return (f"本会话: {session_mode or '跟随默认'}；全局默认: {state.get('global_mode') or '按模型'}。"
                + ("" if session_id else "（当前入口没有会话信息）"))
    value = "" if arg == "auto" else arg
    if is_global or not session_id:
        with _locked_state() as state:
            state["global_mode"] = value
        return f"全局默认已设为 {arg}，下一轮生效；单独设置过的会话不受影响。"
    _update_session(session_id, mode=value)
    return f"本会话模式已设为 {arg}，下一轮生效。"


def register(ctx: Any) -> None:
    ctx.register_system_prompt_section(SECTION_ID, _section, position="after_memory", max_chars=MAX_CHARS)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_command("guide", _command, description="model-guidance 模式：long、daily、off、auto（global 改全局）",
                         args_hint="[status|long|daily|off|auto|global <模式>]")

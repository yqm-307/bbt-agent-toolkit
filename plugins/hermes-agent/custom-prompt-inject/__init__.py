"""custom-prompt-inject：按 JSON 条件把自定义提示词注入指定宿主载体。

每条规则声明 prompt 文件、注入目标与条件。system_prompt 规则用于稳定的系统提示
section；user_context 规则通过 pre_llm_call 注入当前用户消息的宿主追加区，并用本地
HMAC 令牌判断历史里是否已经送达。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, Iterator, Mapping

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_DIR / "config.json"
SECTION_ID = "custom-prompt-inject"
MAX_CHARS = 2000
MARKER = "[custom-prompt-inject]"
LEAD = "以下规则由 custom-prompt-inject 注入：\n\n"
REVOKE_MARKER = "[custom-prompt-inject revoke]"
_TOKEN_RE = re.compile(
    re.escape(MARKER) + r" rule=([A-Za-z0-9_.-]+) key=([0-9a-f]{12}) token=([0-9a-f]{16})｜"
)
_REVOKE_RE = re.compile(
    re.escape(REVOKE_MARKER) + r" rule=([A-Za-z0-9_.-]+) token=([0-9a-f]{16})｜"
)
_RULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_VALID_TARGETS = {"system_prompt", "user_context"}
_VALID_CONDITIONS = {"subagent", "model", "models", "model_regex", "first_injection"}
_secret_cache: bytes | None = None


def _resolve_prompt(rel: str) -> Path:
    path = (PLUGIN_DIR / rel).resolve()
    if path != PLUGIN_DIR and PLUGIN_DIR not in path.parents:
        raise ValueError(f"prompt path escapes plugin directory: {rel}")
    return path


def _load_config() -> dict[str, Any]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError("config.json must contain a rules array")
    max_chars = data.get("max_chars", MAX_CHARS)
    if not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_CHARS:
        raise ValueError(f"max_chars must be between 1 and {MAX_CHARS}")
    seen_ids: set[str] = set()
    for rule in data["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be an object")
        rule_id = rule.get("id")
        prompt = rule.get("prompt")
        targets = rule.get("inject_into")
        when = rule.get("when", {})
        if not isinstance(rule_id, str) or not _RULE_ID_RE.fullmatch(rule_id) or rule_id in seen_ids:
            raise ValueError(f"invalid or duplicate rule id: {rule_id!r}")
        seen_ids.add(rule_id)
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"rule {rule_id}: prompt must be a non-empty path")
        if not isinstance(targets, list) or not targets or not set(targets) <= _VALID_TARGETS:
            raise ValueError(f"rule {rule_id}: inject_into has an unsupported target")
        if not isinstance(when, dict) or not set(when) <= _VALID_CONDITIONS:
            raise ValueError(f"rule {rule_id}: unsupported condition")
        if "subagent" in when and not isinstance(when["subagent"], bool):
            raise ValueError(f"rule {rule_id}: subagent must be boolean")
        if "model" in when and not isinstance(when["model"], str):
            raise ValueError(f"rule {rule_id}: model must be a string")
        if "models" in when and not (
            isinstance(when["models"], list) and all(isinstance(value, str) for value in when["models"])
        ):
            raise ValueError(f"rule {rule_id}: models must be a string array")
        patterns = when.get("model_regex", [])
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list) or not all(isinstance(value, str) for value in patterns):
            raise ValueError(f"rule {rule_id}: model_regex must be a string or string array")
        for pattern in patterns:
            re.compile(pattern, re.IGNORECASE)
        if "first_injection" in when and not isinstance(when["first_injection"], bool):
            raise ValueError(f"rule {rule_id}: first_injection must be boolean")
        if "first_injection" in when and "user_context" not in targets:
            raise ValueError(f"rule {rule_id}: first_injection requires user_context")
        _resolve_prompt(prompt)
    return data


CONFIG = _load_config()
MAX_CHARS = CONFIG.get("max_chars", MAX_CHARS)
RULES = CONFIG["rules"]


def _read(rel: str) -> str:
    return _resolve_prompt(rel).read_text(encoding="utf-8").strip()


def _secret_path() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "cache/custom-prompt-inject/secret"


def _secret() -> bytes:
    """本地密钥只用于验证历史里的插件注入令牌。"""
    global _secret_cache
    if _secret_cache is None:
        path = _secret_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
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


def _host_regions(msg: Mapping[str, Any]) -> Iterator[str]:
    """只返回 user 消息中由宿主追加的尾部，排除用户自己写入的正文。"""
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


def _history_events(history: Any, session_id: str) -> list[tuple[str, str, str]]:
    events: list[tuple[str, str, str]] = []
    for msg in history or ():
        if not isinstance(msg, Mapping):
            continue
        for text in _host_regions(msg):
            for match in _TOKEN_RE.finditer(text):
                rule_id, key, token = match.groups()
                if hmac.compare_digest(token, _token(session_id, f"update:{rule_id}:{key}")):
                    events.append(("update", rule_id, key))
            for match in _REVOKE_RE.finditer(text):
                rule_id, token = match.groups()
                if hmac.compare_digest(token, _token(session_id, f"revoke:{rule_id}")):
                    events.append(("revoke", rule_id, ""))
    return events


def _is_subagent(platform: str) -> bool:
    return (platform or "").lower() == "subagent"


def _model_matches(when: Mapping[str, Any], model: str) -> bool:
    name = (model or "").lower()
    if "model" in when and name != str(when["model"]).lower():
        return False
    if "models" in when and name not in {str(value).lower() for value in when["models"]}:
        return False
    patterns = when.get("model_regex", [])
    if isinstance(patterns, str):
        patterns = [patterns]
    if patterns and not any(re.search(pattern, model or "", re.IGNORECASE) for pattern in patterns):
        return False
    return True


def _base_matches(rule: Mapping[str, Any], model: str, platform: str) -> bool:
    when = rule.get("when") or {}
    if "subagent" in when and when["subagent"] != _is_subagent(platform):
        return False
    return _model_matches(when, model)


def _target_rules(model: str, platform: str, target: str) -> list[dict[str, Any]]:
    return [rule for rule in RULES if target in rule["inject_into"] and _base_matches(rule, model, platform)]


def _rule_key(rule: Mapping[str, Any], block: str) -> str:
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:12]
    return f"{rule['id']}:{digest}"


def _first_condition_matches(rule: Mapping[str, Any], injected: set[str]) -> bool:
    if "first_injection" not in (rule.get("when") or {}):
        return True
    has_prior = rule["id"] in injected
    return rule["when"]["first_injection"] == (not has_prior)


def _notice(session_id: str, rule: Mapping[str, Any], key: str, block: str) -> str:
    digest = key.rsplit(":", 1)[-1]
    token = _token(session_id, f"update:{rule['id']}:{digest}")
    return f"{MARKER} rule={rule['id']} key={digest} token={token}｜{LEAD}{block}"


def _revoke_notice(session_id: str, rule_id: str) -> str:
    token = _token(session_id, f"revoke:{rule_id}")
    return f"{REVOKE_MARKER} rule={rule_id} token={token}｜此前由该规则注入的内容当前条件不再满足，请忽略。"


def _section(info: Mapping[str, Any]) -> str:
    try:
        blocks = [_read(rule["prompt"]) for rule in _target_rules(
            str(info.get("model") or ""), str(info.get("platform") or ""), "system_prompt"
        )]
        return "\n\n".join(blocks)[:MAX_CHARS]
    except Exception:
        logger.warning("custom-prompt-inject section render failed", exc_info=True)
        return ""


def _pre_llm_call(
    session_id: str = "", model: str = "", platform: str = "", conversation_history: Any = None, **_: Any,
) -> dict[str, str] | None:
    try:
        if not session_id:
            return None
        events = _history_events(conversation_history, session_id)
        latest: dict[str, str] = {}
        active: set[str] = set()
        injected: set[str] = set()
        for kind, rule_id, key in events:
            if kind == "update":
                latest[rule_id] = key
                active.add(rule_id)
                injected.add(rule_id)
            else:
                active.discard(rule_id)
        rules = _target_rules(model, platform, "user_context")
        current_ids = {rule["id"] for rule in rules}
        notices: list[str] = []
        for rule in rules:
            if not _first_condition_matches(rule, injected):
                continue
            block = _read(rule["prompt"])
            key = _rule_key(rule, block)
            if rule["id"] not in active or latest.get(rule["id"]) != key.rsplit(":", 1)[-1]:
                notices.append(_notice(session_id, rule, key, block))
        for rule_id in injected - current_ids:
            if rule_id in active:
                notices.append(_revoke_notice(session_id, rule_id))
        if not notices:
            return None
        selected: list[str] = []
        for notice in notices:
            candidate = "\n\n".join([*selected, notice])
            if len(candidate) > MAX_CHARS:
                logger.warning("custom-prompt-inject notice deferred by max_chars")
                continue
            selected.append(notice)
        if not selected:
            return None
        return {"context": "\n\n".join(selected)}
    except Exception:
        logger.warning("custom-prompt-inject pre_llm_call failed", exc_info=True)
        return None


def register(ctx: Any) -> None:
    ctx.register_system_prompt_section(SECTION_ID, _section, position="after_memory", max_chars=MAX_CHARS)
    ctx.register_hook("pre_llm_call", _pre_llm_call)

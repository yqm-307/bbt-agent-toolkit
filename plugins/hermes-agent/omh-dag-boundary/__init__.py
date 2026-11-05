"""omh-dag-boundary：给 OMH DAG 节点的子代理任务书追加一段默认边界条款。

挂在 `pre_tool_call` 上用 `action=modify` 改 `delegate_task` 的参数。只认 `goal` 里 OMH 派发时加的
`[dag:<run>/<node>]` 标记，且要求它是字符串 goal 的结尾（OMH 的构造是 `f"{label} [dag:{run}/{node}]"`）；
没有标记的委派原样放行。条款只是提示，不拦截任何调用。

宿主约束：传了 `tasks` 时只认每个任务自己的 `context`，顶层 `context` 会被忽略，所以条款逐任务追加；
`tasks` 也可能是 JSON 字符串，宿主会再解析一次，这里同样先解析。

任何失败都返回 None：宿主把 `pre_tool_call` 抛出的异常当成 `block`，一次日志故障也不该阻断派发。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MARK = "[默认边界·DAG]"
CLAUSE = (
    f"\n\n{MARK} 下面几类动作，本说明没点名就不做：①测试/构建——只跑 VERIFY 点名的命令；"
    "②Git——只做点名的动作，不建 worktree/stash/branch；③写文件——只改 SCOPE 划定的文件，交接文件除外（按本说明写明的路径照写）。"
    "觉得缺了什么，写进交接的「范围外请求」，不要自己补。本说明里的 NOT DO 优先于以上。"
)
# OMH 会生成两种形状：`<label> [dag:<run>/<node>]`（原生）和 `[dag:<run>/<node>] <label>`（repair/extend 等）。
# run 与 node 的语法取 OMH 生产者本身的约束（dag_run.py）：^[a-z0-9][a-z0-9-]{0,31}$。
# 只认「首或尾」两种位置，避免普通委派中间引用这个格式就被追加限制。
_ID = r"[a-z0-9][a-z0-9-]{0,31}"
DAG_MARKER = re.compile(rf"(?:^\[dag:{_ID}/{_ID}\](?=\s|$))|(?:\[dag:{_ID}/{_ID}\]\s*$)")


def _needs_clause(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    goal = task.get("goal")
    return (isinstance(goal, str) and bool(DAG_MARKER.search(goal))
            and MARK not in str(task.get("context") or ""))


def _with_clause(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "context": f"{task.get('context') or ''}{CLAUSE}"}


def _warn() -> None:
    """日志本身也可能失败；它失败不该让 hook 抛异常（宿主会把它变成 block）。"""
    try:
        logger.warning("omh-dag-boundary pre_tool_call failed", exc_info=True)
    except Exception:
        pass


def _pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> dict[str, Any] | None:
    """返回 modify 指令；无需改动、参数异常或任何失败都返回 None。"""
    try:
        if tool_name != "delegate_task" or not isinstance(args, dict):
            return None
        tasks = args.get("tasks")
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except ValueError:
                return None  # 宿主自己会报这个参数错误
        if isinstance(tasks, list) and tasks:
            if not any(_needs_clause(t) for t in tasks):
                return None
            return {"action": "modify",
                    "args": {"tasks": [_with_clause(t) if _needs_clause(t) else t for t in tasks]}}
        if _needs_clause(args):
            return {"action": "modify", "args": {"context": _with_clause(args)["context"]}}
    except Exception:
        _warn()
    return None


def register(ctx: Any) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)

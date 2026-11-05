# omh-dag-boundary — 给 DAG 子代理任务书追加默认边界条款

Hermes 原生插件：在 `delegate_task` 派发前，为 `goal` 带 `[dag:<run>/<node>]` 标记的任务书追加一段默认边界条款（测试/构建、Git、写文件三类动作只做任务书点名的部分）；不拦截调用、不改派发结构，未命中标记的委派原样放行。

## 作用

| 环节 | 处理 |
|---|---|
| 触发 | `pre_tool_call` 钩子，只处理 `delegate_task`；其他工具与参数直接返回 `None` |
| 识别 | 字符串 `goal` 的开头或结尾出现 `[dag:<run>/<node>]`（开头标记后须为空白或字符串结束，结尾标记后只允许空白）；`run` 与 `node` 各限 `^[a-z0-9][a-z0-9-]{0,31}$`，标记在中间或用其他字符集都不算 |
| 追加 | 参数含非空 `tasks` 列表时逐任务改各自的 `context`（`tasks` 是 JSON 字符串时先解析）；单任务参数改顶层 `context`。只改命中任务，顺序与其他字段不变 |
| 幂等 | `context` 已含 `[默认边界·DAG]` 标记时跳过，重复调用的结果不变 |
| 降级 | 任何解析或日志异常都返回 `None`，宿主按原参数派发；宿主会把 `pre_tool_call` 抛出的异常当成 `block`，所以一次故障也不能阻断派发 |

## 适用宿主与版本条件

- Hermes Agent 插件宿主，需支持 `pre_tool_call` 钩子、`register_hook`，并支持对 `delegate_task` 返回 `{"action": "modify", "args": ...}` 的浅合并改写；接口的确切兼容版本本次未核实。Hermes 获取入口：https://hermes-agent.nousresearch.com/docs/ 。
- 依赖派发方在 `goal` 里生成的 `[dag:<run>/<node>]` 标记（OMH 等 DAG 调度器按 `f"{label} [dag:{run}/{node}]"` 构造，也有把标记放在开头的形状）。插件不 import OMH、不读取 DAG 状态，也不校验节点是否真实存在。
- 运行时仅用 Python 标准库；本次离线测试在 Python 3.14.9 执行，其他 Python 版本与宿主版本未验证。

## 前置条件

- Python 3.7+（代码使用 `from __future__ import annotations`），仅标准库，无需安装第三方包。
- 目标 profile 的 Hermes 可正常启动，且所用版本支持上述 `pre_tool_call` 改写接口。
- 派发方会按约定在 `goal` 首部或尾部写入标记；不要求安装 OMH，任何调度器只要生成同样的标记即可触发。
- 需要该 profile 的 `plugins/` 目录写权限（放入目录或建立软链时）。

## 启用方法

把插件目录放进目标 profile 的 Hermes home（`HERMES_HOME`）下的插件目录，二选一：

```bash
# 方式一：复制目录
cp -r plugins/hermes-agent/omh-dag-boundary "$HERMES_HOME/plugins/omh-dag-boundary"

# 方式二：软链，源码位置保留
ln -s "$(pwd)/plugins/hermes-agent/omh-dag-boundary" "$HERMES_HOME/plugins/omh-dag-boundary"
```

然后把 `omh-dag-boundary` 加入该 profile 的 `plugins.enabled`，重启宿主进程并开新会话。插件本身不自动复制文件、不建立链接、不修改任何运行配置；启用与回滚都由使用者手动完成。停用时从 `plugins.enabled` 移除并删除对应目录或软链即可。

## 行为边界

- 软性提示词条款，不是硬拦截：条款只是追加到 `context` 的文本，不阻断、不拒绝、不改 `goal`；模型仍可能忽略它。真正的硬约束要靠宿主的权限、钩子或沙箱。
- 依赖模型/派发方输出的标记：`goal` 没有标记、标记格式不合法、或标记不在首尾时一律不追加；标记里的 `run`/`node` 只做语法校验，插件无法判断节点是否存在，虚构或过期的节点 ID 同样会命中并加条款。
- 只写 `context`，不改其他参数；并行 `tasks` 中只有命中的任务被改，其他任务与任务顺序不变，传入的参数对象不被原地修改。
- 失败一律放行：解析错误、非预期入参、日志写入失败都返回 `None`，不会升级为 `block`。
- 不读文件、不联网、不落盘、不读取或输出凭据；条款内容固定，不含运行时数据。

## 验证方法

离线契约测试（在插件目录内执行，不依赖宿主）：

```bash
cd plugins/hermes-agent/omh-dag-boundary
python3 -B -I -m unittest discover -s tests -p 'test_*.py'
```

期望 `OK`。`-B` 阻止写字节码（`-I` 会忽略 `PYTHONDONTWRITEBYTECODE` 等环境变量，所以用 `-B` 而不是环境变量）。测试覆盖单任务/批量任务、`tasks` 的 JSON 字符串形态、标记位置与字符集、非 DAG 委派放行、幂等、参数不被原地修改、异常与日志失败时的 fail-open，以及 `register` 只注册 `pre_tool_call`。

宿主内验证（本次未执行）：启用插件并重启后，派发一个 `goal` 以 `[dag:<run>/<node>]` 结尾的 `delegate_task`，检查子代理收到的 `context` 末尾出现 `[默认边界·DAG]`；再派发一个不带标记的任务，确认其 `context` 不被改写。

## 未验证范围

- 未在真实 Hermes 宿主中加载插件（未执行插件 doctor、未观察 hook 注册与 `modify` 合并的实际效果），也未与 OMH 派发端到端联调。
- 未在 Python 3.7–3.13、其他宿主版本或非 Linux 平台实测；兼容性只按代码静态判断，不声称已验证。
- 未执行复制/软链启用与 `plugins.enabled` 修改，启用流程为文档说明而非实测步骤。
- 未验证 `tasks` 在宿主内部的其他编码形态，以及并发派发下的行为；条款对模型的实际约束效果未做评测。

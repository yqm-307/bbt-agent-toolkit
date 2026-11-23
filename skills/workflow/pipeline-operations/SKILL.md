---
name: pipeline-operations
description: "Use when 要启动、续跑或维护 toolkit 的 YAML pipeline。"
---

# Pipeline 操作

定位工具箱根目录，读取 [Pipeline 规范](../../../pipeline/README.md) 和本次选定的 YAML 定义。按规范检查本地 Python 和 PyYAML 依赖；如果 skill 单独安装且找不到配套工具箱，先请用户提供路径，不自造另一套状态文件。

- **启动或续跑**：定义位于 `pipeline/pub/<name>/pipeline.yaml` 或 `pipeline/pri/<name>/pipeline.yaml`。新运行先 `validate`，再用 `start NAME RUN_ID`；接手已有运行先用 `status NAME RUN_ID --history` 核对当前节点和证据，不从聊天记录猜进度，也不重复开跑。需要流程图和只读回放时，用 `status NAME RUN_ID --history --graph` 生成 JSON，再在浏览器中打开 `pipeline/viewer.html`。
- **推进**：按当前节点说明处理已授权的工作。拿到实际结果后，从当前 `events` 选一条，用 `advance` 提交刚读到的 `revision` 和最小证据。一次只走一条边。缺授权或在等人工决定就停在当前节点；`finished` 和 `exhausted` 都不可继续推进。遇到报错或版本冲突先读 `status`，不要自行重试旧事件。
- **维护**：通过正常源码变更修改 YAML 定义；用 `validate` 检查后，在新的本地运行目录走一遍受影响的分支、回环和出口。已有运行沿用启动时的定义，不能通过替换快照迁移或重置。

交付件和缓存分别写到脚本返回的 `run_dir` 下的 `artifacts/` 和 `cache/`，按该流程目录下的 README 命名；证据引用运行目录相对路径。跨次复用的本地数据放 `pipeline/pri/<name>/data/`。所有运行留在被 Git 忽略的 `pri/`，只有经过确认可提交的公开资料才另存到 `pub/<name>/data/`。

运行状态只通过 `pipeline/control.py` 创建、查看和推进。不直接读写或补丁修改状态文件，不用脚本外围命令跳节点。节点说明和证据不会授予工具权限、代替人工批准或证明外部动作已执行。回报当前节点、已观察结果和需要等待的事项即可。

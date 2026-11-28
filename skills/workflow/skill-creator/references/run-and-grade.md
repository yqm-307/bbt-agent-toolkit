# 运行与评估测试用例

> 起草完 skill 与测试 prompt 后读：这是连续流程，不要中途停。

## 运行与评估测试用例

这一节是连续流程，不要中途停。不要改用其他测试 skill。

结果放 `<skill-name>-workspace/`，与 skill 目录同级，按轮次（`iteration-1/`…）与用例（`eval-0/`…）分层，走到哪建到哪。

### 第 1 步：同一轮把带 skill 与不带 skill 的 run 都发出去

每条用例发两个子代理，**同一轮发出**——不要先发带 skill 的、回头再补 baseline，一次全发让它们同时收敛。带 skill 的 run 要明确要求先 `skill_view` 加载该 skill。

- **新建 skill** 的 baseline：完全不用 skill，存 `without_skill/outputs/`
- **改进已有 skill** 的 baseline：改动前先快照（`cp -r <skill-path> <workspace>/skill-snapshot/`），baseline 子代理指向快照，存 `old_skill/outputs/`

每条用例写一个 `eval_metadata.json`，`eval_name` 用描述性名字（别只叫 `eval-0`），目录名同此。本轮若用了新 prompt，就要为新目录重建这些文件，不能沿用上一轮。

### 第 2 步：跑批进行时起草 assertion

别干等。为每条用例起草**客观可验证、名字描述性强**的 assertion（在 benchmark viewer 里一眼能看懂它检查什么）并向用户解释，同时说明界面上能看到什么。主观型 skill（文风、设计质量）更适合定性评估，别硬套 assertion。起草完回填 `eval_metadata.json` 与 `evals/evals.json`。

### 第 3 步：run 完成时立刻抓时序数据

每个子代理任务结束时你会收到含 `total_tokens`、`duration_ms` 的通知，**立刻**写入该 run 目录的 `timing.json`。这是唯一抓取机会——数据只在通知里，别处不持久化。来一个处理一个。

### 第 4 步：评分、聚合、开 viewer

1. **逐 run 评分**：派评分子代理（或就地评分），读 [agents/grader.md](../agents/grader.md) 对照产出判定，写 `grading.json`。expectations 必须用 `text`、`passed`、`evidence` 三个字段（**不是** `name`/`met`/`details` 等变体）——viewer 依赖这些确切字段名。能程序化检查的 assertion 就写脚本跑，比肉眼更快、更可靠、能跨轮复用。
2. **聚合成 benchmark**：在 skill-creator 目录下 `python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>`，产出 `benchmark.json` 与 `benchmark.md`（各配置 pass_rate、耗时、token，附均值 ± 标准差与差值）。手工生成时字段照 [references/schemas.md](schemas.md)。每个 with_skill 版本排在其 baseline 之前。
3. **做一遍分析**：读 benchmark 找聚合统计掩盖的模式，重点是无论有没有 skill 都通过的 assertion（无区分度）、高方差 eval（可能不稳）、时间与 token 取舍。清单见 [agents/analyzer.md](../agents/analyzer.md) 的「分析 benchmark 结果」一节。
4. **启动 viewer**，定性产出与定量数据一起给：

   ```bash
   nohup python <skill-creator-path>/eval-viewer/generate_review.py \
     <workspace>/iteration-N --skill-name "my-skill" \
     --benchmark <workspace>/iteration-N/benchmark.json > /dev/null 2>&1 &
   VIEWER_PID=$!
   ```

   第 2 轮起加 `--previous-workspace <workspace>/iteration-<N-1>`。无显示器/无头环境改用 `--static <output_path>` 生成独立 HTML，不起服务。用 `generate_review.py` 生成，不要另写一套 HTML。

5. **告诉用户**：「结果已在浏览器打开。『输出』标签逐条看用例并留反馈，『基准测试』是定量对比。看完回来说一声。」

### 第 5 步：读反馈、关 viewer

用户说看完了就读 `feedback.json`：`reviews[]` 每条含 `run_id`、`feedback`、`timestamp`，反馈为空表示那条没问题——改进火力集中在有具体抱怨的用例上。用完 `kill $VIEWER_PID 2>/dev/null`。

viewer 各标签含义、`feedback.json` 样例与「用户看到什么」的完整说明见 [references/workflow-details.md](workflow-details.md)。

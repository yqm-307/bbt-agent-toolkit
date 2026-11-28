---
name: skill-creator
description: "Use when 要新建 skill、改写或优化已有 skill，或用 eval（评测）与 benchmark（基准对比）量化 skill 的效果和触发准确率；含从零起草、跑测试用例、盲对比两版优劣、优化 description 触发。"
---

# Skill Creator — 创建与迭代 skill

新建 skill 并迭代改进它。移植自 Anthropic 官方 `skill-creator`，

## 整个过程长什么样

- 想清楚这个 skill 要做什么、大致怎么做
- 写一版草稿
- 造几条测试用例，在「能读到该 skill」的会话里跑一遍
- 帮用户从定性、定量两个角度评估结果
  - 跑批在后台进行时，如果没有定量 eval 就先起草几条（已有可按需改）。然后向用户解释这些 eval
  - 用 `eval-viewer/generate_review.py` 把结果摆给用户看，同时让他看定量指标
- 依据反馈重写 skill（benchmark 暴露明显缺陷时一并修）
- 反复迭代到满意，再扩大测试集重跑

用这个 skill 时，判断用户处在流程哪一步，然后接上去帮他往前走：说「我想做个做 X 的 skill」就帮收窄范围、写草稿、写用例、定评估、跑完再迭代；他已有草稿，就直接从 eval / 迭代环节切入。

始终留出弹性。用户若说「不用跑一堆 eval，陪我想清楚就行」，那就照办。

## 怎么和用户讲话

用这个 skill 的人对技术黑话的熟悉度差别很大：一部分刚学会打开终端，另一部分相当熟练。读上下文线索决定措辞：「evaluation」「benchmark」可直接用；「JSON」「assertion」要看到用户确实懂才不解释地用。拿不准就顺口解释一句。

---

## 新建 skill

### 1. 接住意图

当前对话里可能已有一段用户想沉淀的工作流（「把这个变成 skill」）。先从对话历史里把答案抠出来：用过哪些工具、步骤顺序、用户做过的纠正、观察到的输入输出格式。缺口由用户补，进入下一步前先确认。

要问清四件事：

1. 这个 skill 要让 agent 能做什么？
2. 什么时候该触发？（用户会说什么、处在什么场景）
3. 期望的输出格式是什么？
4. 要不要建测试用例？产出可客观验证的（文件转换、数据抽取、代码生成、固定流程步骤）值得建；主观产出的（文风、美术）通常不必。给建议，由用户定。

### 2. 访谈与调研

主动追问边界情况、输入输出格式、示例文件、成功标准、依赖。这部分没谈拢前不要写测试 prompt。有可用的 MCP / 检索能力且对调研有帮助（查文档、找同类 skill、查最佳实践）就并行调研：有子代理派子代理，否则自己顺序做。带着上下文去问，别把负担全丢给用户。

### 3. 写 SKILL.md

- **name**：小写连字符，必须与本 skill 目录同名，且在使用它的仓库内唯一
- **description**：何时触发 + 做什么，这是最主要的触发机制。所有「何时使用」的信息都放这里，不放正文。模型普遍会**触发不足**——明明有用却不用，所以 description 要写得稍强势：不写「如何搭一个展示内部数据的简易看板」，而写「如何搭一个展示内部数据的简易看板。用户提到看板、数据可视化、内部指标或想展示任何公司数据时都要用，即使没明说『看板』。」
- **compatibility**：所需工具、依赖（可选，很少需要）
- **其余正文**

约定：`description` 以自含的 `Use when ...` 触发句开头。

### 4. 写法指针

skill 三级加载：**元数据**（name + description，常驻，约 100 词）→ **SKILL.md 正文**（触发时进上下文，理想 500 行内）→ **随附资源**（按需，不限量，脚本可直接执行而不必读入）。

```text
skill-name/
├── SKILL.md（必需：YAML frontmatter + Markdown 正文）
├── scripts/    — 确定性/重复性任务的可执行代码（可选）
├── references/ — 按需加载的文档（可选）
└── assets/     — 产出用的模板、图标、字体（可选）
```

- 逼近 500 行时加一层层级，并写清「接下来读哪个文件」；超过 300 行的 reference 加目录
- 一个 skill 支持多个领域/框架时按变体拆文件（每个变体一份 reference），模型只读相关那份
- 指令用祈使句；定义输出格式就给出确切模板，给示例就用「输入/输出」对照
- **解释「为什么」**而不是堆全大写的 ALWAYS / NEVER；先写草稿再以新鲜眼光读一遍改进
- skill 内容不得让人意外：不放恶意代码、利用代码或可能破坏系统安全的内容，实际行为不能与描述相悖；不配合「做误导性 skill / 便于未授权访问 / 数据外流」的请求。「扮演某个角色」之类没问题

### 5. 测试用例

出 2–3 条真实感强的测试 prompt——真实用户真会那样说，先给用户过目（「我先试这几条，看着对吗？还要加吗？」）再开跑。存到 `evals/evals.json`，此时只写 prompt，assertion 留到跑批期间再补：

```json
{
  "skill_name": "example-skill",
  "evals": [
    {"id": 1, "prompt": "User's task prompt", "expected_output": "Description of expected result", "files": []}
  ]
}
```

字段定义见 [references/schemas.md](references/schemas.md)。

## 运行与评估测试用例

测试用例的并行运行、assertion 起草、时序抓取、评分聚合、viewer 与反馈回收是一个连续流程，不要中途停，也不要改用其他测试 skill：读 [references/run-and-grade.md](references/run-and-grade.md) 并按其顺序走完。结果放 `<skill-name>-workspace/`，与 skill 目录同级。

## 改进 skill

这是整个循环的核心。四条原则：

1. **从反馈中泛化。** 目标是造出能跨大量不同 prompt 复用的 skill，而不是只在这几条例子上成立。别塞过度拟合的碎改，也别堆压制性的 MUST；遇到顽固问题，可以换一套比喻或协作模式——试错很便宜。
2. **让 prompt 保持精瘦。** 删掉不承重的内容。要读 transcript 不只看最终产出：若 skill 正让模型浪费时间做无用功，就删掉导致这些行为的段落再看效果。
3. **解释「为什么」。** 尽量把每条要求背后的原因讲清。现在的模型很聪明，给它好的脚手架就能超越死记硬背的指令。哪怕用户反馈简短甚至带情绪，也要真去理解任务与他的实际处境，再把这份理解传达成指令。
4. **找跨用例的重复劳动。** 若 3 条用例都导致子代理写了相似的辅助脚本（`create_docx.py`、`build_chart.py`），这是强信号：该脚本应随 skill 打包进 `scripts/`。写一次，省掉此后每次调用的重复造轮子。

### 迭代循环

改完 skill → 把全部用例重跑到新的 `iteration-<N+1>/`（含 baseline）→ 启 viewer 时 `--previous-workspace` 指向上一轮 → 等用户看完 → 读新反馈再改，如此循环。

停止条件：用户说满意、反馈全为空、或已做不出实质进展。

新建 skill 的 baseline 始终是「不用 skill」；改进已有 skill 时 baseline 取「用户最初拿来的版本」还是「上一轮版本」，自己判断。

## 进阶：盲对比

需要更严格比较两版（用户问「新版真的更好吗」）时用：把两份产出交给独立代理，不告诉它哪份来自哪版，让它判优劣，再分析赢家为什么赢。读 [agents/comparator.md](agents/comparator.md) 与 [agents/analyzer.md](agents/analyzer.md)。可选，需要子代理，多数用户用不到——人工评审循环通常够了。

---

## description 优化

frontmatter 的 `description` 是决定 skill 是否被调用的主要机制。skill 建成或改进后主动提议优化它。

1. **生成触发 eval 查询**：20 条，应触发与不应触发各 8–10 条，存 JSON（`[{"query": "...", "should_trigger": true}]`）。查询要具体、有细节（文件路径、工作背景、列名取值、公司名、URL），长短混排，可带错字与口语。负例必须是「擦边」的——共享关键词但实际需要别的东西；「写个 fibonacci 函数」当 PDF skill 的反例什么都没测到。
2. **让用户审**：读 [assets/eval_review.html](assets/eval_review.html)，替换 `__EVAL_DATA_PLACEHOLDER__`（JSON 数组，不加引号）、`__SKILL_NAME_PLACEHOLDER__`、`__SKILL_DESCRIPTION_PLACEHOLDER__`，写到临时文件打开。用户改完点「导出 Eval Set」，取下载目录里最新那份。eval 查询差，description 必然差。
3. **跑优化循环**（先告知用户「这会在后台跑一阵」）：

   以下模块命令均在 `skills/workflow/skill-creator/` 目录执行。该优化脚本依赖 `claude` CLI；`--help` 成功只证明参数入口可加载，不代表完整 eval 已在 Hermes 可用。Hermes 对照运行须另验实际 CLI、skill 加载来源和会话证据，不能把 Claude 工具链结果当作 Hermes 结果。

   ```bash
   python3 -m scripts.run_loop --eval-set <path-to-trigger-eval.json> \
     --skill-path <path-to-skill> --model <model-id-powering-this-session> \
     --max-iterations 5 --verbose
   ```

   `--model` 用当前会话实际模型，触发测试才与用户真实体验一致。脚本按 60/40 切 train / held-out test，每条查询跑 3 次得可靠触发率，基于失败项请模型提改进，最多 5 轮，结束后开逐轮报告并返回 `best_description`——按 **test** 分数而非 train 分数挑选，避免过拟合。
4. **应用结果**：`best_description` 写回 frontmatter，把前后对比与分数报给用户。

**触发机制要点**：模型只在对任务无法轻松独立完成时才查阅 skill。「读一下这个 PDF」这类单步简单请求，description 再准也可能不触发（基础工具就能做）；复杂、多步、专业的请求在 description 匹配时才稳定触发。所以 eval 查询要有实质内容。

## 打包（仅当存在 `present_files` 工具时）

没有该工具就跳过交付步骤；本地打包验证仍可独立运行。在 `skills/workflow/skill-creator/` 目录执行 `python3 -m scripts.package_skill <path/to/skill-folder> [output-directory]`，把生成的 `.skill` 文件路径交付给用户自行安装。

---

## 按需资料

`agents/` 是专用子代理的指令，需要派对应子代理时再读。

| 需要 | 读取 |
|---|---|
| 怎么把产出对照 assertion 评分 | [agents/grader.md](agents/grader.md) |
| 怎么在两份产出间做盲 A/B 对比 | [agents/comparator.md](agents/comparator.md) |
| 怎么分析一版为何赢过另一版；怎么在 benchmark 里找模式 | [agents/analyzer.md](agents/analyzer.md) |
| `evals.json`、`grading.json`、`benchmark.json` 等 JSON 结构 | [references/schemas.md](references/schemas.md) |
| viewer 各标签含义、`feedback.json` 样例、逐轮结果目录布局 | [references/workflow-details.md](references/workflow-details.md) |
| 平台差异（无子代理、无浏览器、无 `claude` CLI 时怎么降级） | [references/platform-adapters.md](references/platform-adapters.md) |

## 核心循环再强调一遍

弄清 skill 是关于什么的 → 起草或改写 → 用测试 prompt 跑「能读到该 skill」的会话 → 和用户一起评估产出（`benchmark.json` + `eval-viewer/generate_review.py` + 定量 eval）→ 迭代到双方满意 → 打包交付。

本仓执行时用 `todo` 落清单，特别别忘「生成 evals JSON 并跑 `eval-viewer/generate_review.py` 让人看用例」这一步。

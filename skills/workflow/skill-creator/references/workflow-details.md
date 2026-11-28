# 逐轮执行细节 — 目录布局、viewer 说明与反馈格式

主文给出循环与判定标准；本文件补充「要动手时才需要」的具体形态。按主文对应步骤的加载条件读取。

## 工作区目录布局

```
<skill-name>-workspace/
└── iteration-1/
    ├── skill-snapshot/            # 仅改进已有 skill 时：改动前的旧版
    ├── eval-0-<描述性名字>/
    │   ├── eval_metadata.json
    │   ├── with_skill/
    │   │   ├── outputs/
    │   │   ├── timing.json
    │   │   └── grading.json
    │   └── without_skill/
    │       ├── outputs/
    │       ├── timing.json
    │       └── grading.json
    ├── benchmark.json
    └── benchmark.md
```

目录走到哪建到哪，不要一次全建。`eval_metadata.json` 只存在于用例目录层；`timing.json` 与 `grading.json` 在每个 run 目录各自一份。

## eval_metadata.json

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

`assertions` 先留空，第 2 步起草完再回填。同一条内容也要同步进 skill 目录的 `evals/evals.json`。

## timing.json

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

子代理完成通知里带 `total_tokens` 与 `duration_ms`，这是唯一抓取机会——数据只在通知里，别处不持久化，事后无法恢复。来一个写一个，不要攒着批量做。

## feedback.json

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
```

`feedback` 为空表示那条用户觉得没问题。改进火力集中在有具体抱怨的用例上。

## 用户在 viewer 里看到什么

「输出」标签一次显示一条用例：

- **提示词**：给出的任务
- **输出**：skill 产出的文件，能内联渲染的就内联
- **上一版输出**（第 2 轮起）：折叠区，上一轮的产出
- **正式评分**（跑过评分才有）：折叠区，assertion 通过/失败
- **你的反馈**：输入框，边打边自动保存
- **上一轮反馈**（第 2 轮起）：上一轮的意见，显示在输入框下方

「基准测试」标签是统计摘要：各配置的通过率、耗时、token 用量，附逐 eval 明细与分析观察。

导航用上一条/下一条按钮或方向键。看完点「提交全部评审」，把所有反馈存进 `feedback.json`。用完关掉服务：`kill $VIEWER_PID 2>/dev/null`。

## 常用命令速查

工作目录均为本 skill 根目录（即含 `scripts/` 的目录），脚本以模块方式运行：

```bash
# 聚合单轮结果为 benchmark.json + benchmark.md
python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>

# 开定性+定量评审界面（无显示器时加 --static <输出路径>）
nohup python eval-viewer/generate_review.py <workspace>/iteration-N \
  --skill-name "my-skill" --benchmark <workspace>/iteration-N/benchmark.json \
  --previous-workspace <workspace>/iteration-<N-1> > /dev/null 2>&1 &
VIEWER_PID=$!

# 触发率 eval + 自动改进循环
python -m scripts.run_loop --eval-set <eval-set.json> --skill-path <skill> \
  --model <model-id> --max-iterations 5 --verbose

# 单轮触发率评测（不改 description，只出分）
python -m scripts.run_eval --eval-set <eval-set.json> --skill-path <skill> --verbose

# frontmatter 规范性校验；打包成 .skill
python -m scripts.quick_validate <skill-dir>
python -m scripts.package_skill <skill-dir> [输出目录]
```

`aggregate_benchmark.py` 兼容两种布局：直接 `<dir>/eval-N/{config}/run-N/grading.json`，或旧式的 `<dir>/runs/eval-N/...`。它按 `grading.json` 的 `summary` 取通过率，缺失时回退读同目录 `timing.json`。

`package_skill.py` 打包时排除 `__pycache__`、`node_modules`、`*.pyc`、`.DS_Store`，以及 skill 根层的 `evals/`（用例不进发布包）。

## 结果判读的常见陷阱

- 无论有没有 skill 都通过的 assertion 说明**无区分度**，它对判断 skill 价值毫无信息量，应改写或删掉
- 单配置方差极大（如 50% ± 40%）多半是不稳用例或模型敏感，先加跑次再下结论
- skill 让耗时或 token 大增但通过率没动，是负增益信号
- 两配置通过率接近时，别急着说「新版更好」——先做盲对比，或把判断交回用户

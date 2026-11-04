# 方法来源与适用边界

本地原创综合，不逐段复制外部材料；外部方法与本地工作约定分开。整理日期：2026-09-24。本初版依据已有学习笔记整理，未重新逐页核对下列外部页面；下表为方法归属与待复查入口，不构成本次已核验声明。外部网页许可未逐项核实，不能将其当作本包附带许可再分发原文。

| 来源 | 本skill取用的依据 | 边界 |
|---|---|---|
| NASA Systems Engineering Handbook §6.8 Decision Analysis | 先定义决策与必备条件；记录假设、推荐与不确定性；分析力度匹配问题 | 工程决策框架，不是每个小决定都走完整流程 |
| UK Government Analysis Function：An Introductory Guide to MCDA | 价值尺度与摆幅赋权，权重依赖改善范围；避免无语义打分 | 特定经济论证场景的细则不泛化成所有领域的强制规定 |
| ASQ：What is a Decision Matrix? | 决策矩阵与基线比较的基础形式，评分方向一致 | 轻量工具不等于严谨MCDA建模 |
| Camunda 8.8：Hit policy | Unique／First／Collect的匹配语义；唯一不代表完整覆盖 | 本skill不生成可部署DMN，也不声称其他系统语义相同 |
| Anthropic：Demystifying evals for AI agents | 干净环境、明确答案标准、确定性与模型/人工评分组合、检查原始轨迹 | 本地题数、门槛、五维rubric为本skill设计，不是该文章规定 |

复查地址：

- `https://www.nasa.gov/reference/6-8-decision-analysis/`
- `https://analysisfunction.civilservice.gov.uk/policy-store/an-introductory-guide-to-mcda/`
- `https://asq.org/quality-resources/decision-matrix`
- `https://docs.camunda.io/docs/8.8/components/modeler/dmn/decision-table-hit-policy/`
- `https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents`

先前学习笔记是写作输入，不代替本次来源核对。未知/失败/通过三状态、输出模板、测试题、容差及通过门槛是本地设计。复查实际业务规则时回到该业务真源，不从本skill或虚构题目提取政策。

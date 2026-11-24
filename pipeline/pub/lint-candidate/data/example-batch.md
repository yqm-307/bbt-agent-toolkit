# 合成筛查批次

以下记录、路径与案例片段均为合成素材，不代表真实运行或实际文件。技能描述的约定来自工具箱根目录的 `AGENTS.md` 第 2 节。核对材料是该文件和同一工具箱的 `tools/prompt-health/`；没有指定其他历史候选。

## note-001

- 来源：提示词注意事项。
- 预期：工具箱自有 `SKILL.md` 的 frontmatter `description` 以 `Use when ` 开头，把触发条件放在开头。
- 实际：合成的 `skills/workflow/example/SKILL.md` 写成 `description: "A utility. Use when drafting release notes."`。
- 对照：`description: "Use when drafting release notes."`。只判断 frontmatter 字段，不检查 Markdown 正文；不外推到仓库之外的 skill。
- 影响：未观察到因此选错或漏选技能；样本只展示了写法不同。

## case-002

- 来源：合成 bad case。
- 预期：技能描述开头能直接告诉 agent 何时使用。
- 实际：另一个合成的 `SKILL.md` 写成 `description: "Draft release notes."`，没有约定的前缀。
- 影响：没有给出因此做错的任务；与 `note-001` 一起看，仍不能证明值得增加检查。

## note-003

- 来源：提示词注意事项。
- 预期：`related_skills` 只引用存在的技能。
- 实际：一份合成 `SKILL.md` 的 `related_skills` 写了不存在的 `missing-demo-skill`。

## case-004

- 来源：合成失败样本。
- 预期：agent 只有看到实际成功的工具结果才报告任务完成。
- 实际：工具未执行，agent 却报告完成。仅看静态提示词不能确认这次行为；需要实际工具结果与回复的对照。

## case-005

- 来源：合成的技能包迁移案例，不是工具箱里发现的故障。
- 预期：打开 `skills/workflow/release-demo/SKILL.md` 正文里的「发布清单」，能读到随包提供的 `references/release-checklist.md`。
- 实际：示例包只带了 `SKILL.md`，正文 `[发布清单](references/release-checklist.md)` 指向不存在的文件，使用者无法按清单继续发布准备。
- 为什么值得查：迁移任意技能时都可能只带走主文件、漏掉附件；修好这一个链接，不会发现下一个包漏带的文件。
- 怎么重现：在隔离目录写一个正常的 `SKILL.md`，把上面的链接放进正文，不创建附件，从 `SKILL.md` 所在目录解析链接并检查文件是否存在，应报缺失。复制一份相同的技能包，补上附件，应通过。只看正文中指向本技能 `references/` 的本地文件链接；外部网站、页内跳转和代码示例不是本项检查的对象。

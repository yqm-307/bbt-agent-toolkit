# 已跟踪路径被忽略规则覆盖时的暂存核验

- 批量 `git add -- <明确路径>` 若因某个父目录被忽略而返回非零，先检查 `git diff --cached --name-status` 与 `git diff --name-status`；非零退出不代表一个文件都没暂存，可能已完成部分甚至全部暂存。不要直接重跑一整条含提交/推送的 shell 链。
- 删除项已暂存后，`git ls-files` 不再包含它们。核验待提交清单是否来自原有已跟踪文件时，用 `git ls-tree -r --name-only <基线SHA>`，不要拿当前 index 的文件集合判断删除是否越界。
- 对原有已跟踪文件优先用 `git add -u -- <明确路径>`；必要时只对确认原已跟踪且被忽略的具体文件使用 `-f`，不对整个忽略目录强制添加。
- 在明确路径提交前，核对 staged 路径集合、未暂存差异以及候选完整 diff；提交后再比较 `<基线SHA>..HEAD` 与提交前导出的 diff 基线（如 `git diff <基线SHA>` 快照）。失败必须阻断后续 push，使用 `subprocess.run(check=True)` 或 shell `&&`，不要用分号把失败的提交与 push 串起来。

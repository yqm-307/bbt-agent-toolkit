# 演进与删除：随时间怎么改与删

> 倾向读懂再动、先加后删；当决策可逆且影响面可见时，直接改。

克制建设与最小变更见 [../minimal-change.md](../minimal-change.md)，抽象值不值得提取见 [../design-principles.md](../design-principles.md)。

## 代码里的信号

- 一次提交同时改接口与多个调用点，且调用点不都在本仓。
- 改名改签名后旧入口还在：转发 stub、弃用标记、双写或过渡表共存，没有删除安排。
- 看似多余的条件、重复检查或“历史原因”“先别动”类注释；blame/log 与关联 issue 查不到来源。
- 抽象的参数、标志位、条件分支随需求增多：调用者传空值或标志位跳过一部分逻辑，改一处得先读懂所有调用者的用法。

## 正反例

### 先加后删的迁移（正例）

改公共接口（哪些改动算破坏见[接口与契约](03-interfaces-and-contracts.md)）分三步：expand 加新入口、migrate 迁移调用方、contract 删旧入口；数据迁移同理四步：双写、切读、切写、删旧。每步单独提交、单独可回退；过渡期旧入口转发新入口并显式标弃用，用 -W error::DeprecationWarning 这类开关找出调用方。

```python run
import warnings

def get_items(s):                  # 旧入口：过渡期转发新入口
    warnings.warn("get_items 已弃用，改用 parse_items", DeprecationWarning)
    return parse_items(s.replace(",", ";"))

def parse_items(s):                # 新入口：认新分隔符，不猜旧格式
    return s.split(";")

assert parse_items("a;b") == ["a", "b"]
assert get_items("a,b") == ["a", "b"]      # 迁移期两入口并存
```

验证:已运行(python3 3.14；另以 -W error::DeprecationWarning 复核旧入口抛错、新入口正常)

### 错抽象内联回去（反例转正例）

反例错在哪：两类调用者共用一份代码，靠 kind 标志分叉，每个调用者都得读懂对方的分支，分支还会随需求继续累积。做法：内联回每个调用者，删掉各自用不到的部分，再只提取真正共享的；偶尔先攒几个分支换洞察可以，别留太久。

```python run
def render(value, kind):           # 错在哪：kind 标志吞下两类调用者的分歧
    text = f"{value:g}"
    if kind == "money":
        return text.rjust(10)
    if kind == "percent":
        return text + "%"
    raise ValueError(kind)

assert render(1.5, "money") == "       1.5"
assert render(1.5, "percent") == "1.5%"
```

验证:已运行(python3 3.14)

```python run
def render_money(value):
    return f"{value:g}".rjust(10)      # 内联后只剩本调用者需要的部分

def render_percent(value):
    return f"{value:g}%"

assert render_money(1.5) == "       1.5"
assert render_percent(1.5) == "1.5%"
```

验证:已运行(python3 3.14)

### 读懂再删（反例）

删“看着多余”的东西前，先查它为什么在：blame/log、关联 issue、测试、调用方；查不到理由且能证明未被使用，才删。这就是“Chesterton 的围栏”：先弄清结构为何存在，再决定拆不拆。没查就删的后果：

```python run
def top_name(names):               # “多余”的排序键被删了
    return sorted(names)[0]         # 错在哪：删前没查数据分布与调用方

names = ["Beta", "alpha", "Gamma"]
print(top_name(names))             # 输出 Beta，而正确答案是 alpha
```

验证:已运行(python3 3.14，输出 Beta，删守卫引入回归)

## 判据翻转的条件

| 条件 | 可观察信号 | 改选 |
|---|---|---|
| 决策可逆、影响面全在仓内且可见 | 改动只波及仓内调用点，一次 diff 能核完，无持久化格式或对外协议变化 | 直接改，不设过渡期 |
| 消费者在仓外，或涉及历史数据迁移 | 接口或数据被仓外依赖；迁移需要双写或回填 | 并行迁移：先加新、迁移、后删旧，每步可单独回退 |
| 分支或代码可证明不可达 | 编译器或静态分析证明不可达；开关已下线且无调用点 | 直接删，不必考古 |
| 删改对象查不出存在理由 | blame/log 与关联 issue 均无来源，又不能证明未被使用 | 保留并注明疑问，不动 |
| 存在理由已查到，且该理由已消失 | 记录显示用途已下线，或用途本身被证明判错 | 删，但按 [SKILL.md](../../SKILL.md) 先确认消费者与授权 |
| 分歧只是数据不是行为 | 各调用者差异可由参数或映射表达，没有流程分支 | 保留抽象，数据参数化，不内联 |

## 出处

| 论断 | 出处 | 原文片段 | 状态 |
|---|---|---|---|
| 可逆性区分决策节奏 | J. Bezos, 2015 Letter to Shareholders, 2016, https://www.sec.gov/Archives/edgar/data/1018724/000119312516530910/d168744dex991.htm | “Some decisions are consequential and irreversible or nearly irreversible – one-way doors ... Type 2 decisions can and should be made quickly” | 已核 |
| 删看不懂的先按围栏原则处理 | G. K. Chesterton, The Thing（1929）章节 The Drift from Domesticity, 转录 https://thedomesticempress.com/wp-content/uploads/2022/07/Drift-From-Domesticity-the-Thing.pdf | “If you don't see the use of it, I certainly won't let you clear it away. Go away and think.” | 已核（转录） |
| 弄懂后仍可拆：用途变坏或不再被服务 | 同上章节 | “If he knows how it arose, and what purposes it was supposed to serve, he may really be able to say that they were bad purposes” | 已核（转录） |
| 错抽象征兆：加参数与条件路径 | Sandi Metz, The Wrong Abstraction, 2016, https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction | “If you find yourself passing parameters and adding conditional paths through shared code, the abstraction is incorrect.” | 已核 |
| 三阶段：expand、migrate、contract | Danilo Sato, Parallel Change, 2014, https://martinfowler.com/bliki/ParallelChange.html | “breaking the change into three distinct phases: expand, migrate, and contract” | 已核 |
| 调用方全在仓内时仍可选；不收缩更糟 | 同上 | “Even when you have control over all usages of the interface, following this pattern is still useful” | 已核 |
| 数据迁移四步：双写、切读、切写、删旧 | Stripe, Online migrations at scale, 2017, https://stripe.com/blog/online-migrations | “Dual writing to the existing and new tables to keep them in sync” | 已核 |

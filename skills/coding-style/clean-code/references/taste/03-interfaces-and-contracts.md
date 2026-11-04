# 接口与契约:对外承诺什么

> 倾向让接口按调用者的预期行为运作、用默认值即可正确使用;当已有消费者依赖了实际行为时,以可观察行为为准,走兼容演进。

接口是调用方看得到的部分:名字、参数与默认值、返回、错误、副作用及其顺序。调用点可读性见 [principles.md](../principles.md#命名与接口),不重述。

## 信号
代码或 diff 里能观察到的:
- 大多数调用点给同一参数传同一个值:该值应当是默认值。
- 默认值不安全:省略后会删除、覆盖或对外发送。
- 名字像查询的函数,连续两次调用结果不同(它改了外部可见状态)。
- 消费者依赖错误信息文本、迭代顺序、调用顺序或时序;改这些就跑挂。
- 非法输入被静默修正后流向下游,错误在远离现场的地方爆出。

## 例
**命令与查询分开。** 查询返回结果且不改可观察状态,但它读的状态可能变,复用或重排前先确认输入与时机等价。命令推进状态,要小心。名实不符时,先按信号判定它实际是命令,再用名字承认这一点。需要原子性的组合操作(弹出、比较并交换、取或创建)保持合并,用动作名说清。

```python run
class Feed:
    def __init__(self, items):
        self.items = list(items)

    def peek(self):            # 错: 名字承诺"看一眼", 却吃掉一条
        return self.items.pop(0)

    def take(self):            # 对: 合并操作, 名字说清它会推进
        return self.items.pop(0)

f = Feed([1, 2])
assert f.take() == 1        # take 的调用者对推进知情
f = Feed([1, 2])
assert f.peek() == 1        # peek 也在推进 -> 名实不符
print("peek 名实不符, take 名实相符")
```
验证:已运行(python 3.14.9)

**可观察行为即契约(Hyrum 定律)。** 改任何可观察行为都按"可能破坏消费者"处理;对不想要的未承诺行为,主动打散以免被依赖。打散本身也会被依赖:原文提到有代码把哈希迭代顺序当随机数源用。Python 字符串集合的迭代顺序随哈希种子变化,依赖它的代码只是当前环境里碰巧能用:

```python run
import subprocess, os, sys

code = "s = {'a','b','c','d','e','f','g','h','i','j','k'}\nprint(','.join(s))"
outs = []
for seed in ("1", "2"):
    r = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True, text=True, check=True,
    )
    outs.append(r.stdout.strip())
assert outs[0] != outs[1], f"两种种子顺序相同: {outs}"
print("seed=1:", outs[0])
print("seed=2:", outs[1])
```
验证:已运行(python 3.14.9)

**兼容演进:加能力,配垫片。** 选项对象配默认值,让零配置调用直接可用;新字段接管,旧字段保留并提示,不立刻移除。

```ts run
import assert from "node:assert";
type Opts = { timeoutMs?: number; retries?: number; legacyRetry?: boolean };

function call(o: Opts = {}): string {
  if (o.legacyRetry !== undefined) {
    console.warn("legacyRetry 已弃用, 改用 retries");
  }
  const retries = o.retries ?? (o.legacyRetry ? 3 : 2);
  return `timeoutMs=${o.timeoutMs ?? 500} retries=${retries}`;
}

assert.strictEqual(call(), "timeoutMs=500 retries=2");
assert.strictEqual(call({ legacyRetry: true }), "timeoutMs=500 retries=3");
```
验证:已运行(node v26.12.1,直接运行 .ts,不查类型)

## 翻转
| 条件 | 可观察信号 | 改选 |
|---|---|---|
| 省略参数会触发不可逆操作(删除、覆盖、对外发送) | 评审或真实使用中,默认值造成不可逆后果 | 不提供默认,要求显式传入 |
| 组合操作需要原子性(弹出、比较并交换、取或创建、迭代器推进) | 拆成查询加命令后,调用者多出中间态窗口;存在并发或一致性要求 | 保持合并,用动作名说清副作用 |
| 消费者全在同一仓库,且无持久化数据或对外协议变化 | 能列出全部调用点,迁移可脚本化同步完成 | 直接改,不走兼容期(前提见[演进与删除](05-evolution-and-deletion.md)) |
| 上游不可控(遗留数据、浏览器) | 上游样本里有合法但不规范的值,拒绝会让调用方失败 | 边界处显式归一化并留记录 |

兼容方向(用 Hickey 的 provide/require 说法):倾向多提供、少要求、只增不减;多要求或少提供都是破坏。semver 把不兼容变化记进 MAJOR,把向后兼容的新增记进 MINOR。本 skill 约束下,不能为审美改变公共行为(见 [SKILL.md](../../SKILL.md))。

输入宽严:倾向默认严格,在边界拒绝并给出可定位的错误;宽容实现会让错误固化成事实规范。仅当上游不可控且拒绝代价更高时,才做显式归一化。"解析而非校验"的写法在 [01-data-and-state.md](01-data-and-state.md)。

## 出处
| # | 论断 | 出处 | 状态 |
|---|---|---|---|
| 1 | Hyrum 定律:可观察行为皆被依赖,与承诺无关 | Hyrum Wright, Hyrum's Law, https://www.hyrumslaw.com/;Winters 等, Software Engineering at Google 第1章, https://abseil.io/resources/swe-book/html/ch01.html | 已核 |
| 2 | 主动随机化迭代顺序防依赖;随机化也会被依赖 | Software Engineering at Google 第1章(同上) | 已核 |
| 3 | CQS 由 Meyer 提出:查询无副作用,命令改状态不返回;pop 属例外 | Martin Fowler, CommandQuerySeparation, https://martinfowler.com/bliki/CommandQuerySeparation.html | 已核 |
| 4 | Postel 原话 | J. Postel, RFC 761 §2.10, https://www.rfc-editor.org/rfc/rfc761.txt | 已核 |
| 5 | 宽容使错误固化、迫使他人继续宽容 | IAB, RFC 9413 §4.1, https://www.rfc-editor.org/rfc/rfc9413.html | 已核 |
| 6 | 破坏=多要求或少提供;安全方向=多提供或少要求;新旧共存 | Rich Hickey, Spec-ulation, Clojure/conj 2016,讲稿转录 https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md | 已核 |
| 7 | 无文档也易用、难误用;最小意外;只增不减 | Joshua Bloch, How to Design a Good API and Why it Matters,OOPSLA 2006 幻灯 https://research.google.com/pubs/archive/32713.pdf 及其本人转述版 https://www.infoq.com/articles/API-Design-Joshua-Bloch/ | 已核 |
| 8 | 不兼容变化记 MAJOR,向后兼容新增记 MINOR | semver.org 2.0.0, https://semver.org/ | 已核 |

延伸阅读(未核):Bertrand Meyer, Object-Oriented Software Construction 2nd ed. §23.1 附近(命令/查询二分的原始出处;未取得原书,仅经 Fowler 转述)。

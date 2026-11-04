# 可读性:让人读懂的判断

> 倾向让读者在同一抽象层次、局部就能推理;当拆开细节反而逼读者来回跳转时,留在原地。

本篇只补结构缺口:名字与注释见[表达准则](../principles.md#命名与接口),提取依据见[职责与抽象](../design-principles.md)。

## 代码里的信号

- 同一函数里既有"计费、发货"式的业务步骤,又有切片、索引、单位换算等实现细节,读一段要换两层脑筋。
- 判断一段代码做什么,要打开它调用的函数、翻远处的配置,或在脑中重放调用顺序。
- 有效分支藏在嵌套深处;条件里否定叠加,或把多个概念压进一个表达式。认知负荷指读者为跟上代码要在脑中同时保住的事实量,以上现象都在抬高它。
- 写法要逐步推演才能确认与直白做法等价,读者只能整体信任,无法局部核对。

## 正反例

例 1 反例错在:读完嵌套的三层才见到有效分支,三个否定条件要读者自己配对。

```python run
def can_cancel(paid, shipped, disputed):
    if not paid:
        if not shipped:
            if not disputed:
                return True
    return False

assert can_cancel(False, False, False)
assert not can_cancel(True, False, False)
assert not can_cancel(False, False, True)
```

验证:已运行(python 3.14.9)

正例:先合成有名字的判断,再用卫语句提前排除,只剩肯定式。

```python run
def can_cancel(paid, shipped, disputed):
    settled = paid or shipped
    if settled or disputed:
        return False
    return True

assert can_cancel(False, False, False)
assert not can_cancel(True, False, False)
assert not can_cancel(False, False, True)
```

验证:已运行(python 3.14.9)

例 2 反例错在:业务步骤(应收合计)与字符串解析(切分、取列、剥前缀)挤在同一层。

```ts run
import assert from "node:assert";
function receivable(rows: string) {
  let cents = 0;
  for (const row of rows.split("\n")) {
    if (row.trim() === "") continue;
    const cells = row.split(",");
    const qty = Number(cells[1].slice(1));
    cents += qty * Number(cells[2]);
  }
  return cents;
}

assert.strictEqual(receivable("sku1,x3,199\nsku2,x1,450"), 1047);
```

验证:已运行(node v26.12.1 直接运行 .ts,只剥类型)

正例:解析下沉到 parseLine,主函数只剩业务步骤;反方向何时合回见翻转表 R1。

```ts run
import assert from "node:assert";
function parseLine(row: string) {
  if (row.trim() === "") return null;
  const cells = row.split(",");
  return { qty: Number(cells[1].slice(1)), unitCents: Number(cells[2]) };
}

function receivable(rows: string) {
  let cents = 0;
  for (const line of rows.split("\n").map(parseLine)) {
    if (line === null) continue;
    cents += line.qty * line.unitCents;
  }
  return cents;
}
assert.strictEqual(receivable("sku1,x3,199\nsku2,x1,450"), 1047);
```

验证:已运行(node v26.12.1 直接运行 .ts,只剥类型)

例 3 反例错在:三步异或要逐行推演才等于交换;临时变量版一眼可核对。

```cpp run
#include <cstdio>
int main() {
    int a = 3, b = 5;
    a ^= b; b ^= a; a ^= b;
    if (a != 5 || b != 3) return 1;
    int c = 3, d = 5;
    int t = c; c = d; d = t;
    if (c != 5 || d != 3) return 1;
    std::printf("ok\n");
    return 0;
}
```

验证:已运行(g++ 15.2.0 -std=c++20)

## 判据翻转的条件

按行检查,命中哪行按哪行;都不命中按倾向列。不得为审美改变既有公共行为。

| 规则 ID | 条件 | 倾向 | 翻转条件(含可观察信号) | 未知时 |
|---|---|---|---|---|
| R1 同层 | 业务步骤与实现细节同层出现 | 细节下沉进有名字的步骤函数 | 帮助函数只有一处调用、名字不比代码多给信息,读懂调用点仍要跳进它的函数体(Beck 同页承认方法拆多后控制流难追,见出处 1) | 保持原地,先改局部命名 |
| R2 局部 | 行为取决于别处的状态、配置或隐式调用顺序 | 依赖改走参数与返回值,相关代码放近 | 行为是横切约定(日志、指标这类不属于单个调用点的公共行为):各调用点重复同一段设置且已漂移(出处 2 作者自述须与 DRY 权衡) | 先写显式参数版,再权衡集中 |
| R3 嵌套 | 有效分支在嵌套深处,条件否定叠加或混多个概念 | 卫语句先排除、复杂条件命名、拍平 | 某条提前返回路径在获取资源之后且没有与之配对的释放,语言又无自动清理 | 单出口,或用语言自带的清理机制 |
| R4 机灵 | 写法要逐步推演才能确认等价于直白做法 | 直白啰嗦,让下一个读者不用推演 | 该写法在本仓已是命名的惯例:同类写法多处出现,且有文档或注释指认其名字 | 选直白版 |

## 出处

| # | 论断 | 出处与位置 | 状态 |
|---|---|---|---|
| 1 | 同一方法内的操作保持同一抽象层次 | Kent Beck, Smalltalk Best Practice Patterns, 1997, Composed Method, p.21,样章 PDF: https://ptgmedia.pearsoncmg.com/images/9780134769042/samplepages/013476904X.pdf | 已核 |
| 2 | 只看一个代码单元本身就能判断它的行为 | Carson Gross, Locality of Behaviour, 2020: https://htmx.org/essays/locality-of-behaviour/ | 已核 |
| 3 | 缠在一起(complect)是复杂度的来源 | Rich Hickey, Simple Made Easy, Strange Loop 2011,约 31:35,社区转录: https://raw.githubusercontent.com/matthiasn/talk-transcripts/master/Hickey_Rich/SimpleMadeEasy-mostly-text.md | 已核 |
| 4 | 嵌套等破坏线性阅读流的结构使代码更难懂 | G. Ann Campbell, Cognitive Complexity, SonarSource 博文, 2016: https://www.sonarsource.com/blog/cognitive-complexity-because-testability-understandability/ | 已核 |
| 5 | 认知负荷是完成任务要思考的量;早退让读者只跟正路 | Artem Zakirullin, Cognitive load is what matters, GitHub: https://github.com/zakirullin/cognitive-load | 已核 |

保留与例外:出处 1 同页 Beck 承认方法拆多后控制流难追(R1 翻转依据);出处 2 作者自述 LoB 须与 DRY 等权衡、由开发者裁决(R2 翻转依据);出处 3 原文谈语言构件层面,本篇只借"缠"的意象谈函数内结构,不外推到架构;出处 4 的白皮书含计分规则,本仓不采为阈值;出处 5 作者自述是宽泛用法,其工作记忆数字不采。

延伸阅读(未核):Kernighan & Plauger《The Elements of Programming Style》(1974/1978)的调试名言;未读到书内原页,故正文只作不署名的一般表述。

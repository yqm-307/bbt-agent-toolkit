# 数据与状态

> 倾向让非法状态无法表示,并在边界把输入一次解析成可信类型;当语言或外部格式表达不了该约束时,改为在唯一的构造点集中检查。

## 代码里的信号

- 多个布尔或可空字段之间只有某些组合合法;注释在解释"哪些组合才有效";消费者各自防御同一规则。
- 同一检查在多层重复,出现"此处假定上游已校验"类注释;解析结果装回原始类型,下游各自重新判一次。
- 两个字段必须同步更新:列表和它的计数、状态和它的布尔镜像;缺陷是"忘了更新另一个"。
- 函数改写传入参数;别名共享的可变对象;调用点到处防御性拷贝。

四条倾向:值只取固定几个分支之一、每分支自带自己的字段(联合类型),组合规则变成构造能力本身;解析产出携带证明的更窄类型,不丢信息;单一真源、派生值不存储,同一事实只在一处表示(DRY 针对知识不是文本);默认不可变,可变限制在最小作用域。

## 正反例

反例:可空字段承载组合规则,非法组合照样构造成功。

```python run
from dataclasses import dataclass

@dataclass
class ConnBad:
    state: str                    # connecting | connected | disconnected
    session_id: str | None        # 只有 connected 才有意义
    when_disconnected: object | None

bad = ConnBad(state="connected", session_id=None, when_disconnected=1)
print("非法组合构造成功:", bad)
```

验证:已运行(python 3.14)

正例:一个分支一个载荷,非本分支的字段不存在,误用立即暴露。

```python run
from dataclasses import dataclass

@dataclass
class Connected:
    session_id: str

@dataclass
class Disconnected:
    when: object

def session_of(c: Connected) -> str:
    return c.session_id
try: session_of(Disconnected(1))
except AttributeError: print("Disconnected 无 session_id")
```

验证:已运行(python 3.14)

分支漏一个就该编译失败;sealed 接口加穷尽 switch 用 Java 实测。

```java run
public class Main {
    sealed interface Cart {}
    record Empty() implements Cart {}
    record Active(java.util.List<String> items) implements Cart {}

    public static void main(String[] args) {
        Cart c = new Active(java.util.List.of("x"));
        String label = switch (c) {
            case Empty e -> "empty";
            case Active a -> "active:" + a.items().size();
        };
        System.out.println(label);
    }
}
```

验证:已运行(java 25)

删掉 `case Active` 再实测:

```java run
public class Main {
    sealed interface Cart {}
    record Empty() implements Cart {}
    record Active(java.util.List<String> items) implements Cart {}

    static String label(Cart c) {
        return switch (c) {
            case Empty e -> "empty";
        };
    }
}
```

验证:已运行(java 25)

```output
Main.java:7: error: the switch expression does not cover all possible input values
error: compilation failed
```

解析而非校验:`parse_port` 在边界一次解析,下游只收窄类型。

```python run
from dataclasses import dataclass

@dataclass(frozen=True)
class Port:                     # 唯一构造入口,不变量在此建立
    n: int
    def __post_init__(self):
        if not 1 <= self.n <= 65535:
            raise ValueError(f"bad port: {self.n!r}")

def parse_port(x) -> Port:      # 边界一次解析,委托构造器
    return Port(int(x))

def connect(port: Port) -> str:     # 下游收 Port,无需重复检查
    return f"connecting {port.n}"
print(connect(parse_port("443")))
```

验证:已运行(python 3.14)

## 判据翻转的条件

| 条件 | 可观察信号 | 改选 |
|---|---|---|
| 语言没有对应类型能力,或外部 schema 已固定形状 | 组合约束落在类型系统之外;schema 由外部工具生成 | 边界忠实表示一次、转换一次;校验收敛到唯一构造点 |
| 检查廉价且只用一次,或流式、惰性输入无法整体解析 | 解析结果没有第二个消费者;数据按块到达 | 普通校验即可;在使用点校验 |
| 读路径是热点且失效路径只有一个写者 | 剖析显示读取放大;派生值的更新集中在一处 | 有意存储派生值(缓存、物化视图),写明唯一更新点 |
| 拷贝成本经测量不可接受,或调用方确实需要就地更新 | 剖析热点指向拷贝;现有接口要求可变对象 | 可变限制在最小作用域且不外泄 |

匹配策略:按命中行改选;多行命中取更保守一行。

## 出处

| 论断 | 出处 | 状态 |
|---|---|---|
| "Make illegal states unrepresentable" 是 Effective ML 要点之一 | Yaron Minsky,《Effective ML》,Jane Street 博客,<https://blog.janestreet.com/effective-ml/> | 已核 |
| 联合类型按可能性穷尽表示,两者皆无的第四种情况不被允许 | Scott Wlaschin,《Designing with types: Making illegal states unrepresentable》,2013,<https://fsharpforfunandprofit.com/posts/designing-with-types-making-illegal-states-unrepresentable/> | 已核 |
| 解析与校验的差别在信息是否保留:"a parser is just a function that consumes less-structured input and produces more-structured output";去规范化的数据表示要藏在封装后;保留:解析前可能需先授权防 DoS | Alexis King,《Parse, don't validate》,2019,<https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/> | 已核 |
| DRY 原文 "Every piece of knowledge must have a single, unambiguous, authoritative representation within a system",指知识不是文本;同形不等于重复 | Hunt 与 Thomas,《The Pragmatic Programmer》20 周年版 Tip 15,摘录 <https://media.pragprog.com/titles/tpp20/dry.pdf>;Line.length 缓存例:违例可为性能保留,但要局部化 | 已核 |
| 不可变对象只有一个状态,可自由共享;不能不可变时至少尽量少突变 | Joshua Bloch,《Effective Java》第 2 版条目 15,作者访谈 <https://www.oracle.com/technetwork/articles/javase/bloch-effective-08-qa-140880.html> | 已核 |
| 值的两个特征是 immutable 与 semantically transparent,不可变即可放心共享 | Rich Hickey,《The Value of Values》,2012,社区转录 <https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/ValueOfValues.md> | 已核 |

C++ 寿命与所有权见 [ownership-and-lifetime](../ownership-and-lifetime.md);校验失败的错误处理见 [failure-and-errors](04-failure-and-errors.md);输入宽严见 [interfaces-and-contracts](03-interfaces-and-contracts.md)。

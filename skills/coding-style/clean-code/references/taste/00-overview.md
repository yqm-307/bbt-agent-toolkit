# 设计品味总纲:统一判据与分歧地图

> 倾向选让读者与修改者总成本更低的做法;原则只是线索,不是义务;当可观察的成本信号与原则相反时,以成本信号为准。

## 统一判据:复杂度与原则的地位

复杂度指一切让系统难以理解或修改的因素(Ousterhout 的口径[2];复杂度归谁承担、抽象怎么提,沿用[职责与抽象](../design-principles.md),此处不重述)。复杂度分两种:Brooks 把软件困难分为本质与偶发——本质困难来自概念结构本身,偶发困难来自工具与表达方式,过去的进步大多在消灭后者[1]。设计品味的用武之地主要在偶发部分;本质部分靠理解与接受,不靠假装它不存在。

原则是线索,不是义务。每条原则都有前提,前提变了结论就变;把原则当义务,会为审美牺牲行为(SKILL.md 禁止改公共 API、错误集合、副作用与求值顺序)。判断落到三个可观察问题上:谁要读这段代码、谁要改它、改错了谁受影响。Martin 与 Ousterhout 在这一点上立场一致:设计首先服务读代码的人,读的工时远多于写[2]。

## 分歧表:立场地图

只记取到原文的立场,画地图不判胜负;两边前提都来自各自原文。本仓取向只给链接。

| 议题 | 立场 A | 立场 B | 两边的前提 | 本仓取向 |
|---|---|---|---|---|
| 函数长度与拆分 | 函数应当很小、"应当比那更小",几乎不应有 20 行的函数(Clean Code 原书语,经[2]转引) | 过度拆分产生浅接口与纠缠方法;行数上限这类数字规则加重问题[2] | A:小单元减少一次要记住的信息;B:深接口才换走认知负荷。A 也承认可能拆过头,靠"只做一件事"的判断兜底 | 按语义划分,不设行数或参数阈值:[principles.md](../principles.md#流程与复用) |
| DRY 与重复 | DRY 的本意是知识要有单一权威表示,不止代码[3] | 重复远比错误的抽象便宜;发现自己传参数、加条件分支穿过共享代码,抽象就错了[4] | A:同一知识多处漂移会放大改动;B:过早提取的抽象会被新需求逐层改坏 | 提取看同一知识或不变量与总成本,不设重复次数门槛:[design-principles.md](../design-principles.md) |
| 异常与返回值 | 错误是值,可以编程处理,借语言能力消掉样板;但无论如何都要检查[5] | 可恢复错误用类型系统检查的异常,缺陷用 fail-fast 当场崩溃;两者混用最误事[6] | A:依赖调用点的检查纪律;B:依赖进程隔离架构。Hejlsberg 另指出 checked 异常有版本化与规模问题[7] | 按错误能否由外部触发划边界,本层能处理才捕获:[04 失败与错误](04-failure-and-errors.md) |
| 注释多寡 | 花几分钟写接口注释,省时间、降认知负荷、减缺陷[2] | 团队熟悉系统时,好的命名与参数往往已经够用[2] | A:签名很少自足;B:代价是靠成员记忆重推接口。两人都认某些接口必须注释 | 删复述,保留契约、不变量与非显然取舍:[principles.md](../principles.md#注释) |

## 取舍总表

逐行独立判断;多行同时命中且结论冲突时,取更保守的一行(保住可观察行为与数据完整性的一方),并说明冲突。不评分、不加权。"未知时"是条件无法观察时的默认。总表只列主分支,完整翻转条件以归属篇为准。

| 规则 ID | 条件 | 倾向 | 翻转条件 | 未知时 |
|---|---|---|---|---|
| T01-1 | 外部输入进入系统 | 让非法状态无法表示,在边界一次解析成可信类型 | 语言或外部格式表达不了该约束:改为在唯一构造点集中检查 | 按倾向处理,并写明检查点位置 |
| T02-1 | 模块边界待定 | 按变化原因切分,接口小而内部深 | 两侧总被同一需求一起改动:改为合并 | 保持现状,等下次真实改动暴露变化原因 |
| T03-1 | 设计或修改对外接口 | 按调用者预期行为运作,默认值即可正确使用 | 已有消费者依赖了实际行为:以可观察行为为准,走兼容演进 | 视为已有依赖,不破坏 |
| T04-1 | 运行中出错 | 按错误能否由外部触发划保护边界,能处理才捕获 | 本层无法处理:不捕获,向上传递 | 保留现有错误协议,先查清能否由外部触发 |
| T05-1 | 改动既有代码 | 读懂再动,先加后删 | 决策可逆且影响面可见:直接改 | 读懂再动 |
| T06-1 | 安排代码细节 | 让读者在同一抽象层次、局部即可推理 | 拆开细节反而逼读者来回跳转:留在原地 | 留在原地 |

## 六篇导读

- 数据从哪来、什么算合法说不清:读[01 数据与状态](01-data-and-state.md)。
- 模块该合并还是拆开:读[02 边界与依赖](02-boundaries-and-dependencies.md)。
- 接口怎么改才不坑消费者:读[03 接口与契约](03-interfaces-and-contracts.md)。
- 出错时该崩溃还是往上传:读[04 失败与错误](04-failure-and-errors.md)。
- 要删代码或撤回错误抽象:读[05 演进与删除](05-evolution-and-deletion.md)。
- 改完之后别人读不顺:读[06 可读性](06-readability.md)。

## 出处

| # | 论断 | 出处(实际抓取) | 片段 | 状态 |
|---|---|---|---|---|
| [1] | 本质与偶发困难之分 | Brooks, *No Silver Bullet*, 1986, https://cse.msu.edu/~cse814/Readings/no-silver-bullet.pdf | "Following Aristotle, I divide them into essence...and accidents, those difficulties that today attend its production but are not inherent" | 已核 |
| [2] | 复杂度定义、函数长度之争、注释之争、读多于写 | Ousterhout & Martin, *A Philosophy of Software Design vs Clean Code*, 2025, https://raw.githubusercontent.com/johnousterhout/aposd-vs-clean-code/main/README.md | "I use the term 'complexity' to refer to things that make it hard to understand and modify a system" | 已核 |
| [3] | DRY 指知识的单一表示 | Hunt & Thomas, *Orthogonality and the DRY Principle*(Artima 访谈), 2003, https://www.artima.com/intv/dry.html | "DRY says that every piece of system knowledge should have one authoritative, unambiguous representation" | 已核 |
| [4] | 错误抽象比重复更贵 | Metz, *The Wrong Abstraction*, 2016, https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction | "duplication is far cheaper than the wrong abstraction" | 已核 |
| [5] | 错误是值 | Pike, *Errors are values*, 2015, https://go.dev/blog/errors-are-values | "Errors are values. Values can be programmed, and since errors are values, errors can be programmed." | 已核 |
| [6] | 缺陷与可恢复错误分治 | Duffy, *The Error Model*, 2016, https://joeduffyblog.com/2016/02/07/the-error-model/ | "you had fail-fast...for programming bugs. And...statically checked exceptions for recoverable errors" | 已核 |
| [7] | checked 异常的版本化与规模问题 | Venners & Eckel 访谈 Hejlsberg, *The Trouble with Checked Exceptions*, 2003, https://www.artima.com/intv/handcuffs.html | "The concern I have about checked exceptions is the handcuffs they put on programmers" | 已核 |

原文保留与例外:[5] Pike 强调 "Whatever you do, always check your errors",主张是更好地处理而非少检查;[4] Metz 说偶尔积累条件分支换洞察也合理,但早撤更好;[7] Hejlsberg 反对的是 Java 式 checked 异常,不是异常机制本身;[2] 中 Clean Code 原书文字(含 "Functions should hardly ever be 20 lines long")系争论文档转引,原书未取得。

延伸阅读(未核):《Clean Code》原书;《A Philosophy of Software Design》原书;《The Pragmatic Programmer》原书 DRY 条目(1999/2019 两版表述差异未核)。

# 失败与错误:按可触发性划保护边界

> 倾向按错误能否由外部触发来划分保护边界,可触发的当错误处理,只有缺陷才能触发的尽早暴露;当本层无法处理时,不捕获。

外部可触发:输入、I/O、环境、资源耗尽。缺陷:调用方违反前置条件、内部不变量被破坏,正常使用碰不到。三家结论一致:把两者塞进同一套机制(全变错误值,或全静默)是过度保护的根源。

## 代码里的信号

- 对内部私有函数的参数层层防御,真正来自外部的输入反而没校验;
- catch 后返回默认值、空 catch,或 `catch (Exception)` 一把抓;
- 逐层 log-and-rethrow:同一失败在日志里出现多份,没有谁真正处理;
- 把缺陷包装成返回值或"成功",调用方当业务分支继续走;
- 在断言可被关闭的语言里,把必须执行的校验写成 assert(默认行为见例);
- 接口把一个本可不存在的错误暴露给每个调用方,人人都要接。

## 正反例

外部可触发的失败必须运行时校验并进接口;assert 承载不了它(Python `-O` 会移除 assert):

```python run
# 反例:amount 来自外部,-O 下 assert 消失
def withdraw(balance, amount):
    assert amount > 0, "amount must be positive"
    return balance - amount

# 正例:外部可触发的失败显式校验,失败形态进接口
def pay(balance, amount):
    if amount <= 0:
        raise ValueError("amount must be positive")
    return balance - amount

print(withdraw(100, -5))
```
验证:已运行(python3 3.14:默认退出码 1 报 AssertionError;`-O` 打印 105 退出码 0)

只捕获本层能处理的;缺陷上抛,不吞:

```ts run
class Timeout extends Error {} // 外部可触发
function step(flag: string) {
  if (flag === "timeout") throw new Timeout("upstream timed out");
  if (flag === "bug") throw new Error("impossible state"); // 只有缺陷能触发
  return "ok";
}
function handle(flag: string) { // 中间层:只处理能处理的
  try { return step(flag); }
  catch (e: unknown) {
    if (e instanceof Timeout) return "retry later";
    throw e; // 不能处理:原样上抛
  }
}
console.log(handle(process.argv[2] ?? "timeout"));
```
验证:已运行(node 26:参数 `timeout` 打印 retry later 退出码 0;`bug` 未捕获退出码 1;TS 类型层结论未验证,本机无 tsc)

断言默认随开关变化:

```java run
public class Main {
    static int withdraw(int balance, int amount) {
        assert amount > 0 : "amount must be positive";
        return balance - amount;
    }
    public static void main(String[] args) {
        System.out.println(withdraw(100, -5)); // 默认打印 105
    }
} // 加 -ea 才抛 AssertionError
```
验证:已运行(openjdk 25:默认打印 105 退出码 0;`-ea` 退出码 1)

```cpp run
#include <cassert>
#include <cstdio>

int withdraw(int balance, int amount) {
    assert(amount > 0 && "amount must be positive");
    return balance - amount;
}

int main() { std::printf("%d\n", withdraw(100, -5)); }
```
验证:已运行(g++ 15 `-std=c++20`:默认 assert 失败退出码 134;`-DNDEBUG` 打印 105 退出码 0)

另一条路线:失败编进签名(错误即值、Result、受检异常),调用方必须分支:

```go
if err := flush(path); err != nil {
    return fmt.Errorf("flush path=%s: %w", path, err) // %w 保留原因链
}
```
验证:未验证(本机无 go;`%w` 语义依据 Go 源码 fmt/errors.go 注释,见出处)

## 判据翻转的条件

| 条件 | 可观察信号 | 改选 |
|---|---|---|
| 失败由外部触发(输入、I/O、环境、资源耗尽) | 真实流量或测试里出现过 | 当错误处理:运行时校验,失败形态进接口 |
| 只有缺陷才能触发 | 生产从未出现,只有构造内部违约才能复现 | 不进错误值:断言或尽早暴露,开发期炸掉 |
| 本层无法处理失败 | 捕获后既不能重试、补偿,也补不出上下文 | 不捕获,让失败传到能处理的位置 |
| 长期运行的服务、插件宿主 | 单个请求的缺陷会拖垮整个进程 | 只在最外层隔离:兜底、记录、丢弃该请求;不在各层吞 |
| 失败是调用方要分支的常态结果 | 调用点下一步必然分支,不分支就没意义 | 返回值或结果类型 |
| 失败罕见且要跨多层传播 | 中间层没人处理它,只为转手写样板 | 异常;一个代码库保持一种习惯 |
| 目标仓禁用异常 | 构建开关或错误协议里明说 | 状态或结果类型,不用异常 |
| 重新定义语义后契约仍成立 | 新契约使原失败路径不再成立 | 重定义语义,让该失败不存在(作者本人提醒勿过度) |

Meyer 写明 demanding 与 tolerant 两种前置条件风格皆可;宽严依本仓既有约定。只管新代码与新接口,既有公共错误集合不动(SKILL.md)。C++ 的 noexcept 与禁异常语境见 [所有权与生命周期](../ownership-and-lifetime.md);[表达准则](../principles.md)有对应约束。

## 出处

| 文中位置 | 论断 | 出处 | 状态 |
|---|---|---|---|
| 判据句 | 缺陷与可恢复错误是两类,混用不可靠;前置条件违约是调用方 bug;缺陷被"善后"等于骗调用方 | Duffy, The Error Model, 2016;Meyer, Applying "Design by Contract", IEEE Computer 1992;Lippert, Vexing exceptions, 2008 | 已核 |
| 判据句 | 错误不应静默通过,除非显式静默 | Peters, PEP 20, 2004 | 已核 |
| 翻转表 | 减少必须处理异常的位置;能消除则消除,但勿过度;断言用于"生产绝不发生" | Ousterhout, CS190 讲稿(winter 2018、winter 2024) | 已核 |
| 翻转表 | 外部失败无法预先排除,必须处理 | Lippert, 同上 | 已核 |
| 断言节 | Python `-O`、Java 默认、C++ `NDEBUG` 下 assert 消失 | 本机实测,命令见 runs.md | 已核 |
| 断言节 | Rust `assert!` 不可关;`debug_assert!` 默认仅调试构建 | Rust std 文档 | 已核 |
| 断言节 | Go 没有断言 | Go FAQ, go.dev | 已核 |
| 翻转表 | 错误是值,处理方式可编程 | Pike, Errors are values, 2015 | 已核 |
| 翻转表 | 受检=可恢复,运行时异常=编程错误 | Bloch, Effective Java 3rd, Item 70(依据为第三方转录) | 待核 |
| 翻转表 | 兜底集中;受检异常有版本化与规模问题 | Hejlsberg 访谈, Artima, 2003 | 已核 |
| Go 例 | `%w` 保留原因链 | Go 源码 src/fmt/errors.go 注释 | 已核 |

### 延伸阅读(未核)

- Ousterhout, A Philosophy of Software Design, 2nd ed., Define Errors (and Special Cases) Out of Existence(书章原文未取得)

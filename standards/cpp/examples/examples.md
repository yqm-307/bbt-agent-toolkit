# Clean Code 正反例：语言无关伪代码

以下例子本地编写，非原书摘录。伪代码表达算法和契约，不指定语法、类型系统、标准库或错误机制；不可直接编译。箭头表示返回类型，`←` 表示赋值，AND/OR 表示逻辑组合。迁移到真实代码时，以项目语言、接口和生命周期规则为准。

<a id="命名与流程"></a>
## 1. 名字表达概念与单位

**反例：** 名字隐藏数据的含义，读者必须从比较推断意图。

```text
FUNCTION Count(a, b)
    n ← 0
    FOR EACH x IN a
        IF x ≤ b
            n ← n + 1
    RETURN n
```

**正例：** 只改善名字，算法保持不变。

```text
FUNCTION CountExpired(deadlines_ms, now_ms)
    expired_count ← 0
    FOR EACH deadline_ms IN deadlines_ms
        IF deadline_ms ≤ now_ms
            expired_count ← expired_count + 1
    RETURN expired_count
```

**契约与核对：** 同一时钟来源、同一单位；等于截止时刻也算到期。`[8, 10, 12]` 在 `now_ms=10` 时应返回 `2`，空集合返回 `0`。
**边界：** 名字足够清楚就停，不为每个数值引入自定义类型；已发布函数改名另需迁移授权。

<a id="提取领域判断"></a>
## 2. 提取领域判断，不拆每一行

**反例：** 通知主流程被资格细节遮住。

```text
FUNCTION Notify(customers)
    FOR EACH customer IN customers
        IF customer.active
            IF customer.accepts_notices
                IF NOT customer.suspended
                    SendNotice(customer)
```

**正例：** 提取可独立理解的业务规则，保留通知顺序。

```text
FUNCTION CanReceiveNotice(customer)
    RETURN customer.active AND customer.accepts_notices
           AND NOT customer.suspended

FUNCTION NotifyEligible(customers)
    FOR EACH customer IN customers
        IF CanReceiveNotice(customer)
            SendNotice(customer)
```

**契约与核对：** 三个属性均为布尔值，在本次操作中稳定可读、读取无副作用。只有 active 与 accepts_notices 为真、suspended 为假时发送一次；空集合不发送。发送失败时保持项目原有处理，不新增吞错、重试或跳过。
**边界：** 若短局部判断已清楚，保留原样；提取应带来独立语义或当前阅读收益，不以静态调用点数量、未来复用或函数行数强制决定；执行时的求值条件和副作用次数必须保持。已发布入口改名另需授权。

<a id="注释的信息增量"></a>
## 3. 删复述，保留不可见的原因

**反例：** 逐行翻译没有说明为何不能调整顺序。

```text
// 释放锁。
Release(lock)
// 调用回调。
Invoke(callback)
```

**正例：** 代码不变，补充时序原因。

```text
// 回调可能重新获取同一把锁，必须在解锁后调用。
Release(lock)
Invoke(callback)
```

**契约与核对：** 进入片段时当前执行者持锁，回调有效且同步执行；观察顺序必须为“释放锁、回调”。回调重新获取该锁不应被本次持锁阻塞。此片段省略锁的获取和异常清理，不是完整实现或并发正确性证明。
**边界：** 所有权、失败保证和复杂状态摘要也可能值得说明；能从代码推导但成本很高的信息，不因“只准写 WHY”被删除。实现时使用目标语言已有的安全资源管理方式。

<a id="调用点的语义"></a>
## 4. 调用点说明模式，而不是猜布尔值

**反例：** 调用点看不出布尔参数的意思。

```text
FormatName("Ada", "Lovelace", TRUE)
```

**正例：** 对获准设计的新接口，使用命名的有限选项。

```text
NameOrder HAS OPTIONS GivenFirst, FamilyFirst
FormatName("Ada", "Lovelace", NameOrder.FamilyFirst)
```

**契约与核对：** `FamilyFirst` 输出 `Lovelace, Ada`，`GivenFirst` 输出 `Ada Lovelace`；其他输入与失败行为沿用原契约。不要把有限选项改成任意字符串而引入拼写错误或新非法状态。
**边界：** 这是新接口设计例，不授权破坏已有布尔 API；`SetEnabled(TRUE)` 已表达明确属性，无需改造。命名选项如何实现属于目标语言规范；等价的具名常量或具名参数同样可以表达意图。

<a id="相似不是同一规则"></a>
## 5. DRY 复用同一知识，不合并偶然相等的值

**反例：** 独立政策因数值相同而被错误耦合。

```text
DEFAULT_LIMIT ← 3
shipment_batch_size ← DEFAULT_LIMIT
login_attempt_limit ← DEFAULT_LIMIT
```

**正例：** 两个值分别表达自己的业务政策，并保留可搜索的名字。

```text
shipment_batch_size ← 3
login_attempt_limit ← 3
```

**契约与核对：** 发货批量和登录尝试上限独立变化；只把发货批量改成 `5`，登录上限仍应为 `3`。
**边界：** 若两处真的共享同一个不变量，应统一维护。不为了套 DRY 合并相似语法，也不反向允许复制同一规则。

## 保持原样也是有效结论

已有的直接循环、短函数、必要的输出参数或明确布尔属性，不因 Clean Code 而必须改变。审查只指出具体理解障碍；没有问题就保留，不为删一条注释造 helper，不为避免分支建继承树。

以上核对项是预期行为，不是执行记录。伪代码只帮助建立判断，不能替代对真实实现的编译、测试与必要的并发验证。


## 6. 边界不是转发层

**反例：** 单一解析函数已经满足需要，为“以后替换”再加 ParsePort、默认工厂和无逻辑转发类，调用者仍须知道全部底层错误。

**正例：** 直接复用现成解析能力，只有已有接口所需的单位转换或错误映射才做小适配；当真实消费者需要稳定替换点时再引入接口。

**契约与核对：** 成功值与失败集合不变，不吞错误、不强装依赖；核调用点和调试是否真的少一次猜测。
**边界：** 已存在且有外部消费者的接口不能只因单实现就擅删；测试隔离或隐藏复杂细节也可以是真实抽象收益。

## 7. 缩小承诺，不偷删需求

**反例：** 关闭路径很复杂，于是不问消费者就删除关闭入口，并把未释放资源称为“进程结束自然清理”。

**正例：** 先核对实际生命周期和资源所有者。如果产品只需进程同生命周期、调用者不依赖重启且迁移获授权，可以删除不需要的关闭/重启承诺；业务资源仍由自己的 owner 按契约释放。

**契约与核对：** 必要资源清理、失败行为与已承诺功能不丢；删除承诺本身是契约变更，另走目标项目权限与兼容验证。
**边界：** 这是职责判断示例，不要求任何项目删除 Stop/取消，也不提供具体运行时实现。

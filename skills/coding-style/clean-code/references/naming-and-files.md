# 命名、排版与文件

仅 C++ 分支读取。以下是已确认的团队默认，不向其他语言套用；目标仓已有规范/formatter 优先。存量差异按周围代码，不顺手全库重排；语言正确性不因存量豁免。语义与来源边界见 [C++ 默认写法](cpp-style.md) 和 [来源](google-adopt.md)。

## 命名

- 类型、别名、函数用 PascalCase；缩写按词处理，如 `GetIpAddr()`（示意）。
- 纯虚接口类用 `I` 前缀并放 `interface/`（`ICoLock`、`ICoroutine`）；接口文件只含纯虚与必要类型。
- 指针类型别名用后缀表达所有权：`Ptr`（裸指针/借用）、`UPtr`（`unique_ptr`）、`SPtr`（`shared_ptr`）。别名不能掩盖所有权时用全写类型，也别让 `Ptr` 悄悄拥有对象。
- 私有方法默认 PascalCase（`Init()`、`Drain()`），可见性由 private 表达。历史 `_Init()` 等是惯例记录，不是标准例外：`_`+大写与含 `__` 的名字在任何作用域都保留，不新生成。存量改名先核消费者、兼容与授权，不能用“类私有”豁免语言规则。
- 变量与参数 snake_case；class 数据成员 `m_` + snake_case（`m_run_status`）；struct 纯数据字段不加前缀。静态成员用 `s_` 前缀。
- `const` 不意味着全程常量：局部 `const int retry_count` 不必用 `k`。新文件作用域常量用 `kName`。
- 枚举值跟文件既有风格（`CO_RUNNING`、`COMUTEX_FREE`）；Google 建议 `kName`，存量不顺手改名，新独立模块可用 `kName`，同一文件不混。
- 名字长短匹配作用域；下标 `i` 合理，公开 API 不删字母缩写。单位和布尔含义明确，如 `timeout_ms`。
- 实现文件和示例反复出现冗长限定名时，优先用 `using namespace` 简化，并尽量缩小作用域；遇到同名冲突或符号来源不清时，改用具名 `using` 或命名空间别名。公共头文件的边界沿用[头文件与构建](headers-and-build.md#自给与依赖)。

## 排版

4 空格缩进（用户偏好，覆盖 Google 的 2 空格）；行宽以 **120 列左右为软参考**（含缩进），不是硬上限，也不是要填满的目标。以语义完整、视觉疏密和阅读负担决定换行：简单表达式可略超，复杂表达式未到参考宽度也可展开；不为凑列数拆碎代码。目标仓已有 formatter/规范仍优先。

- 简单调用、赋值、短签名保持一行；简单取值函数可单行，同类声明保持一致。不把多个独立语句挤到一行，也不把短参数机械地每项拆一行。
- 长参数列表在逗号处按语义成组换行；复杂条件在逻辑运算符处分层，续行保持一致缩进或对齐，不拆开紧密关联的子表达式。多步 lambda/控制流展开，避免嵌套与副作用挤成一团。
- 同一逻辑步骤内紧凑排列；准备、执行、收尾等不同阶段或独立分支之间用空行分组，不每条语句都插空行。相关声明的对齐服务扫读，不为少数长类型拉宽整组（见下文）。

函数、class、控制流左大括号同行，namespace 内容不额外缩进。class 的 `public:` 等访问标签不缩进（与 class 声明的缩进层级对齐，不等于所有嵌套类都强制落绝对列 0），成员缩进 4 空格。本 skill 为统一生成默认给短条件也加大括号；Google 允许的其他形式不是安全缺陷。长 URL 等合理例外不硬拆。

指针默认 `T* ptr`、引用 `const T& value`。通常一行一个语句、一次声明一个变量；合理例外不硬拆。运算符两侧留空格，相关步骤间空一行。

类内声明按名字列对齐：`explicit` 等前缀和类型名之后补空格，让同一类内的函数名与成员变量名落在同一列。列宽取 4 的倍数，按该类大多数声明（不含少数明显更长的类型）定，允许留余量、不必贴合最宽声明；个别明显更长的类型不抬高列宽，而是把名字换到下一行、继续对齐该列。列宽不跨类统一。

```cpp
// 好：访问标签各出现一次，方法在前、成员变量集中在尾部；函数名与成员变量名对齐同一列。
class CoTaskQueue {
public:
    explicit        CoTaskQueue(std::size_t capacity);
    void            Push(std::function<void()> task);
    bool            Empty() const;

private:
    void            Drain();
    std::size_t     m_capacity{0};
    std::mutex      m_mtx;
    std::deque<std::function<void()>>
                    m_tasks;
};
// 反例：类型与名字之间只留一个空格，同文件里两种列宽混用，方法与成员交错。
```
项目有 formatter 时用其配置检查变更范围，不边修功能边重排全库。

## 头文件与 include

头文件用 `#pragma once`（与仓库一致）。
include 顺序：对应头、C 系统头、C++ 标准库、其他库、本项目。组间空一行；平台条件包含按实际依赖保留。
仓库以库形式对外时 include 一律尖括号项目相对路径（`<bbt/coroutine/sync/CoMutex.hpp>`）；纯应用工程可用引号，同一项目内保持一致。

```cpp
// 示意（分组形状，非某个真实文件的原样）
#include <bbt/coroutine/sync/CoMutex.hpp>

#include <mutex>
#include <queue>

#include <bbt/core/Attribute.hpp>
```

不是每个类都要独立文件；文件按紧密相关的概念组织，避免大杂烩和单类强拆。

## 声明与注释

类内按 public、protected、private 分区，每个标签只出现一次：方法在前、成员变量集中在尾部，不与方法交错；相关声明相邻，数据与操作职责清楚。纯数据用 struct，需要维护不变量用 class；不为每个字段生成无意义 getter/setter。

通用注释准则见 [principles.md](principles.md#注释)，不另定义语言特例；TODO 给具体动作与可追踪责任或问题，不留“以后优化”。既有许可证和法律声明保留。

正例：`// 对象交给后台任务后，调用者不得再修改它。`
反例：`// 增加计数` 紧贴 `++count;`。

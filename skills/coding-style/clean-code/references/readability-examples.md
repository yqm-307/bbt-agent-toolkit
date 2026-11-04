# C++ 可读性实现示例

以下 C++17 教学代码本地编写，从通用 clean-code 示例中迁入；不是原书代码或生产组件。这里只补语言层写法，不重复通用命名/注释/DRY 原则。`bad` 表示表达问题，不必然是功能缺陷。

## 1. 标准算法与显式捕获

用 `std::count_if` 表达计数，按值显式捕获只读阈值，计数类型为 `std::size_t`。若短循环更清楚，不强制算法或 lambda。时刻必须使用同一单位与时钟；等于截止时刻算到期。函数改名仅是教学对照，不授权修改公共 API。

```cpp
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <vector>

namespace bad {
std::size_t Count(const std::vector<int>& a, int b) {
    std::size_t n = 0;
    for (int x : a) {
        if (x <= b) {
            ++n;
        }
    }
    return n;
}
}

namespace good {
std::size_t CountExpired(const std::vector<int>& deadlines_ms, int now_ms) {
    return static_cast<std::size_t>(std::count_if(
        deadlines_ms.begin(), deadlines_ms.end(),
        [now_ms](int deadline_ms) { return deadline_ms <= now_ms; }));
}
}

int main() {
    const std::vector<int> deadlines{8, 10, 12};
    assert(good::CountExpired(deadlines, 10) == 2);
    assert(good::CountExpired({}, 10) == 0);
    for (int now = 7; now <= 13; ++now) {
        assert(bad::Count(deadlines, now) == good::CountExpired(deadlines, now));
    }
}
```

## 2. RAII 与回调重入

`std::unique_lock` 管理异常退出，但回调前仍需显式解锁；作用域管理不能自动推断业务所需的解锁位置。约定其他状态访问受同一锁保护，回调有效并同步执行。本检查只覆盖同步重入，不是并发正确性证明；异步逃逸另核捕获与对象寿命。

```cpp
#include <cassert>
#include <functional>
#include <mutex>

namespace bad {
void Publish(std::mutex& mutex, bool& ready, const std::function<void()>& callback) {
    std::unique_lock<std::mutex> lock(mutex);
    // 修改状态。
    ready = true;
    // 释放锁。
    lock.unlock();
    // 调用回调。
    callback();
}
}

namespace good {
void Publish(std::mutex& mutex, bool& ready, const std::function<void()>& callback) {
    std::unique_lock<std::mutex> lock(mutex);
    ready = true;
    // 回调可能重新获取同一把锁，必须在解锁后调用。
    lock.unlock();
    callback();
}
}

int main() {
    std::mutex mutex;
    bool ready = false;
    int called = 0;
    const auto callback = [&] {
        std::lock_guard<std::mutex> lock(mutex);
        assert(ready);
        ++called;
    };
    bad::Publish(mutex, ready, callback);
    good::Publish(mutex, ready, callback);
    assert(called == 2);
}
```

## 3. enum class 表达模式

新接口可用 `enum class` 让调用点的模式有名字；不要用任意字符串替换布尔值而引入拼写错误。已经发布的布尔接口保留兼容；`SetEnabled(bool)` 这类明确属性无需枚举。例子仅接收声明的枚举值，外部整数转枚举必须另做校验。

```cpp
#include <cassert>
#include <string>

namespace bad {
std::string FormatName(const std::string& given, const std::string& family,
                       bool family_first) {
    return family_first ? family + ", " + given : given + " " + family;
}
}

namespace good {
enum class NameOrder { GivenFirst, FamilyFirst };

std::string FormatName(const std::string& given, const std::string& family,
                       NameOrder order) {
    return order == NameOrder::FamilyFirst
        ? family + ", " + given : given + " " + family;
}
}

int main() {
    using good::NameOrder;
    assert(good::FormatName("Ada", "Lovelace", NameOrder::FamilyFirst)
           == "Lovelace, Ada");
    assert(good::FormatName("Ada", "Lovelace", NameOrder::GivenFirst)
           == bad::FormatName("Ada", "Lovelace", false));
    assert(good::FormatName("", "", NameOrder::FamilyFirst)
           == bad::FormatName("", "", true));
}
```

在仓库根执行 `python3 skills/coding-style/clean-code/scripts/check_examples.py`，直接提取本文件三个代码块编译并运行断言。需要 g++ 和 Python 3；不自动安装。样本断言不等于全域等价证明。

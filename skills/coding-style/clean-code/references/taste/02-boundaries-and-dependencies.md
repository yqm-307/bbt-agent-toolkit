# 边界与依赖

> 倾向按变化原因切分模块,接口小而内部深;当两侧总是一起改动时,改为合并。

职责、重复、接口/工厂见 [职责与抽象](../design-principles.md);命名、函数、注释见 [表达准则](../principles.md);本篇补:切分、深浅、耦合、副作用。

## 代码里的信号

- 切分依据:一个需求同时改几个模块;模块名是处理步骤,一条知识散在步骤间;提交历史里两个目录总是一起改;utils/common/helpers 成了堆放处。
- 深浅:只转发的方法、薄包装;调用者得知道内部才敢用;接口和实现一样复杂。
- 耦合:位置参数调用点看不出含义;同一魔法值写在两处;两处算法必须同步改。
- 副作用:要 mock 时钟、数据库才能测决策;读环境与决策在同一函数。

## 正反例

**按变化原因,不按步骤。** Parnas 的两种切分:按处理步骤(流程图式),或按可能变的设计决定;他主张后者,按流程图切"几乎总是"错的。`read_rows → validate_rows → transform_rows → write_rows` 共享"记录长什么样"的知识,规则一改四处同步。依据是变化原因,不是数量:一个真实消费者也可以需要清晰边界。

```cpp run
#include <cassert>
#include <string>
// 反例(下两行):决定散在调用点;位置布尔写反不报错。
std::string lower(std::string s) { for (char& c : s) if (c >= 'A' && c <= 'Z') c += 32; return s; }
std::string squeeze(std::string s) { std::size_t i; while ((i = s.find("  ")) != std::string::npos) s.replace(i, 2, " "); return s; }
// 正例:按"归一"决定切一个模块;参数从位置改为名称。
enum class Case { keep, lower };
struct Norm { Case cse; bool squeeze; };
std::string ingest(const std::string& raw, Norm n) {
    std::string s = raw;
    if (n.squeeze) { std::size_t i; while ((i = s.find("  ")) != std::string::npos) s.replace(i, 2, " "); }
    if (n.cse == Case::lower) for (char& c : s) if (c >= 'A' && c <= 'Z') c += 32;
    return s;
}
int main() { assert(ingest("  Hi  You ", Norm{.cse = Case::lower, .squeeze = true}) == " hi you "); return 0; }
```

验证:已运行(g++ 15.2.0,-std=c++20 -Wall -Wextra)

**接口小,内部深。** 深模块功能相对接口多:复杂度收进去,调用点只表达意图;浅类有时不可避免,但转发层不帮着管复杂度。深浅看吸收了多少复杂度,不看文件大小。

**强耦合换弱,或放近。** connascence(Page-Jones 提出的耦合分类)把"必须一起改"的依赖分型:静态按名称、类型、取值含义、位置、算法,动态按执行顺序、时机、值、身份。改写:位置→名称(例 1)、取值含义→命名常量、算法一致→收到一处共用;改不动就放近:强耦合在同一个函数或文件内可以接受。

**决策与读写分开。** Bernhardt:函数式核心、命令式外壳。核心只决策,输入全来自参数;外壳读时钟、数据库,写结果;要 mock 才能测,是依赖混进了决策。大系统应是多个小的核心/壳组合。翻转:I/O 本身是决策(原子读改写、流式背压)时,拆开会丢原子性。不得借此改变副作用的次数与顺序(见 [SKILL.md](../../SKILL.md))。

```python run
from datetime import date
# 反例:决策里直接 date.today(),测试只能 mock。
# 正例:决策输入全靠参数;外壳读时钟、写输出。
def quote(items, tax, today):
    base = sum(p for _, p in items)
    weekend = today.weekday() >= 5
    return base * (1 + tax) * (0.5 if weekend else 1.0)
print(quote([("milk", 20)], 0, date.today()))  # 外壳:读时钟、写输出
assert quote([("milk", 20)], 0, date(2026, 10, 24)) == 10.0   # 周六
assert quote([("milk", 20)], 0, date(2026, 10, 23)) == 20.0   # 周五
```

验证:已运行(python3 3.14.9)

## 判据翻转的条件

匹配策略:任一翻转条件成立即改选;都不成立按倾向;拿不准选"未知时"。

| 规则 ID | 条件 | 倾向 | 翻转条件 | 未知时 |
|---|---|---|---|---|
| B1 切分 | 两处因同一个会变的设计决定而耦合 | 按该决定切一个模块 | 两侧总随同一需求一起改→合并;找不到稳定语义、真实消费者或变化原因→不拆 | 保持直接写法 |
| B2 深浅 | 功能多而接口窄 | 复杂度收进内部 | 窄接口表达不了调用者真实差异(调用点穿透封装) | 先问真实消费者 |
| B3 耦合 | 强耦合可换弱 | 换弱形式 | 强耦合局限在同一函数或文件内 | 就地保留 |
| B4 副作用 | 决策与读写可分 | 决策纯函数,外壳读写 | I/O 本身是决策(原子读改写、流式背压) | 保持原样,不改副作用次数与顺序 |

## 出处

| 论断 | 出处与原文片段(链接只在此节) | 状态 |
|---|---|---|
| 按会变的设计决定切,不按流程图;每模块藏一个决定 | [Parnas, CACM 1972](https://wstomv.win.tue.nl/edu/2ip30/references/criteria_for_modularization.pdf):"almost always incorrect to begin the decomposition of a system into modules on the basis of a flowchart";"a design decision which it hides from all others" | 已核 |
| 强耦合换弱 | [Weirich 2009,经 Brown 在 Practicing Ruby 转述](https://practicingruby.com/articles/connascence):"convert instance of Type, Meaning, Position, and Algorithm-based connascence down to Connascence of Name" | 已核 |
| 耦合近处优于远处 | [connascence.io](https://connascence.io/):"close together in a codebase are better than ones that are far apart" | 已核 |
| 外壳包住核心;大系统不是一个核心一个壳 | [Bernhardt 2012,rubyevents.org 转录 00:14:08 / 00:23:16](https://www.rubyevents.org/talks/boundaries):"an imperative layer around the functional core—an imperative shell";"don't want a single functional core and a single shell" | 已核 |

延伸阅读(未核):Ousterhout《A Philosophy of Software Design》(2018)的深/浅模块、转发方法、按执行顺序切分,书中原文未取得可核渠道,正文相关表述不署名;Page-Jones 1992 CACM 35(9) 与 1995 年书,connascence 分类名最初出处;原文未取得(dl.acm.org 被 Cloudflare 拦截),分类名以上表转述为准。

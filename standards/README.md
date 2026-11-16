# 通用编码规范

这里保存语言无关原则、代码审美，以及按语言组织的通用写法、注释与格式。它不规定某个家族的命名值、目录、宏、错误布局或运行时实现，也不承担角色执行流程和工具调用入口。

## 项目如何声明采用

在项目的规则入口写明采用本目录的固定版本与具体页面，并列出项目覆盖项；消费仓可通过固定提交的依赖目录引用，而不是复制全文。示例声明：

```text
采用工具箱固定提交中的 standards/general/ 与 standards/cpp/。
语言版本、命名、错误协议和构建入口以本仓声明为准。
下列项目规范补充或覆盖通用默认：……
```

覆盖顺序：**目标仓约束 > 项目规范 > standards 通用默认**。已有仓规、契约、语言标准与工具配置优先；没有冲突才采用候选默认。引入配置或改变公共契约仍须目标仓授权，采用通用规范不等于授权重排或重命名存量代码。

## 目录约定与阅读入口

- `general/`：跨语言判断；[原则](general/principles.md)、[代码品位](general/code-taste.md)、[命名](general/naming.md)、[所有权与并发](general/ownership-and-concurrency.md)、[文档](general/documentation.md)。
- `general/taste/`：[品味总纲](general/taste/00-overview.md)及六篇专项，保留分歧、翻转条件与来源。
- `cpp/`：[语义写法](cpp/style.md)、[文档注释](cpp/documentation.md)、[格式工具](cpp/format.md)、[候选配置](cpp/clang-format.yaml)、[示例](cpp/examples/readability-examples.md)。
- `python/`：[格式工具](python/format.md)、[候选配置](python/ruff.toml)。
- `go/`：[格式工具](go/format.md)，采用工具内建规则，不造配置。

一条规则只保留一个完整正文，其他页面短引；语言细节放对应语言目录，做法步骤留给角色方法或工具入口。本目录不反向依赖这些上层入口；内部文件引用只用相对链接且不出本目录。外部文献保留原始来源地址和核验状态，不把原文记录冒充本次实测。

正反例保持契约和上下文，伪代码明确不可编译。示例检查从工具箱根运行 `python3 -I standards/cpp/examples/check_examples.py`；教学检查不证明生产代码正确性。

许可：[通用内容声明](LICENSE)、[克制建设来源许可](general/ponytail-license.txt)、[C++ 教学示例与检查器许可](cpp/examples/cpp-examples-LICENSE.txt)。这些声明不重新许可外部文献或既有团队材料。

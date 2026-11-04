#!/usr/bin/env python3
"""Validate skill links/templates; optionally exercise explicit formatter bins."""

import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def structure():
    paths = [
        ROOT / name
        for name in (
            "SKILL.md",
            "references/cpp.md",
            "references/python.md",
            "references/golang.md",
            "references/workflow.md",
            "templates/clang-format.yaml",
            "templates/ruff.toml",
        )
    ]
    for path in paths:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"Missing/empty required file: {path.relative_to(ROOT)}")
    for doc in ROOT.rglob("*.md"):
        text = re.sub(
            r"^```[^\n]*\n.*?^```$",
            "",
            doc.read_text(encoding="utf-8"),
            flags=re.M | re.S,
        )
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            target = (doc.parent / link.split("#")[0]).resolve()
            if not target.is_file():
                raise ValueError(f"Broken link: {doc.relative_to(ROOT)} -> {link}")
    config = tomllib.loads((ROOT / "templates/ruff.toml").read_text())
    if config.get("line-length") != 88:
        raise ValueError("Python candidate must not inherit C++ line width")
    cpp = (ROOT / "templates/clang-format.yaml").read_text()
    for expected in (
        "IndentWidth: 4",
        "ColumnLimit: 120",
        "InsertBraces: false",
        "BreakBeforeBraces: Custom",
        "AfterFunction: true",
        "SplitEmptyFunction: true",
        "AllowShortFunctionsOnASingleLine: None",
    ):
        if expected not in cpp:
            raise ValueError(f"Missing C++ mapping: {expected}")
    return {
        "status": "PASS",
        "checks": ["required-files", "local-links", "ruff-toml", "cpp-mapping"],
    }


def run(command, trace):
    result = subprocess.run(list(map(str, command)), capture_output=True, timeout=30)
    trace.append(
        {
            "command": list(map(str, command)),
            "exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace"),
        }
    )
    return result


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# 候选样式的大括号判别样本：函数/构造/析构/类内成员换行，控制流/类/namespace/lambda 不换行。
CPP_BRACE_SAMPLE = """namespace ns {
class Foo {
public:
    Foo() {}
    ~Foo() {}
    void bar() { int x = 1; (void)x; }
    void empty() {}
};
void free_fn() {
    if (true) {
        for (int i = 0; i < 1; ++i) {}
    }
    auto l = []() { return 1; };
    (void)l;
}
}
"""
CPP_BRACE_BREAK = (
    ("free function", r"^void free_fn\(\)[ \t]*\n\{"),
    ("constructor", r"^[ \t]*Foo\(\)[ \t]*\n[ \t]*\{"),
    ("destructor", r"^[ \t]*~Foo\(\)[ \t]*\n[ \t]*\{"),
    ("member function", r"^[ \t]*void bar\(\)[ \t]*\n[ \t]*\{"),
    (
        "empty function body split",
        r"^[ \t]*void empty\(\)[ \t]*\n[ \t]*\{[ \t]*\n[ \t]*\}",
    ),
)
CPP_BRACE_ATTACH = (
    ("namespace", "namespace ns {"),
    ("class", "class Foo {"),
    ("if", "if (true) {"),
    ("for", "for (int i = 0; i < 1; ++i) {"),
    ("lambda", "[]() {"),
)
# 函数定义的左大括号若仍在签名行即判失败；if/for/while/switch/catch 本来就同行。
CPP_BRACE_HEAD_ATTACHED = re.compile(
    r"^[ \t]*(?!(?:if|for|while|switch|catch)\b)([\w:~]+)[ \t]*\([^;{}\n]*\)[ \t]*\{[ \t]*$",
    re.M,
)
# 旧模板（恢复前的 Attach/Inline 映射）留作判别性反例：断言必须能拒绝它。
CPP_LEGACY_ATTACH_STYLE = (
    "{BasedOnStyle: LLVM, IndentWidth: 4, NamespaceIndentation: None, "
    "BreakBeforeBraces: Attach, AllowShortFunctionsOnASingleLine: Inline}"
)


def cpp_brace_problems(text):
    """返回不符合候选大括号映射的条目；空列表表示符合。"""
    problems = [
        f"function brace not on its own line: {name}"
        for name, pattern in CPP_BRACE_BREAK
        if not re.search(pattern, text, re.M)
    ]
    problems += [
        f"non-function brace moved or missing: {name}"
        for name, fragment in CPP_BRACE_ATTACH
        if fragment not in text
    ]
    problems += [
        f"definition brace still attached: {match.group(1)}"
        for match in CPP_BRACE_HEAD_ATTACHED.finditer(text)
    ]
    return problems


def probe(language, binary):
    binary = Path(binary).resolve()
    trace = []
    with tempfile.TemporaryDirectory(prefix=f"coding-format-{language}-") as folder:
        directory = Path(folder)
        if language == "cpp":
            source = directory / "sample.cc"
            original = b"void F(){int x=1;Use(x);}\n"
            source.write_bytes(original)
            config = ROOT / "templates/clang-format.yaml"
            prefix = [
                binary,
                f"--style=file:{config}",
                "--Werror",
                "--fail-on-incomplete-format",
            ]
            version = run([binary, "--version"], trace)
            require(version.returncode == 0, "Cannot read clang-format version")
            require(
                run(prefix + ["--dump-config"], trace).returncode == 0,
                "Invalid C++ template",
            )
            check = lambda: run(prefix + ["--dry-run", source], trace)
            require(
                check().returncode != 0,
                "Bad C++ sample did not produce format differences",
            )
            require(source.read_bytes() == original, "C++ check wrote source")
            formatted = run(prefix + [source], trace)
            require(formatted.returncode == 0, "C++ format failed")
            require(
                re.findall(rb"\w+|[^\s]", original)
                == re.findall(rb"\w+|[^\s]", formatted.stdout),
                "C++ probe tokens changed",
            )
            source.write_bytes(formatted.stdout)
            require(check().returncode == 0, "Formatted C++ sample still fails check")
            require(
                run(prefix + [source], trace).stdout == formatted.stdout,
                "C++ format not idempotent",
            )
            bad = directory / "invalid.yaml"
            bad.write_text("InvalidProbeOption: true\n")
            require(
                run(
                    [binary, f"--style=file:{bad}", "--Werror", "--dump-config"], trace
                ).returncode
                != 0,
                "Invalid C++ config was accepted",
            )
            braces = directory / "braces.cc"
            braces.write_text(CPP_BRACE_SAMPLE, encoding="utf-8")
            brace_check = lambda: run(prefix + ["--dry-run", braces], trace)
            require(
                brace_check().returncode != 0,
                "Unformatted brace sample produced no differences",
            )
            require(
                braces.read_text(encoding="utf-8") == CPP_BRACE_SAMPLE,
                "C++ brace check wrote source",
            )
            brace_formatted = run(prefix + [braces], trace)
            require(brace_formatted.returncode == 0, "C++ brace sample format failed")
            problems = cpp_brace_problems(
                brace_formatted.stdout.decode("utf-8", errors="replace")
            )
            require(not problems, "C++ brace mapping wrong: " + "; ".join(problems))
            braces.write_bytes(brace_formatted.stdout)
            require(
                brace_check().returncode == 0,
                "Formatted brace sample still fails check",
            )
            require(
                run(prefix + [braces], trace).stdout == brace_formatted.stdout,
                "Brace sample format not idempotent",
            )
            legacy = run([binary, "--style=" + CPP_LEGACY_ATTACH_STYLE, braces], trace)
            require(legacy.returncode == 0, "Legacy attach style probe failed")
            require(
                cpp_brace_problems(legacy.stdout.decode("utf-8", errors="replace")),
                "Brace assertion accepted the pre-change attach style (not discriminating)",
            )
        elif language == "python":
            source = directory / "sample.py"
            original = b'def f( x ) :\n return { "value" :x }\n'
            source.write_bytes(original)
            prefix = [binary, "format", "--config", ROOT / "templates/ruff.toml"]
            version = run([binary, "--version"], trace)
            require(version.returncode == 0, "Cannot read Ruff version")
            check = lambda: run(prefix + ["--check", source], trace)
            require(check().returncode == 1, "Bad Python sample must exit 1")
            require(source.read_bytes() == original, "Python check wrote source")
            require(
                run(prefix + [source], trace).returncode == 0, "Python format failed"
            )
            formatted = source.read_bytes()
            require(
                ast.dump(ast.parse(original)) == ast.dump(ast.parse(formatted)),
                "Python probe AST changed",
            )
            require(
                check().returncode == 0, "Formatted Python sample still fails check"
            )
            require(
                run(prefix + [source], trace).returncode == 0,
                "Second Python format failed",
            )
            require(source.read_bytes() == formatted, "Python format not idempotent")
            source.write_text("def broken(:\n")
            require(check().returncode == 2, "Invalid Python input must exit 2")
        else:
            source = directory / "sample.go"
            original = b"package p\nfunc F(){x:=1;_ = x}\n"
            source.write_bytes(original)
            help_result = run([binary, "-h"], trace)
            require(
                b"usage: gofmt" in help_result.stderr, "Selected binary is not gofmt"
            )
            check = lambda: run([binary, "-l", source], trace)
            first = check()
            require(
                first.returncode == 0 and first.stdout.strip(),
                "gofmt differences must be detected by output",
            )
            require(source.read_bytes() == original, "Go check wrote source")
            formatted = run([binary, source], trace)
            require(formatted.returncode == 0, "Go format failed")
            source.write_bytes(formatted.stdout)
            last = check()
            require(
                last.returncode == 0 and not last.stdout.strip(),
                "Formatted Go input still differs",
            )
            second = run([binary, source], trace)
            require(
                second.returncode == 0 and second.stdout == formatted.stdout,
                "Go format not idempotent",
            )
            source.write_text("package p\nfunc {\n")
            require(check().returncode != 0, "Invalid Go input was accepted")
    coverage = [
        "bad-check",
        "check-readonly",
        "format",
        "clean-check",
        "idempotence",
        "error-path",
    ]
    if language == "cpp":
        coverage += ["cpp-brace-mapping", "cpp-brace-discriminator"]
    return {"status": "PASS", "trace": trace, "coverage": coverage}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang-format")
    parser.add_argument("--ruff")
    parser.add_argument("--gofmt")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail unless all three bins were supplied",
    )
    args = parser.parse_args()
    report = {
        "structure": {},
        "tools": {},
        "limitations": ["Synthetic probes, not production semantic validation"],
    }
    failures = []
    try:
        report["structure"] = structure()
    except (OSError, ValueError) as exc:
        report["structure"] = {"status": "FAIL", "error": str(exc)}
        failures.append("structure")
    for language, binary in [
        ("cpp", args.clang_format),
        ("python", args.ruff),
        ("golang", args.gofmt),
    ]:
        if not binary:
            report["tools"][language] = {
                "status": "UNVERIFIED",
                "reason": "No explicit bin supplied",
            }
            if args.require_all:
                failures.append(language)
            continue
        try:
            report["tools"][language] = probe(language, binary)
        except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as exc:
            report["tools"][language] = {"status": "FAIL", "error": str(exc)}
            failures.append(language)
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

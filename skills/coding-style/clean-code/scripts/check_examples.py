#!/usr/bin/env python3
"""编译文档中的完整 C++17 示例；只在临时目录生成产物（尊重 TMPDIR）。"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    for document in root.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        prose = re.sub(r"^```[^\n]*\n.*?^```$", "", text, flags=re.M | re.S)
        for link in re.findall(r"\]\(([^)]+)\)", prose):
            if "://" in link:
                continue
            path, _, anchor = link.partition("#")
            target = document.parent / path if path else document
            if not target.is_file():
                raise SystemExit(f"Broken link: {document.name}: {link}")
            if anchor and f'id="{anchor}"' not in target.read_text(encoding="utf-8"):
                raise SystemExit(f"Missing explicit anchor: {link}")
    text = (root / "references/readability-examples.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^```cpp\n(.*?)^```$", text, re.M | re.S)
    if len(blocks) != 3:
        raise SystemExit(f"Expected 3 examples, found {len(blocks)}")
    compiler = shutil.which("g++")
    if not compiler:
        raise SystemExit("BLOCKED: g++ not available; no installation attempted")
    with tempfile.TemporaryDirectory(prefix="cpp-readability-examples-") as directory:
        for index, code in enumerate(blocks, 1):
            source = Path(directory) / f"example-{index}.cpp"
            binary = source.with_suffix("")
            source.write_text(code, encoding="utf-8")
            subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 "-pthread", str(source), "-o", str(binary)],
                check=True, timeout=30,
            )
            subprocess.run([str(binary)], check=True, timeout=5)
            print(f"PASS example {index}: compile + assertions")
    print("PASS local links and all 3 C++17 examples")


if __name__ == "__main__":
    main()

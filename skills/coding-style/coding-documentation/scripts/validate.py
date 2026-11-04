#!/usr/bin/env python3
"""Validate the candidate coding-documentation skill without installing tools."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def check_structure():
    required = [
        'SKILL.md',
        'references/cpp.md',
        'references/export.md',
        'references/diagrams.md',
        'templates/Doxyfile.in',
    ]
    for rel in required:
        path = ROOT / rel
        if not path.is_file() or not path.read_text(encoding='utf-8').strip():
            raise ValueError(f'missing or empty: {rel}')
    for doc in ROOT.rglob('*.md'):
        text = re.sub(r'^```[^\n]*\n.*?^```$', '', doc.read_text(encoding='utf-8'), flags=re.M | re.S)
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in link or link.startswith('#'):
                continue
            target = (doc.parent / link.split('#', 1)[0]).resolve()
            if not target.is_file():
                raise ValueError(f'broken link: {doc.relative_to(ROOT)} -> {link}')
    doxy = (ROOT / 'templates/Doxyfile.in').read_text(encoding='utf-8')
    for key in ('INPUT', 'GENERATE_HTML', 'GENERATE_XML', 'HAVE_DOT', 'HTML_EXTRA_STYLESHEET', 'WARN_LOGFILE'):
        if not re.search(rf'^\s*{key}\s*=', doxy, flags=re.M):
            raise ValueError(f'missing Doxyfile key: {key}')
    return {'status': 'PASS', 'checks': ['required-files', 'local-links', 'doxyfile-keys']}


def probe_doxygen(binary):
    result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'doxygen --version failed')
    return {'status': 'PASS', 'version': result.stdout.strip(), 'check': 'version-only'}


def probe_export(binary, awesome_dir):
    css = Path(awesome_dir).resolve() / 'doxygen-awesome.css'
    if not css.is_file() or not css.read_bytes():
        raise ValueError('Theme CSS missing or empty')
    with tempfile.TemporaryDirectory(prefix='coding-docs-') as folder:
        work = Path(folder)
        inputs = work / 'include'
        inputs.mkdir()
        fixture = inputs / 'sample.hpp'
        original = '''/** @brief 中文基础类型。 */
struct Base {};
/** @brief 中文派生类型。 */
struct Derived : Base {
    /** @brief 返回输入。
     * @param value 输入值。
     * @return 输入值。
     */
    int echo(int value);
};
'''.encode()
        fixture.write_bytes(original)
        (work / 'docs/doxygen').mkdir(parents=True)
        text = (ROOT / 'templates/Doxyfile.in').read_text(encoding='utf-8')
        values = {'PROJECT_NAME': 'DocumentationProbe', 'PROJECT_VERSION': '0',
                  'PROJECT_SOURCE_DIR': str(work), 'PROJECT_BINARY_DIR': str(work),
                  'DOC_INPUT_DIR': str(inputs), 'DOXYGEN_AWESOME_DIR': str(css.parent)}
        for key, value in values.items():
            if any(c in value for c in ('"', '\n', '\r', '\\')):
                raise ValueError('Unsupported quote/newline/backslash in probe path')
            text = text.replace('@' + key + '@', value)
        if re.search(r'@[A-Z_]+@', text):
            raise ValueError('Unresolved template variables')
        config = work / 'Doxyfile'
        config.write_text(text, encoding='utf-8')
        result = subprocess.run([binary, str(config)], cwd=work,
                                capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or 'Doxygen export failed')
        output = work / 'docs/doxygen'
        warnings = (output / 'warnings.log').read_text(encoding='utf-8')
        if warnings.strip() or result.stderr.strip():
            raise ValueError('Export produced warnings: ' + warnings + result.stderr)
        html = output / 'html'
        index = (html / 'index.html').read_text(encoding='utf-8')
        if 'doxygen-awesome.css' not in index or (html / css.name).read_bytes() != css.read_bytes():
            raise ValueError('Theme not wired into HTML')
        root = ET.parse(output / 'xml/structDerived.xml').getroot()
        functions = root.findall('.//memberdef[@kind="function"]')
        if not any(f.findtext('name') == 'echo' and f.find('.//parameterlist') is not None
                   and f.find('.//simplesect[@kind="return"]') is not None for f in functions):
            raise ValueError('Public function/parameter/return docs missing')
        if '中文派生类型' not in ''.join(root.itertext()):
            raise ValueError('Chinese docs missing')
        if not list(html.glob('*inherit*graph*.svg')):
            raise ValueError('Graphviz inheritance output missing')
        if fixture.read_bytes() != original:
            raise ValueError('Export changed source fixture')
        return {'status': 'PASS', 'checks': ['export', 'warnings-empty', 'html-theme',
                'public-symbol-params-return', 'chinese', 'graphviz', 'source-unchanged'],
                'limitations': ['Synthetic fixture only; no browser visual test',
                                'No Mermaid, PlantUML or manual dark-mode-button test']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--doxygen', help='explicit doxygen binary; no installation is attempted')
    parser.add_argument('--awesome-dir', help='explicit local theme directory; enables real export probe')
    parser.add_argument('--require-export', action='store_true', help='fail if export inputs were not supplied')
    args = parser.parse_args()
    report = {'structure': {}, 'tools': {}, 'export': {'status': 'UNVERIFIED'}, 'limitations': [
        'Version probe alone does not verify export; supply --awesome-dir too',
        'Template variables must be replaced before Doxygen reads the file',
    ]}
    failures = []
    try:
        report['structure'] = check_structure()
    except (OSError, ValueError) as exc:
        report['structure'] = {'status': 'FAIL', 'error': str(exc)}
        failures.append('structure')
    if args.doxygen:
        try:
            report['tools']['doxygen'] = probe_doxygen(args.doxygen)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            report['tools']['doxygen'] = {'status': 'FAIL', 'error': str(exc)}
            failures.append('doxygen')
    else:
        report['tools']['doxygen'] = {'status': 'UNVERIFIED', 'reason': 'No explicit binary supplied'}
    if args.doxygen and args.awesome_dir and not failures:
        try:
            report['export'] = probe_export(str(Path(args.doxygen).resolve()), args.awesome_dir)
        except (OSError, ValueError, RuntimeError, ET.ParseError, subprocess.SubprocessError) as exc:
            report['export'] = {'status': 'FAIL', 'error': str(exc)}
            failures.append('export')
    elif args.require_export or args.awesome_dir:
        failures.append('export-unverified')
    report['failures'] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())

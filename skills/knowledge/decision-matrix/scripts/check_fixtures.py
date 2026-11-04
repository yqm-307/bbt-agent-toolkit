#!/usr/bin/env python3
"""纯本地检查：结构、引用、答案键算术；不评分模型回答。"""
from collections import Counter
from itertools import combinations, product
from math import isclose
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, label):
    require(isclose(actual, expected, rel_tol=0, abs_tol=1e-9),
            f"{label}: {actual} != {expected}")


def load_cases(filename):
    data = json.loads((ROOT / 'references' / filename).read_text(encoding='utf-8'))
    require(data['schema_version'] == 1, f'{filename}: 未知版本')
    cases = data['cases']
    ids = [case['id'] for case in cases]
    require(len(ids) == len(set(ids)), f'{filename}: 重复ID')
    require(bool(cases), f'{filename}: 空题库')
    return {case['id']: case for case in cases}


def main():
    expected_files = [
        'SKILL.md', 'references/authoring.md', 'references/evaluation.md',
        'references/sources.md', 'references/scenarios.json',
        'references/answer-key.json', 'scripts/check_fixtures.py',
    ]
    for name in expected_files:
        require((ROOT / name).is_file(), f'缺文件: {name}')
    skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    require(skill.startswith('---\n'), '缺frontmatter')
    header = skill.split('---', 2)[1]
    require(re.search(r'^name: decision-matrix$', header, re.M), 'name不匹配')
    description = re.search(r'^description: (.+)$', header, re.M)
    require(description is not None and '当' in description[1][:57], '缺触发说明')
    links = 0
    for file in ROOT.rglob('*.md'):
        text = file.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
            if '://' in target or target.startswith('#'):
                continue
            path = (file.parent / target.split('#')[0]).resolve()
            require(path.is_relative_to(ROOT), f'引用越出skill: {target}')
            require(path.exists(), f'失效链接: {file.name} -> {target}')
            links += 1
    cases = load_cases('scenarios.json')
    keys = load_cases('answer-key.json')
    require(cases.keys() == keys.keys(), '题目与答案ID不一致')
    require(len(cases) == 8, '当前约定8题')
    for cid, case in cases.items():
        require(bool(case.get('prompt', '').strip()), f'{cid}: 空题目')
        require(case['split'] in {'development', 'reserve'}, f'{cid}: 分组错误')
        require(bool(keys[cid].get('must')), f'{cid}: 缺标准')
        require(isinstance(keys[cid].get('critical_errors'), list), f'{cid}: 缺关键失败清单')
    require('answer-key.json' not in skill, '正文不应直达评分答案')

    # 独立复算虚构S01，非模型输出验证。
    a, b = (80, 75, 60), (90, 0, 90)
    def score(values, timely):
        weights = ((1 - timely) * 5 / 8, timely, (1 - timely) * 3 / 8)
        close(sum(weights), 1, '权重和')
        return sum(v * w for v, w in zip(values, weights))
    s01 = keys['S01']['objective']
    for label, values in [('A', a), ('B', b)]:
        close(score(values, 0.2), s01['scores'][label], '当前分数')
        close(score(values, 0.18), s01['at_18'][label], '18%情景')
        close(score(values, 0.22), s01['at_22'][label], '22%情景')
    close(score(a, s01['threshold']), score(b, s01['threshold']), '翻转点')

    # S02穷举域内27组合，紧急优先。
    def route(severity, customer, completeness):
        if severity == '紧急':
            return '升级'
        if completeness != '完整':
            return '补资料'
        if severity == '未知' or customer == '未知':
            return '人工分诊'
        return '优先处理' if customer == 'VIP' else '普通处理'
    domain = product(('紧急', '普通', '未知'), ('VIP', '标准', '未知'),
                     ('完整', '缺失', '未知'))
    counts = Counter(route(*row) for row in domain)
    s02 = keys['S02']['objective']
    require(sum(counts.values()) == s02['combinations'], '覆盖计数错误')
    require(dict(counts) == s02['partition_counts'], '分区计数错误')
    examples = [('紧急', 'VIP', '缺失'), ('普通', 'VIP', '缺失'),
                ('未知', '标准', '完整'), ('普通', '未知', '完整'),
                ('普通', 'VIP', '完整'), ('普通', '标准', '完整')]
    require([route(*x) for x in examples] == s02['routes'], '示例路由错误')

    # G06枚举组合，而不是按单项贪心。
    projects = {'A': (6, 9), 'B': (5, 8), 'C': (5, 8)}
    feasible = []
    for n in range(4):
        for names in combinations(projects, n):
            cost = sum(projects[x][0] for x in names)
            value = sum(projects[x][1] for x in names)
            if cost <= 10:
                feasible.append((value, cost, names))
    value, cost, names = max(feasible)
    require({'winner': list(names), 'cost': cost, 'value': value}
            == keys['G06']['objective'], '组合答案错误')
    close(100 * 0.6 + 50 * 0.4, 80, '工作间X')
    close(50 * 0.6 + 90 * 0.4, 66, '工作间Y')
    close(90 * (4 / 9) - 40, 0, '工作间翻转点')

    print(json.dumps({
        'status': 'PASS', 'cases': len(cases), 'local_links': links,
        'enumerated_route_inputs': sum(counts.values()),
        'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(),
        'scope': '结构、题库答案、示例复算；未测模型行为或自动发现',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        sys.exit(1)

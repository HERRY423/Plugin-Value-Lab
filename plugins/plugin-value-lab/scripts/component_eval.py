"""Prepare pinned component/model-series plans and regrade original observations.

These developer utilities do not execute a host, call a model or activate tools.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json, load_suite, suite_digest, write_json
from value_lab import component_studies, saturation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    component = subs.add_parser('plan')
    component.add_argument('suite')
    component.add_argument('--components', required=True, help='JSON with prompt/tools/context payload SHA-256; context may be null')
    component.add_argument('--seed', type=int, default=20260928)
    series = subs.add_parser('series-plan')
    series.add_argument('suite')
    series.add_argument('--models', nargs='+', required=True, help='Pinned model identifiers in prospective chronological order')
    series.add_argument('--minimum-versions', type=int, default=3)
    series.add_argument('--minimum-repetitions', type=int, default=3)
    for sub in (component, series):
        sub.add_argument('--output', required=True, help='New directory for retained design and its ID')
    for name in ('analyze', 'saturation'):
        sub = subs.add_parser(name)
        sub.add_argument('design')
        sub.add_argument('--expected-id', required=True)
        sub.add_argument('--observations', required=True)
        sub.add_argument('--artifacts')
        sub.add_argument('--verifiers')
        sub.add_argument('--output', required=True, help='New directory for JSON and readable Markdown')
    args = parser.parse_args(argv)
    try:
        if args.action == 'plan':
            result = component_studies.plan(load_suite(args.suite), load_json(args.components), args.seed)
        elif args.action == 'series-plan':
            result = saturation.plan(load_suite(args.suite), args.models, args.minimum_versions, args.minimum_repetitions)
        else:
            module = component_studies if args.action == 'analyze' else saturation
            result = module.analyze(load_json(args.design), load_json(args.observations), args.expected_id,
                                    artifact_root=args.artifacts, verifier_root=args.verifiers)
        root = Path(args.output)
        root.mkdir(parents=True, exist_ok=False)
        is_plan = args.action in ('plan', 'series-plan')
        write_json(root / ('design.json' if is_plan else 'report.json'), result)
        if is_plan:
            write_json(root / 'commitment.json', {'design_sha256': suite_digest(result),
                       'retention': 'Retain separately before observations; hash does not prove registration time'})
        (root / 'README.md').write_text(render(result), encoding='utf-8')
        print(json.dumps({'output': str(root), 'design_sha256': suite_digest(result) if is_plan else args.expected_id,
                          'status': result.get('status', 'WRITTEN'), 'model_calls': 0}, ensure_ascii=True))
        return 2 if result.get('status') == 'INCOMPLETE' else 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


def render(result):
    # All user strings are JSON-escaped in fenced JSON blocks; no active HTML.
    def cell(value):
        import html
        return html.escape(str(value)).replace('|', '&#124;').replace('\n', ' ')
    lines = ['# 组件消融与模型饱和度', '', '结论限于提交的材料。配置声明不证明宿主执行、工具调用或因果收益。', '']
    if result['format'] == component_studies.FORMAT:
        lines += ['保留 design.json 与独立保存的 commitment.json；按 assignments 顺序收集原始运行。', '',
                  '| 实验臂 | 名称 |', '|---|---|']
        lines += [f"| {a['id']} | {a['label']} |" for a in result['arms']]
        lines += ['', f"计划运行数：{len(result['assignments'])}。尚未执行或激活任何组件。"]
    elif result['format'] == 'pvl-component-report-1':
        lines += [f"完整性：{result['status']}；观察 / 计划：{result['observed_runs']} / {result['planned_runs']}。", '',
                  '| 因子 | 成功率效应 | 质量效应 |', '|---|---:|---:|']
        lines += [f"| {' × '.join(r['factors'])} | {r['success']} | {r['quality']} |" for r in result['contrasts']]
        lines += ['', '主效应平均其他因子；二阶交互为差中之差的一半。未知结果不补零，无显著性或因果推断。']
    elif result['format'] == 'pvl-saturation-report-1':
        lines += [f"观察饱和度指数：{result['saturation_index']:.3f}。", '', '| 用例 | 状态 | 连续版本数 |', '|---|---|---:|']
        lines += [f"| {cell(r['case_id'])} | {r['status']} | {r['consecutive_latest_versions']} |" for r in result['cases']]
        lines += ['', '只触发复核：在新协议中增加未见过的困难案例，保留原用例和费用、耗时对比。']
    else:
        lines += ['已冻结模型版本序列；模型标识和先后顺序由研究者声明，未核验真实发布顺序。']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    raise SystemExit(main())

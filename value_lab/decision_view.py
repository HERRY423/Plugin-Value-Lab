"""Progressive disclosure of recomputed evidence; never a new decision rule."""
import base64
import hashlib
from html import escape
import json

LABELS = {'FEASIBLE': '满足原要求', 'FAILED': '未满足原要求', 'UNKNOWN': '待核实'}
METRICS = {'context_peak_fraction': '上下文峰值占比', 'cost_usd': '声明费用（美元）', 'duration_seconds': '记录耗时（秒）'}
RELATIONS = {'LEFT_DOMINATES': '左侧各项不更差，至少一项更低',
             'RIGHT_DOMINATES': '右侧各项不更差，至少一项更低',
             'TRADEOFF': '存在取舍', 'EQUAL': '在算术容差内持平', 'UNKNOWN': '数据不足'}


def brief(result):
    """Small host-readable evidence strip, derived only from the current report."""
    if 'design' in result:
        return {'format': 'pvl-evidence-brief-1', 'state': 'AWAITING_OBSERVATIONS',
                'title': '计划已准备，尚未采集运行记录',
                'summary': f"计划 {len(result['design']['assignments'])} 次运行；计划不代表已执行。",
                'evidence_label': '计划阶段', 'flags': [], 'counts': {'received': 0, 'planned': len(result['design']['assignments'])},
                'next_step': {'label': '查看分配与保留要求', 'target': 'records'},
                'source_pointers': ['/combination/design', '/combination/design_sha256'],
                'snapshot_only': True, 'selection_rule_changed': False}
    arms = result['arms']
    failed = [a['arm'] for a in arms if a['status'] == 'FAILED']
    unknown = [a['arm'] for a in arms if a['status'] == 'UNKNOWN']
    eligible = [a['arm'] for a in arms if a['status'] == 'FEASIBLE']
    burden = result.get('burden_view', {})
    gaps = [a['arm'] for a in burden.get('candidates', []) if a['eligibility'] == 'FEASIBLE' and a['missing_dimensions']]
    tradeoffs = [p for p in burden.get('comparisons', []) if p['relation'] == 'TRADEOFF']
    flags = []
    if result['issues']:
        flags.append({'kind': 'RECORD_CHECK', 'text': '记录完整性或比较条件需要核对', 'target': 'conditions'})
    for metric, code, label in (('cost_usd', 'MISSING_COST', '费用'), ('duration_seconds', 'MISSING_DURATION', '耗时')):
        affected = sorted({c['arm'] for c in result['cells'] if c[metric] is None})
        if affected:
            flags.append({'kind': code, 'text': label + '记录不完整：' + '、'.join(affected), 'target': 'gaps'})
    if result['observed_runs'] < result['planned_runs']:
        flags.append({'kind': 'MISSING_RUNS', 'text': f"缺少 {result['planned_runs'] - result['observed_runs']} 份运行记录", 'target': 'records'})
    if failed:
        flags.append({'kind': 'FAILED', 'text': '未满足原要求：' + '、'.join(failed), 'target': 'candidates'})
    if unknown:
        flags.append({'kind': 'UNKNOWN', 'text': '可行性待核实：' + '、'.join(unknown), 'target': 'candidates'})
    if gaps:
        flags.append({'kind': 'BURDEN_GAPS', 'text': '负担数据不全：' + '、'.join(gaps), 'target': 'gaps'})
    if result['issues']:
        state, title, action, target = 'CHECK_RECORDS', '先核对记录与比较条件', '查看阻断比较的问题', 'conditions'
    elif result['observed_runs'] < result['planned_runs']:
        state, title, action, target = 'MISSING_RUNS', '运行记录尚未收齐', '查看缺少的运行', 'records'
    elif unknown:
        state, title, action, target = 'UNRESOLVED_CANDIDATES', '部分候选仍待核实', '查看候选缺口', 'candidates'
    elif not eligible:
        state, title, action, target = 'NO_ELIGIBLE_CANDIDATE', '尚无候选满足原要求', '查看未满足的要求', 'candidates'
    elif gaps:
        state, title, action, target = 'INCOMPLETE_BURDEN', '先补齐负担数据', '查看缺少的负担数据', 'gaps'
    elif tradeoffs:
        state, title, action, target = 'REVIEW_TRADEOFF', '合格方案之间存在取舍', '展开具体取舍', 'comparisons'
    else:
        state, title, action, target = 'REVIEW_COMPARISON', '已有可供复核的比较', '查看比较依据', 'comparisons'
    highlights = []
    for pair in tradeoffs[:2]:
        for side, key in ((pair['left'], 'left_better_on'), (pair['right'], 'right_better_on')):
            labels = '、'.join(METRICS[m].split('（')[0] for m in METRICS if any(p['metric'] == m for p in pair[key]))
            highlights.append(f"{pair['left']} / {pair['right']}：{side} 在部分任务上的{labels}较低。")
    return {'format': 'pvl-evidence-brief-1', 'state': state, 'title': title,
            'summary': f"已收到 {result['observed_runs']}/{result['planned_runs']} 份运行记录；{len(eligible)}/{len(arms)} 个候选满足原要求。",
            'evidence_label': '仅合成演示 · 不构成采用证据' if result['evidence_status'] == 'SIMULATION_ONLY' else '范围内描述性观察 · 未认证宿主执行',
            'flags': flags, 'counts': {'received': result['observed_runs'], 'planned': result['planned_runs'],
                                     'eligible': len(eligible), 'failed': len(failed), 'unknown': len(unknown), 'tradeoff_pairs': len(tradeoffs)},
            'original_candidate_arms': list(result['recommendation']['candidate_arms']),
            'highlights': highlights,
            'next_step': {'label': action, 'target': target},
            'source_pointers': ['/combination/arms', '/combination/cells', '/combination/issues', '/combination/burden_view'],
            'snapshot_only': True, 'selection_rule_changed': False}


def markdown(result):
    from .burden_presentation import escape_markdown as _md
    card = brief(result)
    lines = ['## 此刻需要看的证据', '', f"**{_md(card['title'])}**", '', _md(card['summary']), '', _md(card['evidence_label']), '']
    lines.extend('- ' + _md(f['text']) for f in card['flags'])
    lines.extend('- ' + _md(h) for h in card.get('highlights', []))
    if 'original_candidate_arms' in card:
        lines += ['', '原规则候选：' + _md('、'.join(card['original_candidate_arms']) or '尚未确定') + '；保持原判断。']
    lines += ['', f"下一步：[ {_md(card['next_step']['label'])} ](EVIDENCE.html#{card['next_step']['target']})。",
              '这是本次报告快照；只展开证据，不触发采集、付费或修改选择规则。', '']
    return lines


def _table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join('<th scope="col">' + escape(str(h)) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def _value(v, metric=None):
    if v is None:
        return '未知'
    return f'{v * 100:.2f}%' if metric == 'context_peak_fraction' else f'{v:.6g}' if type(v) in (int, float) else str(v)


def _section(identifier, title, body):
    return f'<details id="{identifier}"><summary>{escape(title)}</summary><div class="detail-body">{body}</div></details>'


SCRIPT = """document.addEventListener('click', function(event) {
  const link = event.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.getElementById(link.getAttribute('href').slice(1));
  if (!target) return;
  event.preventDefault();
  let node = target;
  while (node) { if (node.tagName === 'DETAILS') node.open = true; node = node.parentElement; }
  const focus = target.tagName === 'DETAILS' ? target.querySelector('summary') : target;
  focus.focus(); target.scrollIntoView({block: 'start'});
  history.replaceState(null, '', link.getAttribute('href'));
});
if (location.hash) {
  const target = document.getElementById(location.hash.slice(1));
  if (target && target.tagName === 'DETAILS') target.open = true;
}
"""


def render(result, task):
    """Standalone offline HTML. All submitted content is escaped, never script."""
    card = brief(result)
    digest = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    csp = f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'"
    flags = ''.join(f'<a class="flag" href="#{f["target"]}">{escape(f["text"])}</a>' for f in card['flags'])
    sections = []
    if 'design' in result:
        sections.append(_section('records', '查看计划运行与分配',
            '<p>按冻结顺序独立采集各臂；保留失败及缺失。此页面不会执行计划。</p>' +
            _table(['任务', '重复', '候选', '顺序'], [[r['case_id'], r['repetition'], r['arm'], r['execution_index']] for r in result['design']['assignments']])))
    else:
        burden = result.get('burden_view', {})
        candidate_rows = []
        for a in result['arms']:
            candidate_rows.append([a['arm'], LABELS[a['status']], _value(a['metrics']['quality']['mean']),
                                   '；'.join(a['reasons']) or '已通过原有逐任务门槛'])
        sections.append(_section('candidates', '为什么这些候选合格，其他候选未合格？', _table(['候选', '原可行性', '质量', '原因'], candidate_rows)))
        comparisons = []
        for i, pair in enumerate(burden.get('comparisons', [])):
            evidence = _table(['任务', '负担指标', '左侧减右侧'], [[p['case_id'], METRICS[p['metric']],
                '未知' if p['left_minus_right'] is None else
                f"{p['left_minus_right'] * 100:+.2f} 个百分点" if p['metric'] == 'context_peak_fraction' else
                f"{p['left_minus_right']:+.6g} {'美元' if p['metric'] == 'cost_usd' else '秒'}"] for p in pair['deltas']])
            comparisons.append(_section(f'pair-{i}', f"{pair['left']} / {pair['right']} · {RELATIONS[pair['relation']]}",
                '<p>负数表示左侧负担较低，正数表示右侧负担较低。完整关系按全部任务判断。</p>' + evidence))
        sections.append(_section('comparisons', '哪些方案各有优势？查看逐任务差值', ''.join(comparisons) or '<p>当前没有可以进行两两负担比较的合格候选。</p>'))
        gap_rows = []
        for a in burden.get('candidates', []):
            for case in a['cases']:
                for metric, value in case['metrics'].items():
                    if value is None:
                        gap_rows.append([a['arm'], case['case_id'], METRICS[metric], '待核对原运行的同口径记录'])
                for rep, run in enumerate(case['context_runs'], 1):
                    if run['status'] != 'SUBMITTED_COMPLETE':
                        gap_rows.append([a['arm'], case['case_id'], f'上下文 · 重复 {rep}',
                                         '未提供' if run['status'] == 'MISSING' else f"采样不完整：{run['observed_samples']}/{run['expected_samples']}"])
        sections.append(_section('gaps', '缺少什么证据？', _table(['候选', '任务', '项目', '缺口'], gap_rows) if gap_rows else '<p>本轮没有记录到负担字段缺口。来源仍未独立认证。</p>'))
        sections.append(_section('conditions', '是否存在条件不一致？', '<ul>' + ''.join('<li>' + escape(issue) + '</li>' for issue in result['issues']) + '</ul>' if result['issues'] else '<p>当前分析未报告条件一致性阻断项；这不认证真实宿主隔离或执行。</p>'))
        sections.append(_section('records', '查看每次运行的评分记录（含失败与缺失）',
            _table(['任务', '重复', '候选', '记录状态', '质量', '费用', '耗时', '问题'],
                   [[r['case_id'], r['repetition'], r['arm'], r['status'], _value(r['quality']), _value(r['cost_usd']),
                     _value(r['duration_seconds']), '；'.join(r['issues'])] for r in result['cells']])))
    sources = {'design_sha256': result.get('design_sha256'), 'observations_sha256': result.get('observations_sha256'),
               'context_observations_sha256': result.get('burden_view', {}).get('context_observations_sha256')}
    sections.append(_section('sources', '查看证据来源、口径与完整分析',
        '<p>本页是报告快照，不是实时监控。上下文为提交的主代理请求峰值，费用为声明或估算，不代表结算；缺失不是零。</p>'
        '<p>下列摘要绑定材料内容，不证明来源真实性或独立验证。完整分析数据在旁边的文件中；原始宿主日志与输入材料仍需独立保留。</p>'
        '<p><a href="plan.json">打开完整分析数据</a> · <a href="PLAN.md">打开文字报告</a></p>' +
        '<pre>' + escape(json.dumps(sources, ensure_ascii=False, indent=2)) + '</pre>'))
    body = ''.join(sections)
    highlights = ''.join('<p>' + escape(h) + '</p>' for h in card.get('highlights', []))
    choice = ('<p>原规则候选：<strong>' + escape('、'.join(card['original_candidate_arms']) or '尚未确定') + '</strong>；保持原判断。</p>') if 'original_candidate_arms' in card else ''
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">
<title>需要时出现的证据 · Plugin Value Lab</title>
<style>
:root{{color-scheme:light;--ink:#182c3d;--muted:#526578;--line:#dce3e8;--paper:#f4f6f7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1080px;margin:36px auto;padding:0 24px 48px}}header{{margin-bottom:24px}}.eyebrow{{font-size:12px;letter-spacing:.16em;color:var(--muted)}}h1{{font-size:30px;line-height:1.35;margin:14px 0}}h2{{font-size:22px;margin:8px 0}}p{{overflow-wrap:anywhere}}.task{{color:var(--muted);max-width:80ch}}
.strip{{border:1px solid var(--line);border-left:5px solid #6b8098;background:white;padding:24px;border-radius:12px;margin:20px 0 28px}}
.evidence{{display:inline-block;font-size:13px;color:#624813;background:#fff2cf;padding:4px 10px;border-radius:6px}}.summary{{font-size:18px}}.flags{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}}a{{color:#184e76;text-underline-offset:3px}}.flag{{font-size:14px;background:#f4f0e9;border:1px solid #e5dace;border-radius:6px;padding:7px 10px;text-decoration:none}}
.primary{{display:inline-block;background:#243e55;color:white;border-radius:7px;padding:10px 16px;text-decoration:none}}.footnote{{font-size:13px;color:var(--muted)}}nav{{display:flex;flex-wrap:wrap;gap:16px;margin:24px 0}}
details{{background:white;border:1px solid var(--line);border-radius:9px;margin:12px 0;scroll-margin-top:20px}}summary{{padding:16px 20px;font-weight:600;cursor:pointer}}details[open]>summary{{border-bottom:1px solid var(--line)}}.detail-body{{padding:8px 20px 20px}}.detail-body details{{background:#fafbfc}}a:focus-visible,summary:focus-visible{{outline:3px solid #d68e2b;outline-offset:3px}}
.table-wrap{{overflow:auto}}table{{border-collapse:collapse;min-width:580px;width:100%;font-size:14px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--muted);font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:var(--paper);padding:16px}}footer{{color:var(--muted);font-size:13px;margin-top:28px}}
@media(max-width:600px){{main{{margin:20px auto;padding:0 14px 32px}}h1{{font-size:25px}}.strip{{padding:18px}}summary{{padding:14px}}.detail-body{{padding:6px 12px 16px}}}}
@media print{{details>*{{display:block!important}}details{{break-inside:avoid}}nav,.primary{{display:none}}}}
</style></head><body><main>
<header><div class="eyebrow">PLUGIN VALUE LAB / EVIDENCE</div><h1>当前判断与待核实项</h1><p class="task">{escape(str(task))}</p></header>
<section class="strip" aria-label="证据提示"><span class="evidence">{escape(card['evidence_label'])}</span>
<h2>{escape(card['title'])}</h2><p class="summary">{escape(card['summary'])}</p><div class="flags">{flags}</div>
{highlights}{choice}
<a class="primary" href="#{card['next_step']['target']}">{escape(card['next_step']['label'])}</a>
<p class="footnote">报告快照 · 点击仅展开证据 · 原选择规则保持不变</p></section>
<nav aria-label="证据导航"><a href="#records">运行记录</a><a href="#sources">来源与口径</a></nav>
{body}<footer>未被其他方案全面超过，不等于推荐采用。没有自动采集、付费或安装操作。</footer>
</main><script>{SCRIPT}</script></body></html>'''

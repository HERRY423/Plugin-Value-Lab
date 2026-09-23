"""Offline, injection-safe reports for paired plugin value evaluations.

The report is a view of collected evidence. It never upgrades missing values,
simulation, or local software evidence into measured benefit.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


_ARM_LABELS = {"with": "启用插件", "without": "未启用插件"}
_VERDICTS = {
    "PROMISING_LOCAL_SIGNAL": "检测到本地增益信号",
    "NO_DEMONSTRATED_GAIN": "尚未证明存在增益",
    "REGRESSION_DETECTED": "检测到回退",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "SIMULATION_ONLY": "仅为模拟演示",
    "positive_local_signal": "检测到本地增益信号",
    "positive_signal": "检测到增益信号",
    "no_gain": "未检测到增益",
    "no_clear_gain": "尚无明确增益",
    "regression": "检测到回退",
    "insufficient_evidence": "证据不足",
    "insufficient": "证据不足",
    "simulation_only": "仅为模拟演示",
    "synthetic_only": "仅为模拟演示",
    "synthetic_demo": "仅为模拟演示",
}
_LABELS = {
    "method": "计算方法", "unit": "分析单位", "clusters": "任务簇数",
    "n_clusters": "任务簇数", "confidence_level": "区间覆盖水平",
    "quality_delta_ci": "质量差区间", "quality_delta_ci95": "质量差 95% 区间",
    "quality_delta_ci_95": "质量差 95% 区间", "lower": "下界", "upper": "上界",
    "limitations": "限制", "reason": "原因", "status": "状态",
    "excluded_runs": "排除的运行", "excluded_pairs": "排除的配对",
    "unpaired_runs": "未配对的运行", "suite_sha256": "方案 SHA-256",
    "lock_verified": "方案锁校验", "independent_preregistration": "独立预注册",
}


def _text(value: Any) -> str:
    if value is None:
        return "未知"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def _escape(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _score(value: Any) -> str:
    number = _number(value)
    return "未知" if number is None else f"{number * 100:.1f}%"


def _delta(value: Any) -> str:
    number = _number(value)
    return "未知" if number is None else f"{number * 100:+.1f} 个百分点"


def _money(value: Any, *, signed: bool = False) -> str:
    number = _number(value)
    if number is None:
        return "未知"
    return f"{number:+.4f} USD" if signed else f"{number:.4f} USD"


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _markdown(value: Any) -> str:
    """Escape HTML and Markdown syntax before placing evidence in a table."""
    text = html.escape(_text(value), quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "|", "#", "~"):
        text = text.replace(character, "\\" + character)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _evidence_label(report: dict[str, Any]) -> str:
    evidence = report.get("evidence_type")
    return {"synthetic": "合成演示", "local": "本地运行证据", "external": "外部运行证据", "unverified_native": "原生结果诊断 · 未核验"}.get(evidence, _text(evidence))


def _verdict(report: dict[str, Any]) -> str:
    raw = report.get("verdict")
    return _VERDICTS.get(raw, _text(raw)) if isinstance(raw, str) else _text(raw)


def _bullet_list(value: Any, *, empty: str) -> str:
    items = _items(value)
    if not items:
        return f'<p class="muted">{html.escape(empty)}</p>'
    return '<ul class="notes">' + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>"


def _fact_block(value: Any, *, empty: str) -> str:
    if value is None or value == {} or value == []:
        return f'<p class="muted">{html.escape(empty)}</p>'
    if isinstance(value, dict):
        return '<dl class="facts">' + "".join(
            f"<dt>{_escape(_LABELS.get(str(key), str(key)))}</dt><dd>{_escape(item)}</dd>"
            for key, item in value.items()
        ) + "</dl>"
    return _bullet_list(value, empty=empty)


def _case_state(case: dict[str, Any]) -> str:
    runs = [_mapping(run) for run in _items(case.get("runs"))]
    blocked = bool(case.get("issues") or case.get("blockers")) or any(
        bool(run.get("issues")) or run.get("status") != "completed" for run in runs
    )
    if blocked or _number(case.get("with_score")) is None or _number(case.get("without_score")) is None:
        return "blocked"
    difference = _number(case.get("delta"))
    return "regression" if difference is not None and difference < 0 else "other"


def _run_details(case: dict[str, Any]) -> str:
    pieces = []
    for run_value in _items(case.get("runs")):
        run = _mapping(run_value)
        grades = run.get("grades")
        extra = {key: value for key, value in run.items() if key not in {
            "arm", "repetition", "status", "score", "cost_usd", "grades", "issues"
        }}
        pieces.append(
            '<article class="run">'
            f'<div class="run-title"><strong>{_escape(_ARM_LABELS.get(run.get("arm"), run.get("arm")))}</strong>'
            f'<span>重复 {_escape(run.get("repetition"))} · {_escape(run.get("status"))}</span></div>'
            f'<p>质量 {_escape(_score(run.get("score")))} · 成本 {_escape(_money(run.get("cost_usd")))}</p>'
            + _bullet_list(run.get("issues"), empty="未记录运行问题。")
            + (f'<pre>{_escape(grades)}</pre>' if grades is not None else '<p class="muted">未提供评分明细。</p>')
            + (f'<details><summary>其他运行字段</summary><pre>{_escape(extra)}</pre></details>' if extra else "")
            + "</article>"
        )
    return "".join(pieces) or '<p class="muted">未提供运行记录。</p>'


def _case_html(case: dict[str, Any], index: int) -> str:
    state = _case_state(case)
    state_label = {"blocked": "缺失 / 有问题", "regression": "存在回退", "other": "可比较"}[state]
    score_delta = _number(case.get("delta"))
    tone = "negative" if score_delta is not None and score_delta < 0 else "positive" if score_delta is not None and score_delta > 0 else ""
    case_extra = {key: value for key, value in case.items() if key not in {
        "id", "kind", "cluster", "with_score", "without_score", "delta", "runs"
    }}
    return (
        f'<tbody class="case-group" data-state="{state}">'
        '<tr class="case-row">'
        f'<th scope="row">{_escape(case.get("id"))}<span class="case-kind">{_escape(case.get("kind"))}</span></th>'
        f'<td>{_escape(case.get("cluster"))}</td>'
        f'<td>{_escape(_score(case.get("without_score")))}</td>'
        f'<td>{_escape(_score(case.get("with_score")))}</td>'
        f'<td class="{tone}">{_escape(_delta(case.get("delta")))}</td>'
        f'<td><span class="badge {state}">{state_label}</span></td></tr>'
        f'<tr class="detail-row"><td colspan="6"><details id="case-{index}"><summary>查看运行与评分证据</summary>'
        f'<div class="runs">{_run_details(case)}</div>'
        + (f'<pre>{_escape(case_extra)}</pre>' if case_extra else "")
        + '</details></td></tr></tbody>'
    )


def _bar(label: str, value: Any, arm: str) -> str:
    number = _number(value)
    width = 0 if number is None else max(0, min(100, number * 100))
    fill = f'<span class="bar-fill {arm}" style="width:{width:.4f}%"></span>' if number is not None else ""
    unknown = ' unknown' if number is None else ""
    return (
        f'<div class="bar-row"><span>{label}</span><strong>{_escape(_score(value))}</strong>'
        f'<div class="bar-track{unknown}" role="img" aria-label="{label}：{_escape(_score(value))}">{fill}</div></div>'
    )


_STYLE = """
:root{--ink:#15283a;--muted:#607181;--line:#dce3e7;--paper:#fff;--bg:#f4f6f5;--teal:#087f80;--teal-light:#e6f3ef;--orange:#a7511d;--orange-light:#fff0df;--red:#a33437;--navy:#314e67}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:44px 30px 64px}header{padding-bottom:28px}.eyebrow{letter-spacing:.15em;text-transform:uppercase;font-weight:700;font-size:12px;color:var(--teal)}h1{font-size:34px;letter-spacing:-.035em;line-height:1.3;margin:8px 0 10px}h2{font-size:19px;margin:0 0 16px}h3{font-size:16px;margin:0 0 8px}p{margin:8px 0}.muted,.subtitle{color:var(--muted)}.metadata{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.pill,.badge{display:inline-block;border-radius:999px;padding:3px 11px;font-size:12px;background:#edf1f3;color:var(--navy)}.banner{padding:17px 21px;border:1px solid #e9c899;border-left:4px solid var(--orange);background:var(--orange-light);border-radius:10px;margin-bottom:24px}.banner strong{display:block}.verdict{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:22px;padding:24px 26px;background:var(--ink);color:white;border-radius:13px}.verdict h2{margin:3px 0 6px;font-size:25px}.verdict p{color:#c4d3de;margin:0}.verdict .eyebrow{color:#85d7c7}.verdict-mark{width:56px;height:56px;border:1px solid #496174;border-radius:50%;display:grid;place-items:center;font-size:24px;flex-shrink:0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:22px}.metric,.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px}.metric{padding:19px 20px}.metric-label{color:var(--muted);font-size:13px}.metric-value{font-size:25px;line-height:1.3;font-weight:750;margin:10px 0;overflow-wrap:anywhere}.metric-note{font-size:12px;color:var(--muted)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-bottom:22px}.panel{padding:25px}.full{margin-bottom:22px}.bar-row{display:grid;grid-template-columns:1fr auto;gap:8px;margin:20px 0}.bar-track{grid-column:1/-1;height:12px;border-radius:4px;background:#eef2f3;overflow:hidden}.bar-fill{display:block;height:100%;border-radius:4px}.bar-fill.with{background:var(--teal)}.bar-fill.without{background:#8294a6}.bar-track.unknown{background:repeating-linear-gradient(45deg,#e9edef,#e9edef 5px,#f5f7f8 5px,#f5f7f8 10px)}.cost-table{width:100%;border-collapse:collapse;margin:15px 0}.cost-table td{padding:8px 0;border-bottom:1px solid #eef1f3}.cost-table td:last-child{text-align:right;font-variant-numeric:tabular-nums}.notes{margin:0;padding-left:20px}.notes li{margin:7px 0;overflow-wrap:anywhere;white-space:pre-wrap}.positive{color:var(--teal);font-weight:650}.negative{color:var(--red);font-weight:650}.facts{margin:0;display:grid;grid-template-columns:minmax(110px,1fr) 2fr;gap:9px 18px;font-size:13px}.facts dt{color:var(--muted)}.facts dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.section-top{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}.filters{display:none;gap:6px;flex-wrap:wrap;margin-bottom:16px}.filters.enabled{display:flex}.filters button{background:white;border:1px solid var(--line);border-radius:7px;padding:7px 12px;color:var(--muted);cursor:pointer;font:inherit;font-size:12px}.filters button[aria-pressed=true]{color:white;background:var(--navy);border-color:var(--navy)}button:focus-visible,summary:focus-visible{outline:3px solid #57bcbc;outline-offset:3px}.table-wrap{overflow-x:auto}.cases-table{width:100%;min-width:680px;border-collapse:collapse;text-align:left;font-size:13px}.cases-table thead{color:var(--muted);font-size:12px}.cases-table th,.cases-table td{padding:14px 10px;vertical-align:top}.cases-table thead th{border-bottom:1px solid var(--line)}.case-row th{font-weight:650;max-width:230px;overflow-wrap:anywhere}.case-kind{display:block;font-weight:400;font-size:11px;color:var(--muted);margin-top:4px}.detail-row td{padding:0 10px 14px;border-bottom:1px solid var(--line)}summary{cursor:pointer;color:var(--navy);font-size:13px;display:list-item}details[open]>summary{margin-bottom:12px}.runs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.run{background:#f7f9f9;border:1px solid #e4eaed;border-radius:8px;padding:15px}.run-title{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.run-title span{color:var(--muted);font-size:11px}.run p{font-size:12px}.run .notes{font-size:12px}.badge.blocked{background:var(--orange-light);color:var(--orange)}.badge.regression{background:#fae7e7;color:var(--red)}.badge.other{background:var(--teal-light);color:var(--teal)}pre{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;max-height:360px;overflow:auto;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;background:#f4f7f7;padding:14px;border-radius:7px;margin:12px 0 0}.empty{padding:28px;color:var(--muted);text-align:center}.small{font-size:12px}.footer{font-size:12px;color:var(--muted);display:flex;gap:20px;justify-content:space-between;padding:8px 1px}.footer a{color:var(--navy)}[hidden]{display:none!important}@media(max-width:800px){main{padding:26px 18px 40px}.metrics{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}h1{font-size:28px}.panel{padding:20px}.runs{grid-template-columns:1fr}.footer{flex-direction:column;gap:4px}}@media(max-width:440px){.metric{padding:15px}.metric-value{font-size:21px}.verdict{padding:20px}.verdict-mark{display:none}}@media print{body{background:white}main{padding:0;max-width:none}.filters,.footer a{display:none!important}.panel,.metric,.verdict{break-inside:avoid}.verdict{color:var(--ink);background:#eef3f4}.verdict p,.verdict .eyebrow{color:var(--muted)}details{break-inside:avoid}.case-group[hidden]{display:table-row-group!important}}
"""

_SCRIPT = """
(function () {
  'use strict';
  var filters = document.querySelector('.filters');
  var groups = Array.from(document.querySelectorAll('.case-group'));
  var count = document.getElementById('visible-count');
  var empty = document.getElementById('filter-empty');
  if (!filters) return;
  filters.classList.add('enabled');
  filters.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-filter]');
    if (!button || !filters.contains(button)) return;
    var filter = button.dataset.filter;
    filters.querySelectorAll('button').forEach(function (item) {
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
    var shown = 0;
    groups.forEach(function (group) {
      group.hidden = filter !== 'all' && group.dataset.state !== filter;
      if (!group.hidden) shown += 1;
    });
    count.textContent = String(shown);
    empty.hidden = shown !== 0;
  });
}());
"""


def _cost_detail_html(report):
    costs = report.get("cost_analysis")
    if not costs:
        return ""
    rows = []
    for label, key in (("已知小计", "known_subtotal_usd"), ("类别完整的总成本", "total_usd"), ("每次成功成本（包含失败开销）", "cost_per_success_usd")):
        rows.append("<tr><td>" + label + "</td>" + "".join("<td>" + _escape(_money(costs["arms"][arm][key])) + "</td>" for arm in ("without", "with")) + "</tr>")
    return '<section class="panel full"><h2>完整成本分析</h2><table class="cost-table"><thead><tr><th>指标</th><th>未启用插件</th><th>启用插件</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table><p>覆盖声明完整：' + _escape(costs["complete_category_coverage"]) + '。未知项不填零；原生整批估计不重复加入成本。</p><details><summary>分类明细、计数和人工时薪敏感性</summary><pre>' + _escape(costs) + '</pre></details></section>'


def _render_html(report: dict[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    plugin = _mapping(report.get("plugin"))
    cases = [_mapping(case) for case in _items(report.get("cases"))]
    synthetic = report.get("evidence_type") == "synthetic"
    native = report.get("evidence_type") == "unverified_native"
    banner = (
        '<aside class="banner"><strong>合成演示 · 不代表真实收益</strong>'
        '本页使用合成运行展示评估流程。分数、成本与差异均不能用于宣称插件已被验证有效。</aside>'
        if synthetic else ""
    )
    if native:
        banner = (
            '<aside class="banner"><strong>原生结果诊断 · 不能证明插件增益</strong>'
            '本页展示 Claude 原生汇总值。Value Lab 未重新计算或核验其评分语义；'
            '缺少完整会话、运行条件、插件加载与判据映射证据，不能作为通过评估的收益结果。</aside>'
        )
    quality_label = "原生 meanDelta · 汇总差值" if native else "质量差 · 启用 − 未启用"
    quality_note = "原生汇总，仅供诊断；未重算 Value Lab 结果质量。" if native else "只汇总结果评分；过程检查单独保留。"
    quality_heading = "原生评分诊断" if native else "结果质量"
    score_note = "overallScore、score 和 delta 按原生文件展示，其构成未经过 Value Lab 判据映射与重算。" if native else "评分来自方案中定义的结果判据。分数本身不证明外部有效性。"
    without_label = "原生基线（未提供）" if native else "未启用插件"
    with_label = "原生 overallScore" if native else "启用插件"
    native_cost_row = f'<tr><td>原生总估算费用</td><td>{_escape(_money(summary.get("native_total_estimated_cost_usd")))}</td></tr>' if native else ""
    cost_unit_note = _escape(summary.get("cost_unit")) if summary.get("cost_unit") else "未提供成本汇总口径。"
    native_cost_note = "原生总估算费用覆盖文件中的运行与裁判，不能拆作单臂费用。" if native else ""
    table_without = "原生基线" if native else "未启用"
    table_with = "原生 score" if native else "启用"
    table_delta = "原生 delta" if native else "质量差"
    cost_delta = _number(summary.get("cost_delta_usd"))
    cost_tone = "positive" if cost_delta is not None and cost_delta < 0 else "negative" if cost_delta is not None and cost_delta > 0 else ""
    quality_delta = _number(summary.get("quality_delta"))
    quality_tone = "positive" if quality_delta is not None and quality_delta > 0 else "negative" if quality_delta is not None and quality_delta < 0 else ""
    exclusions = report.get("exclusions", summary.get("exclusions"))
    case_rows = "".join(_case_html(case, index) for index, case in enumerate(cases))
    raw_json = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light"><title>插件价值评估 · {_escape(report.get("study_id"))}</title><style>{_STYLE}</style></head>
<body><main>
<header><div class="eyebrow">Plugin Value Lab / 插件价值实验室</div><h1>插件带来了多少实际增益？</h1>
<p class="subtitle">在相同条件下比较启用与未启用插件的任务表现，并保留缺失、失败与不确定性。</p>
<div class="metadata"><span class="pill">{_escape(plugin.get("name"))} · {_escape(plugin.get("version"))}</span><span class="pill">{_escape(_evidence_label(report))}</span><span class="pill">研究 {_escape(report.get("study_id"))}</span></div></header>
{banner}
<section class="verdict" aria-labelledby="verdict-title"><div><div class="eyebrow">当前结论</div><h2 id="verdict-title">{_escape(_verdict(report))}</h2><p>质量、完整性和成本分别呈现；单个总分不能替代完整证据。</p></div><div class="verdict-mark" aria-hidden="true">↔</div></section>
<section class="metrics" aria-label="评估摘要">
<article class="metric"><div class="metric-label">{quality_label}</div><div class="metric-value {quality_tone}">{_escape(_delta(summary.get("quality_delta")))}</div><div class="metric-note">{quality_note}</div></article>
<article class="metric"><div class="metric-label">完整配对</div><div class="metric-value">{_escape(summary.get("complete_pairs"))}</div><div class="metric-note">观察运行 {_escape(summary.get("observed_runs"))} / 计划运行 {_escape(summary.get("expected_runs"))}</div></article>
<article class="metric"><div class="metric-label">任务簇</div><div class="metric-value">{_escape(summary.get("clusters"))}</div><div class="metric-note">同一案例的重复运行不等于独立样本。</div></article>
<article class="metric"><div class="metric-label">成本差 · 启用 − 未启用</div><div class="metric-value {cost_tone}">{_escape(_money(summary.get("cost_delta_usd"), signed=True))}</div><div class="metric-note">负值表示节省；缺失成本保持未知。</div></article>
</section>
<div class="grid"><section class="panel"><h2>{quality_heading}</h2>{_bar(without_label, summary.get("without_score"), "without")}{_bar(with_label, summary.get("with_score"), "with")}<p class="muted small">{score_note}</p></section>
<section class="panel"><h2>成本与投入</h2><table class="cost-table"><tbody><tr><td>未启用插件</td><td>{_escape(_money(summary.get("without_cost_usd")))}</td></tr><tr><td>启用插件</td><td>{_escape(_money(summary.get("with_cost_usd")))}</td></tr><tr><td>差值</td><td class="{cost_tone}">{_escape(_money(summary.get("cost_delta_usd"), signed=True))}</td></tr>{native_cost_row}</tbody></table><p class="muted small">{cost_unit_note}</p><p class="muted small">金额以评估输入和成本折算规则为准。模型、工具或人工记录缺失时，不把缺失值记为零。{native_cost_note}估算金额不等于已结算费用。</p></section></div>
<div class="grid"><section class="panel"><h2>阻止结论成立的条件</h2>{_bullet_list(report.get("blockers"), empty="未记录阻断项；仍需结合完整性和结论边界判断。")}</section>
<section class="panel"><h2>需要关注</h2>{_bullet_list(report.get("warnings"), empty="未记录额外提示。")}</section></div>
<section class="panel full"><div class="section-top"><h2>逐案例证据</h2><span class="muted small">显示 <span id="visible-count" aria-live="polite">{len(cases)}</span> / {len(cases)} 个案例</span></div>
<div class="filters" role="group" aria-label="筛选案例"><button type="button" data-filter="all" aria-pressed="true">全部案例</button><button type="button" data-filter="regression" aria-pressed="false">存在回退</button><button type="button" data-filter="blocked" aria-pressed="false">缺失 / 有问题</button></div>
<div class="table-wrap"><table class="cases-table"><thead><tr><th scope="col">案例 / 类型</th><th scope="col">任务簇</th><th scope="col">{table_without}</th><th scope="col">{table_with}</th><th scope="col">{table_delta}</th><th scope="col">记录状态</th></tr></thead>{case_rows}</table></div><p class="empty" id="filter-empty"{'' if not cases else ' hidden'}>当前筛选下没有案例。</p><p class="muted small">“存在回退”表示案例差值为负，是否触及停止阈值由评估方案决定。失败和缺失记录始终保留。</p></section>
<div class="grid"><section class="panel"><h2>不确定性</h2>{_fact_block(report.get("uncertainty"), empty="未提供区间或不确定性估计。")}</section><section class="panel"><h2>排除与未纳入项</h2>{_fact_block(exclusions, empty="未提供单独的排除汇总；请同时检查阻断项和逐次运行记录。")}</section></div>
<section class="panel full"><h2>结论能支持到哪里</h2>{_fact_block(report.get("claim_limits"), empty="未提供特定结论范围。仅凭本报告，不能认定外部收益或科学有效性。")}<p class="muted small">方案锁用于一致性核验，不构成独立见证的预注册。来源标为外部也不自动表示独立评审、因果归因或科学认证。</p></section>
<section class="panel full"><details><summary>来源与评估记录</summary><h3>来源信息</h3>{_fact_block(report.get("provenance"), empty="未提供来源信息。")}<h3 style="margin-top:22px">完整评估记录</h3><p class="muted small">保留全部字段，以便复核报告摘要和新增评估字段。</p><pre>{html.escape(raw_json, quote=True)}</pre></details></section>
{_cost_detail_html(report)}
<footer class="footer"><span>离线报告 · 无外部脚本、字体或网络请求</span><span><a href="report.json">完整 JSON</a> · <a href="report.md">Markdown 报告</a></span></footer>
</main><script>{_SCRIPT}</script></body></html>'''


def _render_markdown(report: dict[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    plugin = _mapping(report.get("plugin"))
    native = report.get("evidence_type") == "unverified_native"
    lines = ["# 插件价值评估", "", f"**{_markdown(plugin.get('name'))} · {_markdown(plugin.get('version'))}**", "",
             f"研究：{_markdown(report.get('study_id'))}  ", f"证据类型：{_markdown(_evidence_label(report))}  ",
             f"当前结论：**{_markdown(_verdict(report))}**", ""]
    if report.get("evidence_type") == "synthetic":
        lines += ["> **合成演示 · 不代表真实收益。** 分数、成本与差异只展示流程，不能宣称插件已被验证有效。", ""]
    if native:
        lines += ["> **原生结果诊断 · 不能证明插件增益。** 汇总值来自 Claude 原生文件；Value Lab 未重新计算或核验其评分语义。缺少完整会话、运行条件、插件加载与判据映射证据。", ""]
    quality_row = "原生 overallScore / meanDelta" if native else "结果质量"
    score_note = "原生 overallScore、score 和 delta 仅供诊断，不是 Value Lab 重算的结果质量。" if native else "只有结果判据贡献质量评分。"
    lines += ["## 质量与成本", "", "| 指标 | 未启用插件 | 启用插件 | 差值（启用 − 未启用） |", "| --- | ---: | ---: | ---: |",
              f"| {quality_row} | {_score(summary.get('without_score'))} | {_score(summary.get('with_score'))} | {_delta(summary.get('quality_delta'))} |",
              f"| 成本 | {_money(summary.get('without_cost_usd'))} | {_money(summary.get('with_cost_usd'))} | {_money(summary.get('cost_delta_usd'), signed=True)} |", "",
              "成本缺失保持未知；估算金额不等于已结算费用。" + score_note, "",
              "## 样本完整性", "",
              f"- 计划运行：{_markdown(summary.get('expected_runs'))}", f"- 观察运行：{_markdown(summary.get('observed_runs'))}",
              f"- 完整配对：{_markdown(summary.get('complete_pairs'))}", f"- 任务簇：{_markdown(summary.get('clusters'))}", "",
              "同一案例的重复运行不等于独立样本。", ""]
    if native:
        lines += [f"原生总估算费用：{_money(summary.get('native_total_estimated_cost_usd'))}。覆盖文件中的运行与裁判，不能拆作单臂费用。", ""]
    if summary.get("cost_unit"):
        lines += ["成本汇总口径：" + _markdown(summary["cost_unit"]), ""]
    for title, value, empty in [
        ("阻断项", report.get("blockers"), "未记录阻断项；仍需结合完整性与结论边界判断。"),
        ("需要关注", report.get("warnings"), "未记录额外提示。"),
        ("不确定性", report.get("uncertainty"), "未提供区间或不确定性估计。"),
        ("排除与未纳入项", report.get("exclusions", summary.get("exclusions")), "未提供单独的排除汇总。"),
        ("结论边界", report.get("claim_limits"), "未提供特定结论范围；不能据此认定外部收益或科学有效性。"),
    ]:
        lines += [f"## {title}", ""]
        if isinstance(value, dict) and value:
            lines += [f"- {_markdown(_LABELS.get(str(key), str(key)))}：{_markdown(item)}" for key, item in value.items()]
        else:
            lines += [f"- {_markdown(item)}" for item in _items(value)] or [empty]
        lines += [""]
    case_header = "| 案例 | 类型 | 任务簇 | 原生基线 | 原生 score | 原生 delta |" if native else "| 案例 | 类型 | 任务簇 | 未启用 | 启用 | 质量差 |"
    lines += ["## 逐案例证据", "", case_header, "| --- | --- | --- | ---: | ---: | ---: |"]
    for item in _items(report.get("cases")):
        case = _mapping(item)
        lines.append(f"| {_markdown(case.get('id'))} | {_markdown(case.get('kind'))} | {_markdown(case.get('cluster'))} | {_score(case.get('without_score'))} | {_score(case.get('with_score'))} | {_delta(case.get('delta'))} |")
    if not _items(report.get("cases")):
        lines += ["", "未提供案例记录。"]
    for item in _items(report.get("cases")):
        case = _mapping(item)
        lines += ["", f"### {_markdown(case.get('id'))}", ""]
        for run_item in _items(case.get("runs")):
            run = _mapping(run_item)
            lines += [f"- {_markdown(_ARM_LABELS.get(run.get('arm'), run.get('arm')))} / 重复 {_markdown(run.get('repetition'))} / {_markdown(run.get('status'))}：质量 {_score(run.get('score'))}，成本 {_money(run.get('cost_usd'))}。"]
            for issue in _items(run.get("issues")):
                lines += [f"  - 问题：{_markdown(issue)}"]
            if run.get("grades") is not None:
                lines += [f"  - 评分明细：{_markdown(run['grades'])}"]
    if report.get("cost_analysis"):
        costs = report["cost_analysis"]
        lines += ["", "## 完整成本分析", "", "| 指标 | 未启用插件 | 启用插件 |", "| --- | ---: | ---: |"]
        for label, key in (("已知小计", "known_subtotal_usd"), ("类别完整的总成本", "total_usd"), ("每次成功成本（含失败开销）", "cost_per_success_usd")):
            lines.append(f"| {label} | {_money(costs['arms']['without'][key])} | {_money(costs['arms']['with'][key])} |")
        lines += ["", "费用估计与已结算金额不能互换；分类覆盖和敏感性明细见 report.json。", ""]
    lines += ["", "## 来源", ""]
    provenance = report.get("provenance")
    if isinstance(provenance, dict) and provenance:
        lines += [f"- {_markdown(_LABELS.get(str(key), str(key)))}：{_markdown(value)}" for key, value in provenance.items()]
    else:
        lines += [_markdown(provenance) if provenance is not None else "未提供来源信息。"]
    lines += ["", "方案锁用于一致性核验，不构成独立见证的预注册。外部来源不自动表示独立评审、因果归因或科学认证。", "",
              "全部字段（包括扩展字段）保留在同目录的 `report.json`；交互式逐案例视图见 `report.html`。", ""]
    return "\n".join(lines)


def write_reports(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write JSON, Markdown, and an offline HTML report; return their paths.

    Unknown extension fields are retained in JSON and the HTML evidence panel.
    JSON is serialized first, so non-JSON values cannot leave a partial report.
    """
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    markdown_text = _render_markdown(report)
    html_text = _render_html(report)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"json": json_text, "md": markdown_text, "html": html_text}
    paths = {}
    for extension, content in artifacts.items():
        path = output / f"report.{extension}"
        path.write_text(content, encoding="utf-8")
        paths[extension] = str(path)
    return paths

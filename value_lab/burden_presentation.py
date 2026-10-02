"""Read-only formatting of analyzed burden reports."""


def escape_markdown(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")



def markdown(view):
    """Human-readable view with explicit unknowns and pairwise tradeoffs."""
    labels = {'context_peak_fraction': '上下文峰值占比', 'cost_usd': '费用', 'duration_seconds': '耗时'}
    relation = {'LEFT_DOMINATES': '左侧各项不更差，至少一项更低', 'RIGHT_DOMINATES': '右侧各项不更差，至少一项更低',
                'TRADEOFF': '存在取舍', 'EQUAL': '在算术容差内持平', 'UNKNOWN': '数据不足'}
    def value(v, percent=False):
        return '未知' if v is None else f'{v * 100:.2f}%' if percent else f'{v:.6g}'
    def label(v):
        return str(v).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    lines = ['', '## 独立负担视图', '',
             '仅比较满足原有逐任务要求的候选；不改变最小插件选择规则，不计算综合分。',
             f"证据：{view['evidence_status']}；上下文来源：{view['context_evidence']}。",
             '上下文为每次运行的主代理请求输入占用峰值，再按重复与任务平均；不是累计 token 或结算费用。', '',
             '候选 | 原可行性 | 平均上下文峰值占比 | 完整声明费用（美元） | 记录耗时（秒）',
             '--- | --- | --- | --- | ---']
    for row in view['candidates']:
        m = row['metrics']
        lines.append(f"{row['arm']} | {row['eligibility']} | {value(m['context_peak_fraction'], True)} | {value(m['cost_usd'])} | {value(m['duration_seconds'])}")
    lines += ['', '两两关系按每个任务的三项负担判断，不能由总体均值掩盖单项退步。']
    for pair in view['comparisons']:
        lines.append(f"- {pair['left']} / {pair['right']}：{relation[pair['relation']]}。")
        for side, field in ((pair['left'], 'left_better_on'), (pair['right'], 'right_better_on')):
            points = pair[field]
            if points:
                details = '；'.join(f"{label(p['case_id'])} 的{labels[p['metric']]}低 " +
                                    (f"{abs(p['left_minus_right']) * 100:.2f} 个百分点" if p['metric'] == 'context_peak_fraction'
                                     else value(abs(p['left_minus_right'])) + (' 美元' if p['metric'] == 'cost_usd' else ' 秒'))
                                    for p in points)
                lines.append(f'  - {side}：{details}。')
        if pair['missing']:
            lines.append('  - 缺失：' + '、'.join(sorted({labels[p['metric']] for p in pair['missing']})) + '。')
    frontier = view['frontier']
    lines += ['', f"完整观察中未被支配：{', '.join(frontier['fully_observed_nondominated']) or '暂无'}；范围状态：{frontier['status']}。",
              f"仍未解决的候选：{', '.join(frontier['unresolved_arms']) or '无'}。",
              '未被支配不等于推荐采用。上下文记录与覆盖范围由提交方声明，未认证宿主真实性；合成数据只演示逻辑。']
    return lines

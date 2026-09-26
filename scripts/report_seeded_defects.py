"""Verify an immutable seeded campaign and publish an auditable local report.

Do not tune a detector here. This adds an explicitly labelled diagnostic-union
view of hypotheses that the original run already produced, and deduplicates
negative artifact/check pairs. Original author-entry metrics remain unchanged.
"""
from collections import Counter
from copy import deepcopy
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from value_lab.artifacts import confined, sha
from value_lab.core import load_json, suite_digest, write_json
from value_lab.native_evidence import verify_native_evidence
from validate_seeded_defects import FAMILIES, classify


def metrics(defects, controls):
    """Mutation denominator stays planned; repeated negative observations do not."""
    by_id={r['id']:r for r in controls}
    unique={}
    for row in controls:
        key=row['control_identity']
        if key in unique and unique[key]['alert'] != row['alert']:
            raise ValueError('Same control/check pair has inconsistent verdicts')
        unique[key]=row
    negatives=list(unique.values())
    counts=Counter([classify(r['alert'],True) for r in defects]+[classify(r['alert'],False) for r in negatives])
    ud=sum(r['alert'] is None for r in defects); uc=sum(r['alert'] is None for r in negatives)
    nd,nc=len(defects),len(negatives)
    paired=sum(r['alert'] is True and r['id'] in by_id and by_id[r['id']]['alert'] is False for r in defects)
    return {**{k:counts[k] for k in ('TP','FN','FP','TN','UNKNOWN')},'defects':nd,
        'paired_controls':len(controls),'distinct_controls':nc,'paired_specific_detections':paired,
        'detection_rate':counts['TP']/nd if nd and not ud else None,
        'false_positive_rate':counts['FP']/nc if nc and not uc else None,
        'detection_bounds':[counts['TP']/nd,(counts['TP']+ud)/nd] if nd else [None,None],
        'false_positive_bounds':[counts['FP']/nc,(counts['FP']+uc)/nc] if nc else [None,None]}


def observed_rows(root, results):
    output=[]
    for original in results['runs']:
        row=deepcopy(original)
        home=root/'cases'/row['id']/row['phase']
        index=0 if row['arm']=='with' else 1
        recipe=load_json(root/'cases'/row['id']/'recipe.json')
        spec=recipe['cases'][0]
        artifact=home/'workspaces'/row['arm']/spec['artifacts']['result']
        profile=row['profile']
        declared=[g for g in spec['graders'] if g['id'].startswith('basic-' if profile=='artifact_only' else 'task-')]
        extra={}
        if profile=='configured_workflow':
            h=load_json(home/'hypotheses.json')['runs'][index]
            row['already_recorded_hypotheses']=[x['stage'] for x in h['hypotheses']]
            row['author_entry_alert']=row['alert']
            if h['hypotheses']:
                row['alert']=True
                row['localization']=sorted(set(row['localization']+[x['stage']+'/hypothesis' for x in h['hypotheses']]))
            if row['family']=='trigger':
                extra['invocation_route']=load_json(home/'workspaces'/row['arm']/'host-observation.json')['route']
            if row['runtime_backend']:
                receipt=load_json(home/'workspaces'/row['arm']/'backend-receipt.json')
                extra['backend']={k:receipt[k] for k in ('backend','version','entrypoint','fallback')}
        row['control_identity']=suite_digest({'artifact_sha256':sha(artifact),'rules':declared,'observations':extra})
        output.append(row)
    return output


def aggregate(rows):
    output={}
    for profile in ('artifact_only','configured_workflow'):
        output[profile]={}
        for family in FAMILIES:
            chosen=[r for r in rows if r['profile']==profile and r['family']==family]
            defects=[r for r in chosen if r['phase']=='before' and r['arm']=='with']
            if family=='trigger':
                controls=[r for r in chosen if r['phase']=='after' and r['arm']=='with']
            else:
                controls=[r for r in chosen if r['phase']=='before' and r['arm']=='without']
            output[profile][family]=metrics(defects,controls)
    return output


def fraction(n,d): return f'{n}/{d}（{100*n/d:.1f}%）' if d else '未覆盖'


def build_report(root, summary, results):
    basic=summary['metrics']['artifact_only']; full=summary['metrics']['configured_workflow']
    levels={'multiple-testing':'L2：BH／完整检验集合', 'id-alignment':'L2：ID 与数值绑定／覆盖',
        'pseudoreplication':'L2：独立单位数／标准误', 'reference-leakage':'L2：声明的训练 ID 列表；隐藏读取未定位',
        'backend-fallback':'L2：额外采集器的后端／版本／入口', 'label-semantics':'L2：标签契约；不判断生物学真值',
        'over-refusal':'L2：decision 字段；答案实用性未检查', 'trigger':'L1：触发／选择／调用证据缺口'}
    lines=['# DETECTION-VALIDITY：PVL 种子缺陷元验证','',
        '日期：2026-09-25。PVL 版本：0.6.0，检测器代码在执行前冻结，实验中未修改。', '',
        '**PVL 在明确的任务契约、完整参考和所需运行证据下适合做回归检查；结构合格、文件存在、ARI 一致或自报成功，都不足以证明科学任务正确。** 本实验包含 8 类、每类 3 个源码缺陷，共 24 个变异；24 个配对正常对照；恢复原代码后的 24 个 WITH 和 24 个重复控制，共 96 次真实本地进程执行。', '',
        '全部是公开构造输入和小型种子插件，无真实用户数据、LLM、远端宿主或付费服务。本地文件副本隔离与清空子进程账户环境不等于针对恶意插件的 OS 沙箱。宿主事件由受控适配器生成，不是真实模型调用记录。WITH/WITHOUT 是既有采集器的槽位名；WITHOUT 执行未变异参照程序，不是无插件模型基线。', '',
        '## 每类结果', '',
        '检出率 = 有报警的种子缺陷 / 3；误报率 = 报警的正常对照 / 去重后的正常对照。恢复复测与重复对照不扩充分母。相同产物、判据与相关观测去重；不同源码缺陷仍按变异计数，不能当作独立总体样本。没有 UNKNOWN 时才给点率，有 UNKNOWN 时保留计划分母并给上下界。', '',
        '“配对净检出”要求缺陷报警而对应正常对照不报警，避免把原有判据偏好算成缺陷检出。这是描述性配对差异，不是因果或总体估计。', '',
        '| 缺陷类 | 仅产物：检出 | 完整诊断：检出 | 完整诊断：误报 | 配对净检出 | PVL 实际定位上限 |',
        '| --- | ---: | ---: | ---: | ---: | --- |']
    for family,title in FAMILIES.items():
        b,f=basic[family],full[family]
        lines.append(f"| {title} | {fraction(b['TP'],b['defects'])} | {fraction(f['TP'],f['defects'])} | {fraction(f['FP'],f['distinct_controls'])} | {f['paired_specific_detections']}/{f['defects']} | {levels[family]} |")
    lines += ['', '仅产物配置的误报均为 0；其负对照分母同样去重，详见机器记录，不能由低误报率推断其有检出能力。L1 指流程阶段，L2 指失败判据／字段／后端身份，L3 指致因源码行。**本实验没有建立自动 L3 定位能力**；报告中的 mutation.diff 来自实验者注入记录，不是 PVL 找出的根因。', '',
        '## 检测配置与统计视图', '',
        '- **仅产物**：BH 检查、字段结构或 ARI。它是明确列出的轻量配置，不冒充 PVL 的全部能力。',
        '- **作者入口**：冻结任务检查，加 diagnose 的调用缺口；后端另加现有 backend_identity 验证器。原始 results.json 保留这个预先执行的口径。',
        '- **完整诊断**：在作者入口结果上，合并同次运行已经生成的 native-hypotheses 报警。本表是执行后生成的派生统计视图，不是新的盲测；未改变种子、标签、参考、阈值、检测器或原始结果。唯一增加的缺陷报警是 trigger-2：作者入口只认插件命名空间而漏过错误技能，既有假设报告已指出选择／触发问题。',
        '- **后端条件**：backend_identity 目前不在原生 sidecar 的允许判据里，本实验单独调用生产验证器，并提供受控 Python profiler 观察到的函数调用、会话和产物摘要绑定收据。移除这个额外采集器后，仅凭数值和自报 backend 会漏检；哈希及本地采集器不证明独立认证。',
        '- **正常变体**：允许无语义影响的行重排、训练集 ID 顺序变化、声明的标签别名和直接读文件使用插件。规则不支持这些变体时，必须算误报。', '',
        '## 保留的漏检与误报', '',
        '1. **多重检验**：普通 BH 检查检出把 p 当 q 和错误乘数；先过滤再 BH 的结果内部一致，只有绑定完整检验集合才发现缺行。',
        '2. **ID 错位**：轮换 p 值、轮换 ID、重复 ID 覆盖后丢行都可保留内部 BH 一致；需要按 ID 冻结参考数值与完整覆盖。',
        '3. **伪重复**：本组分别把细胞、技术样本当独立单位，或以细胞重算标准误。精确的构造样本计数和标准误契约能检出；不证明 PVL 能识别真实世界伪造或隐瞒的供体身份。',
        '4. **参考泄漏**：可发现声明中出现评估 ID，但不能从干净声明推断未读取评估标签／特征。hidden-label-leakage 的表面报警与正常对照同样存在，是列表顺序偏好，不能记作净检出；hidden-feature-leakage 漏检。',
        '5. **静默回退**：包含数值变化、旧版本同值和异常后等值回退三种变异。检出依赖额外运行身份收据；同值结果不能建立后端一致性。',
        '6. **标签语义**：T/B、CD4/CD8、免疫／基质互换的 ARI 都不变。精确标签检查发现互换，但也误报契约允许的别名；应先审阅或规范化标签语义，不能把字面一致当生物学正确。',
        '7. **过度拒答**：可发现明确 withhold 和凭空抬高样本阈值；decision=allow 但 answer=null 被现有 over_refusal 判据放过。',
        '8. **触发失败**：测试路由遗漏、错误技能和技能错误后宿主兜底。完整诊断能报警；正常直接读取插件文件也会触发调用缺口误报。这里测的是受控路由与事件消费，不是自然语言模型的实际触发概率。', '',
        '## 完整执行与复测', '',
        '先冻结 24 份输入、独立任务标签、源码差异、参考和规则；再逐个在独立目录执行变异、未变异对照、恢复后的代码及重复对照。生产路径为 prepare_native_analysis → 本地种子宿主执行 → capture_native_evidence → verify_native_evidence → diagnose → native-hypotheses → compare-native-repair。原始源码未改写，检测器模块摘要在运行前后相同。', '',
        '每次变异由不调用 PVL 的独立见证检查确认已生效；每个正常／恢复样本都通过任务语义检查。它们由同一实验者编写，不是独立专家标注。恢复后 24/24 满足种子任务契约；完整诊断仍对 3/24 正常恢复结果报警，正是训练 ID 顺序、标签别名、直接文件调用这三项误报，未删去或改标。', '',
        f"所有 48 份采集包的摘要与离线重算均通过。机器诊断计算耗时中位数 {summary['machine_timing']['median_seconds']:.4f} 秒，范围 {summary['machine_timing']['min_seconds']:.4f}–{summary['machine_timing']['max_seconds']:.4f} 秒；不含安装、准备、解释器启动和人的阅读。作者首次诊断耗时仍未知。模型调用 0，新增供应商费用 US$0，未改写此前未知结算。", '',
        '## 何时值得用', '',
        '| 情形 | 本实验支持的用法／限制 |', '| --- | --- |',
        '| 已有 DE 表，明确要求 BH | 快速复算算术；补全测试集合参考以发现筛选后再校正 |',
        '| ID、标签或独立单位错误 | 提供按 ID 对齐且语义审阅过的参考；单靠结构或聚类一致性不足 |',
        '| 要确认后端是否静默回退 | 先取得实际运行身份收据；仅凭输出和自报名称不足 |',
        '| 怀疑参考泄漏、过度拒答或未触发 | 用作调查线索；需要访问观察、答案实用性检查和调用方式审阅 |',
        '| 要宣称普遍检出率、节省作者时间或真实插件收益 | 当前证据不够；需要未见事故族、正常变体、独立标注和真实作者／宿主观测 |', '',
        '## 复现与证据', '',
        'Python 3.11+，仅标准库，无模型或网络：', '', '```sh',
        'python scripts/validate_seeded_defects.py --output work/seeded-validity-new',
        'python scripts/report_seeded_defects.py --input work/seeded-validity-new --output work/seeded-report-new',
        '```', '',
        '每次必须使用新目录，旧尝试不会覆盖。报告命令先核验全部文件清单、24 个变异和 48 份采集收据；不执行已收集的产物代码。', '',
        '- [机器摘要与逐项记录](docs/evidence/detection-validity-20260925.json)',
        '- [种子插件](examples/seeded-defects/plugin.py) · [受控宿主](examples/seeded-defects/host.py) · [执行器](scripts/validate_seeded_defects.py) · [报告器](scripts/report_seeded_defects.py)',
        f'- 协议 SHA-256：`{results["protocol_sha256"]}`',
        f'- 本次原始证据目录：`{root.as_posix()}`。其中 SHA256SUMS.json、mutation.diff、oracle-witness.json、capture-pin.json、诊断和复测结果全部保留。', '',
        '**证据上限：公开开发集、每族仅 3 个已知变异、共享父实现、同一作者定义标签与规则；不是 heldout、代表性事故谱、独立科学验证或自然使用价值闭环。报告不提供置信区间，也不把 3/3 写成普遍 100% 检出。**', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); root=args.input.resolve(); output=args.output.resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise SystemExit('Use a new report directory outside the preserved experiment')
    sums=load_json(root/'SHA256SUMS.json')
    for relative,digest in sums.items():
        if sha(confined(root,relative))!=digest: raise ValueError('Evidence changed: '+relative)
    frozen=load_json(root/'protocol.lock.json'); results=load_json(root/'results.json')
    if sha(root/'protocol.lock.json')!=results['protocol_sha256']: raise ValueError('Protocol digest mismatch')
    if any(sha(ROOT/p)!=digest for p,digest in frozen['pvl_files'].items()): raise ValueError('Use the frozen PVL detector revision')
    for case in frozen['cases']:
        for phase in ('before','after'):
            home=root/'cases'/case['id']/phase
            verify_native_evidence(home/'capture',load_json(home/'capture-pin.json')['receipt_sha256'])
    rows=observed_rows(root,results)
    timing=[load_json(root/'cases'/case['id']/phase/'author-diagnosis/diagnosis.json')['timing']['machine_seconds_to_diagnosis']
        for case in frozen['cases'] for phase in ('before','after')]
    summary={'format':'pvl-detection-validity-report-1','protocol_sha256':results['protocol_sha256'],
        'raw_results_sha256':sha(root/'results.json'),'source_manifest_sha256':sha(root/'SHA256SUMS.json'),
        'reporter_sha256':sha(Path(__file__)),'published_view':'Diagnostic union of already recorded production outputs; distinct negative artifact/check pairs',
        'original_author_entry_metrics':results['summary'],'metrics':aggregate(rows),'rows':rows,
        'processes':96,'verified_captures':48,'seed_mutations':24,'paired_controls':24,
        'machine_timing':{'median_seconds':statistics.median(timing),'min_seconds':min(timing),'max_seconds':max(timing)},
        'human_time_to_first_diagnosis':None,'model_calls':0,'provider_cost_usd':0,
        'representative_accuracy':None,'independent_adjudication':False,'natural_trigger_probability':None}
    output.mkdir(parents=True)
    write_json(output/'detection-validity-20260925.json',summary)
    (output/'DETECTION-VALIDITY.md').write_text(build_report(root,summary,results),encoding='utf-8')
    print(json.dumps({'output':str(output),'metrics':summary['metrics']},ensure_ascii=False,indent=2))


if __name__=='__main__': main()

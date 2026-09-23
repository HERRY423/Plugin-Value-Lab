"use strict";
// Same-origin companion to the workbench. All evidence is rendered as text.
let templateSuite = null;
const money = value => typeof value === "number" ? `$${value.toFixed(4)}` : "未知";
const categories = {model:"模型",tool:"工具",human:"人工",judge:"评分模型",setup:"准备与设置",retry:"重试",other:"其他"};
function button(text, handler, cls="secondary") {
  const b=el("button",text,cls); b.type="button"; b.onclick=handler; return b;
}
function table(headers, rows) {
  const t=el("table"),head=el("tr"); headers.forEach(h=>head.append(el("th",h))); t.append(head);
  for(const values of rows){const row=el("tr");values.forEach(v=>row.append(el("td",String(v))));t.append(row);} return t;
}
function checkField(parent,label,value=false){const box=el("label",undefined,"consent");const input=el("input");input.type="checkbox";input.checked=value;box.append(input,el("span",label));parent.append(box);return input;}
const hourly = field($("setup"),"人工时薪（美元；零表示暂不折算，不代表没有人工投入）","input","0");
hourly.type="number";hourly.min="0";hourly.step="0.01";hourly.id="human-hourly";
$("cases").before(hourly.parentElement);
const rulePanel=el("div");rulePanel.id="rule-check";
const ruleCheck=button("校验规则并试评分",()=>action(checkRules));ruleCheck.id="check-rules";
$("prepare").before(ruleCheck);$("cases").after(rulePanel);

function addRule(parent, data={}) {
  const box=el("div",undefined,"rule-editor");
  const id=data.id||"rule-"+crypto.randomUUID().slice(0,8);
  const head=el("div",undefined,"case-head");head.append(el("strong","评分规则"),button("移除规则",()=>box.remove(),"secondary remove"));box.append(head);
  const type=field(box,"判定方式","select",data.type||"contains",[["contains","应包含指定文字"],["not_contains","不应包含指定文字"],["human","人工规则（原生运行仅作模型诊断）"],["json_equals","JSON 字段精确相等（仅本地评分）"]]);
  const criterion=field(box,"指定文字 / 人工判定规则 / JSON 目标值","textarea",data.type==="human"?data.rubric:data.type==="json_equals"?JSON.stringify(data.value):data.value);
  const path=field(box,"JSON 字段路径（仅精确相等规则使用）","input",data.path||"");
  const grid=el("div",undefined,"grid");box.append(grid);
  const weight=field(grid,"权重","input",String(data.weight??1));weight.type="number";weight.min="0.001";weight.step="any";
  const dimension=field(grid,"评分对象","select",data.dimension||"outcome",[["outcome","任务结果：计入质量"],["process","执行过程：仅作诊断"]]);
  const critical=checkField(box,"关键结果规则：失败时不能用其他高分抵消",data.critical||false);
  const examples=el("details");examples.append(el("summary","校准样例：检查规则是否会把错答案判对"));box.append(examples);
  const exampleRows=el("div");examples.append(exampleRows);
  function exampleRow(value={output:"",passed:true}){
    const row=el("div",undefined,"rule-editor");const output=field(row,"样例输出","textarea",value.output);
    const passed=field(row,"预期判定","select",String(value.passed),[["true","应该通过"],["false","应该失败"]]);
    row.append(button("移除样例",()=>row.remove(),"secondary remove"));row.read=()=>({output:output.value,passed:passed.value==="true"});exampleRows.append(row);
  }
  for(const item of data.examples||[])exampleRow(item);
  examples.append(button("添加校准样例",()=>exampleRow()));
  const update=()=>{path.parentElement.hidden=type.value!=="json_equals";};type.onchange=update;update();
  box.read=()=>{const g={id,type:type.value,dimension:dimension.value,weight:Number(weight.value),critical:critical.checked};
    if(type.value==="human")g.rubric=criterion.value;
    else {g.value=type.value==="json_equals"?JSON.parse(criterion.value):criterion.value;if(type.value==="json_equals")g.path=path.value;}
    if(exampleRows.children.length)g.examples=[...exampleRows.children].map(r=>r.read());return g;};
  parent.append(box);
}
addCase = function(data={}) {
  const card=el("div",undefined,"case");const head=el("div",undefined,"case-head");head.append(el("strong","评估任务"),button("移除任务",()=>card.remove(),"secondary remove"));card.append(head);
  const grid=el("div",undefined,"grid");card.append(grid);
  const kind=field(grid,"任务类型","select",data.kind||"task",[["task","正常任务"],["negative","不应触发插件"],["abstention","应承认无法判断"]]);
  const cluster=field(grid,"任务类别（同类任务填相同名称）","input",data.cluster||"");
  const prompt=field(card,"给 Agent 的任务","textarea",data.prompt||"");prompt.required=true;
  const rules=el("div");card.append(rules);for(const g of data.graders||[{}])addRule(rules,g);
  card.append(button("＋ 添加评分规则",()=>addRule(rules)));
  const sample=field(card,"试评分文本（可选；只测试规则，不记入实测）","textarea","");
  card.read=()=>({id:data.id,kind:kind.value,cluster:cluster.value,prompt:prompt.value,graders:[...rules.children].map(r=>r.read())});
  card.sample=()=>sample.value;$("cases").append(card);
};
function editorData(){
  const cases=[...$("cases").children].map((c,i)=>({...c.read(),id:c.read().id||`case-${i+1}`,cluster:c.read().cluster||`family-${i+1}`}));
  const data={plugin_path:$("plugin-path").value,model:$("model").value,runs:Number($("runs").value),budget_usd:Number($("budget").value),human_hourly_usd:Number(hourly.value),cases};
  if(templateSuite){const s=structuredClone(templateSuite);s.id="study-"+crypto.randomUUID().slice(0,8);s.cases=cases;s.runs_per_case=data.runs;s.conditions.model=data.model;s.conditions.budget.max_cost_usd=data.budget_usd;s.policy.human_hourly_usd=data.human_hourly_usd;data.suite=s;}
  data.samples={};[...$("cases").children].forEach((c,i)=>{if(c.sample())data.samples[cases[i].id]=[c.sample()];});return data;
}
async function checkRules(){rulePanel.replaceChildren();const checked=await api("/api/rules/check",editorData());
  rulePanel.append(el("p",checked.valid?"结构检查通过。校准和试评分不构成实测。":"规则未通过校验。","panel"));
  for(const item of [...checked.errors,...checked.warnings])rulePanel.append(el("p",item,"small"));
  for(const c of checked.cases){for(const s of c.samples){rulePanel.append(el("h3",c.id+" · 试评分 "+number(s.score)),table(["规则","判定"],s.grades.map(g=>[g.id,g.passed===null?"待人工审阅":g.passed?"通过":"失败"])));if(s.critical_failures.length)rulePanel.append(el("p","关键失败："+s.critical_failures.join(", "),"panel"));}}
}
$("setup").onsubmit=event=>{event.preventDefault();action(async()=>{$("prepare").disabled=true;try{const result=await api("/api/studies",editorData());await openStudy(result.state.id);}finally{$("prepare").disabled=false;}});};
$("cases").replaceChildren();addCase();addCase({kind:"negative"});

const compareView=el("article");compareView.id="comparison";compareView.hidden=true;$("detail").after(compareView);
compareView.append(el("h2","插件版本与模型变化比较"),el("p","选择两项研究。任务、规则或其他条件变化会被列出；不会把同时改变插件和模型得到的差异归因给其中一项。","muted"));
const beforeSelect=field(compareView,"原研究","select","");beforeSelect.id="compare-before";
const afterSelect=field(compareView,"新研究","select","");afterSelect.id="compare-after";
const compareResult=el("div");
const compareButton=button("检查可比性并比较",()=>action(async()=>{const result=await api("/api/compare",{before:beforeSelect.value,after:afterSelect.value});showComparison(result);}));compareButton.id="compare-submit";
compareView.append(compareButton,compareResult);
const compareNav=button("比较两项评估",()=>action(async()=>{selected=null;current=null;$("setup").hidden=true;$("detail").hidden=true;compareView.hidden=false;await comparisonOptions();}));compareNav.id="compare-nav";$("demo").after(compareNav);
async function comparisonOptions(){const studies=await api("/api/studies");for(const select of [beforeSelect,afterSelect]){const prior=select.value;select.replaceChildren();for(const s of studies){const o=el("option",`${s.plugin.name} ${s.plugin.version} · ${s.created_at.slice(0,19)} · ${s.id.slice(0,6)}`);o.value=s.id;select.append(o);}if(studies.some(s=>s.id===prior))select.value=prior;}if(beforeSelect.value===afterSelect.value&&studies.length>1)beforeSelect.value=studies[1].id;}
function showComparison(result){compareResult.replaceChildren();const statuses={SIMULATION_ONLY:"仅模拟比较",COMPARABLE_DESCRIPTIVE:"可作局部描述性比较",NOT_COMPARABLE:"条件或证据不足，不能作升级判断"};const axes={plugin_revision:"插件版本 / 内容变化",model:"模型变化",combined:"插件与模型同时变化",replicate:"重复研究"};
  compareResult.append(el("h3",statuses[result.status]),el("p",axes[result.axis],"muted"));
  for(const issue of result.blockers)compareResult.append(el("p",issue,"panel"));
  compareResult.append(table(["变化项","原值","新值"],result.differences.map(d=>[d.field,JSON.stringify(d.before),JSON.stringify(d.after)])));
  compareResult.append(el("p","以下数值为提交数据的诊断差值；上方存在阻断时不作归因或推荐。","small"));
  compareResult.append(table(["任务","有插件得分变化","基线变化","插件贡献变化","回退"],result.cases.map(c=>[c.case_id,number(c.with_change),number(c.baseline_change),number(c.plugin_gain_change),c.regression?"是":"未检出 / 未知"])));
  compareResult.append(table(["成本指标","原研究","新研究"],[
    ["有插件组总成本",money(result.costs.before.arms.with.total_usd),money(result.costs.after.arms.with.total_usd)],
    ["有插件组每次成功成本",money(result.costs.before.arms.with.cost_per_success_usd),money(result.costs.after.arms.with.cost_per_success_usd)]]));
  compareResult.append(el("p",result.cost_comparison_eligible?"两边成本口径可作描述性比较；仍非独立账单核验。":"成本尚不可作节省判断，请检查类别覆盖、证据和估计/结算口径。","panel"));
  for(const w of result.warnings)compareResult.append(el("p",w,"small"));
  const download=button("下载比较 JSON",()=>{const blob=new Blob([JSON.stringify(result,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=el("a");a.href=url;a.download="study-comparison.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});compareResult.append(download);
}
const originalNew=$("new").onclick;
$("new").onclick=()=>{compareView.hidden=true;templateSuite=null;rulePanel.replaceChildren();originalNew();};
const originalOpen=openStudy;
openStudy=async function(id){compareView.hidden=true;await originalOpen(id);};
const cloneButton=button("以此方案准备版本 / 模型对照",()=>{
  const source=current;if(!source)return;$("new").onclick();templateSuite=structuredClone(source.suite);
  $("plugin-path").value=source.state.source_plugin||"";$("model").value=source.suite.conditions.model;$("runs").value=source.suite.runs_per_case;$("budget").value=source.suite.conditions.budget.max_cost_usd??"";hourly.value=source.suite.policy.human_hourly_usd;
  $("cases").replaceChildren();source.suite.cases.forEach(addCase);notice("已复制方案。仅修改待测插件目录或模型，可保留其他条件；任务、评分或时薪改动会在比较中显示。旧研究保持原样。");
});cloneButton.id="clone-study";$("stop").before(cloneButton);

const costPanel=el("section");costPanel.id="cost-analysis";$("result").after(costPanel);
function addExpense(parent, entry={}) {
  const row=el("div",undefined,"rule-editor");const id=entry.id||"expense-"+crypto.randomUUID().slice(0,8);
  const category=field(row,"成本类别","select",entry.category||"judge",Object.entries(categories));
  const arm=field(row,"分配到","select",entry.arm||"with",[["with","有插件组"],["without","无插件组"],["shared","两组共同成本"]]);
  const fraction=field(row,"共同成本中有插件组的比例（0—1）","input",String(entry.with_fraction??.5));fraction.type="number";fraction.min="0";fraction.max="1";fraction.step="any";
  const amount=field(row,"金额（美元；留空表示未知）","input",entry.amount_usd==null?"":String(entry.amount_usd));amount.type="number";amount.min="0";amount.step="any";
  const basis=field(row,"金额来源","select",entry.basis||"estimate",[["estimate","费用估计"],["settled","账单已结算"],["declared","人工声明"]]);
  const treatment=field(row,"是否已计入原记录","select",entry.treatment||"additional",[["additional","尚未计入：增加到总成本"],["included","已经计入：仅保留明细，避免重复"]]);
  const ref=field(row,"凭据明细行或日志引用（不填密钥）","input",entry.evidence_ref||"");
  const caseId=field(row,"指定任务编号（可选；留空分摊到全部计划任务）","input",entry.case_id||"");
  const repetition=field(row,"指定重复次序（可选）","input",entry.repetition==null?"":String(entry.repetition));repetition.type="number";repetition.min="1";
  const timerBox=el("div");row.append(timerBox);timerBox.append(el("p","补充人工成本使用原始计时与冻结时薪换算，不能把机器运行时长当成人工时间。","small"));
  const timers=el("div");timerBox.append(timers);
  function timer(data={}){const wrap=el("div",undefined,"rule-editor");const actor=field(wrap,"计时人员","input",data.actor||"");const start=field(wrap,"开始时间（含时区，如 2026-09-22T09:00:00+08:00）","input",data.start||"");const end=field(wrap,"结束时间（含时区）","input",data.end||"");wrap.read=()=>({actor:actor.value,start:start.value,end:end.value});wrap.append(button("移除计时",()=>wrap.remove(),"secondary remove"));timers.append(wrap);}
  for(const t of entry.human_intervals||[])timer(t);timerBox.append(button("添加原始计时",()=>timer()));
  const visibility=()=>{timerBox.hidden=category.value!=="human";fraction.parentElement.hidden=arm.value!=="shared";};category.onchange=visibility;arm.onchange=visibility;visibility();
  row.append(button("移除此项",()=>row.remove(),"secondary remove"));
  row.read=()=>{const value={id,category:category.value,arm:arm.value,amount_usd:amount.value===""?null:Number(amount.value),basis:basis.value,evidence_ref:ref.value,treatment:treatment.value};
    if(arm.value==="shared")value.with_fraction=Number(fraction.value);if(caseId.value)value.case_id=caseId.value;if(repetition.value)value.repetition=Number(repetition.value);if(category.value==="human")value.human_intervals=[...timers.children].map(t=>t.read());return value;};parent.append(row);
}
async function renderCosts(id,data){const costs=await api(`/api/costs/${id}`);if(selected!==id)return;costPanel.replaceChildren();costPanel.append(el("h3","完整成本分析"));
  costPanel.append(el("p",`原生整批估计：${money(costs.native_estimate_usd)}。单独展示，不再次加到下面的总成本。`,"small"));
  costPanel.append(el("p",`原生估计额度：${money(costs.budget?.native_estimate_limit_usd)}；${costs.budget?.native_estimate_over_limit===true?"原生估计已超出额度":costs.budget?.native_estimate_over_limit===false?"当前原生估计未超额度":"尚无法核对"}。该额度不覆盖全部人工和工具投入。`,"small"));
  costPanel.append(table(["指标","有插件组","无插件组"],[
    ["已知小计",money(costs.arms.with.known_subtotal_usd),money(costs.arms.without.known_subtotal_usd)],
    ["完整记录总成本",money(costs.arms.with.total_usd),money(costs.arms.without.total_usd)],
    ["每次计划执行成本",money(costs.arms.with.mean_per_planned_run_usd),money(costs.arms.without.mean_per_planned_run_usd)],
    ["每次成功成本（含失败开销）",money(costs.arms.with.cost_per_success_usd),money(costs.arms.without.cost_per_success_usd)],
    ["失败次数",costs.arms.with.failed_runs,costs.arms.without.failed_runs],
    ["已记录人工分钟",number(costs.arms.with.declared_human_minutes),number(costs.arms.without.declared_human_minutes)],
    ["运行时长中位数 / 秒",number(costs.arms.with.latency.median_seconds),number(costs.arms.without.latency.median_seconds)]
  ]));
  function categoryValue(arm,key){const value=costs.arms[arm].components_known_usd[key];if(costs.coverage[key]==="included")return "已包含于原记录（不重复加计）";if(costs.coverage[key]==="unknown")return "已知 "+money(value)+" · 尚未核实";return money(value);}
  costPanel.append(table(["已知成本类别","有插件组","无插件组"],Object.entries(categories).map(([k,v])=>[v,categoryValue("with",k),categoryValue("without",k)])));
  costPanel.append(el("p",costs.complete_category_coverage?"成本类别已有覆盖声明；这不等于已结算或独立核验。":"额外成本类别尚未完整确认；已知小计不能当成完整投入。","panel"));
  if(costs.arms.with.known_amounts_by_basis_usd)costPanel.append(table(["已知金额来源（不混作结算）","有插件组","无插件组"],[["费用估计","estimate"],["声明已结算","settled"],["人工声明 / 时间折算","declared"]].map(([label,key])=>[label,money(costs.arms.with.known_amounts_by_basis_usd[key]),money(costs.arms.without.known_amounts_by_basis_usd[key])])));
  const gaps=el("details");gaps.append(el("summary","成本缺口与核算说明"),el("pre",[...costs.issues,...costs.arms.with.unknown,...costs.arms.without.unknown,...costs.warnings].join("\n")));costPanel.append(gaps);
  const sensitivity=el("details");sensitivity.append(el("summary","人工时薪敏感性（不改变冻结结论）"),table(["假定时薪","有插件组","无插件组","成本差"],costs.human_rate_sensitivity.map(r=>[money(r.hourly_usd),money(r.with),money(r.without),money(r.delta_usd)])));costPanel.append(sensitivity);
  const usage=el("details");usage.append(el("summary","已提交 Token 计数与费用来源"),el("pre",JSON.stringify({with:costs.arms.with.tokens,without:costs.arms.without.tokens,basis:costs.basis,basis_counts:costs.basis_counts},null,2)));costPanel.append(usage);
  if(["frozen","running","stopping","interrupted"].includes(data.state.status))return;
  const editor=el("details");editor.append(el("summary","补充成本明细 · 保留原记录并生成新分析"));costPanel.append(editor);
  const ledger=data.analysis?.ledger||{schema_version:1,entries:[],coverage:{}};
  const coverage={};for(const key of ["judge","setup","retry","other"])coverage[key]=field(editor,categories[key]+"的覆盖状态","select",ledger.coverage[key]||"unknown",[["unknown","尚不清楚"],["included","已包含在原记录"],["not_applicable","本研究不适用"],["itemized","在以下明细列出"]]);
  const expenses=el("div");editor.append(expenses);for(const entry of ledger.entries)addExpense(expenses,entry);
  editor.append(button("添加成本明细",()=>addExpense(expenses)),button("保存成本分析修订",()=>action(async()=>{const payload={schema_version:1,coverage:Object.fromEntries(Object.entries(coverage).map(([k,v])=>[k,v.value])),entries:[...expenses.children].map(e=>e.read())};await api(`/api/studies/${id}/costs`,payload);await render();notice("已生成新的成本分析、报告和使用卡；原始执行记录保持原样。");})));
  if(data.analysis)costPanel.append(el("p",`当前成本修订：${data.analysis.id}；重算结论：${verdicts[data.analysis.report.verdict]||data.analysis.report.verdict}。原始执行报告仍保留。`,"small"));
  if(data.analysis_integrity_issues?.length)costPanel.append(el("p","分析修订完整性异常："+data.analysis_integrity_issues.join(", "),"panel"));
}
const originalRender=render;
render=async function(){const id=selected;await originalRender();if(id&&selected===id&&current?.state.id===id)await renderCosts(id,current);};

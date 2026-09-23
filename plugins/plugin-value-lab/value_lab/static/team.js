"use strict";
// Explicit local team decisions; no score can silently become adoption.
(()=>{
  const view=el("article");view.id="team-workbench";view.hidden=true;$("detail").after(view);
  view.append(el("h2","团队使用记录"),el("p","把一次使用卡与研究背景、团队决定保存为新修订。旧卡片和决定保留；条件变化时提示重新评估。所有内容仅存本机。","muted"));
  const study=field(view,"从哪项评估生成当前使用卡","select","");study.id="team-study";
  const previous=field(view,"接续哪份团队记录（首轮选新记录）","select","");previous.id="team-previous";
  const grid=el("div",undefined,"research-grid");view.append(grid);
  const actor=field(grid,"声明这次决定的人","input","");actor.id="team-actor";
  const choice=field(grid,"团队当前选择","select","undecided",[["undecided","尚未决定"],["trial","小范围试用"],["keep","继续使用"],["pause","暂停采用"],["retire","停止采用"]]);choice.id="team-choice";
  const rationale=field(view,"决定理由和仍需核对的问题","textarea","");rationale.id="team-rationale";
  const context=field(view,"当前研究上下文 JSON（可选；后续留空会沿用上轮）","textarea","");context.id="team-research-context";context.className="research-json";context.spellcheck=false;
  const upload=field(view,"从研究方向诊断载入上下文文件","input","");upload.type="file";upload.accept=".json,application/json";
  upload.onchange=()=>action(async()=>{if(upload.files?.[0])context.value=await upload.files[0].text();});
  const result=el("div");result.id="team-result";view.append(button("保存为下一版团队记录",()=>action(save)),result);
  const nav=button("团队使用记录",()=>action(async()=>{
    selected=null;current=null;$("setup").hidden=true;$("detail").hidden=true;$("comparison").hidden=true;$("research-workbench").hidden=true;
    view.hidden=false;await refresh();notice();
  }));nav.id="team-nav";$("research-nav").after(nav);
  for(const id of ["new","compare-nav","research-nav"]){const target=$(id),old=target.onclick;target.onclick=function(event){view.hidden=true;return old.call(this,event);};}
  const oldOpen=openStudy;openStudy=async function(id){view.hidden=true;await oldOpen(id);};
  async function refresh(){
    const [studies,records]=await Promise.all([api("/api/studies"),api("/api/team-records")]);
    const oldStudy=study.value,oldPrevious=previous.value;
    study.replaceChildren();for(const row of studies){const option=el("option",`${row.plugin.name} · ${row.id.slice(0,8)} · ${row.mode==="synthetic"?"模拟":"评估"}`);option.value=row.id;study.append(option);}
    if(studies.some(row=>row.id===oldStudy))study.value=oldStudy;
    previous.replaceChildren();const initial=el("option","新建团队记录");initial.value="";previous.append(initial);
    for(const row of records){const option=el("option",`${row.plugin_name} · 第 ${row.revision} 版 · ${row.choice}`);option.value=row.id;previous.append(option);}
    if(records.some(row=>row.id===oldPrevious))previous.value=oldPrevious;
  }
  async function save(){
    if(!study.value)throw Error("请先准备或选择一项评估。");
    const parsed=context.value.trim()?JSON.parse(context.value):null;
    const data=await api("/api/team-records",{study_id:study.value,decision:{actor:actor.value,choice:choice.value,rationale:rationale.value},
      previous_id:previous.value||null,research_context:parsed});
    const entry=data.record.entries.at(-1),change=entry.change;
    result.replaceChildren(el("h3",`已保存第 ${data.revision} 版`),
      el("p",`使用卡：${entry.card.status} / ${entry.card.verdict}。团队选择：${entry.decision.choice}。`),
      el("p",change.previous_guidance_reassessment_required?"条件、证据或研究背景已变；请重新审视旧指导。":"没有检测到需要重评旧指导的输入变化。","panel"),
      el("p","本地摘要不证明人、数据或执行的真实性，也不会自动安装、扩权或开始研究。","small"));
    const download=button("下载完整团队记录",()=>{
      const blob=new Blob([JSON.stringify(data.record,null,2)],{type:"application/json"});
      const url=URL.createObjectURL(blob),link=el("a");link.href=url;link.download=`team-record-${data.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });result.append(download);await refresh();previous.value=data.id;
  }
})();

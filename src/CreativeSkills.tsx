import {useEffect,useState} from 'react';
type Obj=Record<string,any>;
const names:Obj={script_plan:'改编提纲',script:'剧本正文',storyboard_outline:'分镜汇总',storyboard:'逐镜细化'};
export function CreativeSkills({project,edit,section='script',expanded=false}:{project:Obj;edit:(fn:(p:Obj)=>void)=>void;section?:string;expanded?:boolean}){
 const [catalog,setCatalog]=useState<Obj[]>([]),[preview,setPreview]=useState<Obj>({}),[error,setError]=useState('');
 const selection=project.creative_skills||{mode:'auto',ids:[]},stages=section==='script'?['script_plan','script']:['storyboard_outline','storyboard'];
 const source=JSON.stringify({creative_skills:selection,script_task:project.script_task||'auto',story_policy:project.story_policy||'faithful'});
 useEffect(()=>{fetch('/api/skills').then(r=>r.json()).then(v=>setCatalog(v.items||[])).catch(e=>setError(e.message))},[project.id]);
 useEffect(()=>{let current=true;fetch(`/api/projects/${project.id}/creative-skills/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:source}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.detail);if(current){setPreview(v);setError('')}}).catch(e=>{if(current)setError(e.message)});return()=>{current=false}},[project.id,source]);
 const available=catalog.filter(s=>s.stages?.some((stage:string)=>stages.includes(stage))&&(section!=='script'||['writing','genre'].includes(s.usage))).sort((a,b)=>(a.usage==='writing'?0:1)-(b.usage==='writing'?0:1));
 const audit=section==='script'?project.documents?.creative_rule_application:project.storyboard_generation?.rule_application;
 const selectedIds:string[]=selection.mode==='manual'?selection.ids:stages.flatMap(stage=>preview[stage]?.skills?.map((s:Obj)=>s.id)||[]);
 const choice=(s:Obj)=><label className="skill-choice" key={s.id}><input type="checkbox" checked={selectedIds.includes(s.id)} disabled={!s.enabled||!selectedIds.includes(s.id)&&selectedIds.length>=12} onChange={e=>edit(p=>{p.creative_skills={mode:'manual',ids:e.target.checked?Array.from(new Set([...selectedIds,s.id])):selectedIds.filter(id=>id!==s.id)}})}/><span><strong>{s.name}</strong><small>{s.description}</small>{!s.enabled&&<small>已停用</small>}</span></label>;
 return <section className="creative-skills"><details open={expanded||undefined}><summary>{section==='script'?'剧本技能':'分镜技能'} · {selection.mode==='auto'?'按任务与阶段自动匹配':'手动选择'}</summary><p className="muted">专项方法辅助主任务；用户锁定内容及采用的提纲优先。规则会传入实际生成任务并记录版本，AI意见仍需内容复核。</p>
 <label>技能应用方式<select aria-label={section+'技能应用方式'} value={selection.mode} onChange={e=>edit(p=>{p.creative_skills={mode:e.target.value,ids:e.target.value==='manual'?Array.from(new Set(stages.flatMap(stage=>preview[stage]?.skills?.map((s:Obj)=>s.id)||[]))):[]}})}><option value="auto">自动匹配内置方法</option><option value="manual">手动选择专项方法</option></select></label>
 <h3>编剧核心方法</h3><div className="skill-choice-grid">{available.filter(s=>!s.origin).map(choice)}</div><details><summary>题材与叙述方式 · {available.filter(s=>s.origin).length} 项</summary><div className="skill-choice-grid">{available.filter(s=>s.origin).map(choice)}</div></details>
 {stages.map(stage=><div className="skill-stage" key={stage}><strong>{names[stage]}</strong>{preview[stage]?.ready?<p>{preview[stage].skills.map((s:Obj)=>`${s.name} v${s.version}`).join('、')||'DirectorMaster与主任务规则'}{preview[stage].warnings?.map((s:string)=><small className="muted" key={s}>{s}</small>)}</p>:<p className="trait-warning">{preview[stage]?.error||'正在核对规则…'}</p>}</div>)}
 {error&&<p className="trait-warning">{error}</p>}<p className="muted">导入自定义技能时需声明 stages（作用阶段）和 requires_tools（工具依赖），才能选择为阶段规则。仅安装不会自动成为默认。</p>
 {audit&&<details><summary>上次任务实际传入的规则</summary><p>{audit.status||'规则已传入AI；字段校验与内容审查分开记录'}</p><p>{names[audit.stage]}</p>{audit.skills?.map((s:Obj)=><p key={s.id}>{s.name} · v{s.version} · {s.reason}<small>版本指纹 {s.digest.slice(0,12)}</small></p>)}</details>}
 </details></section>;
}


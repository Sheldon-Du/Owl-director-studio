import {useEffect,useState} from 'react';
type Obj=Record<string,any>;
export function VideoSkills({project,edit}:{project:Obj;edit:(fn:(p:Obj)=>void)=>void}){
 const [items,setItems]=useState<Obj[]>([]),[search,setSearch]=useState(''),[error,setError]=useState('');
 useEffect(()=>{fetch('/api/skills').then(r=>r.json()).then(v=>setItems(v.items||[])).catch(e=>setError(e.message))},[project.id]);
 const ids:string[]=project.prompt_skills?.ids||[],available=items.filter(s=>s.usage==='video'),selected=available.filter(s=>ids.includes(s.id));
 const toggle=(id:string,on:boolean)=>edit(p=>{p.prompt_skills={ids:on?[...ids,id]:ids.filter(v=>v!==id)}});
 return <section className="creative-skills"><details><summary>视频提示词技能 · {selected.length?selected.map(s=>s.name).join('、'):'采用 H3 基础规则'}</summary><p className="muted">在分镜确认后选择，生成 H3 prompt 时实际调用。最多3项；只调整画面表达，不改剧本、资产身份或自然时长。更换后需重新转写提示词，已生成视频保留。</p><input aria-label="搜索视频提示词技能" placeholder="搜索摄影、动画、第一视角、微表情等" value={search} onChange={e=>setSearch(e.target.value)}/><div className="skill-choice-grid">{available.filter(s=>(s.name+s.description).toLowerCase().includes(search.toLowerCase())).map(s=><label key={s.id} className="skill-choice"><input type="checkbox" checked={ids.includes(s.id)} disabled={!s.enabled||!ids.includes(s.id)&&ids.length>=3} onChange={e=>toggle(s.id,e.target.checked)}/><span><strong>{s.name}</strong><small>{s.description}</small>{s.execution_gaps?.length>0&&<small>用于提示词规则；完整技能流程仍有待接入能力。</small>}</span></label>)}</div>{error&&<p className="trait-warning">{error}</p>}</details></section>;
}

import {useEffect,useState} from 'react';
type Obj=Record<string,any>;
export function ImageSkills({asset,editAsset}:{asset:Obj;editAsset:(id:string,fn:(a:Obj)=>void)=>void}){
 const [items,setItems]=useState<Obj[]>([]);
 useEffect(()=>{fetch('/api/skills').then(r=>r.json()).then(v=>setItems((v.items||[]).filter((s:Obj)=>s.usage==='image')))},[]);
 const ids:string[]=asset.image_skill_ids||[];
 return <details className="creative-skills"><summary>图片提示词技能 · {ids.length?`${ids.length} 项`:'Image2.1 基础规则'}</summary><p>仅用于本元素图片提示词，最多3项。更换后重新生成提示词。</p>{items.map(s=><label key={s.id} className="skill-choice"><input type="checkbox" checked={ids.includes(s.id)} disabled={!s.enabled||!ids.includes(s.id)&&ids.length>=3} onChange={e=>editAsset(asset.id,a=>{a.image_skill_ids=e.target.checked?[...ids,s.id]:ids.filter(id=>id!==s.id);a.prompt='';a.prompt_zh=''})}/><span>{s.name}<small>{s.description}</small></span></label>)}</details>;
}

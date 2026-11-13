import {useState} from 'react';
type Obj=Record<string,any>;
function RecordedState({value}:{value:Obj}){
 return <div className="continuity-state"><p>{value.location} · {value.story_time}</p><p className="muted">光线：{value.lighting} · 声音：{value.sound}</p>{value.characters?.map((c:Obj)=><p key={c.asset_id||c.name}><strong>{c.name}</strong> · 位置 {c.position} · 朝向 {c.facing} · 服装 {c.costume}</p>)}{value.props?.map((p:Obj)=><p key={p.asset_id||p.name}><strong>{p.name}</strong> · 持有或位置 {p.holder} · 状态 {p.state}</p>)}</div>;
}
export function ContinuityReview({shot,busy,job}:{shot:Obj;busy:boolean;job?:(kind:string,target?:string,options?:Obj)=>void}){
 const [note,setNote]=useState(''),review=shot.continuity_review,states=shot.native?.['连续性接口'],rules=shot.native?.['创作规则应用'];
 if(!states&&!review&&!rules)return null;
 return <details open={review?.status==='needs_review'}><summary>镜头接续 · {review?.status==='needs_review'?'待人工复核':review?.status==='human_reviewed'?'已人工复核':'状态已记录，声画待核对'}</summary>{review?.issues?.map((i:Obj,n:number)=><p className="trait-warning" key={n}>{({location:'地点',story_time:'故事时间',lighting:'光线'} as Obj)[i.field]||i.field}：前镜 {i.previous} → 本镜 {i.next}</p>)}{review?.note&&<p className="muted">{review.note}</p>}{states&&<><strong>起始状态</strong><RecordedState value={states.start}/><strong>结束状态</strong><RecordedState value={states.end}/><p className="muted">衔接依据：{states.transition?.reason}</p></>}
 {review?.status==='needs_review'&&job&&<><p>先核对实际首帧、视频和声音；若已相容，可说明衔接并保留本镜。记录不符时请修复或重新生成受影响镜头。</p><label>复核依据<textarea aria-label={'第'+shot.generation_index+'镜衔接复核依据'} rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="说明实际画面如何接续，或已采用的转场依据"/></label><button disabled={busy||note.trim().length<4} onClick={()=>job('continuity_confirm',shot.id,{note:note.trim(),shot_hash:review.shot_hash})}>已复核衔接 · 保留本镜</button></>}
 {shot.first_frame_needs_review&&<p className="trait-warning">本镜提示词已重做，已采用首帧仍保留，请核对是否适用。</p>}{rules&&<details><summary>本镜生成实际传入的规则</summary><p className="muted">规则已传入 AI，内容仍需复核。</p>{rules.skills?.map((s:Obj)=><p key={s.id}>{s.name} · v{s.version} · {s.reason}<small>版本指纹 {s.digest.slice(0,12)}</small></p>)}</details>}</details>;
}

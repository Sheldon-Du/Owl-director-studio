import {useEffect,useState} from 'react';
import './h3-setup.css';
type Obj=Record<string,any>;
type Props={project:Obj;shots:Obj[];busy:boolean;edit:(fn:(p:Obj)=>void)=>void;review:(id:string)=>void;previousTail:(id:string)=>void;workflow:Obj;ready:boolean;next?:()=>void};
const frameFields=[['first','首帧','first_frame'],['keyframe','关键帧','adopted_keyframe'],['tail','尾帧','adopted_tailframe']];
const modes:Obj={auto:'自动选择参考',assets:'仅资产参考',first_frame:'本镜首帧',previous_tail:'上一镜尾帧',text:'纯文字'};
export function H3Setup({project,shots,busy,edit,review,previousTail,workflow,ready,next}:Props){
 const [states,setStates]=useState<Obj>({}),[error,setError]=useState(''),[referencePlan,setReferencePlan]=useState<Obj>({}),[referenceError,setReferenceError]=useState('');const ids=shots.map(s=>s.id).join(',');
 useEffect(()=>{let live=true;setStates({});setError('');Promise.all(shots.map(async s=>{const response=await fetch(`/api/projects/${project.id}/shots/${s.id}/performance`);const value=await response.json();if(!response.ok)throw Error(value.detail||'读取定稿状态失败');return [s.id,value.status]})).then(rows=>{if(live)setStates(Object.fromEntries(rows))}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[project.id,project.revision,ids]);
 useEffect(()=>{let live=true;setReferencePlan({});setReferenceError('');if(!shots.length)return;fetch(`/api/projects/${project.id}/shots/${shots[0].id}/h3/reference-preview`).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.detail||'引用准备失败');return value}).then(value=>{if(live)setReferencePlan(value.shots)}).catch(e=>{if(live)setReferenceError(e.message)});return()=>{live=false}},[project.id,project.revision,ids]);
 const change=(id:string,fn:(s:Obj)=>void)=>edit(p=>fn(p.shots.find((s:Obj)=>s.id===id)));
 const adoptedRoles=(s:Obj)=>['first','keyframe','tail'];
 const assets=(s:Obj)=>referencePlan[s.id]?.assets||[];
 const complete=shots.filter(s=>states[s.id]?.visual&&states[s.id]?.audio_current).length;
 return <section className="h3-simple-setup" aria-label="H3 参考与参数">
  <div className="h3-setup-overview"><div><h3>检查本组参考</h3><p className="muted">沿用已定稿的对白、动作和画面，确认参考后继续。</p></div><span className="pill">{complete}/{shots.length} 镜已定稿</span><span className="pill">540P 预览</span></div>
  {error&&<p className="speech-notice">{error}</p>}{referenceError&&<p className="speech-notice">引用准备未通过：{referenceError}</p>}
  {shots.map(s=>{const state=states[s.id],prepared=referencePlan[s.id],bound=assets(s),characters=bound.filter((a:Obj)=>a.kind==='character'),other=bound.filter((a:Obj)=>a.kind!=='character'),frameList=frameFields.filter(([role,,field])=>s[field]&&adoptedRoles(s).includes(role)&&!['assets','text'].includes(s.h3_reference_mode));return <article className="h3-setup-shot" key={s.id}>
   <div className="h3-setup-shot-heading"><strong>分镜 {project.shots.indexOf(s)+1} <small>{Number(s.duration).toFixed(2)} 秒</small></strong><button disabled={busy} onClick={()=>review(s.id)}>查看分镜与定稿</button></div>
   <div className="h3-setup-status">{[['sound','声音'],['timing','时序'],['visual','画面']].map(([key,label])=><span key={key} className={state?.[key]?'done':''}>{label} · {state?(state[key]?'已确认':'待确认'):'读取中'}</span>)}</div>
   <p className="h3-setup-reference-summary">{modes[s.h3_reference_mode||'auto']} · {prepared?`${characters.length} 个角色 · ${other.length} 个其他资产 · ${prepared.frames.length} 张帧图 · ${prepared.audio?'锁定原配音轨':`声音参考 ${(prepared.voice_references||[]).length} 个`}`:referenceError?'引用待补齐':'正在准备引用…'}</p>
   {prepared&&<div className="h3-setup-assets">{bound.map((a:Obj)=><span className="pill" key={a.id}>{a.name} → {a.references.map((r:Obj)=>r.kind+' '+r.label).join('、')}</span>)}{prepared.frames.map((f:Obj,i:number)=><span className="pill" key={'frame-'+i}>{({first:'首帧',keyframe:'关键帧',tail:'尾帧'} as Obj)[f.role]} → {f.label}</span>)}</div>}
   <details className="h3-setup-reference-edit"><summary>已自动沿用的参考</summary>
    <div className="h3-setup-assets">{bound.map((a:Obj)=><span className="pill" key={a.id}>{a.name} · {a.kind==='character'?(a.references?.some((r:Obj)=>r.kind==='角色 mod')?'角色 mod 已制作':'角色 mod 待制作'):a.kind==='scene'?'场景':'道具'}</span>)}{prepared?.voice_references?.map((r:Obj)=><span className="pill" key={r.label}>{r.speaker} · 声音参考 {r.label}</span>)}{!bound.length&&<small className="muted">转写前自动关联本镜资产。</small>}</div>
    <div className="h3-setup-frames">{frameFields.map(([role,label,field])=><label key={role} className={!s[field]?'unavailable':''}>{s[field]&&<img src={'/media/'+encodeURIComponent(s[field])} alt={label}/>}<span>{label}{!s[field]?' · 未采用':''}</span></label>)}</div>
    {s.h3_reference_mode==='previous_tail'&&<button disabled={busy||project.shots.indexOf(s)<1} onClick={()=>previousTail(s.id)}>提取并采用上一镜尾帧</button>}
   </details>
  </article>})}
  {!shots.length&&<p className="muted">全片模式将沿用各镜的定稿和参考设置。</p>}
  <details className="h3-setup-advanced"><summary>自动参数 <small>按镜头类型匹配 · 30 秒上限</small></summary>
   {shots.map(s=><div className="h3-setup-parameters" key={s.id}><strong>分镜 {project.shots.indexOf(s)+1}</strong><div className="parameter-grid"><label>画面动态<select disabled value={'auto'} onChange={e=>change(s.id,row=>{row.h3_motion=e.target.value})}><option value="auto">自动</option><option value="normal">普通动态</option><option value="high">高动态</option></select></label><label>文戏质感<select disabled value={'auto'} onChange={e=>change(s.id,row=>{row.h3_texture=e.target.value})}><option value="auto">自动</option><option value="on">启用</option><option value="off">关闭</option></select></label><label>声音来源<select disabled value="generated" onChange={e=>change(s.id,row=>{row.h3_audio_mode=e.target.value})}><option value="generated">声音作参考 · H3 生成对白与口型</option><option value="locked">锁定原配音轨</option></select></label></div>{s.speech_track&&<details><summary>试听最终配音轨 · {Number(s.speech_track.duration).toFixed(2)} 秒</summary><audio controls preload="none" src={'/media/'+encodeURIComponent(s.speech_track.media)}/></details>}{s.stage3d&&<small className="muted">已绑定保存的 3D 预演。</small>}</div>)}

   <small className="muted">参考上限：9 图、3 视频、3 音频，共 12 项（含角色 mod 和配音轨）。英文提示词上限 7000 字符。</small><p className="muted">{workflow.name||'本地 H3 工作流'} · {workflow.ready?'工作流已连接':workflow.error||'检查工作流连接'}</p>
  </details>
  {next&&<footer className="h3-stage-footer"><small>{ready?'参考确认后即可继续。':'未完成的定稿或参考需先补齐；提示词页会显示具体条件。'}</small><button className="primary" onClick={next}>下一步：H3 提示词 →</button></footer>}
 </section>;
}

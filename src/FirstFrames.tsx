import {Image as ImageIcon, Trash2, Check, RefreshCw} from 'lucide-react';
import {assetReferences} from './assetReferences';
type Obj=Record<string,any>;
type Props={project:Obj;shot:Obj;busy:boolean;generating?:boolean;compact?:boolean;manage?:()=>void;generate:()=>void;action:(action:string,media?:string,jump?:boolean)=>void;preview:(image:Obj)=>void};
const url=(name:string)=>'/media/'+encodeURIComponent(name);

export function FirstFrames({project,shot,busy,generating,compact=false,manage,generate,action,preview}:Props){
 const frames:Obj[]=[],seen=new Set<string>(),trash:Obj[]=shot.frame_trash||[];
 for(const m of shot.frames||[])if(m.media&&!seen.has(m.media)){frames.push(m);seen.add(m.media)}
 if(shot.first_frame&&!seen.has(shot.first_frame))frames.unshift(project.media.find((m:Obj)=>m.media===shot.first_frame)||{media:shot.first_frame});
 const binding=shot.frame_asset_binding,assets=project.assets.filter((a:Obj)=>shot.asset_ids?.includes(a.id));
 if(compact){const shown=frames.find(m=>m.media===shot.first_frame)||frames.at(-1);return <section className="first-frame-compact" aria-label="首帧缩略图">
  {shown?<><button className="frame-image-button" aria-label="放大本镜首帧" title="点击放大" onClick={()=>preview({...shown,kind:'image'})}><img src={url(shown.media)} alt={shot.first_frame?'已采用首帧':'首帧候选 · 待采用'}/></button><small>{shot.first_frame?'已采用首帧':'尚未采用 · 最新候选'} · {frames.length} 张</small></>:<span className="shot-cell-empty">尚无首帧</span>}
  {generating&&<small className="muted">新首帧生成中，已有候选保留</small>}
  <div className="row wrap"><button disabled={busy||!shot.native} onClick={generate}><ImageIcon size={13}/>{shown?'再生成':'生成首帧'}</button><button onClick={manage}>首帧管理{trash.length?' · 含已删除':''}</button></div>
 </section>}
 return <section className="first-frame-gallery" aria-label="首帧候选">
  <div className="first-frame-heading"><strong>首帧图片 <small>{frames.length} 张候选</small></strong></div>
  <p className="muted">{generating?'正在关联资产并生成新候选，已有图片继续保留。':shot.first_frame?'已采用一张首帧，可随时换选。':'生成后逐张预览，最终选择一张采用。'} 每次生成使用新随机种子。</p>
  {frames.length>0?<div className="first-frame-candidates">{frames.map((m,i)=><article className={'first-frame-candidate '+(shot.first_frame===m.media?'adopted':'')} key={m.media}>
   <button className="frame-image-button" aria-label={'预览首帧候选 '+(i+1)} onClick={()=>preview({...m,kind:'image'})}><img src={url(m.media)} alt={'首帧候选 '+(i+1)}/></button>
   <small>候选 {i+1}{m.seed!=null?' · 种子 '+m.seed:''}{m.stale?' · 生成依据已变更':''}</small>
   <div className="row wrap"><button className={shot.first_frame===m.media?'primary':''} disabled={busy||shot.first_frame===m.media} onClick={()=>action('adopt',m.media)}><Check size={13}/>{shot.first_frame===m.media?'已采用首帧':'采用首帧'}</button><button className="icon" disabled={busy} aria-label={'删除首帧候选 '+(i+1)} title="从本镜候选中删除，可恢复" onClick={()=>action('remove',m.media)}><Trash2 size={15}/></button></div>
   <button disabled={busy} onClick={()=>action('adopt',m.media,true)}>采用并进入 H3</button>
  </article>)}</div>:<div className="first-frame-empty"><ImageIcon size={24}/><span>尚无首帧图片</span></div>}
  {shot.first_frame&&<button disabled={busy} onClick={()=>action('clear')}>取消首帧采用</button>}
  <details className="frame-existing"><summary>从项目图片选择首帧</summary><label>采用已有图片<select disabled={busy} value={shot.first_frame||''} onChange={e=>action(e.target.value?'adopt':'clear',e.target.value||undefined)}><option value="">不采用首帧</option>{project.media.filter((m:Obj)=>m.kind==='image'&&!trash.some(r=>r.media===m.media)).map((m:Obj)=><option key={m.id||m.media} value={m.media}>{m.name||m.media}</option>)}</select></label></details>
  {binding&&<details className="frame-association"><summary>AI 关联资产 · {assets.length} 个元素 · {assets.reduce((n:number,a:Obj)=>n+assetReferences(a).length,0)} 张可用参考</summary>{assets.map((a:Obj)=><p key={a.id}><strong>{a.name}</strong> · {assetReferences(a).length} 张参考<br/><small>{binding.bindings?.find((b:Obj)=>b.asset_id===a.id)?.usage||'用户保留的手动绑定'}</small></p>)}<small className="muted">分镜与资产设定相同时复用关联；手动勾选或排除可在“编辑与时序”调整。</small></details>}
  {trash.length>0&&<details className="frame-trash"><summary>已删除首帧 · {trash.length} 张</summary>{trash.map((m,i)=><div className="frame-trash-row" key={m.media}><button className="frame-image-button" onClick={()=>preview({...m,kind:'image'})}><img src={url(m.media)} alt={'已删除首帧 '+(i+1)}/></button><button disabled={busy} onClick={()=>action('restore',m.media)}><RefreshCw size={13}/>恢复候选</button></div>)}</details>}
 </section>;
}

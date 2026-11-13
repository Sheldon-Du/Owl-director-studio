import {VideoCompare} from './VideoCompare';
type Obj=Record<string,any>;
export const adoptedVideos=(shot:Obj)=>(shot.outputs||[]).filter((m:Obj)=>shot.adopted_video_ids?.includes(m.id));
export const canUpscale=(m:Obj)=>m.quality==='first'&&['480P','540P'].includes(m.resolution)&&m.seed!=null&&!!m.workflow_snapshot;

export function VideoVersions({shot,busy,adopt,upscale,addTimeline,exportVersion,showUpscale=true}:{shot:Obj;busy:boolean;adopt:(id:string,enabled:boolean)=>void;upscale:(m:Obj)=>void;addTimeline:(m:Obj)=>void;exportVersion:(m:Obj)=>void;showUpscale?:boolean}){
 const outputs=(shot.outputs||[]).filter((m:Obj)=>m.kind==='video');
 if(!outputs.length)return null;
 return <><VideoCompare shot={shot} busy={busy}/><details className="shot-video-versions" open><summary>视频版本 · {outputs.length} 条 · 已采用 {adoptedVideos(shot).length} 条</summary><p className="muted">同一时间段只能采用一版。多步镜头可分别选择各段；生成新版会追加保留。</p><div className="video-version-list">{[...outputs].reverse().map((m:Obj)=>{const selected=shot.adopted_video_ids?.includes(m.id),start=Number(m.source_offset||0),duration=Number(m.duration||shot.duration);return <article key={m.id} className={'video-version '+(selected?'adopted':'')}>
  <div className="version-adopt-heading"><strong>版本 {outputs.indexOf(m)+1}</strong><button className={selected?'adopted-button':'primary'} aria-pressed={!!selected} disabled={busy} onClick={()=>adopt(m.id,!selected)}>{selected?'✓ 已采用 · 点击取消':'采用此版本'}</button></div>
  <small>{m.quality==='second'?'二采放大':'一采预览'} · {m.resolution||'原始规格'} · {start.toFixed(2)}–{(start+duration).toFixed(2)} 秒{m.stale?' · 旧生成依据':''}</small>
  <small>固定种子：{m.seed??'未记录'}{m.source_output_id?' · 沿用已采用一采版本':''}</small>
  <video controls preload="metadata" src={'/media/'+encodeURIComponent(m.media)}/>
  <div className="row wrap"><a href={'/media/'+encodeURIComponent(m.media)} download>下载</a><button onClick={()=>addTimeline(m)}>加入剪辑</button>{m.workflow_snapshot&&<button disabled={busy} onClick={()=>exportVersion(m)}>导出此版本工作流</button>}{showUpscale&&canUpscale(m)&&<button disabled={busy||!selected} title={selected?'按本版本固定种子进行固定一采参数二采':'请先勾选采用此版本'} onClick={()=>upscale(m)}>二采放大</button>}</div>
 </article>})}</div></details></>;
}

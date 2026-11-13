import {adoptedVideos} from './VideoVersions';
type Obj=Record<string,any>;
export function ShotVideos({shot,manage}:{shot:Obj;manage:()=>void}){
 const outputs=(shot.outputs||[]).filter((m:Obj)=>m.kind==='video'&&m.media);
 const chosen=adoptedVideos(shot).filter((m:Obj)=>m.kind==='video');
 const shown=chosen.at(-1)||outputs.at(-1);
 if(!shown)return <span className="shot-cell-empty">生成视频后展示</span>;
 return <section className="shot-video-summary" aria-label="本镜视频成片">
  <video controls preload="metadata" src={'/media/'+encodeURIComponent(shown.media)}/>
  <small>{chosen.length?'已采用版本':'最新版本 · 待采用'} · {shown.resolution||'原始规格'}</small>
  <small>种子：{shown.seed??'未记录'}</small>
  <button onClick={manage}>查看 / 选择视频版本 · {outputs.length} 条</button>
 </section>;
}

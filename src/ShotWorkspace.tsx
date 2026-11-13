import {useRef,useState,type ReactNode} from 'react';
import {Clapperboard,Image,SlidersHorizontal} from 'lucide-react';
import {ShotTimeline} from './SpeechMixer';
import {ShotReferenceButton} from './ShotReferenceButton';
import {ShotPromptSources} from './ShotPromptSources';
import {ShotStageSummary} from './ShotStageSummary';
import {SeedanceShotEditor} from './SeedanceShots';
import './shot-workspace.css';

type Obj=Record<string,any>;
type Props={
 project:Obj;catalog:Obj;busy:boolean;taskBusy:boolean;selectedId:string;
 select:(id:string)=>void;
 editShot:(id:string,changes:Obj)=>void;
 save:()=>Promise<Obj>;changed:(p:Obj)=>void;notify:(s:string)=>void;
 sync:(id?:string)=>ReactNode;
 openManual:(id:string)=>void;openFrames:(id:string)=>void;
 openH3:(id:string)=>void;openVideo:(id:string)=>void;
};
const frames=[['first_frame','首帧'],['adopted_keyframe','关键帧'],['adopted_tailframe','尾帧']];
const media=(name:string)=>'/media/'+encodeURIComponent(name);

export function ShotWorkspace(props:Props){
 const {project,catalog,busy,taskBusy,selectedId,select,editShot,save,changed,notify,sync,openManual,openFrames,openH3,openVideo}=props;
 const [section,setSection]=useState<'shot'|'timeline'>('shot');
 const [frame,setFrame]=useState('');
 const [advanced,setAdvanced]=useState(false);
 const [batch,setBatch]=useState(false);
 const [timelineVisited,setTimelineVisited]=useState(false);
 const registry=useRef<Obj>({});
 const shots:Obj[]=project.shots;
 const shot=shots.find(row=>row.id===selectedId)||shots[0];
 const index=shots.indexOf(shot);
 const canLeave=()=>!registry.current[shot?.id]?.dirty||window.confirm('本镜时序有未保存的修改，是否离开？');
 const choose=(id:string)=>{
  if(id===shot.id)return;
  if(!canLeave())return;
  delete registry.current[shot.id];
  select(id);
  setFrame('');
 };
 const assets=shot?project.assets.filter((asset:Obj)=>shot.asset_ids?.includes(asset.id)):[];
 const previewFrame=frame||frames.find(([key])=>shot?.[key])?.[0]||'first_frame';
 const picture=shot?.[previewFrame];
 const timelineProps={project,busy,save,changed,notify,openH3,registry};

 return <section className="panel shot-desk" aria-label="镜头编排">
  <div className="section-title">
   <div><h2>镜头编排</h2><small className="muted">{shots.length} 镜</small></div>
   <div className="row wrap">
    <ShotReferenceButton/>
    <button onClick={()=>{if(canLeave())openH3('')}}><Clapperboard size={16}/>H3 视频</button>
   </div>
  </div>
  {!shot?<p className="muted">在创作概览生成分镜后，即可在这里逐镜编排。</p>:<>
   <nav className="shot-desk-strip" aria-label="镜头列表">
    {shots.map((row,i)=>{
     const thumbnail=row.first_frame||row.adopted_keyframe||row.adopted_tailframe;
     return <button key={row.id} aria-current={row.id===shot.id?'true':undefined} onClick={()=>choose(row.id)} title={row.description}>
      {thumbnail?<img src={media(thumbnail)} alt="" loading="lazy"/>:<Image size={18} aria-hidden="true"/>}
      <span>第 {i+1} 镜 <small>{Number(row.duration).toFixed(1)} 秒</small></span>
     </button>;
    })}
   </nav>
   <div className="shot-desk-toolbar">
    <div className="mode-tabs" aria-label="本镜编辑区域">
     <button className={section==='shot'?'active':''} aria-pressed={section==='shot'} onClick={()=>setSection('shot')}>镜头内容</button>
     <button className={section==='timeline'?'active':''} aria-pressed={section==='timeline'} onClick={()=>{setTimelineVisited(true);setSection('timeline')}}>对白与时序</button>
    </div>
    <div className="row wrap">
     <button onClick={()=>setAdvanced(true)}><SlidersHorizontal size={15}/>提示词与绑定</button>
     <button className="primary" disabled={busy} onClick={()=>{if(canLeave())openH3(shot.id)}}>制作视频</button>
    </div>
   </div>
   <div className="shot-desk-columns" hidden={section!=='shot'}>
    <aside className="shot-desk-assets">
     <h3>本镜资产</h3>
     {assets.length?assets.map((asset:Obj)=><div className="shot-desk-asset" key={asset.id}>
      {asset.adopted&&<img src={media(asset.adopted)} alt="" loading="lazy"/>}
      <div><strong>{asset.name}</strong><small className="muted">{asset.kind==='character'?'角色':asset.kind==='scene'?'场景':'道具'}</small></div>
     </div>):<small className="muted">暂无关联资产</small>}
    </aside>
    <div className="shot-desk-writing">
     <div className="shot-desk-toolbar"><h3>第 {index+1} 镜</h3><span className="pill">{Number(shot.duration).toFixed(1)} 秒</span></div>
     <label>画面与动作<textarea rows={7} value={shot.description||''} onChange={event=>editShot(shot.id,{description:event.target.value})}/></label>
     <ShotReferenceButton key={shot.id} selectedIds={shot.shot_reference_ids||[]} onSelect={ids=>editShot(shot.id,{shot_reference_ids:ids})}/>
     <details><summary>查看现有提示词</summary><ShotPromptSources project={project} shot={shot} notify={notify}/></details>
    </div>
    <aside className="shot-desk-frames">
     <h3>帧预览</h3>
     <div className="shot-desk-picture">{picture?<img src={media(picture)} alt={frames.find(([key])=>key===previewFrame)?.[1]}/>:<span className="muted">尚未采用帧图</span>}</div>
     <div className="mode-tabs" aria-label="切换预览帧">{frames.map(([key,label])=><button key={key} aria-pressed={previewFrame===key} className={previewFrame===key?'active':''} onClick={()=>setFrame(key)}>{label}</button>)}</div>
     <div className="row wrap"><button onClick={()=>{if(canLeave())openFrames(shot.id)}}>管理帧图</button>{shot.outputs?.length>0&&<button onClick={()=>openVideo(shot.id)}>视频版本</button>}</div>
    </aside>
   </div>
   {(timelineVisited||batch)&&<div hidden={section!=='timeline'}>
    <ShotTimeline key={shot.id} {...timelineProps} shot={shot}/>
    <button onClick={()=>openManual(shot.id)}>手动编辑动作与时长</button>
   </div>}
   <details className="shot-desk-batch" onToggle={event=>setBatch(event.currentTarget.open)}>
    <summary>批量编排与同步</summary>
    {batch&&<>
     {sync()}
     <ShotStageSummary project={project} registry={registry} save={save} notify={notify} busy={busy} selectShot={id=>{choose(id);setTimelineVisited(true);setSection('timeline')}}/>
     <div hidden>{shots.filter(row=>row.id!==shot.id).map(row=><ShotTimeline key={row.id} {...timelineProps} shot={row}/>)}</div>
    </>}
   </details>
   {advanced&&<SeedanceShotEditor key={shot.id} project={project} shot={shot} catalog={catalog} busy={taskBusy} save={save} changed={changed} notify={notify} close={()=>setAdvanced(false)} syncButton={sync(shot.id)} openH3={openH3}/>}
  </>}
 </section>;
}

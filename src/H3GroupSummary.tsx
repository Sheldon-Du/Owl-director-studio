import {useState,useEffect} from 'react';
import {h3Segments,h3VideoShot,h3Group,h3GroupRunning} from './h3Groups';
import {jsonApi as api} from './jsonApi';
import './h3-groups.css';

type Obj=Record<string,any>;
type Props={tasks:Obj[];edit:(fn:(p:Obj)=>void)=>void;project:Obj;busy:boolean;selectedId:string;openVideo:(id:string)=>void;select:(id:string)=>void;save:()=>Promise<Obj>;changed:(p:Obj)=>void;notify:(message:string)=>void};

export function H3GroupSummary({tasks,edit,project,busy,selectedId,openVideo,select,save,changed,notify}:Props){
 const [working,setWorking]=useState(false);
 const groups=h3Segments(project);
 useEffect(()=>{if(busy)return;const automatic=project.h3_settings?.automatic_defaults===1;
 if(!automatic)edit(p=>{p.h3_settings={...p.h3_settings,automatic_defaults:1,max_step_seconds:30};for(const s of p.shots){s.h3_reference_mode='auto';s.h3_frame_roles=['first','keyframe','tail'];s.h3_audio_mode='generated';s.h3_motion='auto';s.h3_texture='auto'}});
 },[project.id,project.h3_settings?.automatic_defaults,busy]);
 const palette=[{ink:'#a8deca',bg:'#203e37'},{ink:'#a9ccf5',bg:'#263b55'},{ink:'#e2bbef',bg:'#45304e'},{ink:'#ebcd96',bg:'#4a3e28'},{ink:'#ebaebc',bg:'#4b303c'},{ink:'#aedef0',bg:'#25424b'}];
 const groupColor=(group:Obj)=>palette[Math.max(0,(project.h3_shot_groups||[]).findIndex((row:Obj)=>row.id===group.id))%palette.length];

 const [picking,setPicking]=useState(false),[picked,setPicked]=useState<string[]>([]);
 useEffect(()=>{setPicked([]);setPicking(false)},[project.id]);
 const availableKey=project.shots.filter((s:Obj)=>!h3Group(project,s.id)&&!s.merged_from).map((s:Obj)=>s.id).join(',');
 useEffect(()=>{const available=new Set(availableKey.split(','));setPicked(prior=>{const next=prior.filter(id=>available.has(id));return next.length===prior.length?prior:next})},[availableKey]);
 const chosen=project.shots.filter((s:Obj)=>picked.includes(s.id)),positions=chosen.map((s:Obj)=>project.shots.indexOf(s)),seconds=chosen.reduce((n:number,s:Obj)=>n+Number(s.duration||0),0),maximum=Number(project.h3_settings?.max_step_seconds||30);
 const [scale,setScale]=useState(22);
 const totalSeconds=project.shots.reduce((sum:number,shot:Obj)=>sum+Number(shot.duration||0),0);
 const shotStart=(index:number)=>project.shots.slice(0,index).reduce((sum:number,shot:Obj)=>sum+Number(shot.duration||0),0);
 const tickStep=scale<18?10:5;
 const adjacent=positions.every((n:number,i:number)=>!i||n===positions[i-1]+1);
 const combine=async()=>{setWorking(true);try{const p=await save();const result=await api(`/projects/${p.id}/authoring/merge-shots`,{revision:p.revision,ids:chosen.map((s:Obj)=>s.id)});changed(result.project);setPicked([]);setPicking(true);notify('已建立 H3 分组，可以继续选择下一组分镜')}catch(e){notify((e as Error).message)}finally{setWorking(false)}};

 const remove=async(groupId:string)=>{setWorking(true);try{const p=await save();const result=await api(`/projects/${p.id}/authoring/ungroup-shots`,{revision:p.revision,group_id:groupId});changed(result.project);select('');notify('已拆开本组，其他 H3 分组不变；原始分镜与三帧保留')}catch(error){notify((error as Error).message)}finally{setWorking(false)}};
 return <section className="panel h3-group-overview" aria-label="H3 分组汇总与视频">
  <div className="section-title"><div><h2>H3 分组汇总</h2><p className="muted">选择分组，核对参考、转写提示词并生成视频。</p></div></div>
  <div className="row wrap"><button aria-expanded={picking} disabled={busy||working} onClick={()=>setPicking(!picking)}>{picking?'收起分镜选择':'选择 H3 分组'}</button><small className="muted">选择连续分镜组合；建立后可继续选择下一组，清空选择只取消当前勾选。</small></div>
  {picking&&<section aria-label="组合 H3 分镜" style={{padding:12,border:'1px solid #344057',borderRadius:10,margin:'12px 0'}}><div className="row wrap" style={{marginBottom:10}}><strong>全片分镜时间轴 · {Number(totalSeconds.toFixed(2))} 秒</strong><label style={{display:'flex',alignItems:'center',gap:8}}>缩放<input aria-label="H3 分镜时间轴缩放" type="range" min={10} max={60} value={scale} onChange={e=>setScale(+e.target.value)}/></label><small className="muted">片段宽度对应实际时长；同组同色，点击未分组片段进行组合。</small></div><div style={{overflowX:'auto',paddingBottom:12}}><div style={{width:Math.max(1,totalSeconds*scale),minWidth:'100%'}}><div aria-label="全片时间刻度" style={{height:30,position:'relative',borderBottom:'1px solid #526078'}}>{Array.from({length:Math.floor(totalSeconds/tickStep)+1},(_,i)=><span key={i} style={{position:'absolute',left:i*tickStep*scale,fontSize:12,color:'#aab7c9',borderLeft:'1px solid #526078',paddingLeft:4}}>{i*tickStep}s</span>)}</div><div style={{display:'flex',height:96,gap:0}}>{project.shots.map((shot:Obj,i:number)=>{const group=h3Group(project,shot.id),color=group?groupColor(group):picked.includes(shot.id)?{ink:'#e0ceff',bg:'#423456'}:{ink:'#abb5c7',bg:'#222a38'};return <label key={shot.id} title={`第${i+1}镜 · ${shotStart(i).toFixed(2)}–${(shotStart(i)+Number(shot.duration)).toFixed(2)}秒 · ${Number(shot.duration).toFixed(2)}秒${group?' · 已分组':''}`} style={{boxSizing:'border-box',flex:'0 0 '+Number(shot.duration)*scale+'px',width:Number(shot.duration)*scale,overflow:'hidden',display:'flex',flexDirection:'column',alignItems:'flex-start',justifyContent:'center',gap:4,padding:'6px',border:'1px solid '+color.ink+'88',borderRadius:5,color:color.ink,background:color.bg,opacity:1,cursor:group?'default':'pointer',fontSize:12,whiteSpace:'nowrap'}}><input type="checkbox" aria-label={`组合分镜 ${i+1}`} disabled={busy||working||!!group||!!shot.merged_from} checked={picked.includes(shot.id)} onChange={e=>setPicked(e.target.checked?[...picked,shot.id]:picked.filter(id=>id!==shot.id))}/>分镜 {i+1} · {Number(shot.duration).toFixed(2)} 秒{group?` · H3 组${groups.findIndex((row:Obj)=>row.group?.id===group.id)+1}`:picked.includes(shot.id)?' · 已选择':' · 未分组'}</label>})}</div></div></div><div className="row wrap" style={{marginTop:12}}><strong>已选 {chosen.length} 镜 · {Number(seconds.toFixed(2))} / {maximum} 秒</strong><button className="primary" disabled={busy||working||chosen.length<2||!adjacent||seconds>maximum} onClick={combine}>组合为 H3 分组</button><button disabled={!picked.length||working} onClick={()=>setPicked([])}>清空选择</button>{chosen.length>1&&!adjacent&&<small>请选择连续相邻分镜</small>}{seconds>maximum&&<small>超过单次时长上限，请减少分镜</small>}</div></section>}
  {!groups.length&&<p className="muted">先在创作概览生成分镜。</p>}
  {groups.map((segment:Obj,i:number)=>{const first=segment.shots[0],output=project.documents.h3_shots?.[first.id],videos=h3VideoShot(project,first.id).outputs.length,groupRunning=h3GroupRunning(tasks,project.id,segment.shots);return <article className={'h3-group-row'+(selectedId===first.id?' selected':'')} key={first.id} style={segment.group?{borderLeft:'4px solid '+groupColor(segment.group).ink}:undefined}>
   <div className="h3-group-info"><strong style={segment.group?{color:groupColor(segment.group).ink,background:groupColor(segment.group).bg,padding:'5px 9px',borderRadius:6}:undefined}>H3 组{i+1}（{segment.duration}秒）</strong><div className="h3-group-members">{segment.shots.map((shot:Obj,j:number)=><span key={shot.id}>分镜{segment.indices[j]}（{shot.duration}秒）</span>)}</div><small className="muted">累计 {segment.start}–{segment.end} 秒{!segment.group?' · 独立分镜':''}</small><small>{output?'已有 H3 提示词 · 生成前核对当前依据':'待转写 H3 提示词'}</small>
   </div>
   <div className="row wrap h3-group-actions">
    <button className="primary" onClick={()=>select(first.id)}>打开制作</button>
    {videos>0&&<button onClick={()=>openVideo(first.id)}>视频版本 · {videos}</button>}
    {segment.group&&<button disabled={busy||working||groupRunning} onClick={()=>remove(segment.group.id)}>拆开本组</button>}
   </div>
  </article>})}
 </section>;
}

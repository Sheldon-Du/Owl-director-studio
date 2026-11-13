import {createPortal} from 'react-dom';
import {CopyMark,RevisionInput} from './StudioTools';
import {H3Setup} from './H3Setup';
import {h3Group,h3Leader,h3Segments,h3VideoShot,h3GroupRunning} from './h3Groups';
import {productionReady} from './productionSource';
import React, {useEffect,useState} from 'react';
import {Clapperboard, Download, WandSparkles} from 'lucide-react';
import {assetReferences} from './assetReferences';
import {VideoVersions} from './VideoVersions';
type Obj=Record<string,any>;
type Props={tasks:Obj[];save:()=>Promise<Obj>;notify:(message:string)=>void;batchRewrite:()=>void;project:Obj;busy:boolean;edit:(fn:(p:any)=>void)=>void;job:(kind:string,target?:string,options?:Obj)=>void;workflow:Obj;addTimeline:(media:Obj)=>void;shotId:string;selectShot:(id:string)=>void;reviewShot:(id:string)=>void;previousTail:(id:string)=>void;manageVideo?:(id:string)=>void;adoptVideo?:(shotId:string,outputId:string,enabled:boolean)=>void;studio?:boolean;compact?:boolean;upscaleRecord?:Obj|null;upscaleHandled?:()=>void};

export function H3Panel({tasks,save,notify,batchRewrite,project,busy,edit,job,workflow,addTimeline,shotId:requestedShotId,selectShot,reviewShot,previousTail,adoptVideo,manageVideo,studio=false,compact=false,upscaleRecord,upscaleHandled}:Props){
 const shotId=requestedShotId==='__film__'?'':h3Leader(project,requestedShotId);
 const group=h3Group(project,shotId);
 const groupShots=group?group.shot_ids.map((id:string)=>project.shots.find((s:Obj)=>s.id===id)).filter(Boolean):project.shots.filter((s:Obj)=>s.id===shotId);
 const selected=project.shots.find((s:Obj)=>s.id===shotId);
 const output=shotId?project.documents.h3_shots?.[shotId]:project.documents.h3;
 const [studioTab,setStudioTab]=useState<'setup'|'prompts'|'video'>('setup');
 useEffect(()=>setStudioTab('setup'),[requestedShotId,project.id]);

 const [secondPass,setSecondPass]=useState<Obj|null>(null);
 useEffect(()=>{if(upscaleRecord){setSecondPass(upscaleRecord);upscaleHandled?.()}},[upscaleRecord?.id]);
 const history=(selected?.outputs||[]).filter((m:Obj)=>m.h3_step!=null&&m.seed!=null);
 const exportVersion=(m:Obj)=>job('export',String(m.h3_step),{format:'h3_workflow',quality:'first',resolution:'540P',seed:m.seed,workflow_snapshot:m.workflow_snapshot});
 const state=project.storyboard_generation;
 const current=selected&&groupShots.every((s:Obj)=>state?state.status!=='stale'&&s.generation_source_hash===state.source_hash:project.native_storyboard_current);
 const reviewed=selected&&groupShots.every((s:Obj)=>['human_reviewed','ai_reviewed'].includes(s.natural_status)&&s.timing_suggestion?.status!=='pending');

 const options=({resolution:'540P',quality:'first',...(shotId?{scope_shot:shotId}:{})});
 const stages=selected?['frame','keyframe'].flatMap(mode=>{const plan=selected.image_plans?.[mode];return plan?.references?.length?[{mode,references:plan.references,relationship:plan.relationship}]:[]}):[];
 const refs=stages.length?stages.flatMap(stage=>stage.references):selected?project.assets.filter((a:Obj)=>selected.asset_ids?.includes(a.id)).flatMap(assetReferences):[];
 const referenceReady=!selected||selected.h3_reference_mode==='assets'?(!selected||project.assets.length>0):stages.length?true:selected.h3_reference_mode==='first_frame'?!!selected.first_frame:selected.h3_reference_mode==='previous_tail'?!!selected.first_frame&&selected.previous_tail_reference?.media===selected.first_frame:true;
 const groupRunning=h3GroupRunning(tasks,project.id,groupShots);
 const ready=!busy&&!groupRunning&&productionReady(project)&&(shotId?current&&reviewed&&referenceReady:project.confirmed&&project.native_storyboard_current);
 const changeMode=(value:string)=>edit(p=>{p.shots.find((s:Obj)=>s.id===shotId).h3_reference_mode=value;p.confirmed=false});
 const previousIndex=selected?project.shots.indexOf(selected)-1:-1;

 const segmentIndex=h3Segments(project).findIndex((segment:Obj)=>segment.shots[0].id===shotId);
 const title=selected?`H3 组${segmentIndex+1}（${groupShots.reduce((n:number,s:Obj)=>n+Number(s.duration||0),0)}秒）`:'全片高级制作';
 const videos=selected?h3VideoShot(project,selected.id).outputs:[];

 const stageNames=[['setup','参考与参数'],['prompts','H3 提示词'],['video','生成视频']];
 useEffect(()=>{if(!studio)return;const close=(e:KeyboardEvent)=>{if(e.key==='Escape')selectShot('')};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close)},[studio,requestedShotId]);
 if(studio&&!requestedShotId)return null;
 const content=<>
 {studio&&<><header className="h3-studio-heading"><div><small className="muted">H3 分组制作</small><h2>{title}</h2><p className="muted">{selected?groupShots.map((s:Obj)=>`分镜${project.shots.indexOf(s)+1}（${s.duration}秒）`).join(' → '):'全片按时长上限拆分任务'}</p></div><button onClick={()=>selectShot('')}>返回分组列表</button></header>
 <nav className="h3-stage-nav" aria-label="本组制作步骤">{stageNames.map(([key,label],i)=><button key={key} className={studioTab===key?'active':''} aria-current={studioTab===key?'step':undefined} onClick={()=>setStudioTab(key as typeof studioTab)}><b>{i+1}</b><span>{label}<small>{key==='setup'?(reviewed?'时序已审定':'检查参考与时序'):key==='prompts'?(output?'已转写 · 可核对':'待转写'):videos.length?`${videos.length}个视频版本`:'待生成视频'}</small></span></button>)}</nav>
 <label className="h3-studio-scope">当前制作组<select value={shotId} onChange={e=>selectShot(e.target.value||'__film__')}>{h3Segments(project).map((segment:Obj,i:number)=><option key={segment.shots[0].id} value={segment.shots[0].id}>H3 组{i+1}（{segment.duration}秒）· 分镜{segment.indices.join('、')}</option>)}</select></label></>}
 {(!studio||studioTab==='setup')&&<>
 <H3Setup project={project} shots={groupShots} busy={busy} edit={edit} review={reviewShot} previousTail={previousTail} workflow={workflow} ready={!!ready} next={studio?()=>setStudioTab('prompts'):undefined}/>
 </>}
 {(!studio||studioTab==='prompts')&&<>
  <div className="section-title"><div>{compact?<h3>H3 prompt</h3>:<h2>{studio?'2 · 转写与核对 H3 提示词':'H3 中文提示词与视频'}</h2>}</div>{compact&&<button onClick={()=>selectShot('')}>收起提示词</button>}<button className="primary" disabled={!ready} onClick={()=>shotId?job('h3',shotId):batchRewrite()}><WandSparkles size={16}/>{shotId?(output?'重新生成提示词':'生成提示词'):'转写全片 H3 提示词'}</button></div>
  {(project.documents.h3_conflict_drafts||[]).filter((d:Obj)=>(d.scope_shot||'')===shotId).length>0&&<details className="note"><summary>已保留的冲突转写草稿 · 可查看与复制</summary><p>草稿使用生成时的旧依据，尚未采用。请核对变化项后重新转写当前镜头。</p>{(project.documents.h3_conflict_drafts||[]).filter((d:Obj)=>(d.scope_shot||'')===shotId).slice().reverse().map((d:Obj)=><details key={d.task_id}><summary>{new Date(d.created*1000).toLocaleString('zh-CN')} · {d.reason}</summary>{d.result.steps.map((step:Obj)=><div key={step.index}><strong>第{step.index}步 · {step.duration}秒</strong><pre className="document">{step.prompt}</pre><pre className="document">{step.prompt_zh}</pre></div>)}</details>)}</details>}
  {!shotId&&(!project.confirmed||!project.native_storyboard_current)&&<div className="note">全片模式需要完成并确认全部分镜。也可在上方选择已完成的单镜，直接继续 H3。</div>}
 {studio&&selected&&groupRunning&&<p role="status" className="note">本组任务执行中。</p>}
 {studio&&selected&&!ready&&!busy&&!groupRunning&&<div className="note">请先在“参考与参数”完成本组每镜的时序审定和参考检查，再生成提示词。<button onClick={()=>setStudioTab('setup')}>返回检查参考与时序</button></div>}
 </>}
 {!studio&&<>  {!compact&&<label>生成范围<select value={shotId} onChange={e=>selectShot(e.target.value)}><option value="">全片 · 全部分镜确认后使用</option>{h3Segments(project).map((segment:Obj,i:number)=><option key={segment.shots[0].id} value={segment.shots[0].id}>H3 组{i+1}（{segment.duration}秒）· 分镜{segment.indices.join('、')}</option>)}</select></label>}
</>}
 {studio&&studioTab==='video'&&groupRunning&&<p role="status" className="note">本组任务执行中。</p>}
 {studio&&studioTab==='video'&&selected&&!ready&&!busy&&!groupRunning&&<div className="note">{!current?'本组分镜依据已变化，请先更新分镜。':!reviewed?'本组仍有分镜未审定自然时序。':'请先检查本组参考与生成条件。'}<button onClick={()=>setStudioTab('setup')}>返回参考与参数</button></div>}
 {studio&&studioTab==='video'&&<div className="h3-stage-intro"><h3>3 · 生成视频</h3></div>}
 {(!studio||studioTab!=='setup')&&<>
  {output&&<><div className="row wrap"><span className="pill">{shotId?(group?'本组':'本镜'):'全片'} · {output.steps.length} 步 · {output.total_duration.toFixed(2)} 秒</span></div>
  {output.steps.map((s:Obj)=><article className="h3-step" key={(shotId||'film')+s.index}>
   <h3>任务 {s.index} · {s.start.toFixed(2)}–{s.end.toFixed(2)} 秒 · {s.mode}</h3><p className="muted">{s.duration.toFixed(2)} 秒 · {s.audio_binding?'固定实测配音轨 · 高质量数字人-minimaxh3':'图像与声音同步生成'}</p>
   {(!studio||studioTab==='prompts')&&s.references.length>0&&<div className="row wrap">{s.references.map((r:Obj)=><div className="h3-reference" key={r.label}>{r.media_type==='audio'?<audio controls preload="none" src={'/media/'+encodeURIComponent(r.media)}/>:<img src={'/media/'+encodeURIComponent(r.media)} alt={r.label}/>} <small>{r.label}</small></div>)}</div>}
   {(!studio||studioTab==='prompts')&&<><label className="copy-surface"><CopyMark text={s.prompt||''}/>H3 prompt · {String(s.prompt||'').length.toLocaleString('zh-CN')} 字符<textarea readOnly rows={compact?8:12} value={s.prompt}/></label>{selected&&<details><summary>修改提示词</summary><RevisionInput kind="h3" target={shotId} index={s.index} project={project} save={save} notify={notify}/></details>}</>}
   {s.duration<4&&<p className="note">本镜 {s.duration} 秒：H3 按至少4秒提交，输出以正常速度裁至 {s.duration} 秒，不延长分镜、不慢放。</p>}

   {(!studio||studioTab==='video')&&<div className="action-bar"><button disabled={!ready||!workflow.ready} onClick={()=>job('export',String(s.index),{...options,format:'h3_workflow'})}><Download size={15}/>保存已填工作流</button>{!compact&&<><button className="primary" disabled={!ready||!workflow.ready||!s.prompt} onClick={()=>job('h3_generate',String(s.index),options)}><Clapperboard size={16}/>生成 540P 预览</button><button disabled={!ready||!workflow.ready||!s.prompt} onClick={()=>job('h3_generate',String(s.index),{...options,new_variant:true})}>换种子再试</button></>}</div>}
   {compact&&<small className="muted">使用本镜卡片的“H3 视频生成”按钮，每次采用随机种子并保留新视频。</small>}
   {(!studio||studioTab==='video')&&!selected&&(s.outputs||[]).length>0&&<div className="h3-results">{s.outputs.map((m:Obj)=><div key={m.id}><p>{m.quality==='second'?'历史二采视频':'一采预览'} · {m.resolution||'历史规格'} · {m.duration.toFixed(2)} 秒 · 种子 {m.seed??'旧任务未记录'}</p><video controls preload="metadata" src={'/media/'+encodeURIComponent(m.media)}/><div className="row wrap"><a href={'/media/'+encodeURIComponent(m.media)} download>下载视频</a><button onClick={()=>addTimeline(m)}>加入剪辑</button>{m.workflow_snapshot&&<button disabled={!ready} onClick={()=>job('export',String(s.index),{...options,format:'h3_workflow',seed:m.seed,workflow_snapshot:m.workflow_snapshot})}>导出此版本工作流</button>}</div></div>)}</div>}
   {(!studio||studioTab==='prompts')&&s.index<output.steps.length&&<div className="note"><strong>段间衔接</strong><p>{s.continuity_out}</p><p>下一步：{output.steps[s.index].continuity_in}</p></div>}
  </article>)}</>}
  {!output&&<p className="muted">转写完成后，H3 prompt 会显示在此处；核对后再生成视频。</p>}
</>}
 {studio&&studioTab==='prompts'&&<footer className="h3-stage-footer"><button onClick={()=>setStudioTab('setup')}>← 参考与参数</button><button className="primary" disabled={!output} onClick={()=>setStudioTab('video')}>下一步：生成视频 →</button></footer>}
 {(!studio||studioTab==='video')&&<>
  {!studio&&selected&&adoptVideo&&<section className="h3-version-stage"><h3>{group?'本组':'本镜'}视频版本与二采放大</h3><p className="muted">先勾选采用一采版本，再按该版本固定种子二采放大。采用后显示在分组列表中；下载或加入剪辑后可继续制作下一组。</p><VideoVersions shot={h3VideoShot(project,selected.id)} busy={busy} adopt={(id,enabled)=>adoptVideo(selected.id,id,enabled)} upscale={setSecondPass} addTimeline={addTimeline} exportVersion={exportVersion}/>{!h3VideoShot(project,selected.id).outputs?.length&&<p className="muted">生成视频后，在这里选择最终采用版本并进行二采。</p>}</section>}
{studio&&selected&&<button onClick={()=>manageVideo?.(selected.id)}>查看视频版本／采用／二采</button>}{studio&&!output&&<button className="primary" onClick={()=>setStudioTab('prompts')}>先转写 H3 提示词</button>}</>}
  {secondPass&&<div className="modal-backdrop" onClick={e=>{if(e.target===e.currentTarget)setSecondPass(null)}}><section className="modal"><div className="modal-heading"><h2>二采放大 · 已采用版本</h2><button onClick={()=>setSecondPass(null)}>关闭</button></div><p>固定种子：<strong>{secondPass.seed}</strong></p><p>沿用这一版的工作流、提示词、时长与参考图，重新执行原分辨率一采（540P 为2倍，历史480P 为2.25倍）。分块按实际采样时长自动选择；横屏16:9输出1920×1080，竖屏按对应画幅输出。</p><p className="muted">生成后追加新版本，原视频及采用选择继续保留。</p><div className="row wrap"><button disabled={busy} onClick={()=>exportVersion(secondPass)}>导出原版本工作流</button><button className="primary" disabled={busy||!selected?.adopted_video_ids?.includes(secondPass.id)} onClick={()=>{job("h3_upscale",String(secondPass.h3_step),{scope_shot:shotId,source_output_id:secondPass.id});setSecondPass(null)}}>按固定种子生成1080P二采</button></div></section></div>}
 </>;
 return studio?createPortal(<div className="modal-backdrop h3-studio-backdrop" onClick={e=>{if(e.target===e.currentTarget)selectShot('')}}><section className="h3-studio-dialog" role="dialog" aria-modal="true" aria-label="H3 本组制作">{content}</section></div>,document.body):<div className="panel">{content}</div>;
}

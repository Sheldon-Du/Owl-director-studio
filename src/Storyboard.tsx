import {productionReady} from './productionSource';
import {Clapperboard, CheckCircle2, ListChecks} from 'lucide-react';
import type {ReactNode} from 'react';
import {TimingChanges} from './TimingGuidance';
import {ShotTable} from './ShotTable';
import {ContinuityReview} from './ContinuityReview';
type Obj=Record<string,any>;
type Props={project:Obj;busy?:boolean;edit?:(fn:(p:any)=>void)=>void;job?:(kind:string,target?:string,options?:Obj)=>void;renderFrames?:(shot:Obj)=>ReactNode;renderVideo?:(shot:Obj)=>ReactNode;renderShot?:(shot:Obj,index:number)=>ReactNode};

export function StoryboardProgress({project,busy=false,edit,job,renderShot,renderFrames,renderVideo}:Props){
 const state=project.storyboard_generation||{},outlines=state.outlines||[],correction=project.timing_revision||{};
 const draft=state.outline_draft,hasDraft=Boolean(draft&&state.status!=='stale');
 const active=['queued','running'].includes(state.status)||['queued','running'].includes(correction.status),ready=outlines.length>0&&state.status!=='stale'&&!hasDraft;
 const confirmed=ready&&(state.outline_confirmed??project.shots.length>0);
 const canPlan=!busy&&!active&&productionReady(project)&&project.production_scheme?.cinematic&&project.production_scheme?.art;
 const seconds=outlines.reduce((n:number,o:Obj)=>n+Number(o.natural_seconds||0),0);
 const estimates=outlines.filter((o:Obj)=>o.estimate_adjustment);
 return <section className="script-asset-stage" aria-label="分镜汇总与逐镜生成">
  <strong>分镜汇总 → 核对剧本 → 逐镜生成</strong>
  <p className="muted">先按叙事事件核对汇总。有旁白时先规划对应画面、原文依据和切镜理由，避免每句话另拆一镜或反复拍同一睡觉反应。逐镜生成时核对画面要点、完整原句与自然说话时间；有错只修对应字段。最后通过“时间修正”审定自然时长和正式时间标签。</p>
  {edit&&<label>汇总修订要求<textarea aria-label="汇总修订要求" rows={3} maxLength={6000} disabled={busy||active} value={project.storyboard_notes||''} placeholder="例如：把整场中开门、接信和出门按独立事件细分；地点或时间变化单列，完整对白只执行一次。" onChange={e=>edit(p=>{p.storyboard_notes=e.target.value;p.native_storyboard_current=false;p.confirmed=false;if(p.storyboard_generation)p.storyboard_generation.status='stale'})}/><small>保存后重新生成汇总。旧汇总、分镜和媒体保留在历史，新版需重新核对；修订要求不会改写已确认剧本。</small></label>}
  {state.message&&<p aria-live="polite">{state.message}</p>}
  {job&&<div className="row wrap">
   {!ready&&<button className="primary" disabled={!canPlan} onClick={()=>job('storyboard_outline',undefined,{force:!hasDraft})}><ListChecks size={16}/>{active?'正在准备分镜…':hasDraft?'继续生成汇总':'生成分镜汇总'}</button>}
   {hasDraft&&<button disabled={!canPlan} onClick={()=>job('storyboard_outline',undefined,{force:true})}>舍弃草稿并重新创建汇总</button>}
   {ready&&<button className="primary" disabled={!canPlan} onClick={()=>job('storyboard',undefined,confirmed?{}:{confirm_outline:true})}>{confirmed?<Clapperboard size={16}/>:<CheckCircle2 size={16}/>} {active?'正在执行…':!confirmed?'确认汇总并逐镜生成':project.native_storyboard_current?'检查并复用已完成分镜':state.completed>0?'继续生成未完成分镜':'按汇总逐镜生成'}</button>}
   {ready&&!confirmed&&<button disabled={!canPlan} onClick={()=>job('storyboard_confirm')}><CheckCircle2 size={16}/>{project.storyboard_method==='source_units'?'已核对原文、单元粒度与背景交付，确认汇总':'仅确认汇总'}</button>}
   {ready&&!confirmed&&project.storyboard_method==='source_units'&&<p className="muted">确认并生成表示你已核对剧情单元粒度、原文意义和背景交付。缓存中的“尚未执行／已执行”是程序记录；具体空间状态在单镜细化，实际画面和声音仍需采用后复核。</p>}
   {ready&&<details><summary>重新创建汇总</summary><p className="muted">按当前剧本重新规划。点击后，当前汇总及对应分镜立即移入历史，新汇总从空白开始，生成后重新核对确认。</p><button disabled={!canPlan} onClick={()=>job('storyboard_outline',undefined,{force:true})}>重新创建分镜汇总</button></details>}
  </div>}
  {hasDraft&&<div className="note"><strong>汇总草稿 · 旁白画面已保存 {draft.completed||0}/{draft.total||0} 套</strong><p className="muted">完整剧本的覆盖与顺序先统一核对，画面方案分批完善。中断后点击“继续生成汇总”，保留已保存结果；全部完成后再确认。</p>{draft.total>0&&<progress aria-label="汇总画面方案进度" max={draft.total} value={draft.completed||0}/>}<details><summary>查看已规划的 {draft.outlines?.length||0} 条汇总</summary>{(draft.outlines||[]).map((o:Obj)=><p key={o.id}>第 {o.index} 镜 · {o.location} · {o.focus} · {o.visual_plan?'画面已保存':o.speech_sources?.some((s:Obj)=>s.kind==='voiceover')?'画面待完善':'汇总已保存'}</p>)}</details></div>}
  {job&&<div className="storyboard-time-correction"><button disabled={busy||active||!project.native_storyboard_current||!project.shots.length} onClick={()=>job('storyboard_timing')}><ListChecks size={16}/>{['queued','running'].includes(correction.status)?'正在修正时间…':['failed','cancelled'].includes(correction.status)?'继续时间修正':'时间修正'}</button><p className="muted">完整分镜生成后，AI 按动作、对白、位移与反应重新审查自然时间，随后更新项目片长及各镜起止标签。已审查动作逐镜保存，中断后可继续。</p>{correction.message&&<p aria-live="polite">{correction.message}</p>}{correction.total>0&&<><progress aria-label="时间修正进度" max={correction.total} value={correction.completed||0}/><small>已审查 {correction.completed||0}/{correction.total} 镜 · 复用 {correction.reused||0} 镜</small></>}</div>}
  {ready&&<>
   <TimingChanges correction={correction}/>
   <p><span className="pill">{outlines.length} 条 · 预计 {seconds.toFixed(1)} 秒</span> <span className="pill">{confirmed?'汇总已确认':'待核对确认'}</span></p>
   {estimates.length>0&&<div className="note"><strong>{estimates.length} 条初估已按原文朗读下限校正</strong><p>完整原句需要更多说话时间，汇总已调整初估。具体画面动作、停顿与最终时长在逐镜生成时审定。</p><details><summary>查看初估调整</summary>{estimates.map((o:Obj)=><p key={o.id}>第 {o.index} 镜：{o.estimate_adjustment.ai_seconds} → {o.natural_seconds} 秒 · 原文朗读下限 {o.speech_min_seconds} 秒</p>)}</details></div>}
   {state.outline_review&&<small className="muted">剧本内容覆盖与银幕顺序已通过程序核对。预计时长按动作估算，具体镜头仍需审定自然时序。</small>}
   <ShotTable renderFrames={renderFrames} renderShot={renderShot} renderVideo={renderVideo} rows={outlines.map((o:Obj,i:number)=>{
    const saved=project.shots.find((s:Obj)=>s.generation_outline_id===o.id),prefixReady=outlines.slice(0,i).every((p:Obj)=>project.shots.some((s:Obj)=>s.generation_outline_id===p.id)),start=outlines.slice(0,i).reduce((n:number,p:Obj)=>n+Number(p.natural_seconds||0),0),label=correction.status==='completed'?correction.rows?.find((r:Obj)=>r.shot_id===o.id):null;
    const reason=!confirmed?'先确认分镜汇总':!prefixReady?'先完成前面的镜头，以衔接人物、空间和动作':saved?'只替换此镜，旧版本及视频种子保留':'本次只生成这一镜，完成即保存';
    return {id:o.id,index:o.index,location:o.location,focus:o.focus,shot:saved,
     timing:label?`${label.start.toFixed(1)}–${label.end.toFixed(1)} 秒 · 已修正`:`${start.toFixed(1)}–${(start+Number(o.natural_seconds)).toFixed(1)} 秒 · 初估`,
     actions:job&&<button disabled={!canPlan||!confirmed||!prefixReady} title={reason} onClick={()=>job('storyboard',o.id,{regenerate:!!saved})}><Clapperboard size={15}/>{saved?'重新生成此镜':'生成此镜'}</button>,
     details:<>{saved&&<ContinuityReview shot={saved} busy={busy} job={job}/>} {o.content_units&&<details><summary>剧情单元承载 · 执行 / 上下文 / 结果</summary>{o.unit_carriers.map((c:Obj)=>{const u=o.content_units.find((v:Obj)=>v.id===c.unit_id);return <p key={c.unit_id}><strong>{({execute:"本镜执行",context:"仅作上下文",result:"仅呈现结果"} as Obj)[c.mode]}</strong> · {u?.quote}<small className="muted">{u?.start_state} → {u?.end_state} · {u?.story_time}</small></p>})}</details>}{o.visual_plan&&<details><summary>旁白与画面方案 · {o.visual_plan.time_context}</summary><p>{o.visual_plan.image}</p><p className="muted">画面作用：{o.visual_plan.purpose}</p><p className="muted">切镜理由：{o.visual_plan.cut_reason}</p>{o.visual_plan.evidence?.map((e:Obj,j:number)=><p key={j}>依据 {e.block_id}：{e.quote}</p>)}{o.speech_min_seconds>0&&<small className="muted">原文说话至少需 {o.speech_min_seconds} 秒，停顿与表演另计。</small>}</details>}<details><summary>对应剧本原文 · {o.source_block_ids?.join('、')||'原生结构'}</summary>{o.context_excerpt&&<p className="muted">{o.context_excerpt}</p>}<pre className="document">{o.source_excerpt}</pre></details></>};
   })}/>

  </>}
  {state.total>0&&state.status!=='planned'&&<><progress aria-label="分镜生成进度" max={state.total} value={state.completed||0}/><small>已保存 {state.completed||0}/{state.total} 镜 · 本次复用 {state.reused||0} 镜</small></>}
  {state.completed>0&&<p className="muted">已完成镜头可以先查看与编辑。取消、超时或失败后继续生成剩余镜头；全部完成并校验后再确认分镜。</p>}
  {project.storyboard_archive?.length>0&&<details><summary>历史分镜资料 · {project.storyboard_archive.length} 版</summary>{project.storyboard_archive.map((a:Obj,i:number)=><details key={i}><summary>{new Date(a.created*1000).toLocaleString()} · {a.state?.outlines?.length||0} 条汇总 · {a.shots.length} 镜</summary>{a.reason&&<p className="muted">{a.reason}</p>}{a.state?.outlines?.length>0&&<details><summary>历史汇总内容</summary>{a.state.outlines.map((o:Obj)=><p key={o.id}>第 {o.index} 镜 · {o.location} · {o.natural_seconds} 秒：{o.focus}</p>)}</details>}{a.shots.map((s:Obj,j:number)=><div key={s.id}><strong>第 {j+1} 镜 · {s.duration} 秒</strong><p>{s.description}</p><pre className="document">{s.prompt}</pre>{(s.outputs||[]).map((m:Obj)=><a key={m.id} href={'/media/'+encodeURIComponent(m.media)} target="_blank" rel="noreferrer">查看历史视频</a>)}</div>)}</details>)}</details>}
  {project.shot_history?.length>0&&<details><summary>单镜历史版本 · {project.shot_history.length} 版</summary>{project.shot_history.map((h:Obj,i:number)=><details key={i}><summary>第 {h.index} 镜 · {new Date(h.created*1000).toLocaleString()}</summary><p>{h.shot.description} · {h.shot.duration} 秒</p><pre className="document">{h.shot.prompt}</pre>{(h.shot.outputs||[]).map((m:Obj)=><p key={m.id}><a href={'/media/'+encodeURIComponent(m.media)} target="_blank" rel="noreferrer">查看历史视频</a> · 种子 {m.seed??'未记录'}</p>)}</details>)}</details>}
 </section>;
}

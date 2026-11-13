import {Clock, CheckCircle2} from 'lucide-react';
type Obj=Record<string,any>;
const seconds=(n:number)=>Number(n).toFixed(2).replace(/\.?0+$/,'');
const delta=(n:number)=>(n>0?'+':'')+seconds(n);

export function TimingGuidance({shot,busy,onAdopt}:{shot:Obj;busy:boolean;onAdopt:()=>void}){
 if(shot.speech_track)return <section className="timing-guidance"><strong>分镜配音轨 · {seconds(shot.speech_track.duration)} 秒</strong><p>{shot.natural_status==='unverified'?'内容或音色已修改，请重新测时。':'人声按实际音频安排；其余动作段用静音补齐。'}</p><audio controls src={'/media/'+encodeURIComponent(shot.speech_track.media)}/><details><summary>对白／旁白的实际落点</summary>{shot.speech_track.placements.map((a:Obj,i:number)=><p key={i}>{a.speaker} · {seconds(a.start)}–{seconds(a.end)} 秒</p>)}</details><a href={'/media/'+encodeURIComponent(shot.speech_track.media)} download>下载完整配音轨</a></section>;
 const proposal=shot.timing_suggestion;
 if(!proposal){const review=shot.timing_review_summary;return review?<p className="timing-guidance">AI已自动更新时间：{seconds(review.before_seconds)} → {seconds(review.recommended_seconds)} 秒。{shot.natural_status==='unverified'?'内容已编辑，请重新审查时长。':'无需人工采用。'}</p>:null;}
 if(proposal.status==='stale')return <p className="muted">镜头或生成依据已修改，旧时长建议已失效。请重新点击“AI 拆解与审查时序”。</p>;
 if(proposal.status!=='pending')return null;
 const limit=Number(proposal.task_limit_seconds||30),duration=Number(proposal.recommended_seconds);
 return <section className="timing-guidance" aria-label="自然时长建议" aria-live="polite">
  <strong><Clock size={16}/>建议{proposal.delta_seconds>0?'延长':'缩短'}至 {seconds(duration)} 秒</strong>
  <p>当前 {seconds(proposal.before_seconds)} 秒 → 建议 {seconds(duration)} 秒（{delta(proposal.delta_seconds)} 秒）。AI 给出的自然时长参考范围：{seconds(proposal.minimum_seconds)}–{seconds(proposal.maximum_seconds)} 秒。</p>
  <p className="muted">时长按完整动作、原文说话和反应计算。采用后同步本镜时长、动作段与提示词；全部分镜完成后点击“时间修正”，核对全片起止标签。</p>
  <p>{duration>limit?<>超过当前 H3 单任务 {limit} 秒上限，至少需 {proposal.estimated_task_count} 个任务；转写时按自然动作边界分段。整段对白或旁白无法放入一个任务时，先按原文句段拆开说话动作，再审定时序。</>:<>当前 H3 单任务上限为 {limit} 秒；本镜时长未超限，H3 转写会按全片时序分组。</>}</p>
  <details><summary>查看各动作的时长依据</summary><ul>{proposal.reasons.map((r:Obj,i:number)=><li key={i}><strong>{r.description} · {seconds(r.natural_seconds)} 秒</strong><p>{r.rationale}</p></li>)}</ul></details>
  {proposal.auto_apply?<p className="muted">后续分镜结束后自动更新时间，无需人工采用。</p>:<button className="primary" disabled={busy} onClick={onAdopt}><CheckCircle2 size={16}/>采用建议时长（{seconds(duration)} 秒）</button>}
 </section>;
}

export function TimingChanges({correction}:{correction:Obj}){
 const changes=correction.changes||[];
 if(!changes.length||correction.status==='stale')return null;
 return <section className="timing-change-summary" aria-label="时间修正前后对比">
  {correction.status==='completed'&&<p>项目原预计 {seconds(correction.initial_target_duration)} 秒 → 审定 {seconds(correction.total_seconds)} 秒（{delta(correction.total_seconds-correction.initial_target_duration)} 秒）。</p>}
  <ul>{changes.map((r:Obj)=><li key={r.shot_id}>第 {r.index} 镜：{seconds(r.before_seconds)} → {seconds(r.recommended_seconds)} 秒（{delta(r.delta_seconds)} 秒）{r.recommended_seconds>r.task_limit_seconds&&<> · 超过 H3 单任务 {r.task_limit_seconds} 秒，需按动作边界分任务</>}</li>)}</ul>
 </section>;
}

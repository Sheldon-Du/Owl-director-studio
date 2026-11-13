type Obj=Record<string,any>;
export function h3Group(project:Obj,sid:string){return (project.h3_shot_groups||[]).find((g:Obj)=>g.shot_ids?.includes(sid)) as Obj|undefined}
export function h3Leader(project:Obj,sid:string){return h3Group(project,sid)?.shot_ids[0]||sid}
export function h3GroupLabel(project:Obj,sid:string){const group=h3Group(project,sid);const segments=h3Segments(project),index=segments.findIndex(s=>s.shots.some((r:Obj)=>r.id===sid));return group&&index>=0?`H3 组${index+1}（${segments[index].duration}秒）`:''}

export function h3Segments(project:Obj){
 const rows:Obj[]=[];let start=0;
 for(let i=0;i<project.shots.length;){
  const first=project.shots[i],group=h3Group(project,first.id),shots=group?group.shot_ids.map((id:string)=>project.shots.find((s:Obj)=>s.id===id)).filter(Boolean):[first];
  if(!shots.length){shots.push(first)}
  const duration=Number(shots.reduce((n:number,s:Obj)=>n+Number(s.duration||0),0).toFixed(6));
  rows.push({group,shots,duration,start,end:Number((start+duration).toFixed(6)),indices:shots.map((s:Obj)=>project.shots.indexOf(s)+1)});start=Number((start+duration).toFixed(6));i+=shots.length;
 }
 return rows;
}

// Render current group outputs without changing each source shot's clip metadata.
export function h3VideoShot(project:Obj,sid:string){
 const first=project.shots.find((s:Obj)=>s.id===h3Leader(project,sid));
 if(!first)return {id:sid,outputs:[]};
 const ids=h3Group(project,first.id)?.shot_ids||[first.id];
 const duration=ids.reduce((sum:number,id:string)=>sum+Number(project.shots.find((s:Obj)=>s.id===id)?.duration||0),0);
 const outputs=(first.outputs||[]).filter((m:Obj)=>{const sources=m.source_shot_ids;return ids.length>1?Array.isArray(sources)&&sources.length===ids.length&&sources.every((id:string,i:number)=>id===ids[i]):!sources?.length||(sources.length===1&&sources[0]===first.id)}).map((m:Obj)=>ids.length>1?{...m,duration:Number(m.delivery_duration||duration),source_offset:0,in:0}:m);
 return {...first,duration,outputs};
}

export function h3GroupRunning(tasks:Obj[],projectId:string,shots:Obj[]){
 const ids=new Set(shots.map(shot=>shot.id));
 return tasks.some(task=>task.project_id===projectId
  &&['queued','running','cancelling'].includes(task.status)
  &&['creative_refine','h3','h3_generate','h3_upscale'].includes(task.kind)
  &&(ids.has(task.target)||ids.has(task.options?.scope_shot)));
}

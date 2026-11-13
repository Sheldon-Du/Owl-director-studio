type Obj=Record<string,any>;
export function WorldPolicy({project,edit}:{project:Obj;edit:(fn:(p:any)=>void)=>void}){
 const brief=project.video_brief||{},creative=project.story_policy==='creative';
 return <div className="world-policy"><p className="muted">时代、技术条件与人物制度沿用原故事。导演风格指导视觉表达；穿越者的前世知识与当前世界的实物分别处理。</p>{creative&&<><label className="checkbox"><input type="checkbox" checked={!!brief.allow_world_change} onChange={e=>edit(p=>{p.video_brief={...(p.video_brief||{}),allow_world_change:e.target.checked}})}/>允许改写时代与世界观</label>{brief.allow_world_change&&<label>目标时代与技术条件<input value={brief.target_world||''} placeholder="例如：改为现代都市，明确保留哪些原故事关系" onChange={e=>edit(p=>{p.video_brief={...(p.video_brief||{}),target_world:e.target.value}})}/></label>}</>}</div>;
}


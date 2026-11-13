type Obj=Record<string,any>;
export function AudioInfo({item,tasks=[]}:{item:Obj;tasks?:Obj[]}){
 const task=tasks.find(t=>t.id===item.task_id),seconds=item.generation_seconds??(task?.started&&task?.finished?task.finished-task.started:null);
 return <div className="muted"><div>生成时间：{item.created?new Date(item.created*1000).toLocaleString('zh-CN',{hour12:false}):'旧记录未保存'}</div>{seconds!=null&&<div>生成用时：{Math.floor(seconds/60)}分{Math.round(seconds%60)}秒</div>}{item.duration!=null&&<div>音频时长：{Number(item.duration).toFixed(1)}秒</div>}{item.voice_role&&<div>说话人：{item.voice_role} · {item.voice_mode==='clone'?'克隆音色':item.voice_mode==='silence'?'静音':item.voice_mode==='design'?'新建音色':item.voice_mode==='saved'?'复用音色':'预设音色'}</div>}{item.voice_filename&&<details><summary>声音记录</summary><small>{item.voice_filename}</small>{item.voice_description&&<p>{item.voice_description}</p>}</details>}{item.model==='qwen3-tts'&&<div>种子：{item.seed}</div>}</div>;
}

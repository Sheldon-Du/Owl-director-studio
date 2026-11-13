import {useState} from 'react';
type Row=Record<string,any>;
export function ChatCutPanel({project,save,changed,notify}:{project:Row;save:()=>Promise<Row>;changed:()=>Promise<void>;notify:(s:string)=>void}){
 const [busy,setBusy]=useState(false),[result,setResult]=useState<Row|null>(null);
 async function run(action:string){
  setBusy(true);
  try{
   const p=['send','export','collect'].includes(action)?await save():project;
   const read=['status','progress'].includes(action);
   const url=action==='status'?'/api/chatcut/status':`/api/projects/${p.id}/chatcut/${action}`;
   const response=await fetch(url,{method:read?'GET':'POST',headers:{'Content-Type':'application/json'},...(read?{}:{body:JSON.stringify({revision:p.revision})})});
   const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
   setResult(action==='status'?{connected:data.connected,active:data.active,tools:data.tools}:data);
   if(['send','collect','export'].includes(action))await changed();
   notify(action==='send'?'时间线已发送到 ChatCut，可在 Agent 中继续剪辑':action==='export'?'已提交导出，请查询进度，完成后收回成片':'ChatCut 状态已更新');
  }catch(error){notify(error instanceof Error?error.message:String(error));}finally{setBusy(false);}
 }
 return <section className="panel"><h3>ChatCut 剪辑</h3><p className="muted">将当前时间线发送到独立的 ChatCut 工程，再让 Owl Agent 执行裁剪、声音和字幕编辑。ChatCut 编辑不会改写此处的原时间线。</p>
 <div className="export-options"><button disabled={busy} onClick={()=>run('status')}>检查连接</button><button disabled={busy||(!!project.chatcut?.project_id&&project.chatcut?.owl_project_id===project.id)} onClick={()=>run('send')}>发送当前时间线</button><button disabled={busy||!project.chatcut?.project_id} onClick={()=>run('export')}>导出 MP4</button><button disabled={busy||!project.chatcut?.project_id} onClick={()=>run('progress')}>查询导出进度</button><button disabled={busy||!project.chatcut?.export_task} onClick={()=>run('collect')}>收回成片到素材库</button></div>
 {project.chatcut?.project_id&&<p>已绑定工程：{project.chatcut.project_id} · {project.chatcut.stage}</p>}
 {result&&<details open><summary>执行结果</summary><pre style={{whiteSpace:'pre-wrap',maxHeight:280,overflow:'auto'}}>{JSON.stringify(result,null,2)}</pre></details>}
 </section>;
}

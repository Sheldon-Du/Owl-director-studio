type Api=(path:string,body?:any)=>Promise<any>;
const active=new Set(['queued','running','cancelling']);

export async function cancelAllJobs(api:Api){
 try{return await api('/tasks/cancel-all',{})}
 catch(error){if(![404,405].includes((error as Error & {status?:number}).status||0))throw error}
 // The page can update before an older server finishes its current jobs.
 // Use its existing cancellation API until the new server can start safely.
 const rows=(await api('/tasks')).filter((t:any)=>active.has(t.status)).sort((a:any,b:any)=>Number(a.status!=='queued')-Number(b.status!=='queued'));
 const result={cancelled:0,cancelling:0,failed:0};
 for(const task of rows){
  try{const saved=await api('/tasks/'+task.id+'/cancel',{});if(saved.status==='cancelled')result.cancelled++;else if(saved.status==='cancelling')result.cancelling++}
  catch{result.failed++}
 }
 return result;
}

import {useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {jsonApi as authoringApi} from './jsonApi';
type Obj=Record<string,any>;
export function OverviewSync({scope,target,project,busy,save,changed,notify}:{scope:'assets'|'frames'|'shots';target?:string;project:Obj;busy:boolean;save:()=>Promise<Obj>;changed:(p:Obj)=>void;notify:(s:string)=>void}){
 const [working,setWorking]=useState(false);
 const ready=project.authoring_run?.adopted&&project.authoring_run?.status==='completed';
 const update=async()=>{setWorking(true);try{const p=await save();const v=await authoringApi(`/projects/${p.id}/authoring/update-${scope}`,{revision:p.revision,target});changed(v.project);notify(`已从创作概览更新 ${v.updated_count} ${scope==='assets'?'张资产卡片':scope==='shots'?'个分镜':'组三帧描述'}，已有媒体保留`)}catch(e){notify((e as Error).message)}finally{setWorking(false)}};
 return <button disabled={busy||working||!ready} title={ready?'复制已采用的创作概览成果，覆盖对应文字；已有媒体保留，不调用 AI':'请先完成并采用创作概览成果'} onClick={update}><RefreshCw size={14}/>{working?'正在更新…':target?(scope==='assets'?'从概览更新本卡':'从概览更新本镜'):'从创作概览更新'}</button>
}

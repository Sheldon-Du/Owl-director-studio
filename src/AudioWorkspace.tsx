import {useState} from 'react';
import {VoiceStudio} from './VoiceStudio';
import {SpeechMixer} from './SpeechMixer';
import {Soundtrack} from './Soundtrack';
import {ToolWindow} from './StudioTools';

type Obj=Record<string,any>;
type Props={
 project:Obj;
 busy:boolean;
 job:(kind:string,target?:string,options?:Obj)=>Promise<any>;
 notify:(message:string)=>void;
 save:()=>Promise<Obj>;
 changed:(project:Obj)=>void;
 upload:(files:FileList|null)=>void;
 addTimeline:(media:Obj)=>void;
 openH3:(id:string)=>void;
 batchSpeechTiming:()=>void;
 section:'speech'|'music';
 select:(tab:string)=>void;
};

export function AudioWorkspace(props:Props){
 const {project,busy,save,changed,notify,job,openH3,section,select,batchSpeechTiming}=props;
 const [musicPrompt,setMusicPrompt]=useState('');
 return <section className="audio-workspace" aria-label="声音工作室">
  <div className="section-title">
   <h2>声音工作室</h2>
   <button onClick={()=>select('media')}>打开素材库 ↗</button>
  </div>
  <nav className="mode-tabs" aria-label="声音工作室分区">
   <button className={section==='speech'?'active':''} aria-pressed={section==='speech'} onClick={()=>select('voice')}>对白与音色</button>
   <button className={section==='music'?'active':''} aria-pressed={section==='music'} onClick={()=>select('soundtrack')}>配乐</button>
  </nav>
  {section==='speech'?<>
   <div className="audio-workspace-actions row wrap">
    <ToolWindow title="配音与音色"><VoiceStudio {...props}/></ToolWindow>
    <button disabled={busy||!project.shots.length} onClick={batchSpeechTiming}>批量配音与实测时序</button>
   </div>
   <SpeechMixer project={project} busy={busy} save={save} changed={changed} notify={notify} job={job} openH3={openH3} openShots={()=>select('shots')}/>
  </>:<>
   <Soundtrack {...props}/>
   <details className="panel audio-extra-workflows">
    <summary>其他音乐工作流</summary>
    <label>音乐方向<textarea rows={3} value={musicPrompt} onChange={e=>setMusicPrompt(e.target.value)}/></label>
    <button disabled={busy||!musicPrompt.trim()} onClick={()=>job('audio',undefined,{profile:'music',media_kind:'audio',prompt:musicPrompt})}>生成音乐</button>
   </details>
  </>}
 </section>;
}

import {useEffect,useRef,useState} from 'react';

// A shared context avoids the browser's limit on simultaneous audio contexts.
let sharedContext:AudioContext|undefined;
const bounded=(gain:number)=>Number.isFinite(gain)?Math.max(0,Math.min(2,gain)):1;

export function GainPreview({src,gain,label}:{src:string;gain:number;label:string}){
 const audio=useRef<HTMLAudioElement>(null);
 const graph=useRef<{source:MediaElementAudioSourceNode;gain:GainNode;context:AudioContext}|null>(null);
 const latestGain=useRef(bounded(gain));
 const [error,setError]=useState('');
 latestGain.current=bounded(gain);
 useEffect(()=>{
  const current=graph.current;
  if(current){current.gain.gain.cancelScheduledValues(current.context.currentTime);current.gain.gain.setTargetAtTime(bounded(gain),current.context.currentTime,.01);}
 },[gain]);
 useEffect(()=>()=>{audio.current?.pause();graph.current?.source.disconnect();graph.current?.gain.disconnect();graph.current=null},[]);
 const play=()=>{
  try{
   if(!audio.current)return;
   if(!graph.current){
    sharedContext??=new AudioContext();
    const source=sharedContext.createMediaElementSource(audio.current),volume=sharedContext.createGain();
    volume.gain.value=latestGain.current;
    source.connect(volume);volume.connect(sharedContext.destination);
    graph.current={source,gain:volume,context:sharedContext};
   }
   if(graph.current.context.state==='suspended')void graph.current.context.resume().catch(()=>{audio.current?.pause();setError('浏览器未允许播放，请再次点击试听')});
   setError('');
  }catch{audio.current?.pause();setError('试听音量初始化失败，请刷新页面后重试')}
 };
 return <div className="gain-preview"><audio ref={audio} aria-label={label+' 按音量试听'} controls preload="none" src={src} onPlay={play}/><small aria-live="polite">试听音量 {Math.round(bounded(gain)*100)}%{gain===0?' · 静音':''} · 调整立即生效</small>{error&&<small role="alert">{error}</small>}</div>;
}

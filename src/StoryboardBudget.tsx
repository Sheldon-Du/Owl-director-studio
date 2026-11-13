type Props={config:Record<string,any>;onChange:(config:Record<string,any>)=>void};
export function StoryboardBudget({config,onChange}:Props){
 return <label>分镜 AI 输出预算
  <select value={config.ai_storyboard_max_tokens??32768} onChange={e=>onChange({...config,ai_storyboard_max_tokens:Number(e.target.value)})}>
   {[4096,8192,16384,32768,65536,131072].map(n=><option key={n} value={n}>{n.toLocaleString()} tokens{n===32768?' · 默认':''}</option>)}
  </select>
  <small>分镜请求保留完整剧本上下文。此值控制输出（含模型思考），上下文容量和实际输出上限由接口决定；汇总的画面方案分批保存，可中断后继续。</small>
 </label>;
}

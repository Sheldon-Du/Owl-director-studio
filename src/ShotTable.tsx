import type {ReactNode} from 'react';
type Obj=Record<string,any>;
export type ShotTableRow={id:string;index:number;location?:string;focus:string;timing?:string;shot?:Obj;actions?:ReactNode;details?:ReactNode};
type Props={rows:ShotTableRow[];renderFrames?:(shot:Obj)=>ReactNode;renderShot?:(shot:Obj,index:number)=>ReactNode;renderVideo?:(shot:Obj)=>ReactNode};

export function ShotTable({rows,renderFrames,renderShot,renderVideo}:Props){
 const full=!!(renderFrames||renderShot||renderVideo);
 return <div className="shot-table-scroll"><table className={'shot-table'+(full?' four-columns':' overview-columns')} aria-label={full?'分镜制作四列表格':'分镜汇总表格'}>
  <colgroup><col className="shot-directory-col"/>{full&&<col className="shot-frame-col"/>}<col className="shot-prompt-col"/>{full&&<col className="shot-video-col"/>}</colgroup>
  <thead><tr><th scope="col">分镜目录</th>{full&&<th scope="col">首帧 / 关键帧</th>}<th scope="col">{full?'分镜提示词与时序':'分镜内容与剧本依据'}</th>{full&&<th scope="col">视频成片</th>}</tr></thead>
  <tbody>{rows.map(row=><tr key={row.id}>
   <th scope="row" className="shot-directory-cell"><strong>第 {row.index} 镜</strong>{row.location&&<small>{row.location}</small>}{row.timing&&<small>{row.timing}</small>}<span className={'shot-row-status '+(row.shot?'ready':'')}>{row.shot?'已生成':'待生成'}</span></th>
   {full&&<td className="shot-frame-cell">{row.shot&&renderFrames?renderFrames(row.shot):<span className="shot-cell-empty">具体分镜完成后生成</span>}</td>}
   <td className="shot-prompt-cell"><p className="shot-row-focus">{row.focus}</p>{row.shot&&renderShot?renderShot(row.shot,row.index-1):full?<p className="muted">先生成此镜，再查看和编辑提示词。</p>:null}<div className="shot-row-actions">{row.actions}</div>{row.details}</td>
   {full&&<td className="shot-video-cell">{row.shot&&renderVideo?renderVideo(row.shot):<span className="shot-cell-empty">生成视频后展示</span>}</td>}
  </tr>)}</tbody>
 </table></div>;
}

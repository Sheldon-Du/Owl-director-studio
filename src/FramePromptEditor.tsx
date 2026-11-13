import React from 'react';

const sections = [
 ['任务目标', '这张图用于哪个阶段，视觉重点是什么'],
 ['Subject 主体', '资产身份、皮肤毛发、服饰道具、姿态视线、位置与相互关系'],
 ['Style 风格', '项目时代、审美、配色和材质质感'],
 ['Shot 镜头与构图', '景别机位、主体占比、视觉重心与前中后景清晰度'],
 ['Setting 场景', '地点时间、空间结构、必要陈设和准确的场景文字'],
 ['Scene lighting 光照与影调', '主光方向、软硬冷暖、补光轮廓光与阴影过渡'],
 ['约束与优先级', '必须保留、禁止出现、状态连续性与冲突处理'],
];

export function FramePromptEditor({prompt,onChange}:{prompt:string;onChange:(value:string)=>void}){
 const pattern=/【(任务目标|Subject 主体|Style 风格|Shot 镜头与构图|Setting 场景|Scene lighting 光照与影调|约束与优先级)】/g;
 const matches=[...prompt.matchAll(pattern)];
 const structured=matches.length===sections.length&&matches.every((m,i)=>m[1]===sections[i][0])&&!prompt.slice(0,matches[0].index).trim();
 if(!structured)return <><label>Image2.1 生图提示词<textarea rows={6} value={prompt} onChange={e=>onChange(e.target.value)}/></label><small>现有提示词可继续使用；点击“AI 重新编写提示词与所需资产”会按任务目标、5S与约束生成。</small></>;
 const values=matches.map((m,i)=>prompt.slice(m.index!+m[0].length,matches[i+1]?.index??prompt.length).trim());
 const edit=(index:number,value:string)=>onChange(sections.map(([title],i)=>`【${title}】${(i===index?value:values[i]).replace(/\s*\n\s*/g,' ').trim()}`).join(' '));
 return <section><h3>Image2.1 生图提示词 · 5S</h3><p className="muted">任务目标 → 主体 → 风格 → 镜头 → 场景 → 光照 → 约束。分段编辑，提交时合并为一条完整指令；标题不会作为画面文字。</p>{sections.map(([title,help],i)=><label key={title}>{title}<small className="muted">{help}</small><textarea rows={i===1?4:2} value={values[i]} onChange={e=>edit(i,e.target.value)}/></label>)}<details><summary>查看完整提示词</summary><textarea rows={8} value={prompt} readOnly aria-label="完整5S提示词"/></details></section>;
}

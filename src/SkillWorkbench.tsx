import {CreativeSkills} from './CreativeSkills';
type Obj=Record<string,any>;
export function SkillWorkbench({project,edit}:{project:Obj;edit:(fn:(p:Obj)=>void)=>void;[key:string]:any}){
 return <div className="panel"><h2>剧本技能</h2><p>先选择编剧方法，再进入剧本创作。这里的选择用于后续剧本编写与改编。</p><CreativeSkills project={project} edit={edit} expanded/><div className="note">视频提示词技能在「H3 视频」选择；图片资产技能在对应元素卡选择。</div></div>;
}

type Obj=Record<string,any>;
type Slot={exists:boolean;value?:any};
type Patch={path:string[];before:Slot;after:Slot};
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
const object=(v:any)=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const slot=(o:Obj,k:string):Slot=>Object.prototype.hasOwnProperty.call(o,k)?{exists:true,value:structuredClone(o[k])}:{exists:false};
function changes(before:Obj,after:Obj,path:string[]=[]):Patch[]{
 const result:Patch[]=[];
 for(const key of new Set([...Object.keys(before),...Object.keys(after)])){
  const a=slot(before,key),b=slot(after,key);if(same(a,b))continue;
  if(a.exists&&b.exists&&object(a.value)&&object(b.value))result.push(...changes(a.value,b.value,[...path,key]));
  else result.push({path:[...path,key],before:a,after:b});
 }
 return result;
}
function read(root:Obj,path:string[]):Slot{let at=root;for(const key of path.slice(0,-1)){if(!object(at)||!(key in at))return {exists:false};at=at[key]}return object(at)?slot(at,path.at(-1)!):{exists:false}}
function write(root:Obj,path:string[],value:Slot){let at=root;for(const key of path.slice(0,-1))at=at[key];if(value.exists)at[path.at(-1)!]=structuredClone(value.value);else delete at[path.at(-1)!]}
/** Apply only manual field changes; never restore an old server revision or AI output. */
export class ProjectHistory{
 private past:Patch[][]=[];private future:Patch[][]=[];
 clear(){this.past=[];this.future=[]}
 get canUndo(){return this.past.length>0}get canRedo(){return this.future.length>0}
 record(before:Obj,after:Obj){const patch=changes(before,after).filter(p=>!['revision','updated','updated_at'].includes(p.path[0]));if(!patch.length)return;this.past.push(patch);if(this.past.length>50)this.past.shift();this.future=[]}
 apply(current:Obj,redo=false):{project?:Obj;conflict?:boolean}{
  const source=redo?this.future:this.past,dest=redo?this.past:this.future,patch=source.at(-1);if(!patch)return {};
  if(patch.some(p=>!same(read(current,p.path),redo?p.before:p.after))){this.clear();return {conflict:true}}
  const next=structuredClone(current);for(const p of patch)write(next,p.path,redo?p.after:p.before);source.pop();dest.push(patch);return {project:next};
 }
}
export const nativeUndoTarget=(target:EventTarget|null)=>target instanceof Element&&!!target.closest('input,textarea,[contenteditable="true"],[contenteditable=""]');

type Obj=Record<string,any>;
export const productionText=(p:Obj)=>p.documents?.script?.trim()&&!p.script_needs_rewrite?p.documents.script:(p.story||'');
export const productionReady=(p:Obj)=>!!productionText(p).trim();
export const productionLabel=(p:Obj)=>p.documents?.script?.trim()&&!p.script_needs_rewrite?'有效剧本':'原始故事';

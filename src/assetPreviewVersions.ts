type Obj=Record<string,any>;

/** Pair only proven derivatives. Separate Comfy outputs remain separate. */
export function assetPreviewVersions(asset:Obj):Obj[]{
 const previews:Obj[]=asset.previews||[],byMedia=new Map(previews.map(m=>[m.media,m])),children=new Map<string,Obj>();
 for(const m of previews){
  const source=m.source_media||m.layout?.source_media,raw=byMedia.get(source);
  if(m.character_card&&m.layout_normalized&&raw?.character_card&&raw.task_id&&raw.task_id===m.task_id&&!children.has(source))children.set(source,m);
 }
 const paired=new Set([...children.values()].map(m=>m.id));
 return previews.filter(m=>!paired.has(m.id)).map(m=>{
  const processed=children.get(m.media);
  if(!processed){
   const source=m.source_media||m.layout?.source_media;
   if(m.character_card&&m.layout_normalized&&source&&source!==m.media){
    const original={...m,id:m.id+'-source',media:source,layout_normalized:false,layout:null,source_media:null};
    const selected=asset.adopted===source?original:m,alternative=selected===m?original:m;
    return {...selected,version_ids:[m.id],version_media:[m.media,source],alternative};
   }
   return {...m,version_ids:[m.id],version_media:[m.media]};
  }
  const selected=asset.adopted===m.media?m:processed,alternative=selected===m?processed:m;
  return {...selected,version_ids:[m.id,processed.id],version_media:[m.media,processed.media],alternative};
 });
}

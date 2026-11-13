type Obj=Record<string,any>;
export function assetReferences(asset:Obj):Obj[]{
 const role=({character:'identity',scene:'environment',prop:'prop'} as Obj)[asset.kind]||'identity';
 const result:Obj[]=[],seen=new Set<string>();
 const add=(ref:Obj)=>{if(ref.media&&!seen.has(ref.media)){result.push({...ref});seen.add(ref.media);}};
 if(asset.variant){const media=asset.adopted||[...(asset.previews||[])].reverse().find(p=>p.media&&!p.stale)?.media;if(media)add({media,role,source:'variant_output'});return result;}
 (asset.references||[]).forEach(add);
 if(asset.adopted)add({media:asset.adopted,role,source:'adopted'});
 if(!result.length){const preview=[...(asset.previews||[])].reverse().find(p=>p.media&&!p.stale);if(preview)add({media:preview.media,role,source:'latest_preview'});}
 return result;
}

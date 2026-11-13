"""Normalize a generated sheet's geometry while preserving each complete view."""
from PIL import Image,ImageDraw,ImageOps
import numpy as np
from . import store


def normalize(media,width=1152,height=2048):
    with Image.open(store.media_path(media)) as original:
        source=original.convert('RGB')
    pixels=np.asarray(source)
    # Restrict divider detection to the interior. Prefer the thin full-width
    # light separator requested by the card prompt, excluding the outer border.
    white=(pixels.min(axis=2)>230).mean(axis=1)
    candidates=np.flatnonzero((white>.94)&(np.arange(source.height)>source.height*.2)&(np.arange(source.height)<source.height*.8))
    split=int(min(candidates,key=lambda y:abs(y-source.height/2))) if len(candidates) else source.height//2
    mid=source.width//2
    boxes=((0,0,mid,split),(mid,0,source.width,split),(0,split,mid,source.height),(mid,split,source.width,source.height))
    # Contain each full view, with neutral padding. No stretching or body crop.
    result=Image.new('RGB',(width,height),(195,195,195));cw=width//2;ch=height//2
    for i,box in enumerate(boxes):
        view=ImageOps.contain(source.crop(box),(cw-4,ch-4),Image.Resampling.LANCZOS)
        x=(i%2)*cw+(cw-view.width)//2;y=(i//2)*ch+(ch-view.height)//2
        result.paste(view,(x,y))
    draw=ImageDraw.Draw(result)
    draw.line([(cw-1,0),(cw-1,height-1)],fill=(238,238,238),width=2)
    draw.line([(0,ch-1),(width-1,ch-1)],fill=(238,238,238),width=2)
    name=store.uid()+'.png';result.save(store.media_path(name))
    return name,{'source_media':media,'source_divider_y':split,'source_size':list(source.size),'equal_cells':[cw,ch],'size':[width,height],'divider_detected':bool(len(candidates))}

import bpy,sys
from pathlib import Path
source,output=sys.argv[sys.argv.index('--')+1:]
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for text in list(bpy.data.texts):bpy.data.texts.remove(text)
bpy.data.texts.new('Main').write(Path(source).read_text(encoding='utf-8'))
bpy.ops.wm.save_as_mainfile(filepath=output)

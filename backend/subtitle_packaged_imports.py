"""Read-only module loader for the user's PyInstaller Python archive.

No modules are extracted or changed in pyVideoTrans. Code executes only in its
matching bundled Python 3.10 process, with its original dependencies and model.
"""
import sys,_struct as struct,zlib,marshal,os
from _frozen_importlib import spec_from_loader

def enable(executable):
    with open(executable,'rb') as f:data=f.read()
    root=os.path.dirname(executable);magic=b'MEI\x0c\x0b\x0a\x0b\x0e';cookie=data.rfind(magic)
    if cookie<0:raise RuntimeError('Unsupported pyVideoTrans package: missing Python archive')
    _,size,offset,length,version,_=struct.unpack('!8sIIII64s',data[cookie:cookie+88])
    if version!=310:raise RuntimeError('Subtitle adapter requires the installed Python 3.10 package')
    start=cookie+88-size;index=start+offset;end=index+length;pyz=None;bootstrap={}
    while index<end:
        entry_size,position,compressed_size,uncompressed_size,compressed,kind=struct.unpack('!iIIIBc',data[index:index+18])
        if entry_size<18:raise RuntimeError('Invalid package directory')
        name=data[index+18:index+entry_size].rstrip(b'\0').decode('utf-8')
        if kind==b'z':
            pyz=data[start+position:start+position+compressed_size]
            if compressed:pyz=zlib.decompress(pyz)
        elif kind in (b'm',b'M'):
            blob=data[start+position:start+position+compressed_size]
            bootstrap[name]=zlib.decompress(blob) if compressed else blob
        index+=entry_size
    if not pyz or pyz[:4]!=b'PYZ\0':raise RuntimeError('Cannot locate packaged Python modules')
    toc=dict(marshal.loads(pyz[struct.unpack('!I',pyz[8:12])[0]:]))
    class Loader:
        def __init__(self,name):self.name=name
        def create_module(self,spec):return None
        def exec_module(self,module):
            if self.name in bootstrap:
                exec(marshal.loads(bootstrap[self.name]),module.__dict__);return
            package,position,length=toc[self.name]
            folder=os.path.join(root,'_internal',*self.name.split('.'))
            module.__file__=os.path.join(folder,'__init__.pyc') if package else folder+'.pyc'
            if package:module.__path__=[folder]
            exec(marshal.loads(zlib.decompress(pyz[position:position+length])),module.__dict__)
        def is_package(self,fullname):return bool(toc.get(fullname,(0,))[0])
    class Finder:
        def find_spec(self,fullname,path=None,target=None):
            if fullname in bootstrap or fullname in toc and toc[fullname][0] in (0,1):return spec_from_loader(fullname,Loader(fullname),is_package=bool(toc.get(fullname,(0,))[0]))
    sys.meta_path.insert(0,Finder())

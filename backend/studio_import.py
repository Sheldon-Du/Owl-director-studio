"""Bounded local document imports for the studio landing page."""
import io,re,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('文档包含不支持的 XML 定义')
    return ET.fromstring(data)

def extract(name, raw):
    suffix=Path(name).suffix.lower();warnings=[]
    if len(raw)>25*1024*1024:raise ValueError('导入文档最大 25 MB')
    if suffix in ('.txt','.md'):
        try:text=raw.decode('utf-8-sig')
        except UnicodeError:raise ValueError('文本请保存为 UTF-8 编码')
    elif suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(''):raise ValueError('请先将 PDF 另存为无需打开密码的版本')
        if not 1<=len(reader.pages)<=500:raise ValueError('PDF 支持 1–500 页')
        text='\n\n'.join(p.extract_text() or '' for p in reader.pages)
        warnings.append('PDF 的表格、阅读顺序和关键数字仍需对照原文核对')
    elif suffix in ('.docx','.xlsx'):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(f.file_size for f in z.infolist())>40*1024*1024:raise ValueError('文档解压内容过大，请拆分后导入')
            if suffix=='.docx':
                root=xml(z.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                text='\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p',ns))
            else:
                ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                shared=[]
                if 'xl/sharedStrings.xml' in z.namelist():shared=[''.join(n.itertext()) for n in xml(z.read('xl/sharedStrings.xml')).findall('x:si',ns)]
                sheets=sorted(n for n in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n));rows=[]
                for n in sheets:
                    rows.append('工作表 '+Path(n).stem)
                    for row in xml(z.read(n)).findall('.//x:row',ns):
                        cells=[]
                        for cell in row.findall('x:c',ns):
                            v=cell.find('x:v',ns);value=v.text or '' if v is not None else ''
                            if cell.get('t')=='s':value=shared[int(value)] if value.isdigit() and int(value)<len(shared) else value
                            elif cell.get('t')=='inlineStr':value=''.join(cell.find('x:is',ns).itertext()) if cell.find('x:is',ns) is not None else ''
                            address=re.match(r'[A-Z]+',cell.get('r',''));index=0
                            for ch in address.group() if address else '':index=index*26+ord(ch)-64
                            if index>100:raise ValueError('表格列数过多，请缩小导入范围')
                            if index>0:
                                while len(cells)<index:cells.append('')
                                cells[index-1]=value
                            else:cells.append(value)
                        rows.append('\t'.join(cells))
                text='\n'.join(rows);warnings.append('电子表格读取已保存的单元格值，不计算公式；合并单元格请核对原表')
    else:raise ValueError('支持 TXT、MD、DOCX、XLSX 与 PDF')
    if len(text)>350000:raise ValueError('文档超过 35 万字，请按章节拆分')
    return {'name':Path(name).name,'text':text.strip(),'warnings':warnings,'needs_ocr':suffix=='.pdf' and len(text.strip())<40}

def install(app):
    from fastapi import File,UploadFile
    from pypdf.errors import PdfReadError
    @app.post('/api/studio/import-text')
    async def upload(file:UploadFile=File(...)):
        try:return extract(file.filename or 'document',await file.read(25*1024*1024+1))
        except (zipfile.BadZipFile,ET.ParseError,KeyError,PdfReadError,RuntimeError):raise ValueError('文件结构无法读取，请重新导出文档后导入')

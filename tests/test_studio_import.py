import io,os,sys,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(r'D:\2video\codex\reference-replica');ROOT.mkdir(parents=True,exist_ok=True)
os.environ['DIRECTOR_STUDIO_DATA']=tempfile.mkdtemp(prefix='import-tests-',dir=ROOT)
sys.path.insert(0,r'D:\2video\Owl')
from backend.studio_import import extract
from backend.app import app,SESSIONS,SESSION_COOKIE
from fastapi.testclient import TestClient
from pypdf import PdfWriter

def zipped(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:
  for name,value in files.items():z.writestr(name,value)
 return out.getvalue()

class ImportTests(unittest.TestCase):
 def test_text_and_docx(self):
  self.assertEqual(extract('test.md','测试正文'.encode())['text'],'测试正文')
  doc=zipped({'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合成测试</w:t></w:r></w:p><w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>'})
  self.assertEqual(extract('test.docx',doc)['text'],'合成测试\n第二段')
 def test_spreadsheet_retains_empty_column_and_cached_value(self):
  raw=zipped({'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="inlineStr"><is><t>测试</t></is></c><c r="C1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'})
  self.assertIn('测试\t\t2',extract('test.xlsx',raw)['text'])
 def test_scanned_pdf_and_unsupported(self):
  writer=PdfWriter();writer.add_blank_page(600,800);out=io.BytesIO();writer.write(out)
  self.assertTrue(extract('scan.pdf',out.getvalue())['needs_ocr'])
  with self.assertRaises(ValueError):extract('test.exe',b'test')
 def test_route_authentication_and_real_import(self):
  client=TestClient(app)
  self.assertEqual(client.post('/api/studio/import-text',files={'file':('a.txt',b'fixture')}).status_code,401)
  SESSIONS['import-fixture-session']=9999999999;client.cookies.set(SESSION_COOKIE,'import-fixture-session')
  r=client.post('/api/studio/import-text',files={'file':('a.txt','合成脚本'.encode())})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['text'],'合成脚本')
 def test_xml_entities_rejected(self):
  raw=zipped({'word/document.xml':'<!DOCTYPE a [<!ENTITY x "test">]><a>&x;</a>'})
  with self.assertRaises(ValueError):extract('test.docx',raw)

if __name__=='__main__':unittest.main(verbosity=2)

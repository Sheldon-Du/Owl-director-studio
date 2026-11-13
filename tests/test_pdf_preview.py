import io,sys,unittest
sys.path.insert(0,r'D:\2video\Owl\tests')
from test_local_ocr import LocalOCRAPITests
from PIL import Image

class PDFPreviewTests(unittest.TestCase):
    setUp=LocalOCRAPITests.setUp
    upload=LocalOCRAPITests.upload
    def test_original_page_image_and_access_bounds(self):
        source,_=self.upload()
        base=self.base+'/sources/'+source['id']+'/pages/'
        response=self.client.get(base+'1/preview')
        self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
        self.assertEqual(response.headers['content-type'],'image/png')
        image=Image.open(io.BytesIO(response.content))
        self.assertGreater(image.width,1000)
        self.assertEqual(self.client.get(base+'1/preview').content,response.content)
        self.assertEqual(self.client.get(base+'2/preview').status_code,422)
        self.assertEqual(self.client.get(self.base+'/sources/unknown/pages/1/preview').status_code,404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(base+'1/preview').status_code,401)

if __name__=='__main__':unittest.main(verbosity=2)

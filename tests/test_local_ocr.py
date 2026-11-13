"""Use isolated synthetic data; never read user projects or call an AI provider."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, r'D:\2video\Owl\tests')
import test_medical_director as base
from backend import local_ocr as ocr, medical_director as m, jobs, store
from pypdf import PdfWriter


class LocalOCRAPITests(unittest.TestCase):
    setUp = base.MedicalDirectorTests.setUp
    call = base.MedicalDirectorTests.call

    def upload(self):
        writer = PdfWriter()
        writer.add_blank_page(600, 800)
        stream = io.BytesIO(); writer.write(stream)
        response = self.client.post(self.base + '/sources/upload',
            data={'revision': self.p['revision']},
            files={'file': ('scanned-fixture.pdf', stream.getvalue(), 'application/pdf')})
        self.assertEqual(response.status_code, 200, response.text)
        self.p = response.json()['project']
        return m.state(self.p)['sources'][0], stream.getvalue()

    def test_empty_pdf_waits_for_ocr_then_explicit_source_review(self):
        source, original = self.upload()
        self.assertEqual(source['blocks'], [])
        self.assertEqual(source['page_count'], 1)
        with self.assertRaises(ValueError): m.prerequisites(self.p, 'analysis')
        result = {'id': 'synthetic-ocr', 'source_hash': source['hash'], 'base_hash': ocr.basis(source),
                  'blocks': m.split_text('合成 OCR 测试资料，不含临床建议。2026 年。', 1),
                  'pages': [{'page': 1, 'raw': 'synthetic'}], 'page_count': 1,
                  'warnings': ['请核对合成测试页'], 'provider': 'synthetic-test'}
        with patch.object(ocr, 'status', return_value={'ready': True}), \
             patch.object(ocr, 'settings', return_value={'gpu': 0, 'dpi': 200}):
            response = self.call('/sources/' + source['id'] + '/ocr')
        task = store.task_get(response['task_id'])
        self.assertEqual(task['kind'], 'medical_ocr')
        self.assertIs(jobs.task_queue(task), jobs.EXPORT_QUEUE)
        with patch.object(jobs, 'run_text', return_value=result): jobs.process_task(task)
        task = store.task_get(task['id'])
        self.assertEqual(task['status'], 'completed', task['message'])
        self.p = store.get_project(self.p['id'])
        current = m.state(self.p)['sources'][0]
        self.assertEqual(current['blocks'], [])
        self.assertTrue(m.public(self.p)['sources'][0]['ocr_candidate']['current'])
        self.call('/sources/' + source['id'] + '/ocr/adopt')
        current = m.state(self.p)['sources'][0]
        self.assertFalse(current['quality_reviewed'])
        with self.assertRaises(ValueError): m.prerequisites(self.p, 'analysis')
        self.call('/sources/' + source['id'] + '/review', note='已对照合成测试页核对数字、单位与完整内容')
        m.prerequisites(self.p, 'analysis')
        self.assertEqual(self.client.get(self.base + '/sources/' + source['id'] + '/file').content, original)

    def test_local_ocr_routes_require_authentication(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/local-ocr').status_code, 401)
        self.assertEqual(self.client.post('/api/local-ocr/settings', json={'gpu': 0}).status_code, 401)


if __name__ == '__main__': unittest.main(verbosity=2)

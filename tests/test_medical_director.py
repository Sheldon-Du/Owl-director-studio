"""Integration fixtures are synthetic software-test material, not medical advice."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix='owl-medical-tests-'))
os.environ['DIRECTOR_STUDIO_DATA'] = str(TEST_ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import medical_director as m, store, jobs
from backend.app import app, SESSIONS, SESSION_COOKIE
from fastapi.testclient import TestClient


def fake_ask(system, user):
    payload = json.loads(user)
    if 'blocks' in payload:
        b = payload['blocks'][0]
        return {'metadata': {'title': '合成测试资料，非医学指南'}, 'claims': [{'id': 'c', 'block_id': b['id'], 'quote': b['text'], 'statement': '仅检查软件引用链', 'kind': 'background', 'population': '合成情境', 'conditions': '软件测试', 'exceptions': '不用于实际诊疗', 'recommendation_grade': '', 'certainty': ''}], 'modules': [{'id': 'm', 'title': '合成模块', 'summary': '测试流程', 'claim_ids': ['c']}], 'pending_checks': ['合成资料不得当作医学建议']}
    k = payload['inputs']['analysis']; cid = k['claims'][0]['id']; mid = k['modules'][0]['id']
    if 'plans:[' in system:
        return {'plans': [{'id': d, 'depth': d, 'title': '合成方案', 'objective': '验证流程', 'module_ids': [mid], 'claim_ids': [cid], 'must_keep': '非医学资料', 'optional': '无', 'duration_advice': '按测试需要', 'rationale': '验证独立深度'} for d in m.DEPTHS], 'pending_checks': []}
    if 'questions:[' in system:
        return {'questions': [{'id': 'q', 'claim_ids': [cid], 'application': '软件应用', 'life_connection': '理解工具', 'question': '如何验证资料链？'}], 'hooks': [{'id': f'h{i}', 'question_id': 'q', 'claim_ids': [cid], 'type': '测试开场', 'narration': '这是软件流程测试，不是医学知识。', 'first_screen': '软件示意', 'bridge': '下面检查资料链。', 'rationale': '明确测试', 'payoff': '展示依据'} for i in range(3)], 'pending_checks': []}
    if 'outline:string' in system:
        hook = next(h for h in payload['inputs']['hooks']['hooks'] if h['id'] == payload['settings']['selected_hook'])
        return {'outline': '开场、说明、回应', 'segments': [{'id': 's'+str(i), 'title': role, 'role': role, 'depth': 'reasoning', 'narration': hook['narration'] if not i else '这是合成教学情境，只用于验证软件。', 'claim_ids': [cid], 'goal': '测试', 'transition': ''} for i, role in enumerate(('hook', 'explanation', 'payoff'))], 'hook_answer': '软件引用可检查', 'pending_checks': []}
    if 'beats:[' in system:
        return {'beats': [{'id': 'b'+str(i), 'segment_id': s['id'], 'purpose': '辅助画面 B-roll', 'visual': '测试示意', 'method': '可编辑图表动画', 'presenter': '旁白', 'layout': '图表覆盖', 'audio': '旁白连续', 'annotations': '合成测试', 'rationale': '帮助理解', 'alternative': '静态示意', 'production_brief': '制作测试图表', 'duration_weight': 1} for i,s in enumerate(payload['inputs']['script']['segments'])], 'pending_checks': []}
    return {'summary': '合成软件检查', 'hook_delivery': '回应开场', 'source_consistency': '定位摘录', 'visual_clarity': '示意', 'duration_advice': '需实际配音', 'issues': [], 'pending_checks': []}


class MedicalDirectorTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        SESSIONS['synthetic-test-session'] = 9999999999
        self.client.cookies.set(SESSION_COOKIE, 'synthetic-test-session')
        r = self.client.post('/api/projects', json={'name': '合成资料 · 软件测试', 'project_type': 'medical', 'story': '仅测试，不用于临床', 'duration': 180})
        self.assertEqual(r.status_code, 200, r.text)
        self.p = r.json(); self.base = '/api/projects/' + self.p['id'] + '/medical-director'

    def call(self, path, **body):
        self.p = store.get_project(self.p['id'])
        r = self.client.post(self.base+path, json={'revision': self.p['revision'], **body})
        self.assertEqual(r.status_code, 200, r.text)
        if 'project' in r.json(): self.p = r.json()['project']
        return r.json()

    def source(self):
        self.call('/sources/text', text='合成测试资料：用于检验来源定位；不用于医学诊疗。', name='fixture.txt')

    def run_stage(self, stage):
        result = self.call('/runs', stage=stage)
        task = store.task_get(result['task_id'])
        with patch.object(m.ai, 'ask', side_effect=fake_ask):
            generated = jobs.text_result(task)
        with patch.object(jobs, 'run_text', return_value=generated):
            jobs.process_task(task)
        done = store.task_get(task['id'])
        self.assertEqual(done['status'], 'completed', done['message'])
        self.p = store.get_project(self.p['id'])
        row = m.state(self.p)['artifacts'][-1]
        self.call('/adopt', artifact_id=row['id'])
        return row

    def complete(self):
        self.source()
        for stage in m.STAGES:
            self.run_stage(stage)

    def test_end_to_end_exports_copy_save_and_archive(self):
        self.complete()
        self.assertTrue(all(m.public(self.p)['current_stages'].values()))
        self.assertEqual(m.artifact(self.p, 'analysis')['data']['coverage']['blocks_total'], 1)
        for fmt in ('md', 'csv', 'json'):
            r = self.client.get(self.base+'/export?format='+fmt)
            self.assertEqual(r.status_code, 200)
            self.assertGreater(len(r.content), 200)
        copy_response = self.client.post('/api/projects/'+self.p['id']+'/copy', json={**self.p, 'copy_name': '合成测试副本'})
        self.assertEqual(copy_response.status_code, 200, copy_response.text)
        copied = copy_response.json()
        self.assertEqual(m.state(copied)['sources'], m.state(self.p)['sources'])
        saved = self.client.put('/api/projects/'+self.p['id'], json=self.p)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['medical_director'], self.p['medical_director'])
        import zipfile
        from backend import exporter
        archive = exporter.archive(self.p)
        with zipfile.ZipFile(store.media_path(archive)) as z:
            self.assertIn('media/'+m.state(self.p)['sources'][0]['media'], z.namelist())

    def test_stale_dependency_does_not_overwrite_manual_edit(self):
        self.complete()
        original = m.artifact(self.p, 'script')
        updated = copy.deepcopy(original['data']); updated['segments'][1]['narration'] = '手动修改的合成测试段落。'
        self.call('/artifacts/'+original['id']+'/edit', data=updated)
        new = m.state(self.p)['artifacts'][-1]
        self.call('/adopt', artifact_id=new['id'])
        self.assertFalse(m.artifact(self.p, 'visuals', False))
        self.assertEqual(m.artifact(self.p, 'script')['data']['segments'][1]['narration'], '手动修改的合成测试段落。')
        result = {'stage': 'script', 'data': original['data'], 'input_hash': original['input_hash']}
        self.call('/settings', settings={'notes': '新要求使在途任务过期'})
        p = store.get_project(self.p['id']); m.apply_result(p, result)
        self.assertEqual(m.state(p)['artifacts'][-1]['status'], 'stale')
        self.assertEqual(m.state(p)['adopted']['script'], new['id'])
        self.assertIsNone(m.artifact(p, 'script', False))

    def test_quote_validation_unknown_ids_and_hook_integrity(self):
        self.source(); self.run_stage('analysis'); self.run_stage('depths'); self.run_stage('hooks')
        analysis = m.artifact(self.p, 'analysis')['data']
        wrong = copy.deepcopy(analysis); wrong['claims'][0]['quote'] = '不存在的原文'
        with self.assertRaises(ValueError): m.validate(wrong, self.p, 'analysis')
        task = {'snapshot': self.p, 'options': {'stage': 'script'}}
        with patch.object(m.ai, 'ask', side_effect=fake_ask): data = m.generate(task, lambda _: None)['data']
        data['segments'][0]['narration'] = '擅自改写钩子'
        with self.assertRaises(ValueError): m.validate(data, self.p, 'script')
        data['segments'][0]['narration'] = m.artifact(self.p, 'hooks')['data']['hooks'][0]['narration']
        data['segments'][1]['claim_ids'] = ['forged']
        with self.assertRaises(ValueError): m.validate(data, self.p, 'script')

    def test_auth_conflict_prerequisites_and_duplicates(self):
        r = TestClient(app).get(self.base)
        self.assertEqual(r.status_code, 401)
        r = self.client.post(self.base+'/runs', json={'revision': self.p['revision'], 'stage': 'script'})
        self.assertEqual(r.status_code, 422)
        self.source()
        r = self.client.post(self.base+'/settings', json={'revision': 0, 'settings': {}})
        self.assertEqual(r.status_code, 409)
        r = self.client.post(self.base+'/sources/text', json={'revision': self.p['revision'], 'text': '合成测试资料：用于检验来源定位；不用于医学诊疗。'})
        self.assertEqual(r.status_code, 422)
        r = self.client.get(self.base+'/sources/unknown/file')
        self.assertEqual(r.status_code, 404)

    def test_complete_text_split_pdf_quality_and_recovery(self):
        text = '\n'.join('测试段落'+str(i)+'：'+('甲乙丙丁'*350) for i in range(12))
        blocks = m.split_text(text)
        self.assertEqual(''.join(b['text'].replace('\n','') for b in blocks), text.replace('\n',''))
        self.assertGreater(len(blocks), 2)
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
        writer = PdfWriter(); page = writer.add_blank_page(600, 800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject(); content.set_data(b'BT /F1 12 Tf 40 700 Td (Synthetic software testing only. This is not medical advice. Verify the complete text.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        output = io.BytesIO(); writer.write(output)
        response = self.client.post(self.base+'/sources/upload', data={'revision': self.p['revision']}, files={'file': ('test.pdf', output.getvalue(), 'application/pdf')})
        self.assertEqual(response.status_code, 200, response.text); self.p=response.json()['project']
        with self.assertRaises(ValueError): m.prerequisites(self.p, 'analysis')
        source = m.state(self.p)['sources'][0]
        self.assertIn('Synthetic software', source['blocks'][0]['text'])
        self.call('/sources/'+source['id']+'/review', note='已核对测试页文字与原文件完全一致')
        m.prerequisites(self.p, 'analysis')
        self.assertEqual(self.client.get(self.base+'/sources/'+source['id']+'/file').content, output.getvalue())

    def test_readable_encrypted_pdf_and_password_required_pdf(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
        for algorithm in ('RC4-128', 'AES-256'):
            for password in ('', 'test-open-password'):
                writer = PdfWriter(); page = writer.add_blank_page(600, 800)
                font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
                page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
                content = DecodedStreamObject(); content.set_data(b'BT /F1 12 Tf 40 700 Td (Synthetic PDF import test. This document contains no clinical advice. Verify encryption handling.) Tj ET')
                page[NameObject('/Contents')] = writer._add_object(content)
                writer.encrypt(user_password=password, owner_password='test-owner-password', algorithm=algorithm)
                output = io.BytesIO(); writer.write(output)
                p = store.get_project(self.p['id'])
                response = self.client.post(self.base+'/sources/upload', data={'revision': p['revision']}, files={'file': ('restricted.pdf', output.getvalue(), 'application/pdf')})
                if not password:
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn('Synthetic PDF import test', response.json()['project']['medical_director']['sources'][-1]['blocks'][0]['text'])
                else:
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn('需要打开密码', response.json()['detail'])

    def test_review_global_scope_and_unknown_target(self):
        self.complete()
        data = copy.deepcopy(m.artifact(self.p, 'review')['data'])
        data['issues'] = [{'id': 'r1', 'target_id': 'global', 'severity': 'high', 'issue': '合成测试问题', 'suggestion': '用于验证范围映射'}]
        result = m.validate(data, self.p, 'review')
        self.assertEqual(result['issues'][0]['target_id'], 'document')
        self.assertEqual(result['issues'][0]['severity'], 'critical')
        data['issues'][0]['target_id'] = m.artifact(self.p, 'hooks')['data']['hooks'][0]['id']
        self.assertEqual(m.validate(data, self.p, 'review')['issues'][0]['target_id'], data['issues'][0]['target_id'])
        data['issues'][0]['target_id'] = 'script.estimated_seconds'
        result = m.validate(data, self.p, 'review')
        self.assertEqual(result['issues'][0]['target_id'], 'script')
        self.assertEqual(result['issues'][0]['target_field'], 'script.estimated_seconds')
        data['issues'][0]['target_id'] = 'nonexistent-invented-target'
        with self.assertRaises(ValueError): m.validate(data, self.p, 'review')

    def test_compatible_model_lists_preserve_every_entry(self):
        row = {'must_keep': ['适用条件', '例外及不确定性', '来源说明']}
        self.assertEqual(m.string(row, 'must_keep'), '适用条件\n例外及不确定性\n来源说明')
        self.assertEqual(row['must_keep'].splitlines(), ['适用条件', '例外及不确定性', '来源说明'])
        with self.assertRaises(ValueError): m.string({'must_keep': {'invented': 'structure'}}, 'must_keep')


if __name__ == '__main__':
    print('Isolated test data:', TEST_ROOT)
    unittest.main(verbosity=2)

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from photo_organizer.catalog import connect
from photo_organizer.ingest import scan
from photo_organizer.results import create, page
from photo_organizer.planning import plan
from photo_organizer.service import dispatch
from photo_organizer.provider import Provider


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'photos'; self.root.mkdir()
        self.state = self.base / 'state'
        for i, color in enumerate(('red', 'blue', 'green')):
            Image.new('RGB', (30 + i, 20), color).save(self.root / f'{i}.jpg')
        scan(self.state, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_pagination_scope_and_new_files(self):
        parent = create(self.state, {})['result_set_id']
        first = page(self.state, parent, limit=1)
        Image.new('RGB', (40, 20), 'yellow').save(self.root / 'new.jpg')
        scan(self.state, self.root)
        self.assertEqual(create(self.state, {})['total'], 4)
        child = create(self.state, {'orientation': 'landscape'}, parent)
        self.assertEqual(child['total'], 3)
        self.assertEqual(page(self.state, parent, limit=1, offset=1)['total'], 3)
        self.assertNotEqual(first['items'][0]['id'], page(self.state, parent, limit=1, offset=1)['items'][0]['id'])
        self.assertEqual(plan(self.state, {'result_set_id': parent})['selected'], 3)

    def test_stale_prevents_silent_replacement(self):
        parent = create(self.state, {})['result_set_id']
        Image.new('RGB', (40, 20), 'white').save(self.root / '0.jpg')
        scan(self.state, self.root)
        self.assertEqual(page(self.state, parent)['stale_members'], 1)
        with self.assertRaises(ValueError): create(self.state, {}, parent)
        with self.assertRaises(ValueError): plan(self.state, {'result_set_id': parent})

    def test_unknown_negation_and_boolean_short_circuit(self):
        self.assertEqual(create(self.state, {'not': {'all_tags': ['person']}})['total'], 0)
        self.assertEqual(create(self.state, {'or': [{'orientation': 'landscape'}, {'all_tags': ['person']}]})['total'], 3)
        result = create(self.state, {'and': [{'orientation': 'portrait'}, {'all_tags': ['person']}]})
        self.assertEqual(result['judgments'], {'not_matched': 3})
        self.assertEqual(create(self.state, {'not': {'orientation': 'portrait'}})['total'], 3)

    def test_overlap_does_not_silently_pick_first(self):
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            plan(self.state, {'group_by': 'rules', 'groups': [{'name': 'a', 'where': {}}, {'name': 'b', 'where': {}}]})
        with connect(self.state) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM plans').fetchone()[0], 0)

    def test_cli_reopens_result_across_process(self):
        result_id = create(self.state, {})['result_set_id']
        process = subprocess.run([sys.executable, '-m', 'photo_organizer.cli', '--state', str(self.state),
                                  'call', 'results', '--args', json.dumps({'result_id': result_id})], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['data']['total'], 3)

    def test_album_rechecks_source_without_scan(self):
        from photo_organizer.execution import apply
        task = plan(self.state, {})
        (self.root / '0.jpg').write_bytes(b'changed after plan')
        result = apply(self.state, task['plan_id'])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['outcomes']['memberships'], 2)

    def test_error_contract_and_config_without_ccswitch(self):
        self.assertEqual(dispatch(self.state, 'search', {'rule': {'invented': True}})['error']['code'], 'invalid_request')
        config = self.base / 'provider.json'
        config.write_text(json.dumps({'protocol': 'anthropic', 'endpoint': 'https://example.invalid/v1/messages',
                                      'model': 'test', 'api_key_env': 'PHOTO_TEST_CREDENTIAL'}))
        from unittest.mock import patch
        with patch.dict(os.environ, {'PHOTO_TEST_CREDENTIAL': 'test-only-not-real'}):
            provider = Provider.from_config(config)
        self.assertEqual(provider.model, 'test')
        self.assertNotIn('test-only-not-real', provider.version)
        self.assertEqual(provider.url, 'https://example.invalid/v1/messages')


if __name__ == '__main__': unittest.main()

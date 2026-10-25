"""Real subprocess stdio integration; not an independent agent acceptance test."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'install the mcp extra')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_roundtrip_and_cli_shared_state(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / 'photos'; root.mkdir()
            Image.new('RGB', (100, 60), 'red').save(root / 'image.jpg')
            state = base / 'state'
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'photo_organizer.mcp_server', '--state', str(state)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    names = {t.name for t in (await client.list_tools()).tools}
                    self.assertIn('photo_search', names)
                    async def call(name, arguments):
                        result = await client.call_tool(name, arguments)
                        self.assertFalse(result.isError, result)
                        body = result.structuredContent or json.loads(result.content[0].text)
                        self.assertEqual(body['status'], 'completed', body)
                        return body['data']
                    await call('photo_scan', {'root': str(root)})
                    result = await call('photo_search', {'rule': {}})
                    child = await call('photo_search', {'rule': {'orientation': 'landscape'}, 'parent_id': result['result_set_id']})
                    self.assertEqual(child['total'], 1)
                    planned = await call('photo_plan', {'spec': {'result_set_id': child['result_set_id']}, 'mode': 'copy', 'target': str(base / 'output')})
                    applied = await call('photo_apply', {'plan_id': planned['plan_id']})
                    self.assertEqual(applied['outcomes']['written'], 1)
                    self.assertEqual(next((base / 'output').rglob('*.jpg')).read_bytes(), (root / 'image.jpg').read_bytes())
            # Different process and transport must preserve exactly the same result membership.
            result = subprocess.run([sys.executable, '-m', 'photo_organizer.cli', '--state', str(state),
                'call', 'results', '--args', json.dumps({'result_id': child['result_set_id']})], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['data']['total'], 1)

"""SDK transport interoperability; distinct from dependency-free replay checks."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from value_lab.replay import record_tools
from test_offline_replay import TOOLS, EXCHANGES


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'MCP SDK required for transport acceptance')
class OfflineMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_live_recording_then_dependency_free_playback(self):
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from value_lab.core import load_json
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / 'live'
            params = StdioServerParameters(command=sys.executable, args=['-S',
                str(root / 'scripts/offline_eval.py'), 'record-live', '--output', str(capture),
                '--tool', 'matrix_sum', '--public-data', '--timeout', '20', '--',
                sys.executable, '-S', str(root / 'tests/fixtures/recording_server.py')])
            async with asyncio.timeout(30):
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.protocolVersion, '2025-06-18')
                        self.assertEqual((await session.list_tools()).tools[0].name, 'matrix_sum')
                        live = await session.call_tool('matrix_sum', {'values': [4, 5, 6]})
                        self.assertEqual(live.structuredContent['sum'], 15)
                receipt = load_json(capture / 'recording.json')
                self.assertEqual(receipt['status'], 'RECORDING_COMPLETE', receipt)
                playback = StdioServerParameters(command=sys.executable, args=['-S',
                    str(root / 'scripts/offline_eval.py'), 'serve', str(capture / 'cassette'),
                    '--expected-id', receipt['cassette_sha256']])
                async with stdio_client(playback) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        value = await session.call_tool('matrix_sum', {'values': [4, 5, 6]})
                        self.assertEqual(value.structuredContent, live.structuredContent)

    async def test_real_sdk_negotiates_and_preserves_both_error_kinds(self):
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.shared.exceptions import McpError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.replay'
            pin = record_tools(root, TOOLS, EXCHANGES, provenance={'origin': 'manufactured', 'description': 'SDK transport fixture'})['cassette_sha256']
            params = StdioServerParameters(command=sys.executable, args=['-S',
                str(Path(__file__).resolve().parents[1] / 'scripts/offline_eval.py'), 'serve', str(root), '--expected-id', pin])
            async with asyncio.timeout(20):
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        init = await session.initialize()
                        self.assertIn(init.protocolVersion, ('2024-11-05', '2025-03-26', '2025-06-18'))
                        self.assertEqual((await session.list_tools()).tools[0].name, 'science_summary')
                        value = await session.call_tool('science_summary', EXCHANGES[0]['request']['arguments'])
                        self.assertEqual(value.structuredContent, EXCHANGES[0]['response']['result']['structuredContent'])
                        failure = await session.call_tool('science_summary', EXCHANGES[1]['request']['arguments'])
                        self.assertTrue(failure.isError)
                        with self.assertRaises(McpError):
                            await session.call_tool('science_summary', EXCHANGES[2]['request']['arguments'])


if __name__ == '__main__':
    unittest.main()

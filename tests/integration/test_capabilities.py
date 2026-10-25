import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from photo_organizer.capabilities import registry as capabilities
from photo_organizer.library.ingest import scan
from photo_organizer.organizing import discovery
from photo_organizer.search import results
from photo_organizer.vision import analysis_tools, people


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        root = self.base / "images"
        root.mkdir()
        self.state = self.base / "state"
        for i in range(3):
            Image.new("RGB", (20 + i, 10), "red").save(root / f"{i}.jpg")
        scan(self.state, root)
        self.r = results.create(self.state, {})
        self.rid = self.r["result_set_id"]
        self.first = self.r["items"][0]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/fail":
                    self.send_response(401)
                    self.end_headers()
                    return
                if "messages" in body:
                    text = json.dumps(
                        {"caption": "red image", "category": "object", "tags": ["red"]}
                    )
                    output = {"choices": [{"message": {"content": text}}]}
                elif body.get("operation") == "ocr":
                    output = {"text": "Invoice 123"}
                else:
                    output = {
                        "space": "test-space",
                        "embeddings": [[1, 0, 1] if isinstance(body["input"], dict) else [0, 1, 1]],
                    }
                encoded = json.dumps(output).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_real_protocol_probe_and_role_isolation(self):
        capabilities.configure(
            self.state, "vision", {"protocol": "openai", "endpoint": self.url, "model": "test"}
        )
        result = capabilities.probe(self.state, "vision", self.rid, self.first["id"])
        self.assertEqual(result["status"], "available")
        status = capabilities.diagnose(self.state, ["image_text"])
        self.assertEqual(status["missing"], ["image_text"])
        config = {
            "protocol": "photo-http",
            "endpoint": self.url,
            "model": "test",
            "revision": "1",
            "space": "test-space",
        }
        capabilities.configure(self.state, "image_text", config)
        self.assertEqual(
            capabilities.probe(self.state, "image_text", self.rid, self.first["id"])["status"],
            "available",
        )
        capabilities.configure(self.state, "image_text", config)
        self.assertEqual(
            capabilities.diagnose(self.state)["roles"]["image_text"]["status"], "available"
        )
        with self.assertRaises(ValueError):
            capabilities.configure(
                self.state,
                "vision",
                {"protocol": "openai", "endpoint": self.url, "model": "test", "api_key": "secret"},
            )

    def test_failure_is_classified_and_not_marked_available(self):
        capabilities.configure(
            self.state,
            "vision",
            {"protocol": "openai", "endpoint": self.url + "/fail", "model": "test"},
        )
        r = capabilities.probe(self.state, "vision", self.rid, self.first["id"])
        self.assertEqual(r["verification"]["error"]["code"], "authentication_failed")
        self.assertEqual(r["status"], "verification_failed")
        with self.assertRaises(Exception):
            capabilities.configure(
                self.state,
                "image_text",
                {"protocol": "openai-text", "endpoint": self.url, "model": "test"},
            )

    def test_ocr_text_and_technical_ranking(self):
        capabilities.configure(
            self.state,
            "ocr",
            {"protocol": "photo-http", "endpoint": self.url, "model": "ocr", "revision": "1"},
        )
        self.assertEqual(
            capabilities.probe(self.state, "ocr", self.rid, self.first["id"], expected_text="123")[
                "status"
            ],
            "available",
        )
        self.assertFalse(analysis_tools.analyze(self.state, self.rid, "ocr")["errors"])
        self.assertEqual(analysis_tools.text_search(self.state, "123", self.rid)["total"], 3)
        analysis_tools.analyze(self.state, self.rid)
        self.assertEqual(analysis_tools.rank(self.state, self.rid)["total"], 3)

    def test_face_identity_and_persistent_manual_split(self):
        records = [
            {"file_id": r["id"], "hash": r["hash"], "box": [1, 1, 4, 4], "vector": [1, 0.01 * i, 1]}
            for i, r in enumerate(self.r["items"])
        ]
        people.submit(self.state, self.rid, records, "face-v1", {"kind": "host"}, "1")
        people.cluster(self.state, "face-v1")
        p = people.manage(self.state)["people"]
        self.assertEqual(len(p), 1)
        fid = people.manage(self.state, "faces", p[0]["id"])["faces"][0]["id"]
        new = people.manage(self.state, "split", face_ids=[fid], name="Person B")
        people.cluster(self.state, "face-v1")
        self.assertEqual(len(people.manage(self.state, "faces", new["person_id"])["faces"]), 1)
        self.assertIn("group_spec_id", discovery.suggest(self.state, self.rid, "person"))


if __name__ == "__main__":
    unittest.main()

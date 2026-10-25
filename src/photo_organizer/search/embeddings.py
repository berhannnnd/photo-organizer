"""Digest-bound local Ollama image/text embeddings and persistent candidate retrieval."""

import base64
import datetime
import hashlib
import json
import math
import struct
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from photo_organizer.core.errors import CapabilityError
from photo_organizer.library.ingest import PREP
from photo_organizer.search import results
from photo_organizer.storage.catalog import connect, writer_lock

SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_spaces(id TEXT PRIMARY KEY,model TEXT,digest TEXT,endpoint TEXT,prep TEXT,dimensions INTEGER);
CREATE TABLE IF NOT EXISTS image_vectors(space_id TEXT,hash TEXT,vector BLOB,PRIMARY KEY(space_id,hash));
CREATE TABLE IF NOT EXISTS description_vectors(space_id TEXT,hash TEXT,observation_version TEXT,text_hash TEXT,vector BLOB,PRIMARY KEY(space_id,hash));
CREATE TABLE IF NOT EXISTS query_vectors(space_id TEXT,query TEXT,vector BLOB,PRIMARY KEY(space_id,query));
"""


def initialize(c):
    c.executescript(SCHEMA)


def pack(vector):
    if (
        not isinstance(vector, list)
        or not vector
        or any(type(x) not in (float, int) or not math.isfinite(x) for x in vector)
    ):
        raise ValueError("invalid embedding vector")
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("zero or invalid vector")
    return struct.pack("<" + "f" * len(vector), *(x / norm for x in vector))


def unpack(blob):
    return struct.unpack("<" + "f" * (len(blob) // 4), blob)


class Ollama:
    def __init__(self, model="embeddinggemma-2:latest", endpoint="http://127.0.0.1:11434"):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Ollama embedding endpoint must be local loopback HTTP")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.digest = self.current_digest()
        self.space = hashlib.sha256(
            json.dumps(
                [self.endpoint, model, self.digest, PREP, "raw-input-normalized-f32-v1"]
            ).encode()
        ).hexdigest()

    def request(self, path, body=None):
        from photo_organizer.capabilities.adapters.http import request

        return request(
            {"protocol": "ollama", "endpoint": self.endpoint, "timeout": 180}, body, path
        )

    def current_digest(self):
        rows = self.request("/api/tags").get("models", [])
        row = next(
            (r for r in rows if r.get("name") == self.model or r.get("model") == self.model), None
        )
        if not row or not row.get("digest"):
            raise ValueError("installed Ollama model not found; no automatic download")
        return row["digest"]

    def encode(self, value):
        if self.current_digest() != self.digest:
            raise ValueError("model artifact changed; start a new embedding space")
        response = self.request(
            "/api/embed",
            {"model": self.model, "input": value, "keep_alive": "10m", "truncate": False},
        )
        if self.current_digest() != self.digest:
            raise ValueError("model artifact changed during inference")
        vectors = response.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1:
            raise ValueError("expected exactly one embedding")
        return pack(vectors[0])


def register(c, provider, blob):
    dimensions = len(blob) // 4
    row = c.execute(
        "SELECT dimensions FROM embedding_spaces WHERE id=?", (provider.space,)
    ).fetchone()
    if row and row[0] != dimensions:
        raise ValueError("embedding dimension changed within one space")
    c.execute(
        "INSERT OR IGNORE INTO embedding_spaces VALUES(?,?,?,?,?,?)",
        (provider.space, provider.model, provider.digest, provider.endpoint, PREP, dimensions),
    )


def provider_for(state, model, endpoint, role="image_text"):
    with connect(state) as c:
        row = c.execute("SELECT role FROM capability_configs WHERE role=?", (role,)).fetchone()
    if row:
        from photo_organizer.capabilities.adapters.encoding import Encoder
        from photo_organizer.capabilities.registry import get_config

        return Encoder(get_config(state, role))
    return Ollama(model, endpoint)


def index(state, model="embeddinggemma-2:latest", endpoint="http://127.0.0.1:11434", limit=None):
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be positive")
    provider = provider_for(state, model, endpoint)
    start = time.perf_counter()
    completed = 0
    errors = []
    # Independent stage lock: short SQL commits may coexist with cloud visual indexing.
    with writer_lock(Path(state) / "embedding-lock"), connect(state) as c:
        initialize(c)
        rows = c.execute(
            """SELECT a.hash,a.derivative FROM assets a WHERE a.prep_version=?
          AND EXISTS(SELECT 1 FROM files f WHERE f.hash=a.hash AND f.present=1 AND f.error IS NULL)
          AND NOT EXISTS(SELECT 1 FROM image_vectors v WHERE v.hash=a.hash AND v.space_id=?)
          ORDER BY a.hash LIMIT ?""",
            (PREP, provider.space, limit or -1),
        ).fetchall()
        for row in rows:
            try:
                content = Path(row["derivative"]).read_bytes()
                if len(content) > 4_000_000:
                    raise ValueError("derivative exceeds embedding input budget")
                blob = provider.encode({"image": base64.b64encode(content).decode()})
                with c:
                    register(c, provider, blob)
                    c.execute(
                        "INSERT OR REPLACE INTO image_vectors VALUES(?,?,?)",
                        (provider.space, row["hash"], blob),
                    )
                completed += 1
            except (OSError, ValueError, CapabilityError) as e:
                errors.append({"hash": row["hash"], "error": str(e)[:200]})
                if len(errors) >= 3:
                    break
            if completed and completed % 25 == 0:
                import sys

                print(
                    json.dumps({"embedding_completed": completed, "requested": len(rows)}),
                    file=sys.stderr,
                    flush=True,
                )
        total = c.execute(
            "SELECT count(*) FROM image_vectors WHERE space_id=?", (provider.space,)
        ).fetchone()[0]
    return {
        "space_id": provider.space,
        "model": model,
        "digest": provider.digest,
        "completed_now": completed,
        "indexed_contents": total,
        "requested": len(rows),
        "errors": errors,
        "seconds": time.perf_counter() - start,
    }


def index_descriptions(
    state, model="embeddinggemma-2:latest", endpoint="http://127.0.0.1:11434", limit=None
):
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be positive")
    with connect(state) as c:
        independent = c.execute(
            "SELECT 1 FROM capability_configs WHERE role='description_text'"
        ).fetchone()
    provider = provider_for(
        state, model, endpoint, "description_text" if independent else "image_text"
    )
    start = time.perf_counter()
    completed = 0
    errors = []
    with writer_lock(Path(state) / "description-lock"), connect(state) as c:
        initialize(c)
        rows = c.execute(
            "SELECT a.hash,a.caption,a.vision_version,v.text_hash,v.observation_version FROM assets a LEFT JOIN description_vectors v ON v.hash=a.hash AND v.space_id=? WHERE a.vision_state='complete' AND a.caption IS NOT NULL AND EXISTS(SELECT 1 FROM files f WHERE f.hash=a.hash AND f.present=1 AND f.error IS NULL)",
            (provider.space,),
        ).fetchall()
        for row in rows:
            text_hash = hashlib.sha256(row["caption"].encode()).hexdigest()
            if (
                row["text_hash"] == text_hash
                and row["observation_version"] == row["vision_version"]
            ):
                continue
            if limit is not None and completed >= limit:
                break
            try:
                vector = provider.encode(row["caption"])
                with c:
                    register(c, provider, vector)
                    c.execute(
                        "INSERT OR REPLACE INTO description_vectors VALUES(?,?,?,?,?)",
                        (provider.space, row["hash"], row["vision_version"], text_hash, vector),
                    )
                completed += 1
            except (OSError, ValueError, CapabilityError) as e:
                errors.append({"hash": row["hash"], "error": str(e)[:200]})
                if len(errors) >= 3:
                    break
    return {
        "space_id": provider.space,
        "completed_now": completed,
        "errors": errors,
        "seconds": time.perf_counter() - start,
    }


def search(
    state,
    text,
    model="embeddinggemma-2:latest",
    endpoint="http://127.0.0.1:11434",
    top_k=30,
    parent_id=None,
    ranking="hybrid",
):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        raise ValueError("text must contain 1..2000 characters")
    if type(top_k) is not int or not 1 <= top_k <= 1000:
        raise ValueError("top_k must be 1..1000")
    if ranking not in ("image", "hybrid"):
        raise ValueError("ranking must be image or hybrid")
    text = text.strip()
    start = time.perf_counter()
    provider = provider_for(state, model, endpoint)
    with connect(state) as c:
        initialize(c)
        results.initialize(c)
        space = c.execute("SELECT * FROM embedding_spaces WHERE id=?", (provider.space,)).fetchone()
        if not space:
            raise ValueError("no index for this exact model artifact; run embed-index")
        row = c.execute(
            "SELECT vector FROM query_vectors WHERE space_id=? AND query=?", (provider.space, text)
        ).fetchone()
        cached = row is not None
        if cached:
            vector = row[0]
        else:
            vector = provider.encode(text)
            if len(vector) // 4 != space["dimensions"]:
                raise ValueError("query and image dimension mismatch")
            with c:
                c.execute(
                    "INSERT OR REPLACE INTO query_vectors VALUES(?,?,?)",
                    (provider.space, text, vector),
                )
        c.execute("BEGIN IMMEDIATE")
        try:
            scope = ""
            params = [provider.space]
            if parent_id:
                results.require(c, parent_id)
                if results.stale_count(c, parent_id):
                    raise ValueError("parent snapshot is stale")
                scope = " AND f.id IN(SELECT file_id FROM result_members WHERE result_id=? AND verdict IN ('matched','candidate'))"
                params.append(parent_id)
            rows = c.execute(
                """SELECT f.id,f.path,f.hash,v.vector FROM files f LEFT JOIN image_vectors v
                ON v.hash=f.hash AND v.space_id=? WHERE f.present=1 AND f.error IS NULL"""
                + scope,
                params,
            ).fetchall()
            query = unpack(vector)
            scored = []
            for row in rows:
                if row["vector"] is not None:
                    values = unpack(row["vector"])
                    if len(values) != len(query):
                        raise ValueError("corrupt vector dimension")
                    score = sum(a * b for a, b in zip(query, values))
                    scored.append((score, row))
            scored.sort(key=lambda item: (-item[0], item[1]["id"]))
            image_count = len(scored)
            description_count = 0
            fused_enabled = False
            if ranking == "hybrid":
                descriptions = {
                    r["hash"]: r
                    for r in c.execute(
                        "SELECT d.*,a.caption,a.vision_version FROM description_vectors d JOIN assets a ON a.hash=d.hash WHERE d.space_id=? AND a.vision_state='complete'",
                        (provider.space,),
                    )
                }
                text_scored = []
                for row in rows:
                    desc = descriptions.get(row["hash"])
                    if (
                        not desc
                        or desc["observation_version"] != desc["vision_version"]
                        or desc["text_hash"] != hashlib.sha256(desc["caption"].encode()).hexdigest()
                    ):
                        continue
                    values = unpack(desc["vector"])
                    if len(values) != len(query):
                        raise ValueError("corrupt description vector dimension")
                    text_scored.append((sum(a * b for a, b in zip(query, values)), row))
                description_count = len(text_scored)
                text_scored.sort(key=lambda item: (-item[0], item[1]["id"]))
                if text_scored and description_count == len(rows) == len(scored):
                    fused_enabled = True
                    fused = {}
                    for channel in (scored, text_scored):
                        for rank, (_, row) in enumerate(channel, 1):
                            entry = fused.setdefault(row["id"], [0, row])
                            entry[0] += 1 / (60 + rank)
                    scored = sorted(fused.values(), key=lambda item: (-item[0], item[1]["id"]))
            chosen = scored[:top_k]
            rid = uuid.uuid4().hex
            counts = {
                "candidate": len(chosen),
                "not_retrieved": len(scored) - len(chosen),
                "unindexed": len(rows) - len(scored),
            }
            rule = {
                "retrieval": text,
                "top_k": top_k,
                "space_id": provider.space,
                "ranking": ranking,
                "description_coverage": description_count,
                "scope_count": len(rows),
                "effective_ranking": "hybrid" if fused_enabled else "image",
                "score_kind": "rrf" if fused_enabled else "cosine",
            }
            c.execute(
                "INSERT INTO result_sets VALUES(?,?,?,?,?)",
                (
                    rid,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    parent_id,
                    json.dumps(rule, ensure_ascii=False),
                    json.dumps(counts),
                ),
            )
            c.executemany(
                "INSERT INTO result_members(result_id,file_id,hash,path,verdict,score) VALUES(?,?,?,?,?,?)",
                [(rid, r["id"], r["hash"], r["path"], "candidate", s) for s, r in chosen],
            )
            c.commit()
        except Exception:
            c.rollback()
            raise
    result = results.page(state, rid)
    return {
        **result,
        "seconds": time.perf_counter() - start,
        "query_cache_hit": cached,
        "model_calls": 0 if cached else 1,
        "coverage": {
            "scope_files": len(rows),
            "image_vectors_searched": image_count,
            "description_vectors_available": description_count,
            "missing_image_vectors": len(rows) - image_count,
        },
        "coverage_notice": f"Searched {image_count} of {len(rows)} source-file image vectors. Visual-label completion is a separate stage and does not exclude files from image retrieval. Candidates are not exhaustive semantic matches.",
        "scope_note": "Ranked candidates, not verified matches or exhaustive semantic recall.",
    }

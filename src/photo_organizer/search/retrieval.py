"""Multi-channel retrieval with explicit vector spaces and candidate provenance."""

import hashlib
import json

from photo_organizer.core.errors import CapabilityError
from photo_organizer.search import results
from photo_organizer.search.embeddings import initialize, pack, provider_for, register, unpack
from photo_organizer.search.selection import members, retrieval_context, save
from photo_organizer.storage.catalog import connect


def submit_vectors(
    state, result_id, records, space, model, revision, query=None, query_vector=None
):
    if not all(isinstance(x, str) and 1 <= len(x) <= 300 for x in (space, model, revision)):
        raise ValueError("space, model and immutable revision required")
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("at most 100 vector records")
    if query is not None and (not isinstance(query, str) or not 1 <= len(query) <= 2000):
        raise ValueError("invalid query")

    class Host:
        endpoint = "host-tool"

    host = Host()
    host.model = model
    host.digest = revision
    host.space = hashlib.sha256(json.dumps(["host", space, model, revision]).encode()).hexdigest()
    with connect(state) as c:
        initialize(c)
        scope = {r["file_id"]: r for r in members(c, result_id)}
        validated = []
        for r in records:
            if r.get("file_id") not in scope or r.get("hash") != scope[r["file_id"]]["hash"]:
                raise ValueError("out-of-scope or stale vector")
            validated.append((r["hash"], pack(r.get("vector"))))
        q = pack(query_vector) if query is not None else None
        if query is None and query_vector is not None:
            raise ValueError("query required with query_vector")
        dimensions = {len(v) for _, v in validated}
        if q:
            dimensions.add(len(q))
        if len(dimensions) != 1:
            raise ValueError("nonempty compatible vectors required")
        for sha, blob in validated:
            register(c, host, blob)
            c.execute("INSERT OR REPLACE INTO image_vectors VALUES(?,?,?)", (host.space, sha, blob))
        if q:
            register(c, host, q)
            c.execute("INSERT OR REPLACE INTO query_vectors VALUES(?,?,?)", (host.space, query, q))
    return {
        "space_id": host.space,
        "saved": len(validated),
        "query_cached": q is not None,
        "source": "host",
        "quality": "not_evaluated",
    }


def vector_search(state, space_id, text=None, reference_id=None, parent_id=None, top_k=30):
    if (text is None) == (reference_id is None):
        raise ValueError("provide exactly one of text or reference_id")
    if type(top_k) is not int or not 1 <= top_k <= 1000:
        raise ValueError("top_k must be 1..1000")
    if parent_id is None:
        parent_id = results.create(state, {})["result_set_id"]
    with connect(state) as c:
        initialize(c)
        rows = members(c, parent_id)
        if text is not None:
            query = c.execute(
                "SELECT vector FROM query_vectors WHERE space_id=? AND query=?", (space_id, text)
            ).fetchone()
        else:
            query = c.execute(
                "SELECT v.vector FROM files f JOIN image_vectors v ON f.hash=v.hash WHERE f.id=? AND f.present=1 AND f.error IS NULL AND v.space_id=?",
                (reference_id, space_id),
            ).fetchone()
        if not query:
            raise CapabilityError(
                "missing_query_vector", "Encode the query/reference in this exact space first"
            )
        q = unpack(query[0])
        ranked = []
        indexed = 0
        for row in rows:
            v = c.execute(
                "SELECT vector FROM image_vectors WHERE space_id=? AND hash=?",
                (space_id, row["hash"]),
            ).fetchone()
            if not v:
                continue
            vector = unpack(v[0])
            indexed += 1
            if len(vector) != len(q):
                raise ValueError("incompatible vector dimensions")
            ranked.append(
                {**row, "score": sum(a * b for a, b in zip(vector, q)), "verdict": "candidate"}
            )
        ranked.sort(key=lambda r: (-r["score"], r["file_id"]))
        criterion = text or "similar to file " + str(reference_id)
        rid = save(
            c,
            ranked[:top_k],
            {"retrieval": criterion, "space_id": space_id, "top_k": top_k},
            parent_id,
            retrieval_context(
                c,
                parent_id,
                criterion,
                coverage="ranked_subset",
                scope_count=len(rows),
                indexed=indexed,
            ),
        )
    return results.page(state, rid)


def search(
    state,
    text,
    top_k=30,
    parent_id=None,
    model="embeddinggemma-2:latest",
    endpoint="http://127.0.0.1:11434",
    ranking="hybrid",
    allow_text_fallback=False,
):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        raise ValueError("text must contain 1..2000 characters")
    if type(top_k) is not int or not 1 <= top_k <= 1000 or ranking not in ("image", "hybrid"):
        raise ValueError("invalid retrieval settings")
    text = text.strip()
    if parent_id is None:
        parent_id = results.create(state, {})["result_set_id"]
    # Model calls happen before taking a write transaction; committed metadata remains queryable.
    channels = []
    errors = []
    calls = 0
    for role in ("image_text", "description_text") if ranking == "hybrid" else ("image_text",):
        with connect(state) as c:
            configured = c.execute(
                "SELECT 1 FROM capability_configs WHERE role=?", (role,)
            ).fetchone()
        if role == "description_text" and not configured:
            if channels:
                channels.append(("description", channels[0][1], channels[0][2]))
                continue
            continue
        try:
            provider = provider_for(state, model, endpoint, role)
            with connect(state) as c:
                initialize(c)
                cached = c.execute(
                    "SELECT vector FROM query_vectors WHERE space_id=? AND query=?",
                    (provider.space, text),
                ).fetchone()
            if cached:
                q = cached[0]
            else:
                q = provider.encode(text)
                calls += 1
                with connect(state) as c:
                    register(c, provider, q)
                    c.execute(
                        "INSERT OR REPLACE INTO query_vectors VALUES(?,?,?)",
                        (provider.space, text, q),
                    )
            channels.append(("image" if role == "image_text" else "description", provider.space, q))
        except (ValueError, OSError, CapabilityError) as e:
            if not allow_text_fallback:
                raise
            errors.append({"role": role, "reason": str(e)[:250]})
    with connect(state) as c:
        initialize(c)
        rows = members(c, parent_id)
        rankings = []
        coverage = {}
        provenance = {}
        scope = {r["file_id"]: r for r in rows}
        for kind, space, qblob in channels:
            q = unpack(qblob)
            scores = []
            for row in rows:
                if kind == "image":
                    v = c.execute(
                        "SELECT vector FROM image_vectors WHERE space_id=? AND hash=?",
                        (space, row["hash"]),
                    ).fetchone()
                else:
                    v = c.execute(
                        "SELECT d.vector,d.text_hash,a.caption FROM description_vectors d JOIN assets a ON a.hash=d.hash WHERE d.space_id=? AND d.hash=? AND d.observation_version=a.vision_version AND a.vision_state='complete'",
                        (space, row["hash"]),
                    ).fetchone()
                    if v and hashlib.sha256(v["caption"].encode()).hexdigest() != v["text_hash"]:
                        v = None
                if not v:
                    continue
                vector = unpack(v["vector"])
                if len(vector) != len(q):
                    raise ValueError("incompatible vector dimensions")
                scores.append((sum(a * b for a, b in zip(q, vector)), row["file_id"]))
            scores.sort(key=lambda x: (-x[0], x[1]))
            coverage[kind] = len(scores)
            rankings.append((kind, scores))
        if ranking == "hybrid":
            scores = []
            indexed = 0
            for row in rows:
                a = c.execute(
                    "SELECT caption FROM assets WHERE hash=? AND vision_state='complete'",
                    (row["hash"],),
                ).fetchone()
                o = c.execute(
                    "SELECT payload FROM observations WHERE hash=? AND kind='ocr' ORDER BY created DESC LIMIT 1",
                    (row["hash"],),
                ).fetchone()
                values = ([a[0]] if a and a[0] else []) + (
                    [json.loads(o[0]).get("text", "")] if o else []
                )
                if values:
                    indexed += 1
                count = sum(v.casefold().count(text.casefold()) for v in values)
                if count:
                    scores.append((count, row["file_id"]))
            scores.sort(key=lambda x: (-x[0], x[1]))
            coverage["literal_text"] = indexed
            rankings.append(("literal_text", scores))
        fused = {}
        # Each channel contributes only its bounded candidate window; absent evidence is not a negative score.
        for name, scores in rankings:
            for rank, (score, fid) in enumerate(scores[: max(top_k * 4, 100)], 1):
                fused[fid] = fused.get(fid, 0) + 1 / (60 + rank)
                provenance.setdefault(fid, []).append(
                    {"channel": name, "rank": rank, "score": score}
                )
        ranked = sorted(fused, key=lambda fid: (-fused[fid], fid))[:top_k]
        chosen = [{**scope[fid], "score": fused[fid], "verdict": "candidate"} for fid in ranked]
        rid = save(
            c,
            chosen,
            {"retrieval": text, "top_k": top_k, "ranking": ranking},
            parent_id,
            retrieval_context(
                c,
                parent_id,
                text,
                coverage="ranked_subset",
                scope_count=len(rows),
                channel_coverage=coverage,
                fallbacks=errors,
            ),
            {fid: {"channels": provenance[fid]} for fid in ranked},
        )
    return {
        **results.page(state, rid),
        "model_calls": calls,
        "channel_coverage": coverage,
        "fallbacks": errors,
    }

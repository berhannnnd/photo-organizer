"""Per-stage coverage over the complete frozen scope, including unreturned verdicts."""

from photo_organizer.search import results
from photo_organizer.search.embeddings import initialize
from photo_organizer.search.evaluation import evaluate
from photo_organizer.storage.catalog import connect


def inspect(state, result_id, condition=None):
    with connect(state) as c:
        results.require(c, result_id)
        initialize(c)
        rows = c.execute(
            "SELECT m.*,f.present,f.error,a.vision_state,a.vision_version FROM result_members m LEFT JOIN files f ON f.id=m.file_id LEFT JOIN assets a ON a.hash=m.hash WHERE m.result_id=?",
            (result_id,),
        ).fetchall()
        hashes = {r["hash"] for r in rows if r["hash"]}
        stages = {}
        for kind in ("ocr", "quality", "face_detection"):
            indexed = {
                r[0]
                for r in c.execute("SELECT DISTINCT hash FROM observations WHERE kind=?", (kind,))
            } & hashes
            stages[kind] = {
                "indexed_contents": len(indexed),
                "missing_contents": len(hashes - indexed),
            }
        vectors = {}
        for space in c.execute("SELECT id,model,digest,dimensions FROM embedding_spaces"):
            covered = {
                r[0]
                for r in c.execute(
                    "SELECT hash FROM image_vectors WHERE space_id=?", (space["id"],)
                )
            } & hashes
            vectors[space["id"]] = {
                **dict(space),
                "indexed_contents": len(covered),
                "missing_contents": len(hashes - covered),
            }
        verdicts = {}
        if condition is not None:
            from photo_organizer.search.predicates import predicate

            predicate({"semantic": condition})
            ancestry = []
            current = result_id
            while current:
                ancestry.append(current)
                current = results.require(c, current)["parent_id"]
            for row in rows:
                state_name = (
                    "error"
                    if row["error"] or not row["present"]
                    else evaluate(
                        c, {**dict(row), "id": row["file_id"]}, {"semantic": condition}, ancestry
                    )["verdict"]
                )
                verdicts[state_name] = verdicts.get(state_name, 0) + 1
        return {
            "result_set_id": result_id,
            "scope_files": len(rows),
            "scope_contents": len(hashes),
            "stale_members": results.stale_count(c, result_id),
            "stages": stages,
            "image_spaces": vectors,
            "criterion": condition,
            "criterion_verdicts": verdicts,
            "visual_files": sum(r["vision_state"] == "complete" for r in rows),
            "freshness": "last committed observations; inspect versions before reuse",
            "model_calls": 0,
        }

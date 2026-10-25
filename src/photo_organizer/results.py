"""Persistent membership snapshots, bounded paging, and parent-scoped refinement."""
import datetime
import json
import uuid
from .catalog import connect, writer_lock
from .predicates import predicate

SCHEMA = '''
CREATE TABLE IF NOT EXISTS result_sets(
 id TEXT PRIMARY KEY, created TEXT NOT NULL, parent_id TEXT, rule TEXT NOT NULL,
 counts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS result_members(
 result_id TEXT NOT NULL, file_id INTEGER NOT NULL, hash TEXT, path TEXT NOT NULL,
 verdict TEXT NOT NULL, PRIMARY KEY(result_id,file_id));
CREATE INDEX IF NOT EXISTS result_page ON result_members(result_id,verdict,file_id);
'''


def initialize(c):
    c.executescript(SCHEMA)


def require(c, result_id):
    row = c.execute('SELECT * FROM result_sets WHERE id=?', (result_id,)).fetchone()
    if row is None: raise ValueError('unknown result_set_id')
    return row


def stale_count(c, result_id):
    return c.execute('''SELECT count(*) FROM result_members m LEFT JOIN files f ON f.id=m.file_id
        WHERE m.result_id=? AND m.verdict='matched'
        AND (f.id IS NULL OR f.present!=1 OR f.error IS NOT NULL OR f.hash IS NOT m.hash)''', (result_id,)).fetchone()[0]


def create(state, rule, parent_id=None):
    # Bound the total AST before recursive compilation and SQLite parameter expansion.
    encoded = json.dumps(rule, ensure_ascii=False)
    if len(encoded) > 16000: raise ValueError('rule exceeds 16000 characters')
    sql, params = predicate(rule)
    with writer_lock(state), connect(state) as c:
        initialize(c)
        with c:
            c.execute('BEGIN IMMEDIATE')
            if parent_id:
                require(c, parent_id)
                if stale_count(c, parent_id): raise ValueError('parent snapshot has stale members; refresh explicitly')
            scope = ''
            scope_params = []
            if parent_id:
                scope = " AND f.id IN (SELECT file_id FROM result_members WHERE result_id=? AND verdict='matched')"
                scope_params.append(parent_id)
            rows = c.execute("SELECT f.id,f.path,f.hash,CASE WHEN f.error IS NOT NULL THEN 'error' WHEN (" + sql + ") THEN 'matched' WHEN NOT (" + sql + ") THEN 'not_matched' ELSE 'unknown_or_unanalyzed' END AS verdict FROM files f LEFT JOIN assets a ON a.hash=f.hash WHERE f.present=1" + scope + ' ORDER BY f.id', params + params + scope_params).fetchall()
            counts = {}
            for row in rows: counts[row['verdict']] = counts.get(row['verdict'], 0) + 1
            result_id = uuid.uuid4().hex
            c.execute('INSERT INTO result_sets VALUES(?,?,?,?,?)', (result_id, datetime.datetime.now(datetime.timezone.utc).isoformat(), parent_id, encoded, json.dumps(counts)))
            c.executemany('INSERT INTO result_members VALUES(?,?,?,?,?)', [(result_id, r['id'], r['hash'], r['path'], r['verdict']) for r in rows])
    return page(state, result_id)


def page(state, result_id, limit=50, offset=0, verdict='matched'):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or offset < 0:
        raise ValueError('invalid pagination')
    if verdict not in ('matched', 'not_matched', 'unknown_or_unanalyzed', 'error'):
        raise ValueError('invalid verdict')
    with connect(state) as c:
        initialize(c)
        c.execute('BEGIN')
        result = require(c, result_id)
        counts = json.loads(result['counts'])
        rows = c.execute('''SELECT m.file_id AS id,m.hash,m.path,m.verdict,f.path AS current_path,
            CASE WHEN f.id IS NULL OR f.present!=1 OR f.error IS NOT NULL OR f.hash IS NOT m.hash THEN 1 ELSE 0 END AS stale
            FROM result_members m LEFT JOIN files f ON f.id=m.file_id
            WHERE m.result_id=? AND m.verdict=? ORDER BY m.file_id LIMIT ? OFFSET ?''', (result_id, verdict, limit, offset)).fetchall()
        total = counts.get(verdict, 0)
        return {'result_set_id': result_id, 'parent_id': result['parent_id'], 'created': result['created'],
                'rule': json.loads(result['rule']), 'judgments': counts, 'total': total,
                'items': [dict(r) for r in rows], 'offset': offset, 'limit': limit,
                'next_offset': offset + limit if offset + limit < total else None,
                'stale_members': stale_count(c, result_id), 'model_calls': 0,
                'freshness': 'relative_to_last_scan; run scan before operations requiring current files'}


def select_snapshot(c, result_id):
    initialize(c)
    require(c, result_id)
    if stale_count(c, result_id): raise ValueError('snapshot has stale members; refresh explicitly')
    return c.execute('''SELECT f.id,f.path,f.hash,a.taken,a.width,a.height,a.category,a.vision_state
        FROM result_members m JOIN files f ON f.id=m.file_id JOIN assets a ON a.hash=m.hash
        WHERE m.result_id=? AND m.verdict='matched' ORDER BY f.id''', (result_id,)).fetchall()

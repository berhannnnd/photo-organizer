"""SQLite source of truth for content, locations, observations and execution receipts."""
import contextlib
import fcntl
import json
import sqlite3
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS assets(
 hash TEXT PRIMARY KEY, width INTEGER, height INTEGER, taken TEXT, date_source TEXT,
 derivative TEXT, prep_version TEXT, prep_error TEXT, vision_state TEXT DEFAULT 'pending',
 vision_version TEXT, caption TEXT, category TEXT, vision_error TEXT, elapsed REAL, usage TEXT);
CREATE TABLE IF NOT EXISTS files(
 id INTEGER PRIMARY KEY, root TEXT NOT NULL, path TEXT UNIQUE NOT NULL, hash TEXT,
 size INTEGER, mtime_ns INTEGER, present INTEGER DEFAULT 1, error TEXT);
CREATE INDEX IF NOT EXISTS file_root ON files(root,present);
CREATE INDEX IF NOT EXISTS file_hash ON files(hash);
CREATE INDEX IF NOT EXISTS date_idx ON assets(taken);
CREATE TABLE IF NOT EXISTS tags(hash TEXT, tag TEXT, PRIMARY KEY(hash,tag));
CREATE INDEX IF NOT EXISTS tag_lookup ON tags(tag,hash);
CREATE TABLE IF NOT EXISTS conditions(id TEXT PRIMARY KEY, text TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS judgments(hash TEXT, condition_id TEXT, version TEXT, verdict TEXT, evidence TEXT, PRIMARY KEY(hash,condition_id,version));
CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, created TEXT, spec TEXT, target TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS actions(
 id TEXT PRIMARY KEY, plan_id TEXT, file_id INTEGER, source TEXT, hash TEXT, relative TEXT,
 status TEXT DEFAULT 'pending', error TEXT, output_hash TEXT, output_bytes INTEGER);
CREATE INDEX IF NOT EXISTS action_plan ON actions(plan_id,status);
'''

@contextlib.contextmanager
def connect(state):
    state = Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(state / 'catalog.sqlite', timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    c.executescript(SCHEMA)
    try:
        with c:
            yield c
    finally:
        c.close()

@contextlib.contextmanager
def writer_lock(state):
    """One writer task per library; readers remain available during slow indexing."""
    Path(state).mkdir(parents=True, exist_ok=True)
    with open(Path(state) / 'writer.lock', 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another writer is active; retry after it finishes') from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def report(c):
    counts = dict(c.execute("SELECT COALESCE(a.vision_state,'unavailable'),count(*) FROM files f LEFT JOIN assets a ON f.hash=a.hash WHERE f.present=1 GROUP BY COALESCE(a.vision_state,'unavailable')").fetchall())
    return {'files':c.execute('SELECT count(*) FROM files WHERE present=1').fetchone()[0],
            'unique_contents':c.execute('SELECT count(DISTINCT hash) FROM files WHERE present=1').fetchone()[0],
            'file_errors':c.execute('SELECT count(*) FROM files WHERE present=1 AND error IS NOT NULL').fetchone()[0],
            'dated_files':c.execute('SELECT count(*) FROM files f JOIN assets a ON f.hash=a.hash WHERE f.present=1 AND a.taken IS NOT NULL').fetchone()[0],
            'vision':counts,
            'vision_versions':[r[0] for r in c.execute('SELECT DISTINCT vision_version FROM assets WHERE vision_version IS NOT NULL')]}

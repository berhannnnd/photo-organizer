"""Transactional, forward-only catalog upgrades; old catalogs remain readable."""

import datetime

VERSION = 4
DDL = """
CREATE TABLE roots(id INTEGER PRIMARY KEY,path TEXT UNIQUE NOT NULL,status TEXT NOT NULL DEFAULT 'online',last_scan TEXT,last_success TEXT,revision INTEGER DEFAULT 0,error TEXT,enabled INTEGER DEFAULT 1);
CREATE TABLE scans(id TEXT PRIMARY KEY,root_id INTEGER,started TEXT,finished TEXT,status TEXT,error TEXT);
CREATE TABLE observations(id TEXT PRIMARY KEY,hash TEXT NOT NULL,kind TEXT NOT NULL,version TEXT NOT NULL,source TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX observation_asset ON observations(hash,kind,created);
CREATE TABLE corrections(id TEXT PRIMARY KEY,hash TEXT NOT NULL,field TEXT NOT NULL,value TEXT NOT NULL,scope_id TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX correction_field ON corrections(hash,field,scope_id,created);
CREATE TABLE result_context(result_id TEXT PRIMARY KEY,context TEXT NOT NULL);
CREATE TABLE result_details(result_id TEXT,file_id INTEGER,detail TEXT NOT NULL,PRIMARY KEY(result_id,file_id));
CREATE TABLE group_specs(id TEXT PRIMARY KEY,result_id TEXT NOT NULL,parent_id TEXT,definition TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE collections(id TEXT PRIMARY KEY,name TEXT NOT NULL,result_id TEXT NOT NULL,plan_id TEXT,created TEXT NOT NULL);
CREATE TABLE collection_members(collection_id TEXT,file_id INTEGER,hash TEXT,path TEXT,group_path TEXT,PRIMARY KEY(collection_id,file_id,group_path));
CREATE TABLE capability_configs(role TEXT PRIMARY KEY,config TEXT NOT NULL,revision TEXT NOT NULL,status TEXT NOT NULL,verification TEXT,updated TEXT NOT NULL);
CREATE TABLE jobs(id TEXT PRIMARY KEY,operation TEXT NOT NULL,arguments TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,control TEXT,owner TEXT,progress TEXT NOT NULL,result TEXT,error TEXT,budget TEXT NOT NULL);
CREATE TABLE job_items(job_id TEXT,item_id TEXT,status TEXT NOT NULL,attempts INTEGER DEFAULT 0,result TEXT,error TEXT,PRIMARY KEY(job_id,item_id));
CREATE TABLE people(id TEXT PRIMARY KEY,name TEXT,version INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
CREATE TABLE faces(id TEXT PRIMARY KEY,hash TEXT NOT NULL,space TEXT NOT NULL,box TEXT NOT NULL,vector BLOB NOT NULL,person_id TEXT,source TEXT NOT NULL,version TEXT NOT NULL);
CREATE TABLE face_constraints(face_id TEXT PRIMARY KEY,person_id TEXT,updated TEXT NOT NULL);
CREATE TABLE library_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""


def migrate(c):
    version = c.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION:
        raise ValueError("catalog is newer than this engine; upgrade the engine")
    if version == VERSION:
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        if c.execute("PRAGMA user_version").fetchone()[0] < 1:
            for statement in DDL.split(";"):
                if statement.strip():
                    c.execute(statement)
            for table, additions in {
                "files": [("device", "INTEGER"), ("inode", "INTEGER"), ("imported_at", "TEXT")],
                "assets": [("latitude", "REAL"), ("longitude", "REAL"), ("timezone", "TEXT")],
            }.items():
                columns = {r[1] for r in c.execute("PRAGMA table_info(" + table + ")")}
                for name, kind in additions:
                    if name not in columns:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c.execute("UPDATE files SET imported_at=? WHERE imported_at IS NULL", (now,))
            c.execute("INSERT OR IGNORE INTO roots(path) SELECT DISTINCT root FROM files")
            c.execute("PRAGMA user_version=1")
        if c.execute("PRAGMA user_version").fetchone()[0] < 2:
            c.execute("ALTER TABLE job_items ADD COLUMN charged INTEGER NOT NULL DEFAULT 0")
            c.execute("PRAGMA user_version=2")
        if c.execute("PRAGMA user_version").fetchone()[0] < 3:
            effective_view(c)
            c.execute("PRAGMA user_version=3")
        if c.execute("PRAGMA user_version").fetchone()[0] < 4:
            c.execute("ALTER TABLE assets ADD COLUMN format TEXT")
            c.execute("DROP VIEW effective_assets")
            effective_view(c)
            c.execute("PRAGMA user_version=4")
        c.commit()
    except Exception:
        c.rollback()
        raise


def effective_view(c):
    fields = {"taken", "category", "caption", "latitude", "longitude"}
    columns = []
    for row in c.execute("PRAGMA table_info(assets)"):
        name = row[1]
        original = 'a."' + name + '"'
        if name in fields:
            value = (
                "(SELECT json_extract(value,'$') FROM corrections WHERE hash=a.hash AND field='"
                + name
                + "' AND scope_id='' ORDER BY created DESC,id DESC LIMIT 1)"
            )
            columns.append("COALESCE(" + value + "," + original + ") AS " + name)
        else:
            columns.append(original)
    for field in ("category", "caption"):
        columns.append(
            "(SELECT json_extract(value,'$') IS NOT NULL FROM corrections WHERE hash=a.hash AND field='"
            + field
            + "' AND scope_id='' ORDER BY created DESC,id DESC LIMIT 1) AS user_"
            + field
        )
    c.execute("CREATE VIEW effective_assets AS SELECT " + ",".join(columns) + " FROM assets a")

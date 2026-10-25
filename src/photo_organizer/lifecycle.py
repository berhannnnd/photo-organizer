"""Root health, scan receipts, opt-in polling and conservative derivative retention."""
import datetime
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from .catalog import connect,writer_lock
from .selection import now


def synchronize(state,root,workers=4,verify=False):
    from .ingest import scan
    root=str(Path(os.path.abspath(root)));sid=uuid.uuid4().hex
    with connect(state) as c:
        c.execute('INSERT OR IGNORE INTO roots(path) VALUES(?)',(root,));r=c.execute('SELECT * FROM roots WHERE path=?',(root,)).fetchone()
        if not r['enabled']:raise ValueError('root disabled; enable it before synchronization')
        c.execute('INSERT INTO scans VALUES(?,?,?,?,?,?)',(sid,r['id'],now(),None,'running',None))
        c.execute('UPDATE roots SET last_scan=? WHERE id=?',(sid,r['id']))
    try:
        result=scan(state,root,workers,verify)
    except (OSError,ValueError) as error:
        offline=not Path(root).is_dir()
        with connect(state) as c:
            c.execute('UPDATE scans SET finished=?,status=?,error=? WHERE id=?',(now(),'failed',type(error).__name__,sid))
            c.execute('UPDATE roots SET status=?,error=? WHERE id=?',('offline' if offline else 'scan_failed',type(error).__name__,r['id']))
        raise
    with connect(state) as c:
        c.execute('UPDATE scans SET finished=?,status=? WHERE id=?',(now(),'completed',sid))
        c.execute("UPDATE roots SET status='online',error=NULL,last_success=?,revision=revision+1 WHERE id=?",(now(),r['id']))
        revision=c.execute('SELECT revision FROM roots WHERE id=?',(r['id'],)).fetchone()[0]
    return {**result,'scan_id':sid,'root_id':r['id'],'root_revision':revision}


def roots(state,root=None,enabled=None):
    with connect(state) as c:
        if enabled is not None:
            if type(enabled) is not bool or root is None:raise ValueError('root and boolean enabled required')
            changed=c.execute('UPDATE roots SET enabled=? WHERE path=?',(enabled,str(Path(os.path.abspath(root))))).rowcount
            if not changed:raise ValueError('unknown root')
        return {'roots':[dict(r) for r in c.execute('SELECT * FROM roots ORDER BY id')],'freshness':'relative_to_last_successful_scan'}


def watch(state,action='status',interval=30):
    if action not in ('start','stop','status'):raise ValueError('invalid watcher action')
    if type(interval) is not int or not 5<=interval<=3600:raise ValueError('interval must be 5..3600 seconds')
    with connect(state) as c:
        if action!='status':c.execute('INSERT INTO library_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('watch',json.dumps({'enabled':action=='start','interval':interval})))
        row=c.execute("SELECT value FROM library_settings WHERE key='watch'").fetchone();settings=json.loads(row[0]) if row else {'enabled':False}
        heartbeat=c.execute("SELECT value FROM library_settings WHERE key='watch_heartbeat'").fetchone()
    if action=='start':
        log=Path(state)/'watcher.log'
        with log.open('ab') as out:subprocess.Popen([sys.executable,'-m','photo_organizer.watcher','--state',str(Path(state).resolve())],stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True)
    return {**settings,'heartbeat':json.loads(heartbeat[0]) if heartbeat else None,'mechanism':'periodic reconciliation; not instantaneous filesystem events'}


def watch_loop(state):
    try:
        with writer_lock(Path(state)/'watch-lock'):
            while True:
                settings=watch(state)
                if not settings['enabled']:return
                for root in roots(state)['roots']:
                    if not root['enabled']:continue
                    try:synchronize(state,root['path'])
                    except (OSError,ValueError):pass
                with connect(state) as c:c.execute('INSERT INTO library_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('watch_heartbeat',json.dumps({'pid':os.getpid(),'updated':now()})))
                for _ in range(settings['interval']):
                    time.sleep(1)
                    if not watch(state)['enabled']:return
    except ValueError as e:
        if 'another writer' not in str(e):raise


def cleanup(state,retention_days=30,apply=False):
    if type(retention_days) is not int or retention_days<1 or type(apply) is not bool:raise ValueError('positive retention_days and boolean apply required')
    cutoff=datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=retention_days)
    candidates=[]
    with writer_lock(state),connect(state) as c:
        from .results import initialize
        initialize(c)
        rows=c.execute('''SELECT a.hash,a.derivative FROM assets a WHERE NOT EXISTS(SELECT 1 FROM files f WHERE f.hash=a.hash AND f.present=1)
          AND NOT EXISTS(SELECT 1 FROM result_members m WHERE m.hash=a.hash)
          AND NOT EXISTS(SELECT 1 FROM actions x WHERE x.hash=a.hash)''').fetchall()
        base=(Path(state).resolve()/'derivatives')
        for row in rows:
            path=Path(row['derivative'])
            if path.is_symlink() or not path.is_file() or base not in path.resolve().parents:continue
            if datetime.datetime.fromtimestamp(path.stat().st_mtime,datetime.timezone.utc)>cutoff:continue
            # First unreferenced observation starts retention; file age is not deletion age.
            key='unreferenced:'+row['hash'];first=c.execute('SELECT value FROM library_settings WHERE key=?',(key,)).fetchone()
            if first is None:
                c.execute('INSERT INTO library_settings VALUES(?,?)',(key,now()));continue
            if datetime.datetime.fromisoformat(first[0])>cutoff:continue
            candidates.append({'hash':row['hash'],'path':str(path)})
            if apply:path.unlink()
        c.execute("DELETE FROM library_settings WHERE key LIKE 'unreferenced:%' AND substr(key,14) IN (SELECT hash FROM files WHERE present=1)")
    return {'dry_run':not apply,'candidates':candidates,'removed':len(candidates) if apply else 0,'originals_deleted':0}

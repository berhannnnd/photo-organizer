"""Checkpoint each actual model result; no labels derived from source titles."""
import concurrent.futures
import json
import time
from .catalog import connect,writer_lock,report
from .provider import ProviderError

def index(state,provider,limit=None,workers=3,reindex=False):
    start=time.perf_counter()
    with writer_lock(state),connect(state) as c:
        versions={r[0] for r in c.execute("SELECT DISTINCT vision_version FROM assets WHERE vision_state='complete'")}
        if versions-{provider.version} and not reindex: raise ValueError('model/prompt changed; use --reindex explicitly')
        if reindex:
            with c: c.execute("UPDATE assets SET vision_state='pending' WHERE vision_version IS NOT ?",(provider.version,))
        rows=c.execute("SELECT a.hash,a.derivative FROM assets a WHERE a.vision_state!='complete' AND a.prep_error IS NULL AND EXISTS(SELECT 1 FROM files f WHERE f.hash=a.hash AND f.present=1) ORDER BY a.hash LIMIT ?",(limit or -1,)).fetchall()
        def run(r):
            try: return r['hash'],provider.label(r['derivative']),None
            except Exception as e: return r['hash'],None,str(e)[:200] if isinstance(e,ProviderError) else type(e).__name__
        completed=failed=0; usage={}; image_bytes=0
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(run,r) for r in rows]
            for future in concurrent.futures.as_completed(futures):
                sha,result,error=future.result()
                with c:
                    if error:
                        c.execute("UPDATE assets SET vision_state='error',vision_error=? WHERE hash=?",(error,sha)); failed+=1
                    else:
                        label,metrics=result
                        c.execute("UPDATE assets SET vision_state='complete',vision_version=?,caption=?,category=?,vision_error=NULL,elapsed=?,usage=? WHERE hash=?",(provider.version,label['caption'],label['category'],metrics['seconds'],json.dumps(metrics['usage']),sha))
                        c.execute('DELETE FROM tags WHERE hash=?',(sha,))
                        c.executemany('INSERT OR IGNORE INTO tags VALUES(?,?)',[(sha,t.strip().casefold()) for t in label['tags']])
                        completed+=1; image_bytes+=metrics['image_bytes']
                        for k,v in metrics['usage'].items():
                            if isinstance(v,(int,float)): usage[k]=usage.get(k,0)+v
                if (completed+failed)%25==0:
                    print(json.dumps({'progress':completed+failed,'total':len(rows),'completed':completed,'failed':failed}),flush=True)
        return {**report(c),'completed_now':completed,'failed_now':failed,'seconds':time.perf_counter()-start,'usage':usage,'image_bytes':image_bytes,'provider':provider.provider_id,'model':provider.model,'endpoint':provider.url}

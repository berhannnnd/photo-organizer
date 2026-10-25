"""Exhaustive, reusable condition-specific visual judgments for open-ended organization."""
import concurrent.futures
import json
import time
from .catalog import connect,writer_lock
from .query import condition_key,semantic_coverage
from .provider import ProviderError

def enrich(state,provider,condition,limit=None,workers=4):
    if not isinstance(condition,str) or not 1<=len(condition.strip())<=2000: raise ValueError('criterion must contain 1..2000 characters')
    condition=condition.strip(); key=condition_key(condition); version=provider.version+'-judge-v1'
    start=time.perf_counter()
    with writer_lock(state),connect(state) as c:
        with c:
            c.execute('INSERT INTO conditions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version',(key,condition,version))
        rows=c.execute('SELECT a.hash,a.derivative FROM assets a WHERE EXISTS(SELECT 1 FROM files f WHERE f.hash=a.hash AND f.present=1) AND NOT EXISTS(SELECT 1 FROM judgments j WHERE j.hash=a.hash AND j.condition_id=? AND j.version=?) ORDER BY a.hash LIMIT ?',(key,version,limit or -1)).fetchall()
        def run(row):
            try: return row['hash'],provider.judge(row['derivative'],condition),None
            except Exception as e: return row['hash'],None,str(e)[:200] if isinstance(e,ProviderError) else type(e).__name__
        errors=[]; completed=0; usage={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for sha,result,error in pool.map(run,rows):
                if error: errors.append({'hash':sha,'error':error}); continue
                obj,metrics=result
                with c: c.execute('INSERT OR REPLACE INTO judgments VALUES(?,?,?,?,?)',(sha,key,version,obj['verdict'],obj['evidence']))
                completed+=1
                for k,v in metrics['usage'].items():
                    if isinstance(v,(int,float)): usage[k]=usage.get(k,0)+v
                if completed%25==0: print(json.dumps({'semantic_completed':completed,'requested':len(rows)}),flush=True)
        return {'condition':condition,'completed_now':completed,'errors':errors,'coverage':semantic_coverage(c,condition),'seconds':time.perf_counter()-start,'usage':usage,'model':provider.model,'version':version}

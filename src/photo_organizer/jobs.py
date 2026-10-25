"""Durable bounded jobs with process-independent controls and resumable item receipts."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from .catalog import connect,writer_lock
from .selection import members,now
from .errors import CapabilityError

ALLOWED={'index','review','embed','ocr','quality','faces','scan','apply'}
MODEL_JOBS={'index','review','embed','ocr','faces'}


def status(state,task_id=None,limit=50,offset=0):
    if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or offset<0:raise ValueError('invalid pagination')
    with connect(state) as c:
        if task_id is None:return {'tasks':[dict(r) for r in c.execute('SELECT id,operation,status,created,updated FROM jobs ORDER BY created DESC LIMIT ? OFFSET ?',(limit,offset))]}
        row=c.execute('SELECT * FROM jobs WHERE id=?',(task_id,)).fetchone()
        if not row:raise ValueError('unknown task')
        data=dict(row)
        for key in ('arguments','progress','result','error','budget'):data[key]=json.loads(data[key]) if data[key] else None
        data['items']=[{**dict(r),'result':json.loads(r['result']) if r['result'] else None} for r in c.execute('SELECT * FROM job_items WHERE job_id=? ORDER BY item_id LIMIT ? OFFSET ?',(task_id,limit,offset))]
        data['counts']=dict(c.execute('SELECT status,count(*) FROM job_items WHERE job_id=? GROUP BY status',(task_id,)))
        total=sum(data['counts'].values());data['total']=total;data['next_offset']=offset+limit if offset+limit<total else None
        data['in_flight']=data['counts'].get('running',0)
        return data


def launch(state,task_id):
    # Worker survives host sessions; lock ownership is held by the worker itself.
    log=Path(state).resolve()/'workers.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('ab') as output:
        subprocess.Popen([sys.executable,'-m','photo_organizer.worker','--state',str(Path(state).resolve()),'--task',task_id],stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True,close_fds=True)


def start(state,operation,arguments,budget=None,background=True):
    if operation not in ALLOWED or not isinstance(arguments,dict):raise ValueError('unsupported job operation')
    allowed={'result_id','condition'} if operation=='review' else {'root','verify'} if operation=='scan' else {'plan_id'} if operation=='apply' else {'result_id'}
    if set(arguments)-allowed:raise ValueError('invalid job arguments')
    if operation=='review' and (not isinstance(arguments.get('condition'),str) or not 1<=len(arguments['condition'].strip())<=2000):raise ValueError('review condition required')
    budget=validate_budget(budget or {})
    if type(background) is not bool:raise ValueError('background must be boolean')
    with writer_lock(Path(state)/'jobs-lock'),connect(state) as c:
        roles={'index':['vision'],'review':['vision'],'embed':['image_text'],'ocr':['ocr','vision'],'faces':['faces']}.get(operation,[])
        revisions={r['role']:r['revision'] for r in c.execute('SELECT role,revision FROM capability_configs') if r['role'] in roles}
        spec={**arguments,'capability_revisions':revisions}
        key=json.dumps([operation,spec],sort_keys=True)
        for existing in c.execute("SELECT id,operation,arguments FROM jobs WHERE status IN ('queued','running','pausing')"):
            if json.dumps([existing['operation'],json.loads(existing['arguments'])],sort_keys=True)==key:return {'task_id':existing['id'],'deduplicated':True}
        if operation not in ('scan','apply'):
            if not arguments.get('result_id'):raise ValueError('result_id required to freeze job scope')
            rows=members(c,arguments['result_id']);items={r['hash']:r for r in rows} if operation in MODEL_JOBS or operation=='quality' else {str(r['file_id']):r for r in rows}
        elif operation=='apply':
            if not c.execute('SELECT 1 FROM plans WHERE id=?',(arguments.get('plan_id'),)).fetchone():raise ValueError('unknown plan')
            items={r['id']:{'action_id':r['id']} for r in c.execute('SELECT id FROM actions WHERE plan_id=?',(arguments['plan_id'],))}
        else:
            if not isinstance(arguments.get('root'),str):raise ValueError('root required')
            items={'scan':{'root':arguments['root']}}
        tid=uuid.uuid4().hex;timestamp=now()
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,operation,json.dumps(spec), 'queued',timestamp,timestamp,None,None,json.dumps({'completed':0,'requests':0,'images':0,'seconds':0}),None,None,json.dumps(budget)))
        c.executemany('INSERT INTO job_items(job_id,item_id,status,result) VALUES(?,?,?,?)',[(tid,str(k),'pending',json.dumps({'input':v})) for k,v in items.items()])
    if background:launch(state,tid)
    return {'task_id':tid,'status':'queued','total':len(items),'background':background}


def validate_budget(budget):
    if not isinstance(budget,dict) or set(budget)-{'max_images','max_requests','max_seconds','max_cost','max_request_cost'}:raise ValueError('unknown budget fields')
    if any(type(v) not in (int,float) or not 0<v<1e12 for v in budget.values()):raise ValueError('budgets must be positive finite numbers')
    if any(type(budget[k]) is not int for k in ('max_images','max_requests') if k in budget):raise ValueError('image/request limits must be integers')
    if 'max_cost' in budget and 'max_request_cost' not in budget:raise ValueError('unknown model pricing: use image/request caps or supply an explicit conservative max_request_cost')
    return budget


def control(state,task_id,action,budget=None,rebind=False):
    if action not in ('pause','cancel','resume','retry'):raise ValueError('action must be pause, cancel, resume or retry')
    with connect(state) as c:
        c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT status FROM jobs WHERE id=?',(task_id,)).fetchone()
        if not r:raise ValueError('unknown task')
        if budget is not None:c.execute('UPDATE jobs SET budget=? WHERE id=?',(json.dumps(validate_budget(budget)),task_id))
        if action in ('pause','cancel'):
            target='pausing' if action=='pause' else 'cancelling'
            if r[0] in ('queued','paused','needs_input','cancelled','failed','partial_failed'):target='paused' if action=='pause' else 'cancelled'
            if r[0]=='completed':raise ValueError('completed task has no running work')
            c.execute('UPDATE jobs SET control=?,status=?,updated=? WHERE id=?',(action,target,now(),task_id))
        else:
            if rebind:
                job=c.execute('SELECT operation,arguments FROM jobs WHERE id=?',(task_id,)).fetchone()
                spec=json.loads(job['arguments'])
                roles={'index':['vision'],'review':['vision'],'embed':['image_text'],'ocr':['ocr','vision'],'faces':['faces']}.get(job['operation'],[])
                spec['capability_revisions']={x['role']:x['revision'] for x in c.execute('SELECT role,revision FROM capability_configs') if x['role'] in roles}
                c.execute('UPDATE jobs SET arguments=? WHERE id=?',(json.dumps(spec),task_id))
                if job['operation'] in MODEL_JOBS:
                    c.execute("UPDATE job_items SET status='pending',attempts=0 WHERE job_id=?",(task_id,))
                    c.execute('UPDATE jobs SET progress=? WHERE id=?',(json.dumps({'completed':0,'requests':0,'images':0,'seconds':0}),task_id))
            if r[0] in ('running','pausing','cancelling'):raise ValueError('wait for in-flight work or explicitly recover an interrupted worker')
            if r[0]=='completed':return {'task_id':task_id,'status':'completed'}
            if action=='retry':c.execute("UPDATE job_items SET status='pending',error=NULL,attempts=0 WHERE job_id=? AND status='failed'",(task_id,))
            c.execute("UPDATE jobs SET control=NULL,status='queued',error=NULL,updated=? WHERE id=?",(now(),task_id))
    if action in ('resume','retry'):launch(state,task_id)
    return {'task_id':task_id,'control':action,'status':target if action in ('pause','cancel') else 'queued'}


def recover(state,task_id):
    with writer_lock(Path(state)/'job-locks'/task_id),connect(state) as c:
        row=c.execute('SELECT status FROM jobs WHERE id=?',(task_id,)).fetchone()
        if not row:raise ValueError('unknown task')
        if row[0] in ('running','pausing','cancelling'):
            c.execute("UPDATE jobs SET status='paused',owner=NULL,updated=? WHERE id=?",(now(),task_id))
            c.execute("UPDATE job_items SET status='pending' WHERE job_id=? AND status='running'",(task_id,))
    return {'task_id':task_id,'next_action':'resume; completed actions are reconciled, not replayed blindly'}


def run(state,task_id):
    try:
        with writer_lock(Path(state)/'job-locks'/task_id):return _run(state,task_id)
    except ValueError as error:
        if 'another writer' not in str(error):raise
        return {'task_id':task_id,'status':'owned_by_another_worker'}


def _run(state,task_id):
    from .job_actions import execute
    with connect(state) as c:
        c.execute('BEGIN IMMEDIATE');job=c.execute('SELECT * FROM jobs WHERE id=?',(task_id,)).fetchone()
        if not job or job['status'] not in ('queued','running'):return
        spec=json.loads(job['arguments']);progress=json.loads(job['progress']);budget=json.loads(job['budget']);operation=job['operation']
        c.execute("UPDATE jobs SET status='running',owner=?,updated=? WHERE id=?",(str(os.getpid()),now(),task_id))
        c.execute("UPDATE job_items SET status='pending' WHERE job_id=? AND status='running'",(task_id,))
    started=time.monotonic();previous_seconds=progress.get('seconds',0)
    while True:
        with connect(state) as c:
            c.execute('BEGIN IMMEDIATE');job=c.execute('SELECT * FROM jobs WHERE id=?',(task_id,)).fetchone()
            progress['seconds']=previous_seconds+time.monotonic()-started
            if job['control'] in ('pause','cancel'):
                state_name='paused' if job['control']=='pause' else 'cancelled'
                c.execute('UPDATE jobs SET status=?,owner=NULL,progress=?,updated=? WHERE id=?',(state_name,json.dumps(progress),now(),task_id));return
            item=c.execute("SELECT * FROM job_items WHERE job_id=? AND status='pending' ORDER BY item_id LIMIT 1",(task_id,)).fetchone()
            if not item:
                failed=c.execute("SELECT count(*) FROM job_items WHERE job_id=? AND status='failed'",(task_id,)).fetchone()[0]
                final='partial_failed' if failed else 'completed'
                final_result={}
                if operation=='apply':
                    from .organization import record_collection
                    plan=c.execute('SELECT * FROM plans WHERE id=?',(spec['plan_id'],)).fetchone()
                    cid,rid=record_collection(c,plan);final_result={'collection_id':cid,'result_set_id':rid}
                c.execute('UPDATE jobs SET status=?,owner=NULL,progress=?,result=?,updated=? WHERE id=?',(final,json.dumps(progress),json.dumps(final_result),now(),task_id));return
            changed=any(c.execute('SELECT revision FROM capability_configs WHERE role=?',(role,)).fetchone()[0]!=rev for role,rev in spec['capability_revisions'].items())
            model=operation in MODEL_JOBS
            reached=(progress['seconds']>=budget.get('max_seconds',float('inf')) or progress.get('images',0)>=budget.get('max_images',float('inf')) or model and progress.get('requests',0)>=budget.get('max_requests',float('inf')) or model and (progress.get('requests',0)+1)*budget.get('max_request_cost',0)>budget.get('max_cost',float('inf')))
            if changed or reached:
                error={'code':'version_conflict' if changed else 'budget_exhausted','message':'Configuration changed' if changed else 'Increase budget to resume; completed items are preserved'}
                c.execute("UPDATE jobs SET status='needs_input',owner=NULL,error=?,progress=?,updated=? WHERE id=?",(json.dumps(error),json.dumps(progress),now(),task_id));return
            c.execute("UPDATE job_items SET status='running',attempts=attempts+1 WHERE job_id=? AND item_id=?",(task_id,item['item_id']))
            # Reserve before dispatch; a crash cannot silently erase possible request cost.
            if model:progress['requests']=progress.get('requests',0)+1
            if operation not in ('scan','apply') and item['attempts']==0: progress['images']=progress.get('images',0)+1
            c.execute('UPDATE jobs SET progress=?,updated=? WHERE id=?',(json.dumps(progress),now(),task_id))
        payload=json.loads(item['result'])['input'];error=None
        try:
            stage=hashlib.sha256(json.dumps([operation,payload.get('hash'),spec.get('condition'),spec.get('capability_revisions')],sort_keys=True).encode()).hexdigest()
            with writer_lock(Path(state)/'stage-locks'/stage):output=execute(state,operation,spec,payload)
        except Exception as e:
            error={'code':e.code if isinstance(e,CapabilityError) else 'operation_failed','message':str(e)[:300] if isinstance(e,(CapabilityError,ValueError,OSError)) else type(e).__name__,'retryable':isinstance(e,CapabilityError) and e.retryable}
            output=None
        with connect(state) as c:
            if error:
                retry=error['retryable'] and item['attempts']<2
                c.execute('UPDATE job_items SET status=?,error=? WHERE job_id=? AND item_id=?',('pending' if retry else 'failed',json.dumps(error),task_id,item['item_id']))
                if error['code'] in ('missing_capability','unverified_capability','authentication_failed','authentication_required','permission_denied','version_conflict','host_action_required'):
                    c.execute("UPDATE job_items SET status='pending' WHERE job_id=? AND item_id=?",(task_id,item['item_id']))
                    c.execute("UPDATE jobs SET status='needs_input',owner=NULL,error=?,updated=? WHERE id=?",(json.dumps(error),now(),task_id));return
            else:
                c.execute("UPDATE job_items SET status='done',result=?,error=NULL WHERE job_id=? AND item_id=?",(json.dumps({'input':payload,'output':output}),task_id,item['item_id']))
                progress['completed']=progress.get('completed',0)+1
            c.execute('UPDATE jobs SET progress=?,updated=? WHERE id=?',(json.dumps(progress),now(),task_id))
        if error and retry:
            # Short interruptible backoff: controls remain responsive.
            for _ in range(2**(item['attempts']+1)*5):
                time.sleep(.2)
                with connect(state) as c:
                    if c.execute('SELECT control FROM jobs WHERE id=?',(task_id,)).fetchone()[0]:break

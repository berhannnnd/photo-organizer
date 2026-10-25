"""Freeze full-scope memberships and source identities before applying actions."""
import datetime
import json
import os
import time
import uuid
from pathlib import Path
from .catalog import connect,writer_lock,report
from .query import select,semantic_coverage
from .filesystem import relative_parts

MODES={'album','copy','compress'}

def plan(state,spec,target=None,mode='album'):
    start=time.perf_counter()
    if mode not in MODES: raise ValueError('unsupported output mode')
    if not isinstance(spec,dict) or set(spec)-{'filter','group_by','groups','quality','long_edge','result_set_id'}: raise ValueError('invalid plan spec')
    group_by=spec.get('group_by','none')
    if group_by not in ('none','month','category','rules'): raise ValueError('invalid group_by')
    if mode=='compress':
        if type(spec.get('quality',82)) is not int or not 1<=spec.get('quality',82)<=95: raise ValueError('invalid JPEG quality')
        if type(spec.get('long_edge',1600)) is not int or not 64<=spec.get('long_edge',1600)<=8192: raise ValueError('invalid long edge')
    with writer_lock(state),connect(state) as c:
        if mode!='album':
            if not target: raise ValueError('destination required')
            target=Path(os.path.abspath(target))
            for row in c.execute('SELECT DISTINCT root FROM files'):
                source=Path(row[0])
                if target==source or source in target.parents or target in source.parents: raise ValueError('source/destination overlap')
        if spec.get('result_set_id'):
            if 'filter' in spec: raise ValueError('refine the result set before planning; do not mix filter and result_set_id')
            from .results import select_snapshot
            items=select_snapshot(c,spec['result_set_id'])
        else:
            items=select(c,spec.get('filter',{}))
        rules=[]; cover={}
        if group_by=='rules':
            groups=spec.get('groups')
            if not isinstance(groups,list) or not groups: raise ValueError('groups required')
            names=set()
            for group in groups:
                if not isinstance(group,dict) or set(group)!={'name','where'}: raise ValueError('invalid group')
                name=group['name']; parts=relative_parts(name)
                if len(parts)!=1 or name in names or name=='unclassified': raise ValueError('invalid/duplicate group name')
                names.add(name); rules.append((name,{r['id'] for r in select(c,group['where'])}))
                if group['where'].get('semantic'): cover[name]=semantic_coverage(c,group['where']['semantic'])
        plan_id=uuid.uuid4().hex; actions=[]; counts={}
        for row in items:
            if group_by=='month': group=row['taken'][:7].replace('-','/') if row['taken'] else 'date-unknown'
            elif group_by=='category': group=row['category'] if row['vision_state']=='complete' and row['category'] else 'unclassified'
            elif group_by=='rules':
                matches=[name for name,ids in rules if row['id'] in ids]
                if len(matches)>1: raise ValueError('overlapping categories require clarification; no plan created')
                group=matches[0] if matches else 'unclassified'
            else: group='selected'
            counts[group]=counts.get(group,0)+1
            suffix='.jpg' if mode=='compress' else Path(row['path']).suffix.lower()
            if not suffix or len(suffix)>12 or not suffix[1:].isalnum(): suffix='.image'
            relative=f'{group}/{row["id"]:06d}-{row["hash"][:12]}{suffix}'
            relative_parts(relative)
            actions.append((uuid.uuid4().hex,plan_id,row['id'],row['path'],row['hash'],relative))
        with c:
            c.execute('INSERT INTO plans VALUES(?,?,?,?,?)',(plan_id,datetime.datetime.now(datetime.timezone.utc).isoformat(),json.dumps(spec,ensure_ascii=False),str(target) if target else None,mode))
            c.executemany('INSERT INTO actions(id,plan_id,file_id,source,hash,relative) VALUES(?,?,?,?,?,?)',actions)
        return {'plan_id':plan_id,'selected':len(items),'groups':counts,'library':report(c),'semantic_coverage':cover,'mode':mode,'seconds':time.perf_counter()-start,'model_calls':0}

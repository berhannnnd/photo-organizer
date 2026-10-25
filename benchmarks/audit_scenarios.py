"""Audit real tool traces against engine state and output files, not model self-reports."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from PIL import Image


def audit(state,directory,dataset):
    directory=Path(directory);seeds=json.loads((directory/'seeds.json').read_text())
    c=sqlite3.connect(Path(state)/'catalog.sqlite');c.row_factory=sqlite3.Row
    results={};hash_errors=[]
    for line in (Path(dataset)/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split(maxsplit=1);path=Path(dataset)/'images'/name.strip()
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:hash_errors.append(name)
    def members(rid):return {r[0] for r in c.execute("SELECT file_id FROM result_members WHERE result_id=? AND verdict IN ('matched','candidate')",(rid,))}
    for path in sorted(directory.glob('*.json')):
        if path.stem not in ('A1_full_library','A2_semantic_direct','B1_result_organization','B2_overlap','C1_refine','C2_scope_recovery','D1_subjective','D2_missing_facts'):continue
        obj=json.loads(path.read_text())
        if obj.get('status')=='running': continue
        trace=[t for t in obj['trace'] if 'tool' in t];checks={}
        errors=[t for t in trace if t['result'].get('status') not in ('completed',)]
        checks['agent_finished']=obj['status']=='completed'
        checks['no_tool_errors']=not errors
        plans=[t['result']['data']['plan_id'] for t in trace if t['tool']=='photo_plan' and t['result'].get('status')=='completed']
        applications=[t for t in trace if t['tool']=='photo_apply']
        if path.stem.startswith(('A','B')):
            checks['executed_plan']=bool(plans and applications)
        for pid in plans:
            plan=c.execute('SELECT * FROM plans WHERE id=?',(pid,)).fetchone();actions=c.execute('SELECT * FROM actions WHERE plan_id=?',(pid,)).fetchall()
            checks[pid+'_receipts']=all(r['status']=='done' and not r['error'] for r in actions)
            ids={r['file_id'] for r in actions}
            if path.stem=='A1_full_library':checks['all_1000']=len(ids)==1000
            if path.stem=='A2_semantic_direct':checks['twenty_candidates']=len(ids)==20
            if path.stem=='B1_result_organization':checks['exact_seed_scope']=ids==members(seeds['LANDSCAPE'])
            if path.stem=='B2_overlap':checks['all_unique_members']=ids==members(seeds['ALL']);checks['overlap_expanded']=len(actions)>len(ids)
            if plan['mode']!='album':
                good=True
                for row in actions:
                    p=Path(plan['target'])/row['relative']
                    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['output_hash']:good=False;continue
                    if plan['mode']=='copy' and row['output_hash']!=row['hash']:good=False
                    if plan['mode']=='compress':
                        with Image.open(p) as im:
                            if im.format!='JPEG' or max(im.size)>json.loads(plan['spec']).get('long_edge',1600):good=False
                checks[pid+'_output_verified']=good
        searches=[t for t in trace if t['tool']=='photo_search' and t['result'].get('status')=='completed']
        if path.stem in ('C1_refine','C2_scope_recovery'):
            checks['saved_filter']=bool(searches);checks['no_apply']=not applications
            if searches:
                ids=members(searches[-1]['result']['data']['result_set_id'])
                checks['subset_of_original_candidates']=ids<=members(seeds['LANDSCAPE'])
                if path.stem=='C2_scope_recovery':
                    expected={r[0] for r in c.execute('SELECT f.id FROM files f JOIN assets a ON f.hash=a.hash WHERE a.height>a.width')} & members(seeds['LANDSCAPE'])
                    checks['exact_portrait_scope']=ids==expected
                else:
                    checks['all_landscape']=all(c.execute('SELECT a.width>a.height FROM files f JOIN assets a ON f.hash=a.hash WHERE f.id=?',(i,)).fetchone()[0] for i in ids)
                    checks['scoped_review_used']=any(t['tool']=='photo_enrich' for t in trace)
        if path.stem.startswith('D'):
            checks['clarified']=any(t['tool']=='ask_user' for t in trace);checks['no_apply']=not applications
            if path.stem=='D1_subjective':
                questions=[i for i,t in enumerate(trace) if t['tool']=='ask_user'];retrievals=[i for i,t in enumerate(trace) if t['tool']=='photo_retrieve']
                checks['clarification_before_exploration']=bool(questions and retrievals and questions[0]<retrievals[0])
            if path.stem=='D2_missing_facts':checks['no_plan']=not plans
        results[path.stem]={'checks':checks,'passed':all(checks.values()),'seconds':obj['seconds'],'tools':[t['tool'] for t in trace],'final':obj['final']}
    output={'original_hashes_checked':1000,'original_hash_errors':hash_errors,'cases':results,
            'scope':'Workflow/output audit only; image semantics require separate visual review.'}
    (directory/'audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2));print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--directory',required=True);p.add_argument('--dataset',required=True);a=p.parse_args();audit(a.state,a.directory,a.dataset)

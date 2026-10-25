"""Versioned observations and scoped host judgments, independent of model transport."""
import base64
import hashlib
import io
import json
import uuid
from PIL import Image, ImageOps
from .catalog import connect, writer_lock
from .filesystem import read_source, digest_file
from .predicates import condition_key
from .selection import now, members
from .provider import validate_label


def source_record(source):
    if not isinstance(source,dict) or set(source)-{'kind','model','version'} or source.get('kind') not in ('host','provider','user'):
        raise ValueError('source needs kind host, provider or user and optional model/version')
    if any(not isinstance(v,str) or not 1<=len(v)<=300 for v in source.values()): raise ValueError('invalid source')
    return {'kind':source['kind'],'model':source.get('model','unknown'),'version':source.get('version','unknown')}


def submit(state, result_id, records, source, condition=None, expected_version=None):
    source=source_record(source)
    if not isinstance(records,list) or not 1<=len(records)<=100: raise ValueError('submit 1..100 records')
    if condition is not None and (not isinstance(condition,str) or not 1<=len(condition.strip())<=2000): raise ValueError('invalid condition')
    condition=condition.strip() if condition else None
    with writer_lock(state),connect(state) as c:
        scope={r['file_id']:r for r in members(c,result_id)}
        key=condition_key(condition) if condition else None
        active=c.execute('SELECT version FROM conditions WHERE id=?',(key,)).fetchone() if key else None
        if active and expected_version!=active[0]: raise ValueError('condition version changed or missing; read evidence before submitting')
        if not active and expected_version is not None: raise ValueError('unknown expected condition version')
        version=active[0] if active else uuid.uuid4().hex
        checked=[];seen=set()
        for r in records:
            if not isinstance(r,dict) or set(r)-{'file_id','hash','verdict','evidence','observation','input'}: raise ValueError('invalid observation record')
            fid=r.get('file_id')
            if fid in seen or fid not in scope or r.get('hash')!=scope[fid]['hash']: raise ValueError('duplicate, out-of-scope or stale observation')
            seen.add(fid)
            if condition:
                if r.get('verdict') not in ('yes','no','uncertain') or not isinstance(r.get('evidence'),str) or not 1<=len(r['evidence'])<=2000: raise ValueError('judgment requires verdict and evidence')
            else: validate_label(r.get('observation'))
            inp=r.get('input',{})
            if not isinstance(inp,dict) or len(json.dumps(inp))>2000: raise ValueError('invalid input provenance')
            checked.append(r)
        with c:
            if key and not active: c.execute('INSERT INTO conditions VALUES(?,?,?)',(key,condition,version))
            for r in checked:
                oid=uuid.uuid4().hex
                payload={'condition':condition,'condition_version':version if key else None,**r}
                c.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)',(oid,r['hash'],'judgment' if key else 'visual',version,json.dumps(source),json.dumps(payload,ensure_ascii=False),now()))
                if key:
                    if source['kind']=='user':
                        c.execute('INSERT INTO corrections VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,r['hash'],'semantic:'+key,json.dumps(r['verdict']),result_id,json.dumps(source),now()))
                    else:
                        c.execute('INSERT OR REPLACE INTO judgments VALUES(?,?,?,?,?)',(r['hash'],key,version,r['verdict'],r['evidence']))
                else:
                    label=r['observation']
                    c.execute("UPDATE assets SET caption=?,category=?,vision_state='complete',vision_version=?,vision_error=NULL WHERE hash=?",(label['caption'],label['category'],version,r['hash']))
                    c.execute('DELETE FROM tags WHERE hash=?',(r['hash'],))
                    c.executemany('INSERT OR IGNORE INTO tags VALUES(?,?)',[(r['hash'],t.strip().casefold()) for t in label['tags']])
    return {'saved':len(checked),'result_set_id':result_id,'condition_version':version if key else None,'source':source}


def read(state,result_id,condition=None,limit=50,offset=0):
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0: raise ValueError('invalid pagination')
    from . import results
    with connect(state) as c:
        results.initialize(c);results.require(c,result_id)
        all_rows=c.execute('SELECT * FROM result_members WHERE result_id=? ORDER BY file_id',(result_id,)).fetchall()
        key=condition_key(condition) if condition else None
        active=c.execute('SELECT version FROM conditions WHERE id=?',(key,)).fetchone() if key else None
        items=[]
        for r in all_rows[offset:offset+limit]:
            obs=c.execute('SELECT * FROM observations WHERE hash=? ORDER BY created DESC LIMIT 20',(r['hash'],)).fetchall()
            observations=[{**dict(o),'source':json.loads(o['source']),'payload':json.loads(o['payload'])} for o in obs]
            judgment=c.execute('SELECT * FROM judgments WHERE hash=? AND condition_id=? AND version=?',(r['hash'],key,active[0])).fetchone() if active else None
            items.append({'file_id':r['file_id'],'hash':r['hash'],'judgment':dict(judgment) if judgment else None,'observations':observations})
        return {'result_set_id':result_id,'condition_version':active[0] if active else None,'items':items,'total':len(all_rows),'next_offset':offset+limit if offset+limit<len(all_rows) else None}


def image(state,result_id,file_id,long_edge=1280,crop=None):
    if type(long_edge) is not int or not 64<=long_edge<=4096: raise ValueError('long_edge must be 64..4096')
    with connect(state) as c:
        scope={r['file_id']:r for r in members(c,result_id)}
        if file_id not in scope: raise ValueError('image outside selected scope')
        row=scope[file_id]
        current=c.execute('SELECT path FROM files WHERE id=?',(file_id,)).fetchone()[0]
    with read_source(current) as f:
        if digest_file(f)!=row['hash']: raise ValueError('source changed since selection')
        f.seek(0)
        with Image.open(f) as original:
            im=ImageOps.exif_transpose(original).convert('RGB')
            if crop is not None:
                if not isinstance(crop,list) or len(crop)!=4 or any(type(x) is not int for x in crop) or not (0<=crop[0]<crop[2]<=im.width and 0<=crop[1]<crop[3]<=im.height): raise ValueError('crop must be valid oriented pixel bounds')
                im=im.crop(crop)
            im.thumbnail((long_edge,long_edge));out=io.BytesIO();im.save(out,format='JPEG',quality=85)
            if len(out.getvalue())>8_000_000: raise ValueError('derived image exceeds tool byte budget')
            result={'file_id':file_id,'hash':row['hash'],'mime_type':'image/jpeg','width':im.width,'height':im.height,'crop':crop,'data':base64.b64encode(out.getvalue()).decode()}
        f.seek(0)
        if digest_file(f)!=row['hash']: raise ValueError('source changed while deriving image')
    return result

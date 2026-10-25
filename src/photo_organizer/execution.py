"""No-clobber export with per-action journals and inode-backed publication recovery."""
import hashlib
import json
import os
import time
from pathlib import Path
from PIL import Image,ImageOps
from .catalog import connect,writer_lock
from .filesystem import directory,read_source,digest_file,relative_parts,digest

def fd_digest(fd,name):
    handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
    with os.fdopen(handle,'rb') as f: return digest_file(f)

def exists(fd,name):
    try: return os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError: return None

def export_one(c,row,plan,spec):
    parts=relative_parts(row['relative']); parent=Path(plan['target']).joinpath(*parts[:-1]); name=parts[-1]
    tmp='.photo-organizer-'+row['id']+'.tmp'
    with directory(parent,create=True) as fd:
        current=exists(fd,name); temp=exists(fd,tmp)
        if row['status']=='done':
            if not current or fd_digest(fd,name)!=row['output_hash']: raise ValueError('completed destination missing or changed')
            if temp and (temp.st_ino,temp.st_dev)==(current.st_ino,current.st_dev): os.unlink(tmp,dir_fd=fd)
            return 'reused'
        if current:
            # A surviving hardlink to our journaled temp proves publication before a crash.
            if row['status']=='running' and temp and (temp.st_ino,temp.st_dev)==(current.st_ino,current.st_dev) and row['output_hash'] and fd_digest(fd,name)==row['output_hash']:
                with c: c.execute("UPDATE actions SET status='done',error=NULL WHERE id=?",(row['id'],))
                os.unlink(tmp,dir_fd=fd); return 'recovered'
            raise ValueError('destination already exists; refusing overwrite')
        if temp:
            if row['status']!='running': raise ValueError('unexpected temporary file')
            # This exact task-owned unpublished file is safe to discard and rebuild.
            os.unlink(tmp,dir_fd=fd)
        with c: c.execute("UPDATE actions SET status='running',error=NULL,output_hash=NULL WHERE id=?",(row['id'],))
        outfd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(outfd,'wb') as out, read_source(row['source']) as source:
                if plan['mode']=='copy':
                    h=hashlib.sha256()
                    while data:=source.read(1024*1024): h.update(data); out.write(data)
                    if h.hexdigest()!=row['hash']: raise ValueError('source changed since plan')
                else:
                    # Hash the same opened file, then decode; check again before publication.
                    if digest_file(source)!=row['hash']: raise ValueError('source changed since plan')
                    source.seek(0)
                    with Image.open(source) as im:
                        im=ImageOps.exif_transpose(im); im.thumbnail((spec.get('long_edge',1600),)*2)
                        if im.mode=='RGBA':
                            bg=Image.new('RGB',im.size,'white'); bg.paste(im,mask=im.getchannel('A')); im=bg
                        else: im=im.convert('RGB')
                        import io
                        quality=spec.get('quality',82)
                        while True:
                            encoded=io.BytesIO();im.save(encoded,format='JPEG',quality=quality)
                            if 'max_bytes' not in spec or encoded.tell()<=spec['max_bytes']: break
                            if quality<=10: raise ValueError('cannot meet max_bytes without changing requested dimensions; adjust export settings')
                            quality=max(10,quality-5)
                        out.write(encoded.getvalue())
                    source.seek(0)
                    if digest_file(source)!=row['hash']: raise ValueError('source changed during compression')
                out.flush(); os.fsync(out.fileno())
            result_hash=fd_digest(fd,tmp); size=os.stat(tmp,dir_fd=fd).st_size
            with c: c.execute('UPDATE actions SET output_hash=?,output_bytes=? WHERE id=?',(result_hash,size,row['id']))
            os.link(tmp,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
            os.fsync(fd)
            with c: c.execute("UPDATE actions SET status='done',error=NULL WHERE id=?",(row['id'],))
            os.unlink(tmp,dir_fd=fd)
            return 'written'
        except Exception:
            # Keep running journal and temp; next invocation reconciles instead of overwriting.
            raise

def apply(state,plan_id):
    start=time.perf_counter(); outcomes={}; errors=[]
    with writer_lock(state),connect(state) as c:
        plan=c.execute('SELECT * FROM plans WHERE id=?',(plan_id,)).fetchone()
        if not plan: raise ValueError('unknown plan')
        spec=json.loads(plan['spec']); rows=c.execute('SELECT * FROM actions WHERE plan_id=? ORDER BY file_id',(plan_id,)).fetchall()
        if plan['mode']=='album':
            outcomes={'memberships':0}
            for row in rows:
                try:
                    if digest(row['source'])!=row['hash']:
                        raise ValueError('source changed since plan')
                    with c: c.execute("UPDATE actions SET status='done',error=NULL WHERE id=?",(row['id'],))
                    outcomes['memberships']+=1
                except (OSError,ValueError) as e:
                    error=type(e).__name__+': '+str(e)[:240]
                    with c: c.execute('UPDATE actions SET error=? WHERE id=?',(error,row['id']))
                    errors.append({'action':row['id'],'error':error})
        else:
            for row in rows:
                try:
                    outcome=export_one(c,row,plan,spec); outcomes[outcome]=outcomes.get(outcome,0)+1
                except Exception as e:
                    error=type(e).__name__+': '+str(e)[:240]
                    with c: c.execute('UPDATE actions SET error=? WHERE id=?',(error,row['id']))
                    errors.append({'action':row['id'],'error':error})
        from .organization import record_collection
        with c: collection_id,result_id=record_collection(c,plan)
        return {'collection_id':collection_id,'result_set_id':result_id,'plan_id':plan_id,'mode':plan['mode'],'total':len(rows),'outcomes':outcomes,'errors':errors,'seconds':time.perf_counter()-start,'model_calls':0,'target':plan['target']}

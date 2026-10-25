"""Incremental content hashing, EXIF extraction and real image derivatives."""
import concurrent.futures
import datetime
import io
import os
import time
import warnings
from pathlib import Path
from PIL import Image, ImageOps
from .catalog import connect, report, writer_lock
from .filesystem import read_source
import hashlib

PREP='pillow-orient-rgb-1280-q82-v1'
Image.MAX_IMAGE_PIXELS=60_000_000

def prepare(path,state):
    try:
        with read_source(path) as f:
            before=os.fstat(f.fileno())
            if before.st_size>250_000_000: raise ValueError('input exceeds 250MB limit')
            data=f.read()
            after=os.fstat(f.fileno())
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('source changed while reading')
        sha=hashlib.sha256(data).hexdigest()
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                exif=im.getexif()
                try: detail=exif.get_ifd(34665)
                except (KeyError,TypeError): detail={}
                raw=detail.get(36867) or exif.get(36867)
                taken=None
                if raw:
                    try: taken=datetime.datetime.strptime(str(raw),'%Y:%m:%d %H:%M:%S').isoformat()
                    except ValueError: pass
                offset=detail.get(36881) or exif.get(36881)
                if taken and isinstance(offset,str) and __import__('re').fullmatch(r'[+-]\d{2}:\d{2}',offset): taken+=offset
                latitude=longitude=None
                try:
                    gps=exif.get_ifd(34853)
                    def degrees(v): return float(v[0])+float(v[1])/60+float(v[2])/3600
                    if gps.get(2) and gps.get(4):
                        latitude=degrees(gps[2])*(-1 if gps.get(1)=='S' else 1)
                        longitude=degrees(gps[4])*(-1 if gps.get(3)=='W' else 1)
                except (KeyError,TypeError,ValueError,ZeroDivisionError): pass
                im=ImageOps.exif_transpose(im)
                width,height=im.size
                im.thumbnail((1280,1280))
                if im.mode in ('RGBA','LA') or 'transparency' in im.info:
                    rgba=im.convert('RGBA'); rgb=Image.new('RGB',rgba.size,'white'); rgb.paste(rgba,mask=rgba.getchannel('A')); im=rgb
                else: im=im.convert('RGB')
                target=Path(state)/'derivatives'/PREP/(sha+'.jpg')
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():
                    # Separate tasks may discover identical content; atomic rename is safe for identical derivatives.
                    import uuid
                    tmp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                    im.save(tmp,format='JPEG',quality=82)
                    os.replace(tmp,target)
        return {'hash':sha,'size':before.st_size,'mtime_ns':before.st_mtime_ns,'width':width,'height':height,'taken':taken,'derivative':str(target),'error':None,'device':before.st_dev,'inode':before.st_ino,'latitude':latitude,'longitude':longitude,'timezone':offset if taken else None}
    except Exception as e:
        return {'error':type(e).__name__+': '+str(e)[:240]}

def scan(state,root,workers=4,verify=False):
    start=time.perf_counter(); state=Path(state).resolve(); root=Path(os.path.abspath(root))
    if root.is_symlink() or not root.is_dir(): raise ValueError('source must be an existing non-symlink directory')
    if state==root or root in state.parents: raise ValueError('state must be outside source tree')
    with writer_lock(state), connect(state) as c:
        initial=root.stat();paths=[]
        exports=[Path(r[0]) for r in c.execute('SELECT DISTINCT target FROM plans WHERE target IS NOT NULL')]
        explicitly_importing_export=root in exports
        def fail(error): raise error
        for current,dirs,files in os.walk(root,followlinks=False,onerror=fail):
            for name in list(dirs):
                p=Path(current)/name
                if p in exports and not explicitly_importing_export: dirs.remove(name);continue
                if p.is_symlink(): paths.append(p); dirs.remove(name)
            paths.extend(Path(current)/name for name in sorted(files))
        previous={r['path']:r for r in c.execute('SELECT f.*,a.prep_version,a.derivative FROM files f LEFT JOIN assets a ON f.hash=a.hash WHERE root=?',(str(root),))}
        tasks=[]; cached=0
        seen={str(p) for p in paths}
        missing=[r for p,r in previous.items() if p not in seen]
        for p in paths:
            old=previous.get(str(p)); s=p.lstat()
            if not verify and not p.is_symlink() and old and not old['error'] and old['size']==s.st_size and old['mtime_ns']==s.st_mtime_ns and old['prep_version']==PREP and old['derivative'] and Path(old['derivative']).is_file():
                cached+=1; c.execute('UPDATE files SET present=1 WHERE id=?',(old['id'],))
            else: tasks.append(p)
        # Commit changes only after a successful complete scan. WAL readers see the prior revision.
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for path,result in zip(tasks,pool.map(lambda p:prepare(p,state),tasks)):
                if not result['error']:
                    c.execute('INSERT INTO assets(hash,width,height,taken,date_source,derivative,prep_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(hash) DO UPDATE SET width=excluded.width,height=excluded.height,taken=excluded.taken,date_source=excluded.date_source,derivative=excluded.derivative,prep_version=excluded.prep_version',
                              (result['hash'],result['width'],result['height'],result['taken'],'exif' if result['taken'] else None,result['derivative'],PREP))
                    c.execute('UPDATE assets SET latitude=?,longitude=?,timezone=? WHERE hash=?',(result['latitude'],result['longitude'],result['timezone'],result['hash']))
                    if str(path) not in previous:
                        matches=[r for r in missing if r['device']==result['device'] and r['inode']==result['inode'] and r['hash']==result['hash']]
                        if len(matches)==1:
                            c.execute('UPDATE files SET path=? WHERE id=?',(str(path),matches[0]['id']))
                            missing.remove(matches[0])
                c.execute('INSERT INTO files(root,path,hash,size,mtime_ns,error,device,inode,imported_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET hash=excluded.hash,size=excluded.size,mtime_ns=excluded.mtime_ns,error=excluded.error,present=1,device=excluded.device,inode=excluded.inode',
                          (str(root),str(path),result.get('hash'),result.get('size'),result.get('mtime_ns'),result['error'],result.get('device'),result.get('inode'),datetime.datetime.now(datetime.timezone.utc).isoformat()))
        final=root.stat()
        if (initial.st_dev,initial.st_ino)!=(final.st_dev,final.st_ino):raise ValueError('source root changed during scan')
        seen={str(p) for p in paths}
        with c:
            c.executemany('UPDATE files SET present=0 WHERE id=?',[(r['id'],) for r in missing])
        return {**report(c),'processed':len(tasks),'cache_hits':cached,'seconds':time.perf_counter()-start}

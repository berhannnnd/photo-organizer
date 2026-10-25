"""Deterministic grouping suggestions; assignments are editable immutable proposals."""
import datetime
import json
from collections import Counter
from .catalog import connect
from .selection import members
from .organization import propose
from .errors import CapabilityError


def suggest(state,result_id,method='theme',threshold=0.75,gap_hours=8,space=None):
    if method not in ('theme','event','person','duplicates','similar'):raise ValueError('unknown grouping method')
    if type(threshold) not in (int,float) or not 0<threshold<1:raise ValueError('threshold must be between 0 and 1')
    if type(gap_hours) not in (int,float) or not 0<gap_hours<=168:raise ValueError('gap_hours must be 0..168')
    groups={};unknown=[]
    with connect(state) as c:
        rows=members(c,result_id)
        if method in ('theme','similar'):
            from .embeddings import initialize,unpack
            initialize(c)
            spaces=[r[0] for r in c.execute('SELECT id FROM embedding_spaces')]
            if space is None:
                if len(spaces)!=1:raise ValueError('select an explicit embedding space')
                space=spaces[0]
            representatives=[]
            for row in sorted(rows,key=lambda r:r['hash']):
                v=c.execute('SELECT vector FROM image_vectors WHERE hash=? AND space_id=?',(row['hash'],space)).fetchone()
                if not v:unknown.append(row['file_id']);continue
                vector=unpack(v[0]);best=None;score=-1
                for n,reference in enumerate(representatives):
                    current=sum(a*b for a,b in zip(vector,reference))
                    if current>score:best=n;score=current
                if best is None or score<threshold:
                    best=len(representatives);representatives.append(vector)
                groups.setdefault('theme-'+str(best+1),[]).append(row['file_id'])
        elif method=='event':
            dated=[]
            for row in rows:
                a=c.execute('SELECT taken,latitude,longitude FROM assets WHERE hash=?',(row['hash'],)).fetchone()
                if not a['taken']:unknown.append(row['file_id']);continue
                try:t=datetime.datetime.fromisoformat(a['taken'])
                except ValueError:unknown.append(row['file_id']);continue
                # Compare wall-clock dates only within same offset; unknown timezone stays explicit.
                dated.append((t.replace(tzinfo=None),str(t.utcoffset()),row['file_id'],a['latitude'],a['longitude']))
            dated.sort();previous=None;number=0;key=None
            for t,zone,fid,lat,lon in dated:
                far=False
                if previous and lat is not None and previous[3] is not None:
                    import math
                    a=math.sin(math.radians(lat-previous[3])/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(previous[3]))*math.sin(math.radians(lon-previous[4])/2)**2
                    far=6371*2*math.asin(min(1,math.sqrt(a)))>50
                if previous is None or zone!=previous[1] or (t-previous[0]).total_seconds()>gap_hours*3600 or far:
                    number+=1;key=f'{t.date()}-event-{number}'
                groups.setdefault(key,[]).append(fid);previous=(t,zone,fid,lat,lon)
        elif method=='person':
            for row in rows:
                people=c.execute('SELECT DISTINCT p.id,p.name FROM faces f JOIN people p ON p.id=f.person_id WHERE f.hash=?',(row['hash'],)).fetchall()
                if not people:unknown.append(row['file_id'])
                for p in people:groups.setdefault((p['name'] or 'person')+'-'+p['id'][:8],[]).append(row['file_id'])
        else:
            for row in rows:groups.setdefault('content-'+row['hash'][:12],[]).append(row['file_id'])
        if method in ('duplicates','similar'):
            singles=[fid for ids in groups.values() if len(ids)==1 for fid in ids]
            groups={name:ids for name,ids in groups.items() if len(ids)>1}
            if singles:groups['unique-or-unpaired']=singles
        if unknown:groups['needs-review']=unknown
    if not groups:raise ValueError('empty input; no groups to propose')
    return propose(state,result_id,[{'path':[name],'ids':ids} for name,ids in groups.items()],overlap='multi' if method=='person' else 'error',reason=f'{method} proposal; thresholds are not accuracy probabilities; inspect representative and boundary members before adopting')

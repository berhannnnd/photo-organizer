"""Small real-image smoke test, not a full-library accuracy benchmark."""
import argparse
import base64
import hashlib
import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

MODEL='hf.co/ggml-org/embeddinggemma-2-GGUF:Q8_0'
CASES=[('0001.jpg','白色的小花'),('0005.jpg','生日蛋糕'),('0021.jpg','停在树枝上的鸟'),('0023.jpg','一只狗'),('0024.jpg','一只猫')]

def post(base,route,data):
    req=urllib.request.Request(base+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    start=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=240) as response: result=json.load(response)
    except urllib.error.HTTPError as e:
        body=e.read().decode()[:1000]
        raise RuntimeError(f'HTTP {e.code}: {body}') from None
    return result,time.perf_counter()-start

def similarity(a,b):
    return sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a))*math.sqrt(sum(x*x for x in b)))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:11434'); args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'benchmarks/results/ollama-probe.json'
    result={'model':MODEL,'base_url':args.base,'scope':'five real photos; smoke test only','requests':[],'status':'incomplete'}
    try:
        shown,_=post(args.base,'/api/show',{'model':MODEL})
        result['capabilities']=shown.get('capabilities');result['details']=shown.get('details')
        image_vectors=[];text_vectors=[]
        with sqlite3.connect('file:'+str(root/'.photo-organizer/catalog.sqlite')+'?mode=ro',uri=True) as c:
            for filename,query in CASES:
                source=root/'data/photo-dataset-1000/images'/filename
                row=c.execute('SELECT a.derivative FROM assets a JOIN files f ON a.hash=f.hash WHERE f.path=?',(str(source),)).fetchone()
                if not row: raise ValueError('missing preprocessed file '+filename)
                image=base64.b64encode(Path(row[0]).read_bytes()).decode()
                r,seconds=post(args.base,'/api/embed',{'model':MODEL,'input':{'image':image},'keep_alive':'10m','truncate':False})
                image_vectors.append(r['embeddings'][0])
                result['requests'].append({'type':'image','file':filename,'seconds':seconds,'total_duration_ns':r.get('total_duration'),'load_duration_ns':r.get('load_duration'),'dimensions':len(image_vectors[-1])})
        for query_set in [[q for _,q in CASES],['a white flower','a birthday cake','a bird perched on a branch','a dog','a cat']]:
            r,seconds=post(args.base,'/api/embed',{'model':MODEL,'input':query_set,'keep_alive':'10m','truncate':False})
            vectors=r['embeddings']; text_vectors.extend(vectors)
            result['requests'].append({'type':'text_batch','seconds':seconds,'count':len(vectors)})
            matrix=[[round(similarity(v,im),5) for im in image_vectors] for v in vectors]
            result.setdefault('retrieval',[]).append({'queries':query_set,'files':[f for f,q in CASES],'scores':matrix,'top1':[max(range(len(row)),key=lambda j:row[j]) for row in matrix]})
        all_vectors=image_vectors+text_vectors
        dimensions={len(v) for v in all_vectors}
        if len(dimensions)!=1 or not next(iter(dimensions)): raise ValueError('inconsistent dimensions')
        if any(not all(math.isfinite(x) for x in v) or sum(x*x for x in v)==0 for v in all_vectors): raise ValueError('invalid vectors')
        result['max_image_similarity']=max(similarity(a,b) for i,a in enumerate(image_vectors) for b in image_vectors[i+1:])
        result['dimensions']=next(iter(dimensions))
        result['top1_hits']=[sum(i==j for i,j in enumerate(r['top1'])) for r in result['retrieval']]
        result['status']='completed'
    except Exception as e:
        result['status']='error';result['error']=str(e)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='completed' else 1
if __name__=='__main__': raise SystemExit(main())

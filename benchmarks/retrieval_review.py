"""Fixed diagnostic queries and contact sheets; annotations are intentionally separate."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
from photo_organizer.search.embeddings import search

QUERIES=[('cat','一只猫'),('meal','人们围坐在一起吃饭'),('building','建筑物的外立面'),('document','文字密集的文档或扫描页'),('mountain_lake','有山和湖泊的自然风景')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    reports=[]
    for name,text in QUERIES:
        result=search(args.state,text,top_k=20,ranking='image');reports.append({'name':name,'text':text,'result':result})
        canvas=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(canvas)
        for i,item in enumerate(result['items']):
            with Image.open(item['path']) as im:
                im=ImageOps.exif_transpose(im);im.thumbnail((190,210));x=(i%5)*200;y=(i//5)*250
                canvas.paste(im,(x,y));draw.text((x,y+215),f"{i+1}: {Path(item['path']).name} {item['score']:.3f}",fill='black')
        canvas.save(out/(name+'.jpg'))
    (out/'retrieval.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    print(json.dumps([{'name':r['name'],'seconds':r['result']['seconds'],'result_set_id':r['result']['result_set_id']} for r in reports],indent=2))

if __name__=='__main__':main()

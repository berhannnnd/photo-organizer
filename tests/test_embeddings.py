import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from photo_organizer import embeddings,results
from photo_organizer.catalog import connect
from photo_organizer.ingest import scan
from photo_organizer.planning import plan


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve()
        self.root=self.base/'photos';self.root.mkdir();self.state=self.base/'state'
        for i,color in enumerate(('red','blue','green')): Image.new('RGB',(50+i,30),color).save(self.root/f'{i}.jpg')
        scan(self.state,self.root)
        class Fake:
            space='space';model='model';digest='digest';endpoint='local';calls=0
            def __init__(self,*args): pass
            def encode(self,value):
                Fake.calls+=1
                return embeddings.pack([1,2,3])
        self.fake=Fake;self.patcher=patch.object(embeddings,'Ollama',Fake);self.patcher.start()

    def tearDown(self): self.patcher.stop();self.tmp.cleanup()

    def test_checkpoint_cached_query_candidates_and_scope(self):
        self.assertEqual(embeddings.index(self.state)['completed_now'],3)
        self.assertEqual(embeddings.index(self.state)['completed_now'],0)
        parent=embeddings.search(self.state,'a cat',top_k=2)
        self.assertEqual(parent['selection_kind'],'candidates')
        self.assertEqual(parent['total'],2)
        self.assertFalse(parent['query_cache_hit'])
        self.assertTrue(embeddings.search(self.state,'a cat')['query_cache_hit'])
        self.assertEqual(self.fake.calls,4)
        child=results.create(self.state,{'orientation':'landscape'},parent['result_set_id'])
        self.assertEqual(child['total'],2)
        self.assertEqual(child['selection_kind'],'candidates')
        with self.assertRaisesRegex(ValueError,'accept_candidates'): plan(self.state,{'result_set_id':child['result_set_id']})
        self.assertEqual(plan(self.state,{'result_set_id':child['result_set_id'],'accept_candidates':True})['selected'],2)
        narrow=embeddings.search(self.state,'a cat',top_k=30,parent_id=parent['result_set_id'])
        self.assertEqual(narrow['total'],2)
        self.assertEqual(narrow['rule']['scope_count'],2)

    def test_model_space_change_and_invalid_vector(self):
        embeddings.index(self.state)
        self.fake.space='changed'
        with self.assertRaisesRegex(ValueError,'no index'): embeddings.search(self.state,'cat')
        for vector in ([0,0],[float('nan'),1],[float('inf')],[]):
            with self.assertRaises(ValueError): embeddings.pack(vector)

    def test_partial_caption_index_cannot_bias_fusion(self):
        embeddings.index(self.state)
        with connect(self.state) as c:
            c.execute("UPDATE assets SET caption='a red object',vision_state='complete',vision_version='vision'")
        embeddings.index_descriptions(self.state,limit=2)
        partial=embeddings.search(self.state,'object')
        self.assertEqual(partial['rule']['effective_ranking'],'image')
        self.assertEqual(partial['rule']['description_coverage'],2)
        embeddings.index_descriptions(self.state)
        full=embeddings.search(self.state,'object')
        self.assertEqual(full['rule']['effective_ranking'],'hybrid')
        self.assertEqual(embeddings.index_descriptions(self.state)['completed_now'],0)
        with connect(self.state) as c:
            c.execute("UPDATE assets SET caption='a different object' WHERE hash=(SELECT hash FROM assets LIMIT 1)")
        self.assertEqual(embeddings.search(self.state,'object')['rule']['effective_ranking'],'image')

    def test_multilevel_and_overlap_expansion(self):
        p=plan(self.state,{'levels':[{'field':'year'},{'field':'category'},{'field':'orientation'}]})
        self.assertEqual(p['groups'],{'date-unknown/needs-review/landscape':3})
        p=plan(self.state,{'levels':[{'rules':[{'name':'first','where':{}},{'name':'second','where':{}}],'overlap':'multi'},{'field':'orientation'}]})
        self.assertEqual(p['selected'],3);self.assertEqual(p['memberships'],6)
        self.assertEqual(p['groups'],{'first/landscape':3,'second/landscape':3})

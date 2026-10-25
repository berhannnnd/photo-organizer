import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from PIL import Image
from photo_organizer.ingest import scan
from photo_organizer.indexing import index
from photo_organizer.results import create


class ConcurrencyTests(unittest.TestCase):
    def test_slow_vision_does_not_block_search_and_dispatch_is_bounded(self):
        entered=threading.Event();release=threading.Event()
        class Fake:
            version='v';model='v';provider_id='v';url='local';calls=0
            def label(self,path):
                self.calls+=1;entered.set()
                if not release.wait(5): raise RuntimeError('test timed out')
                return {'caption':'red','category':'object','tags':['red']},{'seconds':0,'usage':{},'image_bytes':1}
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();root=base/'images';root.mkdir();state=base/'state'
            for i in range(4): Image.new('RGB',(20+i,10),'red').save(root/f'{i}.jpg')
            scan(state,root);provider=Fake()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future=pool.submit(index,state,provider,None,1)
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(create(state,{'orientation':'landscape'})['total'],4)
                    self.assertEqual(provider.calls,1)
                finally: release.set()
                self.assertEqual(future.result(timeout=5)['completed_now'],4)

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from clients import company_docs as D
from clients import docs_qa as Q


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)/'index.json'
        rows = []
        for id, source, path, category, title, content in [
            ('public','acme/website','/docs/pros/issues','External / Pros','Job Issues','If a pro cannot access the home, contact the client.'),
            ('private','acme/internal-docs','refunds.md','Internal / Operations','Refund Handling','For a refund policy, tell customers about the process.'),
            ('note','ticoteam/tico','docs/architecture.md','Internal / Company','Historical dispatcher','refund policy historical dispatcher.')]:
            rows.append(dict(id=id,source=source,path=path,category=category,title=title,search=content))
        self.cache.write_text(json.dumps({'documents':rows}))
        for p in [patch.object(D,'CACHE',self.cache),patch.object(Q,'DB',Path(self.tmp.name)/'vectors.sqlite')]:
            p.start(); self.addCleanup(p.stop)

    def test_authorization_and_current_docs_filter_before_ranking(self):
        self.assertEqual([r['id'] for r in Q.retrieve('refund policy',True)[0]], ['private'])
        self.assertEqual(Q.retrieve('refund policy',False)[0], [])
        with self.assertRaises(ValueError): Q.retrieve('refund',False,'private')
        self.assertEqual([r['id'] for r in Q.retrieve('refund',True,collection='notes')[0]], ['note'])

if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from clients import company_docs as D


class CompanyDocsTests(unittest.TestCase):
    def test_internal_and_proposed_docs_not_visible_to_viewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'index.json'
            path.write_text(json.dumps({'documents': [
                {'id':'public','category':'External / PMs','content':'entire page','search':'entire page'},
                {'id':'internal','category':'Internal / Operations','content':'private'},
                {'id':'draft','category':'Proposed / Internal','content':'draft'}],
                'proposals':[{'title':'private PR'}], 'errors':['private error']}))
            with patch.object(D, 'CACHE', path):
                self.assertEqual([d['id'] for d in D.read(False)['documents']], ['public'])
                self.assertEqual(D.document('public', False)['content'], 'entire page')
                for doc_id in ['internal', 'draft', '../secrets/example']:
                    with self.assertRaises(ValueError): D.document(doc_id, False)
                self.assertEqual(D.read(False)['proposals'], [])


if __name__ == '__main__':
    unittest.main()

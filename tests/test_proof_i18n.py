"""Catalog failure detection and actual unchanged operational HTTP contracts."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import proof_web
from scripts import check_proof_i18n_catalog as checker

class CatalogTests(unittest.TestCase):
    def test_catalogs_and_all_static_surfaces_have_complete_keys(self):
        catalog=checker.load_catalog();checker.validate_catalog(catalog)
        self.assertGreater(checker.check_sources(catalog)['keys_per_language'],300)

    def test_delivery_status_has_the_exact_required_primary_labels(self):
        catalog=checker.load_catalog()
        self.assertEqual(catalog['es']['enum_ENTREGA_COMPLETA'],'ENTREGA COMPLETA')
        self.assertEqual(catalog['en']['enum_ENTREGA_COMPLETA'],'COMPLETE DELIVERY')

    def test_state_and_authority_labels_do_not_expose_underscored_codes(self):
        catalog=checker.load_catalog()
        states={'PASS','FAIL','NOT_RUN','UNREACHED','COMPUTED_BY_BASELINE','LITERAL_ONLY','EXCLUDED','ABSTAIN','SOURCE_SET_MISMATCH','UNSUPPORTED_STATUS','INVALID_CITATION','VALIDATION_REJECTED'}
        for language in ('es','en'):
            for key in ['state_'+code for code in states]+['enum_ENTREGADO','enum_ENTREGA_COMPLETA','enum_NO_ENTREGADO','authority_carrier_status','authority_document_count']:
                self.assertIn(key,catalog[language]);self.assertNotIn('_',catalog[language][key])
            self.assertIn('not an exact quotation' if language=='en' else 'no es una cita textual exacta',catalog[language]['readable_presentation'])

    def test_missing_translation_is_rejected_instead_of_falling_back(self):
        catalog=checker.load_catalog();catalog['en'].pop(next(iter(catalog['en'])))
        with self.assertRaisesRegex(ValueError,'key mismatch'):checker.validate_catalog(catalog)

    def test_blank_translation_and_changed_parameters_are_rejected(self):
        catalog=checker.load_catalog();catalog['en']['technical_value']=''
        with self.assertRaisesRegex(ValueError,'Empty translation'):checker.validate_catalog(catalog)
        catalog=checker.load_catalog();catalog['en']['technical_value']='Value: {invented}'
        with self.assertRaisesRegex(ValueError,'Interpolation mismatch'):checker.validate_catalog(catalog)

    def test_unlocalized_new_prose_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shutil.copytree(checker.ROOT/'web',root/'web')
            with patch.object(checker,'ROOT',root):
                with (root/'web/theater.js').open('a') as stream:stream.write("\nnode('p','','Texto sin localizar');\n")
                with self.assertRaisesRegex(ValueError,'Unlocalized JS prose'):checker.check_sources(checker.load_catalog())
            (root/'web/theater.js').write_bytes((checker.ROOT/'web/theater.js').read_bytes())
            with (root/'web/theater.js').open('a') as stream:stream.write("\nnode('button','','Untranslated');\n")
            with patch.object(checker,'ROOT',root),self.assertRaisesRegex(ValueError,'Unlocalized JS prose'):checker.check_sources(checker.load_catalog())
            (root/'web/theater.js').write_bytes((checker.ROOT/'web/theater.js').read_bytes())
            with (root/'web/theater.html').open('a') as stream:stream.write('<p>Unlocalized new prose</p>')
            with patch.object(checker,'ROOT',root),self.assertRaisesRegex(ValueError,'Unlocalized HTML text'):checker.check_sources(checker.load_catalog())

class PresentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=proof_web.make_server(0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3)
    def request(self,method,path,payload=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path,json.dumps(payload) if payload is not None else None,{'Content-Type':'application/json'} if payload is not None else {})
            response=connection.getresponse();return response.status,response.getheader('Content-Type'),response.read()
        finally:connection.close()
    def test_language_selects_neither_engine_facts_nor_permissions(self):
        for path in ('/api/theater/evaluate','/api/evaluate'):
            case='PM01-02' if 'theater' in path else 'A'
            for lang in ('es','en'):
                for extra in ({'lang':lang},{'language':lang},{'human_verdict':'yes'},{'translated_documents':[]},{'explanatory_status':'ENTREGA_COMPLETA'}):
                    self.assertEqual(self.request('POST',path,{'case_id':case,**extra})[0],400)
        for case in ('PM01-03','PM01-05','PM01-02','PM01-07'):
            results=[]
            for lang in ('es','en'):
                self.assertEqual(self.request('GET','/?lang='+lang)[0],200)
                status,_,raw=self.request('POST','/api/theater/evaluate',{'case_id':case});self.assertEqual(status,200)
                result=json.loads(raw);result.pop('execution');result['passport'].pop('execution');results.append(result)
            self.assertEqual(*results)
            self.assertFalse(results[0]['passport']['new_meta_inference'])
            self.assertFalse(results[0]['decision']['operational_result']['automatic_closure_allowed'])
            self.assertFalse(results[0]['decision']['operational_result']['physical_delivery_verified'])
    def test_localization_assets_and_direct_language_pages_are_allowlisted(self):
        for page in ('/','/classic'):
            es=self.request('GET',page+'?lang=es');en=self.request('GET',page+'?lang=en')
            self.assertEqual(es[0],200);self.assertEqual(en[0],200);self.assertEqual(es[2],en[2])
            self.assertIn(b'data-language="en"',es[2])
        for asset in ('i18n-catalogs.js','i18n.js','i18n.css'):
            status,mime,body=self.request('GET','/'+asset)
            self.assertEqual(status,200);self.assertTrue(body);self.assertIn('text/',mime)
        for path in ('/web/i18n.js','/expected.json','/artifacts/','/i18n.json/../.env'):
            self.assertEqual(self.request('GET',path)[0],404)

if __name__=='__main__':unittest.main()

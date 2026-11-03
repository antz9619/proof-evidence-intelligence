"""Validate catalog parity, interpolation and localized HTML/JS surfaces. Stdlib only."""
import json
from pathlib import Path
import re
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]

def load_catalog():
    raw=(ROOT/'web/i18n-catalogs.js').read_text()
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:raise ValueError('Duplicate catalog key: '+key)
            result[key]=value
        return result
    return json.loads(raw[raw.index('{'):raw.rindex(';')],object_pairs_hook=pairs)

def validate_catalog(catalog):
    if set(catalog)!={'es','en','source_keys'}:raise ValueError('Unexpected catalog structure')
    if set(catalog['es'])!=set(catalog['en']):raise ValueError('Language key mismatch')
    if not set(catalog['source_keys'].values())<=set(catalog['es']):raise ValueError('Unknown source key')
    for key,es in catalog['es'].items():
        en=catalog['en'][key]
        if not isinstance(es,str) or not isinstance(en,str) or not es.strip() or not en.strip():raise ValueError('Empty translation: '+key)
        if set(re.findall(r'\{([A-Za-z_]+)\}',es))!=set(re.findall(r'\{([A-Za-z_]+)\}',en)):raise ValueError('Interpolation mismatch: '+key)
        if re.search(r'<\s*(?:script|iframe|img)\b',es+en,re.I):raise ValueError('Markup in catalog')

class Surface(HTMLParser):
    def __init__(self,catalog):super().__init__();self.catalog=catalog;self.stack=[];self.errors=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        for name,value in attrs.items():
            if name.startswith('data-i18n') and value not in self.catalog['es']:self.errors.append('Unknown static key '+value)
        if tag not in {'meta','link','input','br','hr','img','source','path'}:self.stack.append((tag,attrs))
    def handle_endtag(self,tag):
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()
    def handle_data(self,data):
        text=data.strip()
        if not re.search(r'[A-Za-zÁÉÍÓÚáéíóúñ]',text) or text in {'proof','PROOF','PUNTA DE LANZA','ES','EN'}:return
        if not any('data-i18n' in attrs for _tag,attrs in self.stack):self.errors.append('Unlocalized HTML text: '+text)

def check_sources(catalog):
    for name in ('theater.html','index.html'):
        parser=Surface(catalog);parser.feed((ROOT/'web'/name).read_text())
        if parser.errors:raise ValueError(name+': '+str(parser.errors))
    for name in ('theater.js','app.js','i18n.js'):
        source=(ROOT/'web'/name).read_text()
        keys=re.findall(r'\bt\([\'"]([^\'"]+)[\'"](?=\s*[,\)])',source)
        for key in keys:
            if key not in catalog['es']:raise ValueError('Unknown JS key '+key)
        # UI text assignments and element constructors must not introduce raw prose.
        patterns=[r"\.textContent\s*=\s*(['\"])([^'\"\n]+)\1",r"(?:node|el)\(\s*['\"][a-z]+['\"]\s*,\s*['\"][^'\"]*['\"]\s*,\s*(['\"])([^'\"\n]+)\1"]
        for pattern in patterns:
            for _quote,text in re.findall(pattern,source):
                if re.search('[A-Za-zÁÉÍÓÚáéíóúñ]',text) and text not in {'ENTREGADO','ENTREGA_COMPLETA','NO_ENTREGADO','CONFIRMED','UNKNOWN','CONTRADICTORY','PROOF','Meta','tracking','pod'}:raise ValueError('Unlocalized JS prose: '+text)
    return {'keys_per_language':len(catalog['es']),'html_surfaces':2,'js_surfaces':3}

def main():
    catalog=load_catalog();validate_catalog(catalog);print(json.dumps({'result':'PASS',**check_sources(catalog)}))
if __name__=='__main__':main()

'use strict';
/* Presentation only. Never reads or writes evaluator inputs, evidence or passports. */
(() => {
  const catalog=window.PROOF_CATALOG;
  let language=new URL(location.href).searchParams.get('lang')==='en'?'en':'es';
  const rendered=new Set(), missing=new Set(), unknownExplanations=new Set();
  function t(key,values={}){
    const template=catalog[language][key];
    if(typeof template!=='string'){missing.add(key);throw new Error('Missing translation key: '+key);}
    let output=template.replace(/\{([A-Za-z_]+)\}/g,(_match,name)=>{
      if(!Object.hasOwn(values,name))throw new Error('Missing translation parameter: '+name);
      return String(values[name]);
    });
    if(!/^(enum|state|authority)_/.test(key))output=normalizeStates(output);rendered.add(output);return output;
  }
  function normalizeStates(text){
    const output=String(text).replace(/\b(?:ENTREGA_COMPLETA|NO_ENTREGADO|ENTREGADO)\b/g,code=>catalog[language]['enum_'+code]);
    rendered.add(output);return output;
  }
  function state(code){
    if(Object.hasOwn(catalog[language],'enum_'+code))return t('enum_'+code);
    if(Object.hasOwn(catalog[language],'state_'+code))return t('state_'+code);
    return t('state_fallback');
  }
  function authority(code){return Object.hasOwn(catalog[language],'authority_'+code)?t('authority_'+code):t('state_fallback');}
  function quotePresentation(quote){
    if(/^SYN-[A-Z0-9-]+$/.test(quote))return String(quote);
    return Object.hasOwn(catalog.source_keys,quote)?explain(quote):t('readable_quote_unavailable');
  }
  function technicalDetails(titleKey,payload){
    const box=document.createElement('details');box.className='technical-record';box.dataset.technical='true';
    const summary=document.createElement('summary');summary.textContent=t(titleKey);
    const pre=document.createElement('pre');pre.textContent=JSON.stringify(payload,null,2);box.append(summary,pre);return box;
  }
  function evidencePresentation(text){
    const box=document.createElement('div');box.className='document-explanation';box.lang=language;box.dataset.readableEvidence='true';
    const label=document.createElement('strong');label.textContent=t('readable_presentation');
    const paragraph=document.createElement('p');paragraph.className='document-readable';paragraph.textContent=explain(text);
    const limit=document.createElement('small');limit.textContent=t('readable_source_limit');box.append(label,paragraph,limit);return box;
  }
  function explain(source){
    if(Object.hasOwn(catalog.source_keys,source))return t(catalog.source_keys[source]);
    unknownExplanations.add(source);return t('unknown_explanation');
  }
  function apply(){
    document.documentElement.lang=language;
    document.querySelectorAll('[data-i18n]').forEach(element=>element.textContent=t(element.dataset.i18n));
    for(const attr of ['aria-label','title','alt'])document.querySelectorAll('[data-i18n-'+attr+']').forEach(element=>element.setAttribute(attr,t(element.getAttribute('data-i18n-'+attr))));
    document.querySelectorAll('[data-language]').forEach(button=>{button.setAttribute('aria-pressed',String(button.dataset.language===language));button.lang=language;});
    document.querySelectorAll('a[href]').forEach(anchor=>{
      const url=new URL(anchor.getAttribute('href'),location.href);
      if(url.origin===location.origin&&['/','/classic'].includes(url.pathname)&&!anchor.getAttribute('href').startsWith('#')){
        url.searchParams.set('lang',language);anchor.href=url.pathname+url.search+url.hash;
      }
    });
  }
  function setLanguage(next){
    if(!['es','en'].includes(next)||next===language)return;
    language=next;rendered.clear();unknownExplanations.clear();
    const url=new URL(location.href);url.searchParams.set('lang',language);history.replaceState(null,'',url.pathname+url.search+url.hash);
    apply();document.dispatchEvent(new CustomEvent('proof:language',{detail:{language}}));
  }
  function original(text,tag='span'){
    const element=document.createElement(tag);element.dataset.original='true';element.lang='es';element.textContent=text;return element;
  }
  function documentExplanation(text){
    const box=document.createElement('aside');box.className='document-explanation';box.lang=language;
    const label=document.createElement('strong');label.textContent=t('explanation_note');
    const paragraph=document.createElement('p');paragraph.textContent=explain(text);box.append(label,paragraph);return box;
  }
  function technical(element){element.dataset.technical='true';return element;}
  function value(value){
    if(value===null)return t('value_null');
    if(typeof value==='boolean')return t(value?'value_yes':'value_no');
    if(Object.hasOwn(catalog[language],'enum_'+value))return t('enum_'+value);
    if(typeof value==='string'&&/^[A-Z]+(?:_[A-Z0-9]+)+$/.test(value))return state(value);
    return String(value);
  }
  function errorKey(error){
    for(const lang of ['es','en'])for(const [key,message] of Object.entries(catalog[lang]))if(message===error.message)return key;
    return 'error_network';
  }
  function untranslated(text){
    let remaining=text.toLowerCase();
    for(const fragment of [...rendered].filter(s=>s.trim()).sort((a,b)=>b.length-a.length)){
      const text=fragment.trim().toLowerCase(),escaped=text.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      const pre=/^[\p{L}\p{N}_]/u.test(text)?'(?<![\\p{L}\\p{N}_])':'',post=/[\p{L}\p{N}_]$/u.test(text)?'(?![\\p{L}\\p{N}_])':'';
      remaining=remaining.replace(new RegExp(pre+escaped+post,'gu'),' ');
    }
    // Immutable IDs, timestamps, values and technical tokens can accompany translated labels.
    remaining=remaining.replace(/\b[a-f0-9]{8,64}\b/gi,'').replace(/(?:SYN-|PM01-|ML02-|ANNOTATED-|proof-)[A-Za-z0-9._-]+|muse-spark-1\.3|\b(?:tracking|pod|ENTREGADO|ENTREGA_COMPLETA|CONFIRMED|UNKNOWN|COMPUTED_BY_BASELINE|PASS|FAIL|EXCLUDED|NOT_RUN|UNREACHED|LITERAL_ONLY|ABSTAIN|status|ms)\b/gi,'').replace(/[\d\s.,:;+−—–→↗↻↓↑/()«»=≠#⊘·]+/g,'');
    return remaining;
  }
  function auditVisibleCodes(){
    const failures=[],pattern=/\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g;
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const parent=walker.currentNode.parentElement;if(!parent||parent.closest('details.technical-record,script,style'))continue;
      let box=parent;while(box&&getComputedStyle(box).display==='contents')box=box.parentElement;
      const closed=parent.closest('details:not([open])');
      if(!box||!box.getClientRects().length||(closed&&!closed.querySelector('summary')?.contains(parent)))continue;
      const codes=walker.currentNode.textContent.match(pattern);if(codes)failures.push({codes,element:parent.id||parent.className||parent.tagName});
    }
    return failures;
  }
  function auditDOM(){
    const failures=[];
    const immutable=/^(?:[\d\s.,:+−—–→↗↻↓↑/()«»=≠#⊘·]+|(?:SYN-|PM01-|ML02-|ANNOTATED-|proof-)[A-Za-z0-9._-]+|muse-spark-1\.3|proof\.?|PROOF|PUNTA DE LANZA|ES|EN|tracking|pod|carrier_status|document_count|ENTREGADO|ENTREGA_COMPLETA|NO_ENTREGADO|CONFIRMED|UNKNOWN|CONTRADICTORY|NOT_RUN|COMPUTED_BY_BASELINE|PASS|FAIL|EXCLUDED|UNREACHED|LITERAL_ONLY|ABSTAIN|SOURCE_SET_MISMATCH|UNSUPPORTED_STATUS|META LIVE 02)$/;
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const text=walker.currentNode.textContent.trim(),parent=walker.currentNode.parentElement;
      if(!text||!parent||parent.closest('[data-original],[data-technical],script,style'))continue;
      let box=parent;while(box&&getComputedStyle(box).display==='contents')box=box.parentElement;
      if(!box||!box.getClientRects().length)continue;
      if(immutable.test(text))continue;
      const remaining=untranslated(text);
      if(remaining)failures.push({text,element:parent.id||parent.className||parent.tagName});
    }
    const attributes=[];
    document.querySelectorAll('[aria-label],[title],[alt]').forEach(element=>{
      if(element.closest('[data-original],[data-technical]'))return;
      for(const name of ['aria-label','title','alt']){const text=element.getAttribute(name);if(text&&untranslated(text))attributes.push({element:element.id||element.tagName,attribute:name,text});}
    });
    return {language,visible_technical_codes:auditVisibleCodes(),unlocalized_attributes:attributes,missing_keys:[...missing],unmapped_explanations:[...unknownExplanations],unlocalized_text:failures};
  }
  window.PROOF_I18N={t,explain,apply,setLanguage,original,technical,documentExplanation,value,errorKey,auditDOM,state,authority,quotePresentation,technicalDetails,evidencePresentation,auditVisibleCodes,get language(){return language;},liveLabels:factory=>new Proxy({},{get:(_target,key)=>factory()[key]})};
  document.querySelectorAll('[data-language]').forEach(button=>button.addEventListener('click',()=>setLanguage(button.dataset.language)));
  apply();
})();

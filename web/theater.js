'use strict';
const I18n=window.PROOF_I18N, t=I18n.t, explain=I18n.explain;

const $ = selector => document.querySelector(selector);
// Presentation only: keyboard paths remain instant, including source navigation.
let pointerInteraction=false;
document.addEventListener('pointerdown',()=>{pointerInteraction=true;document.documentElement.dataset.input='pointer';},{capture:true});
document.addEventListener('keydown',()=>{pointerInteraction=false;document.documentElement.dataset.input='keyboard';},{capture:true});
let proofMomentObserver=null;
function cancelProofMoment(){proofMomentObserver?.disconnect();proofMomentObserver=null;}
function presentProofMoment(){
  cancelProofMoment();
  const target=document.querySelector('.proof-moment .wrong');
  if(!target||!pointerInteraction||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const emphasize=()=>{
    if(!target.isConnected||!pointerInteraction||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    if(typeof target.animate!=='function')return;
    try{
      target.animate([{transform:'translateX(6px)',opacity:.75},{transform:'translateX(0)',opacity:1}],
        {duration:220,easing:'cubic-bezier(.23,1,.32,1)'});
    }catch{/* Optional emphasis must never invalidate a validated decision. */}
  };
  const bounds=target.getBoundingClientRect();
  if(bounds.top<innerHeight&&bounds.bottom>0){emphasize();return;}
  // Result text is already visible in the DOM. Emphasis waits for the reader, never the other way around.
  if(!('IntersectionObserver' in window))return;
  proofMomentObserver=new IntersectionObserver(entries=>{
    if(entries.some(entry=>entry.isIntersecting)){cancelProofMoment();emphasize();}
  },{threshold:.3});
  proofMomentObserver.observe(target);
}

const names = I18n.liveLabels(() => ({shipment_id:t("envio_declarado_0c4ef3"),status:t("estado_informado_d5cb18"),delivery_complete:t("completitud_independiente_691b85"),expected_packages:t("bultos_esperados_739758"),received_packages:t("bultos_recibidos_799307"),signature_present:t("firma_presente_08ba19"),signature_identity_verified:t("identidad_verificada_17593b")}));
const checkNames = I18n.liveLabels(() => ({schema:t("formato_y_cantidades_d473f9"),sources:t("fuentes_completas_1541e0"),citations:t("citas_y_autoridad_9cbc96"),status_guard:t("guard_semantico_05bd1b"),shipment:t("pertenencia_al_envio_a8380b"),baseline:t("motor_deterministico_3a605d")}));
const checkLabels = I18n.liveLabels(() => ({PASS:t("validado_58d405"),FAIL:t("rechaza_e0951a"),NOT_RUN:t("no_ejecutado_45da5f"),LITERAL_ONLY:t("cita_sin_respaldo_5e8c2e"),EXCLUDED:t("excluido_89fccf"),ABSTAIN:t("se_abstiene_b00918")}));
const uncertaintyNames = I18n.liveLabels(() => ({PHYSICAL_DELIVERY_UNVERIFIED:t("no_existe_verificacion_fisica_independiente_5ff23e"),QUANTITY_UNKNOWN:t("la_cantidad_del_envio_investigado_no_esta_documentad_deeeed"),FOREIGN_DOCUMENT:t("el_comprobante_pertenece_a_otro_envio_779a15"),SIGNER_IDENTITY_UNKNOWN:t("la_identidad_del_firmante_de_este_envio_sigue_sin_ve_b5a2be"),TRACKING_UNKNOWN:t("no_hay_un_estado_admitido_8054b3"),QUANTITY_MISMATCH:t("hay_una_diferencia_documental_cuyo_origen_fisico_no__958c46")}));
const actionNames = I18n.liveLabels(() => ({KEEP_CLOSURE_PENDING:t("mantener_pendiente_el_cierre_conforme_727c9d"),REQUEST_ADDITIONAL_EVIDENCE:t("solicitar_evidencia_adicional_para_revision_6c7858"),VERIFY_SIGNER_IDENTITY:t("verificar_identidad_del_firmante_del_envio_investiga_605c22"),REVIEW_DOCUMENTARY_CLOSURE:t("someter_la_conformidad_documental_a_revision_humana_84c76f")}));
let records = [], current = null, result = null, selected = null, busy = false;
let challenge = false, humanVerdict = null, lastErrorKey=null;
const openOriginalSources=new Set();
const motion = () => !pointerInteraction||window.matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth';

function node(tag, className = '', text = '') {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if(tag==='code'||['source-time','source-tag'].includes(className))I18n.technical(element);
  if (text !== '') element.textContent = String(text);
  return element;
}
function show(value) { return I18n.value(value); }
function lock(value) {
  busy = value;document.querySelectorAll('[data-language]').forEach(button=>{button.disabled=value;}); $('#theater').setAttribute('aria-busy', String(value));
  $('#replay').disabled = value || !current;
  document.querySelectorAll('[data-theater-case]').forEach(button => {button.disabled = value;});
  $('#download-passport').disabled = value || !result;
  $('#challenge-toggle').disabled = value || !current;
  $('#challenge-submit').disabled = value || !humanVerdict || !!result;
  $('#verdict-choices').disabled = value || !!result;
  document.querySelectorAll('[data-challenge-case], #next-round').forEach(button => {button.disabled = value;});
}
function selectQuote(sourceId, field) {
  $('#theater-detail').open=true;
  openOriginalSources.add(sourceId);selected = {sourceId, field}; renderEvidence(); renderExtraction();
  const card = document.getElementById('document-' + sourceId);
  if (card) {card.tabIndex=-1;card.focus({preventScroll:true});card.scrollIntoView({behavior:motion(),block:'center'});}
}
function sourceName(id) {return id === 'tracking' ? t("tracking_del_transportista_ae270b") : t("comprobante_de_recepcion_01f43d");}
function markedText(text, quote) {
  const paragraph = node('p','document-text');paragraph.dataset.original='true';paragraph.lang='es';
  if (!quote || !text.includes(quote)) {paragraph.textContent = text; return paragraph;}
  const index = text.indexOf(quote);
  paragraph.append(document.createTextNode(text.slice(0,index)),node('mark','',quote),document.createTextNode(text.slice(index+quote.length)));
  return paragraph;
}
function renderEvidence() {
  const shipment = current.input.shipment;
  $('#shipment').replaceChildren(node('small','',t("envio_investigado_421b22")),node('strong','',shipment.id),node('p','',shipment.expected_packages + t("bultos_esperados_segun_expediente_sintetico_fde208")));
  const area = $('#documents'); area.replaceChildren();
  for (const source of current.input.documents) {
    const excluded = result?.decision.excluded_sources.some(item => item.source_id === source.source_id);
    const focused = selected?.sourceId === source.source_id;
    const extracted = current.extraction.documents.find(doc => doc.source_id === source.source_id);
    const quote = focused ? extracted?.[selected.field]?.quote : null;
    const card = node('article','document' + (focused ? ' focused' : '') + (excluded ? ' foreign' : '')); card.id = 'document-' + source.source_id;
    const head = node('div','document-head'); head.append(node('h4','',sourceName(source.source_id)),node('span','source-tag',source.source_id));
    card.append(head,node('small','source-time',I18n.authority(source.authority)+' · '+source.at),I18n.evidencePresentation(source.text));
    const original=node('details','technical-record source-original');original.dataset.technical='true';original.open=openOriginalSources.has(source.source_id);original.addEventListener('toggle',()=>{if(original.isConnected){if(original.open)openOriginalSources.add(source.source_id);else openOriginalSources.delete(source.source_id);}});
    original.append(node('summary','',t('view_original_document')),markedText(source.text,quote),I18n.technicalDetails('view_original_codes',{source_id:source.source_id,authority:source.authority,at:source.at}));card.append(original);
    if (excluded) card.append(node('div','foreign-label',t("otro_envio_excluido_del_calculo_6ce4b2")));
    area.append(card);
  }
}
function renderExtraction() {
  $('#meta-kicker').textContent = current.origin.kind === 'HISTORICAL_META' ? t("el_registro_original_297b07") : t("la_anotacion_sintetica_31a370");
  $('#meta-heading').textContent = current.origin.kind === 'HISTORICAL_META' ? t("interpretacion_de_meta_d5b0e0") : t("extraccion_de_prueba_ca9028");
  $('#interpretation-note').textContent = current.origin.kind === 'HISTORICAL_META' ? current.origin.model + ' / ' + current.origin.record_id + t("inferencia_historica_campos_reproducidos_sin_corregi_5531d1") : t("pm01_07_hechos_anotados_sin_inferencia_meta_en_este__3e85c3");
  const area = $('#extraction'); area.replaceChildren();
  for (const source of current.input.documents) {
    const extracted = current.extraction.documents.find(doc => doc.source_id === source.source_id);
    const block = node('article','extraction-source'), head = node('header');
    head.append(node('h4','',source.source_id),node('span','source-status',extracted ? t("campos_registrados_7fcd9a") : t("no_extraido_89e29b"))); block.append(head);
    if (!extracted) {
      const missing = node('div','missing-source'); missing.append(node('strong','',t("documento_omitido_38b405")),node('p','',t("el_documento_original_existe_pero_meta_no_lo_incluyo_312220")));
      const link = node('button','source-link',t("ver_el_documento_original_b4e6ee")); link.addEventListener('click',()=>selectQuote(source.source_id,'shipment_id')); missing.append(link); block.append(missing); area.append(block); continue;
    }
    const relevant = source.authority === 'carrier_status' ? ['status','shipment_id','delivery_complete'] : ['shipment_id','expected_packages','received_packages','signature_present','signature_identity_verified'];
    let field = selected?.sourceId === source.source_id ? selected.field : relevant[0];
    if (!relevant.includes(field)) field = relevant[0];
    for (const key of relevant) {
      const lineage = result?.lineage.find(row => row.source_id === source.source_id && row.field === key);
      const row = node('button','field' + (key === field ? ' selected' : '') + (lineage?.validation === 'FAIL' ? ' invalid' : '') + (lineage?.validation === 'EXCLUDED' ? ' excluded' : ''));
      row.dataset.source = source.source_id; row.dataset.field = key; row.type = 'button'; row.setAttribute('aria-label',t('ui_label',{label:names[key],value:show(extracted[key].value),source:source.source_id})); row.setAttribute('aria-pressed',String(key === field));
      const value=node('span','field-value'+(extracted[key].value===null?' field-null':''),show(extracted[key].value));
      row.append(node('span','field-name',names[key]),value,node('span','field-arrow',extracted[key].quote?'→':'—'));
      row.addEventListener('click',()=>selectQuote(source.source_id,key)); block.append(row);
    }
    const quote = node('div','quote-box');quote.append(node('small','original-note',t('readable_presentation')));
    quote.append(node('small','',source.source_id),node('p','quote-readable',extracted[field].quote?I18n.quotePresentation(extracted[field].quote):t("sin_cita_el_valor_permanece_desconocido_d36a0d")));
    const lineage=result?.lineage.find(row=>row.source_id===source.source_id&&row.field===field);
    if(lineage)quote.append(node('small','field-validation',t("control_2f830a")+I18n.state(lineage.validation)+' · '+(lineage.used_by_engine?t("utilizado_por_el_motor_5146d9"):t("no_utilizado_por_el_motor_0eb67d"))));
    quote.append(I18n.technicalDetails('view_original_quote',{source_id:source.source_id,field,value:extracted[field].value,quote:extracted[field].quote,validation:lineage?.validation??null}));
    block.append(quote); area.append(block);
  }
}
function waiting() {
  cancelProofMoment();
  const panel = $('#decision'); panel.className = 'column-body decision waiting'; panel.replaceChildren(node('div','waiting-symbol','→'),node('span','result-tag',busy ? t("validando_en_python_102616") : t("pendiente_de_reproduccion_809c09")),node('h4','',t("la_evidencia_esta_lista_la_decision_todavia_no_5417d2")),node('p','',t("el_boton_ejecuta_de_nuevo_los_validadores_y_solo_si__547c29")));
  const list = node('ol','waiting-list'); [t("validar_todas_las_fuentes_e6e211"),t("comprobar_el_significado_66cac6"),t("calcular_con_hechos_admitidos_085cf7")].forEach((text,index)=>{const item=node('li');item.append(node('span','',String(index+1).padStart(2,'0')),document.createTextNode(text));list.append(item);}); panel.append(list);
}
function renderDecision() {
  cancelProofMoment();
  const data = result.decision, operation = data.operational_result, blocked = data.outcome === 'blocked';
  const panel = $('#decision'); panel.className = 'column-body decision ' + data.outcome; panel.replaceChildren();
  const label = blocked ? t("extraccion_rechazada_f87068") : data.outcome === 'excluded' ? t("documento_ajeno_excluido_9f0b0b") : data.outcome === 'confirmed' ? t("conformidad_documental_0fa405") : t("revision_requerida_3b43d2");
  panel.append(node('span','result-tag',label));
  const title = blocked ? (data.reason.code === 'SOURCE_SET_MISMATCH' ? t("falta_una_fuente_el_motor_no_empieza_cb13a0") : t("una_palabra_cambia_todo_el_guard_la_detiene_86f738")) : data.outcome === 'excluded' ? t("diez_bultos_pero_de_otro_envio_56fd9e") : t("lo_documental_alcanza_la_revision_permanece_73fad2");
  panel.append(node('h4','',title));
  if (blocked) {
    if (data.reason.code === 'UNSUPPORTED_STATUS') {
      panel.classList.add('proof-moment');
      const contrast = node('div','status-contrast');
      contrast.append(node('small','',t("fuente_tracking_df5159")),node('strong','literal-status',I18n.quotePresentation(data.reason.quote)),node('span','contrast-arrow',t("meta_interpreto_5af632")),node('strong','wrong',show(data.reason.value)),node('p','',t("la_cita_existe_su_significado_no_respalda_la_complet_3bd7cf"))); panel.append(contrast);
      const cite = node('button','link-to-source',t("recorrer_la_cita_del_estado_b8b01b")); cite.addEventListener('click',()=>selectQuote('tracking','status'));panel.append(cite);
    } else panel.append(node('p','',explain(data.reason.message) + t("el_control_de_fuentes_rechaza_antes_de_ejecutar_el_g_9fbf42")));
    const stopped = node('div','blocked-engine'); stopped.append(node('strong','',t("baseline_no_ejecutado_94404e")),node('small','',t("sin_diferencia_calculada_desde_campos_rechazados_b7504d")));panel.append(stopped);
  } else {
    panel.append(node('p','',data.outcome === 'excluded' ? t("el_comprobante_pertenece_a_syn_otro_701_sus_cantidad_877c7d") : t("el_calculo_usa_solo_hechos_extraidos_citados_y_admit_404d11")));
    const metrics = node('div','metrics');
    for (const [key,label] of [['expected',t("esperados_ebb299")],['documented',t("documentados_184551")],['difference',t("diferencia_e702db")]]) {
      const value=data.quantities[key],cell=node('div','metric');cell.append(node('span','',label),node('strong',value===null?'unknown':'',value===null?(key==='difference'?t("sin_calculo_0b3911"):t("sin_dato_102d6d")):value));metrics.append(cell);
    }
    panel.append(metrics);
    if(data.outcome==='confirmed'){
      const trace=node('div','conclusion-links');
      for(const [field,label] of [['expected_packages',data.quantities.expected+t("esperados_b91bd2")],['received_packages',data.quantities.documented+t("documentados_0a6eaf")],['signature_identity_verified',t("identidad_declarada_2748f9")]]){
        const link=node('button','link-to-source',label+' → pod');link.dataset.lineageField=field;link.addEventListener('click',()=>selectQuote('pod',field));trace.append(link);
      }
      trace.append(node('p','',t("diferencia_esperados_documentados_identidad_declarad_7b406a")));panel.append(trace);
    }
    if (data.outcome === 'excluded') {const link=node('button','link-to-source',t("ver_identidad_del_comprobante_5376c8"));link.addEventListener('click',()=>selectQuote('pod','shipment_id'));panel.append(link);}
  }
  const conformity=node('div','conformity'), text=node('div','',t("conformidad_documental_5a07ff"));text.append(node('small','',blocked?t("el_rechazo_impide_evaluarla_18c056"):t("no_acredita_una_entrega_fisica_4494e1")));conformity.append(text,node('span','conformity-label',blocked?t("no_evaluada_c9fe13"):show(operation.documentary_conformity)));panel.append(conformity);
  const checks=node('ul','checks');
  for (const item of result.checks) {const line=node('li');line.title=explain(item.detail);line.append(node('span','',checkNames[item.id]),node('span','check-status check-'+item.status,checkLabels[item.status]||I18n.state(item.status)));checks.append(line);}panel.append(checks);
  const detail=node('details','validation-detail');detail.append(node('summary','',t("ver_que_valida_cada_control_6a2182")));
  for(const item of result.checks)detail.append(node('p','',checkNames[item.id]+' / '+I18n.state(item.status)+': '+explain(item.detail)));panel.append(detail);
  if(!blocked){panel.append(node('h5','',t("lo_que_sigue_incierto_f02bdc")));const unknown=node('ul','review-list');operation.uncertainties.forEach(code=>unknown.append(node('li','',uncertaintyNames[code]||I18n.state(code))));panel.append(unknown);panel.append(node('p','',data.contradictions.length?data.contradictions.map(item=>explain(item.statement)).join(' '):t("sin_contradicciones_explicitas_entre_las_fuentes_adm_be3e10")));
  }
  panel.append(node('h5','',t("para_revision_humana_fe4f47")));const human=node('ul','review-list');data.human_review.forEach(text=>human.append(node('li','',explain(text))));panel.append(human);
  panel.append(node('h5','',blocked?t("propuestas_de_abstencion_2eaa79"):t("propuestas_sin_ejecucion_1d313e")));const actions=node('ul','review-list');operation.proposed_actions.forEach(code=>actions.append(node('li','',actionNames[code]||I18n.state(code))));panel.append(actions);
  const safety=node('div','safety');safety.append(node('span','',t("cierre_automatico_prohibido_dbd63a")),node('span','',t("sin_verificacion_fisica_25d40a")));panel.append(safety,node('div','execution',t("reproduccion_offline_f9f077")+result.execution.id+' · '+result.execution.elapsed_ms.toFixed(2)+' ms'));
  panel.append(I18n.technicalDetails('view_original_codes',{engine_status:data.baseline_status,checks:result.checks,reason:data.reason,documentary_conformity:operation.documentary_conformity}));
  $('#passport-id').textContent=result.passport.decision_id;
}
function renderContext(){
  $('#origin-label').textContent=explain(current.origin.label).toUpperCase();$('#case-id').textContent=current.id+' / '+current.input.shipment.id;
  $('#provenance-label').textContent=current.origin.kind==='HISTORICAL_META'?t("meta_historical_inference_offline_replay_ca4a40"):t("synthetic_challenge_no_meta_inference_c67fb0");
  $('#provenance-case').textContent=current.id;
  $('#provenance-bar').hidden=false;
  $('#case-title').textContent=challenge?t("revisa_la_evidencia_el_veredicto_es_tuyo_c0cb6c"):explain(current.title);$('#origin-detail').textContent=challenge?(current.origin.kind==='HISTORICAL_META'?t("reproduccion_offline_de_una_extraccion_historica_rea_28a261"):t("extraccion_sintetica_anotada_no_proviene_de_una_llam_8d7643")):explain(current.origin.detail);
  document.querySelectorAll('[data-theater-case]').forEach(button=>{const active=button.dataset.theaterCase===current.id;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
  $('#replay').replaceChildren(document.createTextNode(t("reproducir_evaluacion_7dfc72")),node('span','','→'));
}
function selectCase(id) {
  if(busy)return;
  current=records.find(record=>record.id===id);if(!current)return;
  result=null;selected=null;openOriginalSources.clear();$('#error').hidden=true;lastErrorKey=null;$('#passport-id').textContent=t("disponible_despues_de_reproducir_e68943");
  renderContext();
  humanVerdict=null;
  document.querySelectorAll('[name="human-verdict"]').forEach(input=>{input.checked=false;});
  $('#challenge-reveal').hidden=true;
  $('#challenge-progress').textContent=t("tu_eleccion_permanece_solo_en_esta_interfaz_no_se_en_3e9830");
  document.querySelectorAll('[data-challenge-case]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.challengeCase===id)));
  syncChallenge();lock(false);renderEvidence();renderExtraction();waiting();
}
async function evaluateCurrent(){
  if(busy||!current)return;
  lock(true);result=null;$('#error').hidden=true;lastErrorKey=null;$('#passport-id').textContent=t("validando_evidencia_cecc62");renderEvidence();renderExtraction();waiting();
  try{
    const response=await fetch('/api/theater/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:current.id})});
    if(!response.ok)throw new Error(t("no_se_pudo_reproducir_la_evaluacion_no_se_genero_una_6d4656"));
    const data=await response.json();if(data.case_id!==current.id||data.live_inference_enabled!==false)throw new Error(t("contrato_de_respuesta_no_valido_18ec3f"));
    result=data;current=data.record;
    if(data.decision.reason?.source_id&&data.decision.reason.field)selected={sourceId:data.decision.reason.source_id,field:data.decision.reason.field};
    renderEvidence();renderExtraction();renderDecision();presentProofMoment();
    if(challenge)revealChallenge();
    $('#replay').replaceChildren(document.createTextNode(t("volver_a_reproducir_08b7bc")),node('span','','↻'));
    if(!challenge&&window.matchMedia('(max-width:760px)').matches)$('#proof-column').scrollIntoView({behavior:motion(),block:'start'});
  }catch(error){lastErrorKey=I18n.errorKey(error);$('#error').textContent=t(lastErrorKey);$('#error').hidden=false;result=null;waiting();
    $('#passport-id').textContent=t("no_disponible_evaluacion_no_producida_04a6c1");
    if(challenge){$('#challenge-progress').textContent=t("evaluacion_no_disponible_no_se_produjo_un_veredicto__50d459");syncChallenge();}
  }
  finally{lock(false);}
}
$('#replay').addEventListener('click',evaluateCurrent);
$('#download-passport').addEventListener('click',()=>{
  if(!result||busy)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(result.passport,null,2)],{type:'application/json'}));
  const anchor=node('a');anchor.href=url;anchor.download=result.passport.decision_id+'.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function syncChallenge(){
  document.body.classList.toggle('challenge-mode',challenge);
  document.body.classList.toggle('challenge-unrevealed',challenge&&!result);
  $('#challenge-toggle').textContent=challenge?t("volver_a_decision_theater_090daf"):t("entrar_a_proof_challenge_955b92");
  $('#challenge-toggle').setAttribute('aria-pressed',String(challenge));
  $('#challenge-intro').hidden=!challenge;
  $('#challenge-vote').hidden=!challenge||!!result;
  $('#go-to-verdict').hidden=!challenge||!!result;
  $('#theater-detail').open=!challenge||!result;
  $('#theater-detail-label').hidden=!challenge||!result;
}
function revealChallenge({focus=true}={}){
  const decision=result.decision, operation=decision.operational_result;
  const computed=decision.baseline_status==='COMPUTED_BY_BASELINE';
  const confirmed=computed&&operation.documentary_conformity==='CONFIRMED';
  $('#human-verdict').textContent=humanVerdict==='yes'?t("si_confirmada_017dec"):t("no_falta_evidencia_valida_8a83ef");
  $('#proof-verdict-code').textContent=computed?operation.documentary_conformity:'';
  $('#proof-verdict').textContent=computed?show(operation.documentary_conformity):t("no_evaluada_c9fe13");
  $('#verdict-comparison').textContent=!computed?t("proof_se_abstiene_la_validacion_bloqueo_el_calculo_5d224c"):
    ((humanVerdict==='yes')===confirmed?t("tu_veredicto_coincide_con_la_evaluacion_59f764"):t("tu_veredicto_difiere_de_la_evaluacion_73e006"))+t("el_resultado_proviene_del_backend_python_dcc3e6");
  $('#verdict-limit').textContent=!computed?t("extraccion_rechazada_no_hay_una_conformidad_calculad_ab3cac"):confirmed?
    t("conformidad_documental_respaldada_sin_verificacion_f_f45b92"):
    t("la_evidencia_admitida_no_establece_conformidad_docum_42f7b7");
  const area=$('#decisive-evidence');area.replaceChildren();
  area.append(node('p','shipment-comparison',t("envio_investigado_14e51a")+result.record.input.shipment.id));
  // Foreign identifiers are taken from the returned lineage, not inferred by the UI.
  const excluded=new Set(decision.excluded_sources.map(source=>source.source_id));
  const decisive=result.lineage.filter(row=>excluded.has(row.source_id)?row.field==='shipment_id':
    confirmed&&row.used_by_engine&&(row.field==='status'||row.field==='expected_packages'||row.field==='received_packages'));
  for(const row of decisive){
    const block=node('div','decisive-citation');
    block.append(node('small','',row.source_id+' / '+names[row.field]+' / '+I18n.state(row.validation)),
      node('strong','',show(row.value)),node('p','quote-readable',row.quote?I18n.quotePresentation(row.quote):t("sin_cita_disponible_aa1ec8")));
    block.append(node('small','original-note',t('readable_presentation')),I18n.technicalDetails('view_original_quote',{source_id:row.source_id,field:row.field,value:row.value,quote:row.quote,validation:row.validation}));
    if(row.quote){const link=node('button','source-link',t("ver_cita_en_923d15")+row.source_id+' →');link.addEventListener('click',()=>selectQuote(row.source_id,row.field));block.append(link);}
    area.append(block);
  }
  if(!decisive.length)area.append(node('p','',(decision.reason?explain(decision.reason.message):null)||t("revisar_la_trazabilidad_de_las_fuentes_admitidas_370ed9")));
  const controls=node('p','decisive-controls');
  controls.textContent=result.checks.filter(check=>['citations','status_guard','shipment','baseline'].includes(check.id)).map(check=>checkNames[check.id]+': '+(checkLabels[check.status]||I18n.state(check.status))).join(' · ');
  area.append(controls,node('small','',t("baseline_657426")+I18n.state(decision.baseline_status)));
  const review=$('#reconsider-evidence');review.replaceChildren();
  decision.human_review.forEach(text=>review.append(node('li','',explain(text))));
  if(computed&&operation.physical_delivery_verified===false)review.append(node('li','',t("la_conformidad_documental_no_sustituye_una_comprobac_2b1726")));
  $('#next-round').textContent=current.id==='PM01-07'?t("ronda_b_the_proof_f5173a"):t("volver_al_decision_theater_f1b59d");
  syncChallenge();$('#challenge-reveal').hidden=false;
  $('.reconsider').open=!window.matchMedia('(max-width:760px)').matches;
  if(focus){$('#challenge-reveal').focus({preventScroll:true});$('#challenge-reveal').scrollIntoView({behavior:motion(),block:'start'});}
}
$('#go-to-verdict').addEventListener('click',()=>{
  if(busy||!challenge||result)return;
  $('#challenge-vote').scrollIntoView({behavior:motion(),block:'start'});
  $('[name="human-verdict"]').focus({preventScroll:true});
});
new ResizeObserver(()=>document.documentElement.style.setProperty('--provenance-height',Math.ceil($('#provenance-bar').getBoundingClientRect().height)+'px')).observe($('#provenance-bar'));
$('#challenge-toggle').addEventListener('click',()=>{
  if(busy)return;
  challenge=!challenge;selectCase(challenge?'PM01-07':records[0].id);
  if(challenge)$('#challenge-title').scrollIntoView({behavior:motion(),block:'start'});
});
document.querySelectorAll('[data-challenge-case]').forEach(button=>button.addEventListener('click',()=>selectCase(button.dataset.challengeCase)));
document.querySelectorAll('[name="human-verdict"]').forEach(input=>input.addEventListener('change',()=>{
  humanVerdict=input.value;$('#challenge-submit').disabled=busy||!humanVerdict;
}));
$('#challenge-submit').addEventListener('click',()=>{
  if(!challenge||!humanVerdict||result||busy)return;
  $('#challenge-progress').textContent=t("validando_fuentes_y_citas_en_python_tu_eleccion_no_a_b11e9c");
  evaluateCurrent();
});
$('#next-round').addEventListener('click',()=>{
  if(busy)return;
  if(current.id==='PM01-07'){selectCase('PM01-02');$('#challenge-title').scrollIntoView({behavior:motion(),block:'start'});}
  else{challenge=false;selectCase('PM01-02');$('#case-tabs').scrollIntoView({behavior:motion(),block:'start'});}
});

function renderTabs(){
    const nav=$('#case-tabs');nav.replaceChildren();
    records.forEach((record,index)=>{const button=node('button','case-tab');button.dataset.theaterCase=record.id;button.setAttribute('aria-pressed',String(record.id===current?.id));button.classList.toggle('active',record.id===current?.id);const text=node('span');text.append(node('strong','',explain(record.short_title)),node('small','',index===3?t("desafio_sintetico_ed3790"):t("meta_live_02_registro_real_b3d743")));button.append(node('span','',String(index+1).padStart(2,'0')),text,node('span','tab-arrow','→'));button.addEventListener('click',()=>selectCase(record.id));nav.append(button);});
}
async function initialize(){
  lock(true);waiting();
  try{
    const response=await fetch('/api/theater/cases');if(!response.ok)throw new Error(t("no_se_pudo_cargar_la_evidencia_publica_verificada_1179c6"));
    const data=await response.json();records=data.cases;
    renderTabs();
    busy=false;selectCase(records[0].id);
  }catch(error){lastErrorKey=I18n.errorKey(error);$('#error').textContent=t(lastErrorKey);$('#error').hidden=false;lock(false);}
}
document.addEventListener('proof:language',()=>{
  if(!current){waiting();if(lastErrorKey)$('#error').textContent=t(lastErrorKey);return;}
  const detailOpen=$('#theater-detail').open,reviewOpen=$('.reconsider').open;
  renderTabs();renderContext();renderEvidence();renderExtraction();syncChallenge();
  if(result){renderDecision();if(challenge)revealChallenge({focus:false});}
  else{syncChallenge();waiting();}
  $('#theater-detail').open=detailOpen;$('.reconsider').open=reviewOpen;
  if(lastErrorKey){$('#error').textContent=t(lastErrorKey);$('#error').hidden=false;}
  if(!result){
    $('#passport-id').textContent=lastErrorKey?t("no_disponible_evaluacion_no_producida_04a6c1"):t("disponible_despues_de_reproducir_e68943");
    $('#challenge-progress').textContent=lastErrorKey?t("evaluacion_no_disponible_no_se_produjo_un_veredicto__50d459"):t("tu_eleccion_permanece_solo_en_esta_interfaz_no_se_en_3e9830");
  }
  $('#replay').replaceChildren(document.createTextNode(result?t("volver_a_reproducir_08b7bc"):t("reproducir_evaluacion_7dfc72")),node('span','',result?'↻':'→'));
  lock(busy);
});
initialize();

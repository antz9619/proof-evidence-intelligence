'use strict';
const I18n=window.PROOF_I18N, t=I18n.t, explain=I18n.explain;

const $ = (selector) => document.querySelector(selector);
const labels = I18n.liveLabels(() => ({shipment_id: t("envio_citado_887b5f"), status: t("estado_informado_d5cb18"), delivery_complete: t("completitud_explicita_69f05c"), expected_packages: t("bultos_esperados_739758"), received_packages: t("bultos_documentados_4bc8ab"), signature_present: t("firma_presente_08ba19"), signature_identity_verified: t("identidad_verificada_17593b")}));
const uncertaintyLabels = I18n.liveLabels(() => ({PHYSICAL_DELIVERY_UNVERIFIED: t("no_existe_verificacion_fisica_independiente_5ff23e"), QUANTITY_MISMATCH: t("hay_una_diferencia_documental_su_causa_y_destino_fis_1877e9"), SIGNER_IDENTITY_UNKNOWN: t("la_identidad_del_firmante_no_esta_verificada_dafbea"), QUANTITY_UNKNOWN: t("la_cantidad_recibida_no_esta_disponible_como_un_dato_448fc3"), TRACKING_UNKNOWN: t("no_hay_un_estado_de_tracking_confirmado_por_esta_eva_447de8"), DOCUMENTARY_CONFLICT: t("existen_declaraciones_documentales_incompatibles_73ca4e"), FOREIGN_DOCUMENT: t("una_fuente_pertenece_a_otro_envio_y_se_excluyo_15727e"), SHIPMENT_ID_UNKNOWN: t("no_se_pudo_establecer_a_que_envio_pertenece_una_fuen_37a2ba")}));
const actionLabels = I18n.liveLabels(() => ({KEEP_CLOSURE_PENDING: t("mantener_pendiente_el_cierre_conforme_727c9d"), REQUEST_ADDITIONAL_EVIDENCE: t("solicitar_evidencia_adicional_de_recepcion_para_revi_11e1f1"), VERIFY_SIGNER_IDENTITY: t("verificar_firma_e_identidad_mediante_una_fuente_auto_23c2f6"), REVIEW_DOCUMENTARY_CLOSURE: t("someter_la_conformidad_documental_a_revision_humana_84c76f")}));
let catalog = [], current = null, busy = false, selected = {}, lastResult = null, lastErrorKey=null;
const openOriginalSources=new Set();

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if(tag==='code'||tag==='pre'||['source-meta','source-tag'].includes(className))I18n.technical(node);
  if (text !== '') node.textContent = String(text);
  return node;
}
function showValue(value) { return I18n.value(value); }
function setBusy(value) {
  busy = value;document.querySelectorAll('[data-language]').forEach(button=>{button.disabled=value;});
  $('#evaluate').disabled = value || !current;
  document.querySelectorAll('[data-case]').forEach(button => { button.disabled = value; });
  $('#workspace').setAttribute('aria-busy', String(value));
}
function focusSource(sourceId, field = null) {
  openOriginalSources.add(sourceId);if (field) selected[sourceId] = field;
  renderDocuments();
  const card = document.getElementById('source-' + sourceId);
  if (card) { card.classList.add('focused'); card.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth', block: 'center'}); }
}
function highlight(text, extraction, field) {
  const node = el('p', 'document-text');node.dataset.original='true';node.lang='es';
  const quote = extraction[field]?.quote;
  if (!quote || !text.includes(quote)) { node.textContent = text; return node; }
  const index = text.indexOf(quote);
  node.append(document.createTextNode(text.slice(0, index)), el('mark', 'selected', quote), document.createTextNode(text.slice(index + quote.length)));
  return node;
}
function renderDocuments() {
  const area = $('#documents'); area.replaceChildren();
  for (const source of current.input.documents) {
    const extracted = current.extraction.documents.find(doc => doc.source_id === source.source_id);
    const carrier = source.authority === 'carrier_status';
    const fields = carrier ? ['status', 'shipment_id', 'delivery_complete'] : ['expected_packages', 'received_packages', 'signature_present', 'signature_identity_verified', 'shipment_id'];
    const field = selected[source.source_id] || (carrier ? 'status' : 'received_packages');
    const invalid = lastResult?.outcome === 'rejected' && lastResult.reason?.source_id === source.source_id;
    const card = el('article', 'document' + (invalid ? ' rejected' : '')); card.id = 'source-' + source.source_id;
    const head = el('div', 'document-head'), info = el('div');
    info.append(el('h4', '', carrier ? t("tracking_del_transportista_ae270b") : t("comprobante_de_recepcion_01f43d")), el('div', 'source-meta', I18n.authority(source.authority) + ' · ' + source.at.slice(11, 16) + ' (' + source.at.slice(19) + ')'));
    head.append(info, el('span', 'source-tag', source.source_id));
    card.append(head,I18n.evidencePresentation(source.text));
    const original=el('details','technical-record source-original');original.dataset.technical='true';original.open=openOriginalSources.has(source.source_id);original.addEventListener('toggle',()=>{if(original.isConnected){if(original.open)openOriginalSources.add(source.source_id);else openOriginalSources.delete(source.source_id);}});
    original.append(el('summary','',t('view_original_document')),highlight(source.text,extracted,field),I18n.technicalDetails('view_original_codes',{source_id:source.source_id,authority:source.authority,at:source.at}));
    card.append(original,el('div','extraction-label',t("valores_extraidos_explora_sus_citas_477966")));
    const rows = el('div', 'fields');
    for (const key of fields) {
      const item = extracted[key];
      const row = el('button', 'field' + (key === field ? ' selected' : '') + (invalid && key === lastResult.reason.field ? ' invalid' : ''));
      row.type = 'button'; row.dataset.source = source.source_id; row.dataset.field = key;
      row.setAttribute('aria-label',t('ui_label',{label:labels[key],value:showValue(item.value),source:source.source_id}));
      row.setAttribute('aria-pressed', String(key === field));
      const value=el('span','field-value'+(item.value===null?' unknown':''),showValue(item.value));
      row.append(el('span','field-label',labels[key]),value,el('span','cite-arrow',item.quote?'→':'—'));
      row.addEventListener('click', () => {
        openOriginalSources.add(source.source_id);selected[source.source_id] = key; renderDocuments();
        document.querySelector(`[data-source="${source.source_id}"][data-field="${key}"]`)?.focus({preventScroll: true});
      });
      rows.append(row);
    }
    const quote=el('div','quote-detail');quote.append(el('small','original-note',t('readable_presentation')),el('p','quote-readable',extracted[field].quote?I18n.quotePresentation(extracted[field].quote):t("sin_cita_el_campo_permanece_desconocido_0d5f29")),I18n.technicalDetails('view_original_quote',{source_id:source.source_id,field,value:extracted[field].value,quote:extracted[field].quote}));
    let foot = t("pendiente_de_validacion_los_valores_no_establecen_he_ea47e2");
    if (lastResult) foot = lastResult.outcome === 'rejected' ? t("extraccion_rechazada_no_utilizada_para_calcular_b96633") : t("controles_locales_superados_revision_semantica_pendi_eedc2f");
    card.append(rows, quote, el('div', 'document-foot', foot)); area.append(card);
  }
}
function clearAudit() { document.querySelector('.audit-wrap')?.remove(); }
function renderWaiting(evaluating = false) {
  clearAudit(); const panel = $('#decision'); panel.className = 'decision waiting'; panel.replaceChildren();
  const intro = el('div'); intro.append(el('div', 'pending-icon', evaluating ? '↻' : '→'), el('span', 'eyebrow', evaluating ? t("ejecucion_local_en_curso_3deff7") : t("listo_para_validar_522d52")), el('h4', '', evaluating ? t("la_evidencia_entra_las_reglas_verifican_9901f5") : t("la_evidencia_esta_lista_la_decision_todavia_no_5417d2")), el('p', 'intro', t("evalua_el_caso_para_validar_sus_citas_y_ejecutar_el__67fd39")));
  const steps = el('div', 'step-strip'); [t("validar_extraccion_a6dcd0"), t("calcular_con_evidencia_37fdb4"), t("proponer_revision_f36355")].forEach(text => steps.append(el('span', '', text)));
  panel.append(intro, steps);
}
function renderContext() {
  $('#origin').textContent = explain(current.origin.label); $('#origin').className = 'origin' + (current.origin.kind === 'HISTORICAL' ? ' historical' : '');
  $('#shipment').textContent = current.input.shipment.id + ' / ' + current.input.case_id;
  $('#case-title').textContent = explain(current.title); $('#origin-detail').textContent = explain(current.origin.detail);
}
function selectCase(id) {
  if (busy) return;
  current = catalog.find(item => item.id === id); if (!current) return;
  selected = {};openOriginalSources.clear(); lastResult = null;
  document.querySelectorAll('[data-case]').forEach(button => { const active = button.dataset.case === id; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); });
  renderContext();
  $('#evaluate').replaceChildren(document.createTextNode(t("evaluar_evidencia_0bbca1")), el('span', '', '→'));
  $('#app-error').hidden = true;lastErrorKey=null; setBusy(false); renderDocuments(); renderWaiting();
}
function section(panel, title, items, ordered = false) {
  const block = el('div', 'decision-section'); block.append(el('h5', '', title));
  const list = el(ordered ? 'ol' : 'ul'); items.forEach(text => list.append(el('li', '', text)));
  block.append(list); panel.append(block); return block;
}
function renderDecision(data) {
  const panel = $('#decision'), result = data.evaluation, operation = result.operational_result;
  panel.className = 'decision ' + data.outcome; panel.replaceChildren(); clearAudit();
  const rejected = data.outcome === 'rejected', incomplete = data.outcome === 'incomplete';
  panel.append(el('span', 'result-badge', rejected ? t("extraccion_rechazada_f87068") : incomplete ? t("evidencia_insuficiente_8d951d") : t("extraccion_aceptada_revision_pendiente_adbec0")));
  panel.append(el('h4', '', rejected ? t("el_calculo_se_detuvo_antes_de_empezar_912499") : incomplete ? t("sin_evidencia_no_inventamos_una_cantidad_bef621") : t("entrega_informada_conformidad_pendiente_7aa987")));
  if (rejected) {
    panel.append(el('p', 'intro', t("el_guard_rechazo_un_dato_antes_de_que_llegara_al_bas_5e3f78")));
    const box = el('div', 'rejection-box'); box.append(el('p','rejection-explanation'));
    box.querySelector('.rejection-explanation').append(document.createTextNode(t("la_extraccion_afirma_aafd50")),document.createTextNode(showValue(data.reason.value)),document.createTextNode(t("pero_cita_bc8ef0")),document.createTextNode(I18n.quotePresentation(data.reason.quote)),document.createTextNode(t("esa_cita_no_respalda_el_estado_propuesto_3f39ec")));
    const pair = el('div', 'rejection-pair'); pair.append(el('span', '', data.reason.source_id + ' / ' + (labels[data.reason.field]||I18n.state(data.reason.field))), el('span', '', t("guard_semantico_05bd1b")));
    box.append(pair, el('p', 'execution', explain(data.reason.message))); panel.append(box);
    const blocked = el('div', 'blocked-calculation'); const label = el('div', '', t("baseline_no_ejecutado_94404e")); label.append(el('small', '', t("sin_diferencia_calculada_desde_campos_rechazados_b7504d")));
    blocked.append(el('span', '', '⊘'), label); panel.append(blocked);
  } else {
    panel.append(el('p', 'intro', incomplete ? t("los_datos_desconocidos_conservan_null_el_motor_utili_dc4c6f") : t("el_motor_contrasta_lo_esperado_con_lo_documentado_la_b45801")));
    const metrics = el('div', 'metrics');
    for (const [key, label] of [['expected', t("esperados_ebb299")], ['documented', t("documentados_184551")], ['difference', t("diferencia_e702db")]]) {
      const value = data.quantities[key], cell = el('div', 'metric'); cell.append(el('span', 'metric-label', label));
      cell.append(el('strong', 'metric-number' + (value === null ? ' word' : ''), value === null ? (key === 'difference' ? t("sin_calculo_0b3911") : t("sin_dato_102d6d")) : value), el('small', '', value === null ? t("no_se_completa_54fa22") : t("bultos_ecd131"))); metrics.append(cell);
    }
    panel.append(metrics);
  }
  const conformity = el('div', 'conformity'), conformityLabel = el('div', '', t("conformidad_documental_5a07ff"));
  conformityLabel.append(el('small', '', rejected ? t("el_rechazo_impide_evaluar_conformidad_739e3b") : t("se_requiere_revision_no_acredita_entrega_fisica_36ab1b")));
  conformity.append(conformityLabel,el('span','conformity-label',rejected?t("no_evaluada_c9fe13"):showValue(operation.documentary_conformity))); panel.append(conformity);
  if (!rejected) {
    section(panel, t("lo_que_sigue_incierto_d2b636"), operation.uncertainties.map(code => uncertaintyLabels[code] || I18n.state(code)));
    const contradictions = result.baseline_result.contradictions;
    section(panel, t("contradicciones_757138"), contradictions.length ? contradictions.map(item => explain(item.statement)) : [t("no_se_detectaron_declaraciones_explicitamente_contra_f62d90")]);
    const differences = result.baseline_result.discrepancies;
    if (differences.length) {
      const trace = el('div', 'trace-links');
      [...new Set(differences.flatMap(item => item.source_ids))].forEach(id => { const link = el('button', 'trace-link', t("ver_fuente_5f901b") + id); link.addEventListener('click', () => focusSource(id, id === 'pod' ? 'received_packages' : 'status')); trace.append(link); });
      panel.append(trace);
    }
  }
  section(panel, t("propuestas_para_revision_sin_ejecucion_a9f826"), operation.proposed_actions.map(code => actionLabels[code] || I18n.state(code)), true);
  const safety = el('div', 'safety'); safety.append(el('span', '', t("cierre_automatico_prohibido_dbd63a")), el('span', '', t("sin_verificacion_fisica_25d40a"))); panel.append(safety);
  panel.append(el('div', 'execution', t("ejecucion_local_756ee2") + data.execution.id + ' · ' + data.execution.elapsed_ms.toFixed(2) + ' ms · ' + (data.execution.baseline_executed ? t("motor_ejecutado_59b88d") : t("motor_bloqueado_4e7e23"))));
  const wrap = el('div', 'audit-wrap'), audit = el('details', 'audit technical-record'); audit.append(el('small','original-note',t('technical_record')),el('summary', '', t("ver_trazabilidad_de_esta_ejecucion_2e5fb1")), el('pre', '', JSON.stringify({scope: data.execution.scope, sources: current.input.documents, extraction: current.extraction, ...data}, null, 2)));
  const download = el('button', 'download', t("descargar_evaluacion_json_eafea5"));
  download.addEventListener('click', () => { const url = URL.createObjectURL(new Blob([JSON.stringify({demo: current, result: data}, null, 2)], {type: 'application/json'})); const a = el('a'); a.href = url; a.download = 'proof-' + data.case_id + '-' + data.execution.id + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
  const back = el('a', 'download', t("cambiar_caso_293a93")); back.href = '#casos';
  wrap.append(audit, download, document.createTextNode(' '), back); panel.after(wrap);
}

$('#evaluate').addEventListener('click', async () => {
  if (!current || busy) return;
  setBusy(true); lastResult = null; $('#app-error').hidden = true;lastErrorKey=null; renderDocuments(); renderWaiting(true);
  try {
    const response = await fetch('/api/evaluate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({case_id: current.id})});
    if (!response.ok) throw new Error(t("la_evaluacion_local_no_pudo_completarse_820bee"));
    const data = await response.json();
    if (data.case_id !== current.id || data.demo.id !== current.id) throw new Error(t("la_respuesta_no_corresponde_al_caso_seleccionado_b92ef5"));
    current = data.demo; lastResult = data; renderContext(); renderDocuments(); renderDecision(data);
    $('#evaluate').replaceChildren(document.createTextNode(t("volver_a_evaluar_5e27fc")), el('span', '', '↻'));
    if (window.matchMedia('(max-width:760px)').matches) $('#decision-title').scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth', block: 'start'});
  } catch (error) {
    renderWaiting(); lastErrorKey=I18n.errorKey(error);$('#app-error').textContent = t(lastErrorKey) + t("no_se_genero_una_decision_verifica_el_servidor_y_vol_05a7e4"); $('#app-error').hidden = false;
  } finally { setBusy(false); }
});
document.querySelectorAll('[data-case]').forEach(button => button.addEventListener('click', () => selectCase(button.dataset.case)));
async function initialize() {
  setBusy(true); renderWaiting();
  try {
    const response = await fetch('/api/cases'); if (!response.ok) throw new Error(t("no_se_pudo_cargar_la_evidencia_0a8505"));
    const data = await response.json(); catalog = data.cases;
    busy = false; selectCase('A');
  } catch (error) { lastErrorKey=I18n.errorKey(error);$('#app-error').textContent = t(lastErrorKey); $('#app-error').hidden = false; }
  finally {setBusy(false);}
}
document.addEventListener('proof:language',()=>{
  const auditOpen=document.querySelector('.audit')?.open;
  if(current){renderContext();renderDocuments();if(lastResult){renderDecision(lastResult);document.querySelector('.audit').open=!!auditOpen;}else renderWaiting(busy);}
  else renderWaiting(busy);
  if(lastErrorKey){$('#app-error').textContent=t(lastErrorKey);$('#app-error').hidden=false;}
  $('#evaluate').replaceChildren(document.createTextNode(lastResult?t("volver_a_evaluar_5e27fc"):t("evaluar_evidencia_0bbca1")),el('span','',lastResult?'↻':'→'));
  setBusy(busy);
});
initialize();

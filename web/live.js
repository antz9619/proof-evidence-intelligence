/* No credential inputs, hardcoded credentials, storage, URLs or prompt strings.
   HTTP Basic is handled by the browser's native dialog on the /live navigation. */
(() => {
  'use strict';
  let en = new URLSearchParams(location.search).get('lang') === 'en';
  const t = (es, english) => en ? english : es;
  const $ = id => document.getElementById(id);
  const entry = $('live-entry');
  const syncEntry = () => {if(entry) entry.href='/live?lang='+(document.documentElement.lang==='en'?'en':'es');};
  syncEntry(); document.addEventListener('proof:language',syncEntry);
  if (!$('live-panel')) return;
  let status = null, attempt = null, busy = false;
  function localize() {
  $('live-title').textContent = t('Inferencia real · solo Owner', 'Real inference · Owner only');
  $('live-help').textContent = t('Reserva persistente antes del envío. Sin reintentos. Un timeout no cancela el procesamiento en Meta. El cupo no garantiza un límite monetario.', 'Persistent reservation before sending. No retries. A timeout does not cancel Meta processing. Attempt quota is not a guaranteed monetary limit.');
  $('live-label').textContent = t('Escenario sintético autorizado', 'Authorized synthetic scenario');
  $('live-send').textContent = t('Enviar una solicitud', 'Send one request');
  $('live-enable').textContent = t('Activar LIVE · Owner', 'Enable LIVE · Owner');
  $('live-disable').textContent = t('Desactivar LIVE', 'Disable LIVE');
  $('live-doc-title').textContent = t('Fuentes originales · español literal', 'Original sources · verbatim Spanish');
  $('live-result-title').textContent = t('Intento, extracción y controles', 'Attempt, extraction and checks');
  $('live-extraction-title').textContent = t('Extracción devuelta · citas literales', 'Returned extraction · exact quotes');
  $('live-checks-title').textContent = t('Validación y motor determinístico', 'Validation and deterministic engine');
  $('live-technical-title').textContent = t('Solicitud y registro técnico seguro', 'Request and safe technical record');
  $('live-download').textContent = t('Descargar Decision Passport evaluado', 'Download evaluated Decision Passport');
  $('live-attempt').textContent = t('Descargar registro técnico del intento', 'Download technical attempt record');
  $('live-offline').href = '/?lang=' + (en ? 'en' : 'es');
  }
  localize();
  document.addEventListener('proof:language', event => {en=event.detail.language==='en';localize();renderOrigin();});
  function renderOrigin() {
    if(status) $('live-provenance').textContent = status.provider === 'SIMULATED_NO_META_CALL' ?
      t('SIMULADO · NO HAY LLAMADA META · no es una inferencia real', 'SIMULATED · NO META CALL · not a real inference') : 'NEW_META_INFERENCE · muse-spark-1.3';
  }
  function renderSources() {
    $('live-documents').replaceChildren();
    const record = status.cases.find(x => x.case_id === $('live-case').value);
    for (const source of record.input.documents) {
      const div = document.createElement('section'); div.className = 'live-source';
      const heading = document.createElement('h3'); heading.textContent = source.source_id;
      const text = document.createElement('p'); text.lang = 'es'; text.textContent = source.text;
      div.append(heading, text); $('live-documents').append(div);
    }
  }
  async function refresh() {
    const response = await fetch('/api/live/status', {credentials:'same-origin',cache:'no-store'});
    if (!response.ok) throw new Error('OWNER_AUTH_OR_STATE_UNAVAILABLE');
    status = await response.json();
    renderOrigin();
    if (!$('live-case').options.length) for (const item of status.cases) {
      const option = document.createElement('option'); option.value = item.case_id; option.textContent = item.case_id; $('live-case').append(option);
    }
    $('live-send').disabled = busy || !status.enabled || !status.budget.enabled || status.budget.remaining === 0 || status.budget.uncertain_attempts > 0;
    return status;
  }
  const send = async (path, body) => {
    const response = await fetch(path, {method:'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json','X-PROOF-LIVE':'owner-action'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'LIVE_REQUEST_FAILED');
    return data;
  };
  $('live-case').addEventListener('change', renderSources);
  $('live-send').addEventListener('click', async () => {
    if (busy) return;
    busy = true; attempt = null; $('live-send').disabled = true;
    for (const id of ['live-summary','live-extraction','live-checks','live-result']) $(id).textContent = '';
    $('live-download').disabled = true; $('live-attempt').disabled = true;
    $('live-state').textContent = t('Solicitud en curso · no volver a enviar si se interrumpe', 'Request in progress · do not resend if interrupted');
    try {
      attempt = await send('/api/live/infer', {case_id:$('live-case').value,request_id:crypto.randomUUID()});
      $('live-state').textContent = attempt.status + ' · ' + attempt.baseline_status;
      $('live-summary').textContent = JSON.stringify({origin:attempt.origin, status:attempt.status, model_requested:attempt.request.model, model_reported:attempt.model_reported, execution:attempt.execution, usage:attempt.usage, cost:attempt.cost, cost_status:attempt.cost_status, baseline_status:attempt.baseline_status}, null, 2);
      $('live-extraction').textContent = attempt.extraction ? JSON.stringify(attempt.extraction,null,2) : t('No hay extracción evaluable. No se completan datos.', 'No evaluable extraction. No data is filled in.');
      $('live-checks').textContent = attempt.evaluation ? JSON.stringify(attempt.evaluation,null,2) : 'NOT_RUN';
      $('live-result').textContent = JSON.stringify(attempt, null, 2);
      $('live-download').disabled = !attempt.passport; $('live-attempt').disabled = false;
    } catch (error) {
      $('live-state').textContent = error.message;
      $('live-result').textContent = t('No hay decisión inventada ni replay de reemplazo. Revisar el registro persistente antes de volver a intentar.', 'No invented decision or replacement replay. Review the persistent ledger before attempting again.');
    } finally { busy = false; try { await refresh(); } catch (_) { $('live-send').disabled = true; } }
  });
  function download(value, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  $('live-download').addEventListener('click', () => {if(attempt?.passport) download(attempt.passport,'proof-live-passport-'+attempt.execution.id+'.json');});
  $('live-attempt').addEventListener('click', () => {if(attempt) download(attempt,'proof-live-attempt-'+attempt.execution.id+'.json');});
  $('live-enable').addEventListener('click', async () => {
    try { await send('/api/live/enable', {}); await refresh(); $('live-state').textContent=t('Activado por Owner. Ninguna solicitud enviada.', 'Enabled by Owner. No request sent.'); }
    catch(error) { $('live-state').textContent=error.message; }
  });
  $('live-disable').addEventListener('click', async () => {
    try { await send('/api/live/disable', {}); $('live-state').textContent = t('Desactivado. Una solicitud ya enviada no se cancela.', 'Disabled. An already sent request is not cancelled.'); await refresh(); }
    catch (error) {$('live-state').textContent = error.message;}
  });
  refresh().then(renderSources).catch(error => {$('live-state').textContent=error.message; $('live-send').disabled=true;});
})();

# License scope and attribution

The Owner expressly authorized MIT for original PROOF code in this release. Copyright holder/public project identity: @antz9619. Development used Codex assistance; the publication commit does not replace that authorship history with a claim of new authorship. The original project and scenarios were independently created for PROOF; no third-party application code was copied or imported.

## MIT-covered original code

- `proof_baseline.py`
- `proof_hybrid.py`
- `proof_meta_experiment.py`
- `proof_meta_first_call.py`
- `proof_theater.py`
- `proof_web.py`
- `scripts/check_proof_i18n_catalog.py`
- `scripts/check_proof_readiness.py`
- `tests/test_proof_baseline.py`
- `tests/test_proof_i18n.py`
- `tests/test_proof_meta_experiment.py`
- `tests/test_proof_meta_first_call.py`
- `tests/test_proof_meta_hybrid.py`
- `tests/test_proof_meta_schema.py`
- `tests/test_proof_meta_status_guard.py`
- `tests/test_proof_render.py`
- `tests/test_proof_theater.py`
- `tests/test_proof_web.py`
- `web/app.css`
- `web/app.js`
- `web/favicon.svg`
- `web/i18n-catalogs.js`
- `web/i18n.css`
- `web/i18n.js`
- `web/index.html`
- `web/theater.css`
- `web/theater.html`
- `web/theater.js`

## Exclusions

`web/proof-manrope.woff`, `web/proof-newsreader.woff`, and the notices/provenance in `docs/design-licenses/` remain SIL OFL 1.1, with their original copyrights unchanged. No Reserved Font Name is declared in the supplied notices. Original font copyright records remain in the subsets. MIT does not replace OFL.

Original synthetic fixture data, configuration and newly prepared jury documentation accompany the export for demonstration and reproducibility; no new blanket MIT grant is asserted over these non-code materials. No rights are granted over material of unverified ownership. Model weights, voices, AV05/AV06 videos, API service outputs other than the reviewed synthetic public projection, private API envelopes and third-party binaries are not redistributed. The approved synthetic public projection in `demo/decision_theater.json` is deliberately labelled historical or annotated and remains factually unchanged.

Meta Model API remains a separately governed service. No Meta SDK is bundled. The font tools, reference skill projects and audiovisual tools are not redistributed as code dependencies.

## Original LIVE extension code

MIT also covers proof_live.py, proof_live_transport.py, proof_live_web.py, proof_live_postgres.py, web/live.js, web/live.css, web/live-panel.html, scripts/certify_live_cloud.py, new LIVE tests and migrations/001_proof_live_postgres.sql. Optional psycopg/psycopg-binary is installed separately under its own upstream licenses (LGPL-3.0 for psycopg); no dependency binary is redistributed or relicensed here. Font OFL scopes remain unchanged.

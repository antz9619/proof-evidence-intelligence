# PROOF / EVIDENCE INTELLIGENCE

**A delivery status is not proof of a complete delivery.** PROOF separates what logistics documents say, what an AI extraction claims, and what deterministic software can justify. It exposes documentary discrepancies and missing evidence without inventing physical facts.

Built independently for the **Meta Global AI Developer Hackathon 2026 · Indie Developer track**. This is a separate, audited source export prepared for the jury. Synthetic examples only. Research prototype; no affiliation, technical approval or endorsement by Meta is implied.

- **Demo ES:** https://proof-evidence-intelligence.onrender.com/?lang=es
- **Demo EN:** https://proof-evidence-intelligence.onrender.com/?lang=en
- **Classic:** https://proof-evidence-intelligence.onrender.com/classic?lang=en
- **Public repository:** https://github.com/antz9619/proof-evidence-intelligence
- **3-minute demo video (EN):** https://youtu.be/opeMI5ywrtw
- **Original repository:** retained private; its Git history is not part of this export.

The offline core and AV06 derive from original source commit `4254737206d9bdb21513b81eeb1e65964f0fe7bb`. The independent public export starts at root commit `d3308c9273b7c8b767fa2496d0e8e5f8393ef54e`, without private Git history. The deployed Owner LIVE extension is application revision `69771b455a0656f603491f045626baea030d7bc3`; later documentation commits do not imply a new deploy. [Provenance](docs/PROVENANCE.md) · [Verification scopes](docs/VERIFICATION.md).

## How it works

```text
Synthetic documents
    → Muse Spark 1.3 textual interpretation (historical recorded inference)
    → required-source, citation and narrow semantic-status checks
    → deterministic Python quantities and constraints, only if admissible
    → review decision + original citations + downloadable Decision Passport
```

Muse Spark was called through **Meta Model API** to extract structured facts and source quotes. PROOF checks admissibility before using those facts. The model does not decide inventory, verify physical delivery or authorize closure.

The public demo **replays recorded extractions offline** and runs the existing Python controls again. Clicking evaluate, revealing a Challenge result or downloading a Passport does **not** call Meta. No key, database or account is needed to run the offline demo. The separate Owner-only LIVE path accepts a server Meta key only under explicit protected LIVE configuration; offline mode rejects that key. Deployment never sends an inference automatically.

### THE PROOF MOMENT

A historical extraction promoted the original Spanish `ENTREGADO` into `ENTREGA_COMPLETA`. The quote exists, but it does not support that stronger claim. The real semantic guard rejects the extraction and the baseline remains `NOT_RUN`. The interface emphasizes this actual rejection; animation does not manufacture it. This is a bounded status check, not a general semantic or physical verifier.

## Three experiences, different cases

| Experience | What to inspect |
|---|---|
| **Theater** (`/`) | Three recorded historical extractions, their provenance, fields, quotes, guards and Passport; one separately labelled synthetic annotation |
| **Challenge** (entry button on `/`) | Read documents, choose a verdict, then reveal the same offline Python evaluation; the vote is not sent to the engine |
| **Classic** (`/classic`) | Three synthetic demonstration scenarios, including **10 expected / 8 documented / difference 2**, with documentary conformity still unconfirmed |

**Theater PM01-02 is a different case from Classic A:** its **6 / 6 / 0** supports documentary conformity only. These views and results must not be interchanged. AV06 shows Theater, not a recording of Classic A.

ES/EN switches presentation only. Spanish original documents and exact quotes stay byte-preserved in the source data. English explanatory presentations are explicitly informative, **not exact quotations**, and never feed the engine. Source navigation opens the original quote. The JSON download retains original data and codes.

The Decision Passport records sources, quotes, validation, decision and reproducibility information. Hashes establish integrity, not authenticity. No result permits automatic closure, moves stock or proves a physical delivery.

## Run the offline demo locally — standard library only

Tested with **Python 3.12.14** (also recorded in `.python-version`). The application uses the Python standard library and local HTML/CSS/JavaScript/fonts. No Node, database, model weights, TTS or API credentials are required.

```sh
git clone https://github.com/antz9619/proof-evidence-intelligence.git
cd proof-evidence-intelligence
python3 -B proof_web.py --port 8765
```

For a source ZIP, extract it and run the same Python command from its directory. Open `http://127.0.0.1:8765/?lang=en` on the computer running Python; Spanish uses `?lang=es`. Classic is `/classic?lang=es`. The default server binds to loopback. Production hosting configuration is documented in [architecture and execution](docs/ARCHITECTURE.md); these instructions do not authorize a deploy.

For an offline deterministic example:

```sh
python3 -B proof_baseline.py scenarios/PROOF-01.json
python3 -B -m unittest discover -s tests -v
```

The baseline prints a proposal and its evidence; it executes no operational action. Unit tests use local/mocked transport. The included `scripts/check_proof_i18n_catalog.py` and `scripts/check_proof_readiness.py` use standard Python tooling. The separate browser certification uses optional Playwright/Chromium outside the runtime.

## Results and limits

| Case | Historical model result | Current offline control behavior |
|---|---|---|
| PM01-03 | **FAIL** — unsupported status promotion | Semantic guard rejects; baseline `NOT_RUN`; no calculated difference |
| PM01-05 | **FAIL** — required document omitted | Source-set check rejects before guard/baseline; no invented replacement |
| PM01-02 | **PASS for this case only** | Admissible literal status and documentary quantities **6 / 6 / 0**; no physical confirmation |
| PM01-07 | **Not a model inference** — synthetic annotation | Foreign receipt excluded; investigated shipment's documented quantity/difference remain unknown |

Two historical failures remain failures. A successful HTTP response or valid JSON is not proof of correct extraction. This small sample does not demonstrate model reliability or generalization. Unknown is not zero; a documentary difference is not evidence of physical loss. Identity and signatures declared in synthetic documents are not authenticated.

The strict experimental verifier is **not a deployed public-interface capability**. New connected evaluations require separate explicit authorization and verified cost limits.

### Executed evidence

- The certified Impeccable base has a recorded **177-test** suite plus bilingual browser, motion, citation and download evidence: [verification](docs/VERIFICATION.md).
- The initial standalone export passed **177/177 tests**, with external DNS/connect prohibited. The LIVE integration application passed **220/220 tests**, including disposable PostgreSQL TLS checks. These are scoped software checks, separate from model evaluation.
- [Historical Meta results](docs/RESULTS.md), [evaluation boundaries](docs/ARCHITECTURE.md) and [Theater provenance](docs/PROVENANCE.md) summarize the unchanged historical outcomes, separately from current software checks.
- [Verification](docs/VERIFICATION.md) distinguishes local tests, actual Render staging checks, Owner-provided browser/video evidence and remaining submission checks. Internal historical planning records are deliberately not redistributed.

## Authorship, attribution and licensing

Repository Owner: **[@antz9619](https://github.com/antz9619)**. The new commit records publication/export provenance, not a claim that the code was first authored on its commit date. PROOF application, synthetic scenarios and evaluation design were developed independently with AI-assisted coding. No production code, customer data or credentials from other projects were reused.

The visual work studied principles from [Emil Kowalski's skills](https://github.com/emilkowalski/skills) and [Impeccable](https://github.com/pbakaus/impeccable). This attribution is not a claim that their code or branding is included, nor an endorsement.

Local **Newsreader** and **Manrope** font subsets are SIL OFL 1.1, with complete notices and provenance in [docs/design-licenses](docs/design-licenses/SOURCES.md). Their licenses remain unchanged. Meta Model API is an external service governed by its own terms, not an open-source component bundled with PROOF. AV06 reuses synthetic narration from Supertonic-3; its model/voice licensing is separate from the application code and retained with the audiovisual materials.

**Original code in this export is MIT licensed**, as expressly authorized by the Owner. [LICENSE](LICENSE) and [license scope](LICENSE-SCOPE.md) list the covered paths. Font software remains SIL OFL 1.1. No license is granted over third-party services, model weights, voices or audiovisual assets; those assets are not included in this code repository.

## Resumen en español

PROOF hace visible la distancia entre un estado logístico, una interpretación de IA y lo que la evidencia documental permite afirmar. Muse Spark aporta interpretación textual; las fuentes, las citas, el guard y el motor determinístico limitan las conclusiones. La demo bilingüe reproduce extracciones históricas sin una inferencia nueva: conserva dos FAIL y un PASS de caso, más una anotación sintética separada.

Theater muestra el caso histórico **6/6/0**; Classic A muestra otro escenario **10/8/2**. No representan el mismo expediente. Las citas originales siguen en español; las traducciones son informativas. El Passport permite inspeccionar y descargar trazabilidad, sin autenticar una entrega física ni autorizar cierre automático.

El repositorio y el video EN ya están publicados. Una primera inferencia real separada pasó los seis controles de `PM01-02`; la campaña quedó desactivada y con su único intento consumido. La demo pública y AV06 siguen siendo offline/históricos. El envío del formulario todavía no está confirmado.

## Jury videos

**[Watch AV06 EN — 3-minute demo](https://youtu.be/opeMI5ywrtw).** The Owner provided evidence of signed-out incognito playback, a watch-player duration of 3:00 and playback through the end. AV06 EN M1 and ES M3 originals remain preserved outside Git (180-second H.264/AAC, 1080p, SRT/VTT); only EN hosting is confirmed here. Neither video is relabeled as the later real LIVE execution. [Video identity and verification limits](docs/VIDEOS.md).


## Owner-only LIVE integration

This revision adds an optional, separately authenticated Owner panel at `/live`. The public historical/offline demo does not require Neon or Meta and remains available if either provider is down. LIVE starts disarmed and requires an authenticated Owner action; deployment never sends a model request. Only approved synthetic PM01-02 is allowed in cloud.

Optional cloud installation: `pip install -r requirements-live.txt`. Render start: `python -B proof_web.py --mode render`. PostgreSQL requires TLS certificate and hostname verification. Server-only secrets and an explicitly provisioned campaign are required; no secret belongs in browser code or Git. The initial real campaign permits one attempt with a US$0.05 accounting reservation, not a guaranteed provider billing cap. No automatic retries, fallback, reservation refund or stale-attempt expiry.

A separately authorized **real `muse-spark-1.3` Standard inference** completed from Render on 4 November 2026: `PM01-02`, HTTP 200, six checks PASS, documentary difference 0, no physical verification or automatic closure. Its Passport matches the record persisted in Neon and independently revalidates offline. The campaign is disabled, with **1/1 attempt consumed**. This single-case result does not establish general reliability and does not change historical FAILs. [Real-call result](docs/LIVE-RESULT-01.md).

Simulated staging is marked `SIMULATED_NO_META_CALL`; the actual call is `NEW_META_INFERENCE`; historical replay remains separate. Further requests require a new explicit Owner decision, without resetting the completed campaign. See [LIVE deployment and rollback](docs/LIVE-DEPLOYMENT.md).

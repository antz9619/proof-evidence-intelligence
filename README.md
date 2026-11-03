# PROOF / EVIDENCE INTELLIGENCE

**A delivery status is not proof of a complete delivery.** PROOF separates what logistics documents say, what an AI extraction claims, and what deterministic software can justify. It exposes documentary discrepancies and missing evidence without inventing physical facts.

Built independently for the **Meta Global AI Developer Hackathon 2026 · Indie Developer track**. This is a separate, audited source export prepared for the jury. Synthetic examples only. Research prototype; no affiliation, technical approval or endorsement by Meta is implied.

- **Demo ES:** https://proof-punta-de-lanza.onrender.com/?lang=es
- **Demo EN:** https://proof-punta-de-lanza.onrender.com/?lang=en
- **Classic:** https://proof-punta-de-lanza.onrender.com/classic?lang=en
- **Public repository name proposed:** `antz9619/proof-evidence-intelligence` — not created or published yet.
- **Original repository:** retained private; its Git history is not part of this export.

The deployed application and AV06 derive from original commit `4254737206d9bdb21513b81eeb1e65964f0fe7bb`. The public source export has its own new root commit; **it is not that original commit and does not inherit its history**. Exported source/assets/fixtures are byte-identical to their approved blobs. [Provenance and inclusion](docs/PROVENANCE.md). Public HTTPS smoke checks from the preparation environment are blocked by its network policy; the links above are demo addresses, not a fresh uptime certification.

## How it works

```text
Synthetic documents
    → Muse Spark 1.3 textual interpretation (historical recorded inference)
    → required-source, citation and narrow semantic-status checks
    → deterministic Python quantities and constraints, only if admissible
    → review decision + original citations + downloadable Decision Passport
```

Muse Spark was called through **Meta Model API** to extract structured facts and source quotes. PROOF checks admissibility before using those facts. The model does not decide inventory, verify physical delivery or authorize closure.

The public demo **replays recorded extractions offline** and runs the existing Python controls again. Clicking evaluate, revealing a Challenge result or downloading a Passport does **not** call Meta. The public Render mode rejects a configured Meta API key; no key is needed to run the demo.

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

## Run locally — no runtime dependencies

Tested with **Python 3.12.14** (also recorded in `.python-version`). The application uses the Python standard library and local HTML/CSS/JavaScript/fonts. No Node, database, model weights, TTS or API credentials are required.

```sh
git clone <OWNER_APPROVED_PUBLIC_REPOSITORY_URL>
cd <CLONE_DIRECTORY>
python3 -B proof_web.py --port 8765
```

The new remote does not exist yet; clone commands become usable only after Owner-authorized publication. For the prepared ZIP, extract it and run the same Python command from its directory. Open `http://127.0.0.1:8765/?lang=en` on the computer running Python; Spanish uses `?lang=es`. Classic is `/classic?lang=es`. The default server binds to loopback. Production hosting configuration is documented in [architecture and execution](docs/ARCHITECTURE.md); these instructions do not authorize a deploy.

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
- This exact export passed **177/177 tests**, with external DNS/connect prohibited in the test process. This is software verification, not new model evaluation.
- [Historical Meta results](docs/RESULTS.md), [evaluation boundaries](docs/ARCHITECTURE.md) and [Theater provenance](docs/PROVENANCE.md) summarize the unchanged historical outcomes, separately from current software checks.
- [Export verification](docs/VERIFICATION.md) distinguishes executed local checks from public-network and video-hosting blockers. Internal historical planning records are deliberately not redistributed.

## Authorship, attribution and licensing

Repository Owner: **[@antz9619](https://github.com/antz9619)**. The new commit records publication/export provenance, not a claim that the code was first authored on its commit date. PROOF application, synthetic scenarios and evaluation design were developed independently with AI-assisted coding. No production code, customer data or credentials from other projects were reused.

The visual work studied principles from [Emil Kowalski's skills](https://github.com/emilkowalski/skills) and [Impeccable](https://github.com/pbakaus/impeccable). This attribution is not a claim that their code or branding is included, nor an endorsement.

Local **Newsreader** and **Manrope** font subsets are SIL OFL 1.1, with complete notices and provenance in [docs/design-licenses](docs/design-licenses/SOURCES.md). Their licenses remain unchanged. Meta Model API is an external service governed by its own terms, not an open-source component bundled with PROOF. AV06 reuses synthetic narration from Supertonic-3; its model/voice licensing is separate from the application code and retained with the audiovisual materials.

**Original code in this export is MIT licensed**, as expressly authorized by the Owner. [LICENSE](LICENSE) and [license scope](LICENSE-SCOPE.md) list the covered paths. Font software remains SIL OFL 1.1. No license is granted over third-party services, model weights, voices or audiovisual assets; those assets are not included in this code repository.

## Resumen en español

PROOF hace visible la distancia entre un estado logístico, una interpretación de IA y lo que la evidencia documental permite afirmar. Muse Spark aporta interpretación textual; las fuentes, las citas, el guard y el motor determinístico limitan las conclusiones. La demo bilingüe reproduce extracciones históricas sin una inferencia nueva: conserva dos FAIL y un PASS de caso, más una anotación sintética separada.

Theater muestra el caso histórico **6/6/0**; Classic A muestra otro escenario **10/8/2**. No representan el mismo expediente. Las citas originales siguen en español; las traducciones son informativas. El Passport permite inspeccionar y descargar trazabilidad, sin autenticar una entrega física ni autorizar cierre automático.

**STOP: no publicación del repositorio, videos ni envío del formulario hasta la decisión expresa del Owner.**

## Jury videos

AV06 EN M1 and ES M3 are preserved outside this source export: 180-second H.264/AAC 1080p candidates with SRT/VTT subtitles. The observed submission form requires a public GitHub URL and a 3-minute demo link. No video is published yet; allowed hosts and public/unlisted access requirements remain unconfirmed. [Video identity and limits](docs/VIDEOS.md).

# Verification — dated scopes

The initial standalone export at root d3308c9273b7c8b767fa2496d0e8e5f8393ef54e passed **177/177 unit tests** (zero failures/errors/skips) and **20 local ES/EN browser checks**: two home pages, eight Theater evaluations, six Classic evaluations and four Challenges; fourteen downloads, original-source navigation and English informative presentations. No JavaScript/console errors or unexpected external requests were observed. The test process prohibited non-loopback connections, with no blocked attempts. The application ran without META_MODEL_API_KEY and without private artifacts. The executable code and fixtures in this export are from original commit 4254737206d9bdb21513b81eeb1e65964f0fe7bb. Source hashes and the exact inclusion list are in EXPORT-MANIFEST.json. The private history and its personal metadata are excluded.

Direct public HTTPS verification from the agent preparation environment remains limited by networking/tool access to onrender.com. This is an access limitation, not evidence that PROOF is down. Local browser success is not public HTTPS success.

The initial export preparation made no new inference, deploy or publication. Subsequent authorized publication, deployment and real inference are recorded below; this historical initial scope is not the current release status. All final PASS/FAIL claims name the executed scope. No new human listening panel, model evaluation or broader product redesign is claimed.


## LIVE integration application — 4 November 2026

Application revision69771b455a0656f603491f045626baea030d7bc3 passed220/220 tests, zero failures/errors/skips (177 original,29 R1,14 PostgreSQL). The optional PostgreSQL checks used an explicitly disposable TLS database. A plain offline test run skips those optional integration checks if PROOF_TEST_POSTGRES_URL is absent; never point their fixture-cleanup code at a real/shared database.

Actual Render staging certification passed twice on separate deploy instances: client TLS verification to dedicated Neon, anonymous HTTP401, authenticated Owner panel/status, authenticated enable without sending, LIVE OFF rejection, two simultaneous simulated submissions with one reservation/evaluation, evaluated Passport and offline ES/EN/Classic/catalog/health HTTP smoke. The second instance found the previous durable attempt. No Meta calls were made by staging certification. Client TLS was true while backend pg_stat_ssl reported false; the latter does not measure the client-to-provider TLS segment.

A separately authorized single real Render request subsequently returned HTTP200 with muse-spark-1.3, six controls PASS and a computed documentary result. Uploaded Passport matches persisted Neon JSON; independent offline revalidation matches. Campaign disabled, quota1/1 consumed. See [LIVE result](LIVE-RESULT-01.md). This is one synthetic case, not a general model reliability claim.

Owner screenshot establishes the deployed Owner panel loads on a cellphone and displays PM01-02; it does not by itself certify all public offline paths from an external browser. Owner YouTube evidence establishes signed-out incognito playback, subtitles, displayed3:00 duration and completion confirmation. See [videos](VIDEOS.md). Agent full hosted playback and all-region checks were not executed. Form submission remains unconfirmed.

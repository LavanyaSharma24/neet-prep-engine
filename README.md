# NEET Prep Engine

**Live:** https://neet-prep-engine.web.app

The cloud backend runs on a free tier that sleeps when idle, so the first
question that needs it after a quiet period can be slow or time out. The
Gemini free tier behind it is also intermittently slow, so a cloud answer can
fail or take 15-25 seconds even when the service is awake. Answers from the
built-in item bank are unaffected.

An offline-first exam-prep PWA for NEET Biology and Chemistry, built around
one rule: never guess. A question is answered from a local item bank of
NCERT-sourced answers, which works with no internet after the first load. If
nothing in the bank matches well enough, the app either gets an answer that
two independent AI models agree on (clearly labeled as AI-generated), or it
refuses and flags the question for review.

Built solo, using Claude Code alongside manual review and testing. The commit
history shows the debugging trail, not just the finished result.

## Features

- **Offline Q&A from the item bank.** 39 items (9 Biology, 30 Chemistry,
  mostly Chemical Bonding). Matching is deterministic and typo-tolerant, with
  no model and no network involved. Answers are labeled `VERIFIED` and show
  their NCERT source.
- **Refusal and flagging instead of guessing.** A match below the confidence
  threshold (0.55) is never shown as an answer. The question is logged for
  review and the app says it has no verified answer.
- **Installable PWA.** A service worker caches the app shell and the item
  bank, so it can be installed and used offline.
- **On-device "Simplify this explanation".** Optional, shown under verified
  answers only. Runs a small text model (LaMini-Flan-T5, roughly 250 MB,
  downloaded on first use) in the browser with `transformers.js`. Nothing is
  sent to a server, and the original answer stays on screen above the
  simplified one.
- **Cross-checked cloud escalation.** For questions outside the item bank, two
  Gemini models answer independently and a judge step checks that they agree.
  Only then is the answer shown, labeled `AI-GENERATED — PENDING
  VERIFICATION`. Answers are plain text and short (the prompt asks for under
  about 120 words and no markdown). Escalated answers are cached on the
  device so a repeat question works offline. The server also keeps agreed
  answers and serves a repeat question from its stored copy without calling
  Gemini again.
- **Offline flag queue and review queue (phase 1).** Questions that end
  without an answer are queued on the device (IndexedDB) and synced to
  `POST /flags` when online. The server stores them in Postgres (Neon) with a
  reason (`model_refused`, `offline` or `api_error`) and de-duplicates them by
  normalized question, so many students asking the same thing becomes one
  row with an `ask_count`. The reviewer tool and the path from an approved
  question into `item_bank/` are not built yet (planned).
- **Diagrams on 3 items**, rendered inline next to the verified answer.

## How it works

| Tier | Where it runs | What it does |
| --- | --- | --- |
| 0 | Browser, offline | Scores the typed question against every item (character-sequence similarity plus fuzzy keyword overlap). At or above 0.55 it answers from the bank; below that it refuses and flags. |
| 1 | Browser, on-device model | Rephrases an already-verified answer in simpler words. The prompt forbids adding facts, and the output is labeled as on-device AI. |
| 2 | `api/` on Render | Calls `gemini-3.5-flash-lite` (primary) and `gemini-flash-lite-latest` (secondary) in parallel, then asks the secondary model to judge whether the two answers agree. Agreement serves the primary answer. Disagreement serves nothing and stores both answers for review, in separate `primary_answer` and `secondary_answer` columns. If the judge call itself fails, that counts as disagreement. Each Gemini call times out after 8 s; a timed-out call is retried once, immediately (at most 2 attempts). A transient 503 is retried twice (1 s, then 2 s); a 429 quota error is not retried. The whole cross-check has a 25 s deadline, under the web client's 30 s abort. |

Tier 2 behavior is covered by unit tests with the Gemini client mocked. Seen
live from the deployed API: an agreed answer, a model refusal, and one
disagreement, on a question about net ATP per glucose. The two models gave
different headline numbers (38 and 36-38), so nothing was shown and both
answers were stored for review. A successful escalation displayed in the
browser UI has not yet been confirmed.

`docs/architecture.md` has the full design, including the planned human
review step (Tier 3) and the decision log. The two Tier 2 models are from the
same family because the free-tier key has no quota for a Pro-class model;
that trade-off is recorded there.

## Screenshots

Diagrams as rendered in the running web app:

| Item | Diagram |
| --- | --- |
| `chem-0025` — pi (π) bond | ![Pi bond diagram](docs/screenshots/diagram-pi-bond.jpg) |
| `chem-0015` — ethene sp² hybridization | ![Ethene sp2 hybridization diagram](docs/screenshots/diagram-ethene-hybridization.jpg) |
| `bio-0001` — mitochondrion | ![Mitochondrion diagram](docs/screenshots/diagram-mitochondria.jpg) |

## Tests

| Suite | Tests | Covers | Command |
| --- | --- | --- | --- |
| CLI (`unittest`) | 10 | Item bank loading, clear match, typo near-miss, unrelated question refused and logged, pasted MCQ options, diagram note | `python -m unittest discover -s apps/prototype-cli/tests -p "test_*.py" -v` (from the repo root) |
| Web (`vitest`) | 12 | MCQ-option stripping in the TypeScript matcher, the Simplify prompt, and the flag queue: enqueue de-duplication, flush deletes only accepted ids, a failed flush keeps everything, batches of 50, no-op when offline | `npm test` (in `web/`) |
| API (`pytest`) | 49, plus 7 Postgres-only (56 total) | 503 retry, no retry on 429, refusal handling, judge failing closed, agree and disagree outcomes, error priority, per-call timeout, deadline and timeout-retry handling, question normalization, upsert and de-duplication, stored agreed answer served without Gemini, `/flags` idempotency, batch limit and 422 validation, rate limit, database failure handling, `/healthz` backend | `pytest` (in `api/`, after `pip install -r requirements.txt -r requirements-dev.txt`) |

The API tests mock the Gemini client, so they need no API key and make no
network calls. They run against SQLite; the 7 Postgres-only tests are skipped
unless `TEST_DATABASE_URL` is set. To run them, point `TEST_DATABASE_URL` at
a throwaway database or a Neon branch, never the production one.
`npm run typecheck` in `web/` runs the TypeScript compiler without emitting.

## Run locally

Requirements differ per component:

- **CLI** (`apps/prototype-cli/`): Python 3.9+, standard library only.
- **Web** (`web/`): Node.js 20+ and npm (the tests have been run on Node 22
  and 26). Python is also needed once, to build the item bank JSON.
- **API** (`api/`): Python 3.10+ (tested on 3.13; the Docker image uses
  3.12), the packages in `api/requirements.txt`, and a Gemini API key.

### CLI

```
cd apps/prototype-cli
python main.py
```

Type a NEET Biology or Chemistry question at the `>` prompt; `quit` or `exit`
stops it. A confident match prints `[VERIFIED]` with the answer, confidence
and source. Anything else prints `[REFUSED]` and appends the question to
`apps/prototype-cli/flagged_questions.jsonl` (git-ignored). The CLI is Tier 0
only: no model, no network, no diagrams.

### Web

```
python scripts/build_item_bank_json.py
cd web
npm install
npm run dev
```

The first command builds `web/public/item_bank.json` and copies the diagram
SVGs from `item_bank/`. Both are git-ignored build artifacts, so re-run it
whenever a `.jsonl` file changes. The dev server opens on
http://localhost:5173.

To try escalation locally, run the API (below) and copy `web/.env.example` to
`web/.env.local`, which points `VITE_API_BASE_URL` at
`http://localhost:8000`. If the backend cannot be reached, low-confidence
questions fall back to the "NO VERIFIED ANSWER — flagged" message.

### API

Get a Gemini API key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Then, on
Windows:

```
cd api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux:

```
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` in `api/.env`. That file is git-ignored and must never
be committed. Then:

```
uvicorn main:app --reload --port 8000
```

`DATABASE_URL` is optional locally. Unset, flagged questions go to a SQLite
file (`api/flagged_items.db`); set, they go to Postgres. Check the server
with `curl http://localhost:8000/healthz`, which returns
`{"status":"ok","db":"sqlite"}` (or `"postgres"`).

## Deploy

### API on Render

`render.yaml` at the repo root is a Render Blueprint defining one Docker web
service (`neet-prep-api`, free plan, Singapore region, built from
`api/Dockerfile`).

1. In the Render dashboard choose **New → Blueprint** and connect this repo.
2. Enter `GEMINI_API_KEY` when prompted. It is marked `sync: false`, so the
   key lives only in the Render dashboard and is never written to the YAML
   or to git.
3. Apply. Render builds the image and assigns the service URL.
4. In the service's environment settings, add `DATABASE_URL` with a Neon
   Postgres connection string. `render.yaml` does not declare it, so it is
   set manually in the dashboard and never written to the YAML or to git.

The service reads these environment variables:

- `GEMINI_API_KEY`: entered in the dashboard.
- `GEMINI_MODEL`, `GEMINI_SECONDARY_MODEL`: the two Tier 2 models, pinned in
  `render.yaml`.
- `GEMINI_CALL_TIMEOUT_SECONDS` (8) and `GEMINI_CROSS_CHECK_DEADLINE_SECONDS`
  (25): set in `render.yaml`.
- `ALLOWED_ORIGINS`: the live web app, set in `render.yaml`.
- `DATABASE_URL`: entered in the dashboard (see step 4).

With `DATABASE_URL` set, the flagged-question queue lives in Neon and
survives restarts and deploys. Without it, the API falls back to SQLite on
Render's ephemeral disk, which resets on every restart or deploy.

### Web on Firebase Hosting

`web/.firebaserc` already points at the `neet-prep-engine` Firebase project.
The API base URL is read at build time, so `web/.env.local` must set
`VITE_API_BASE_URL` to the Render service URL before building; otherwise the
build calls the wrong server.

```
python scripts/build_item_bank_json.py
cd web
npm run build
firebase deploy --only hosting
```

This needs `firebase login` done once. `npx firebase-tools` works in place
of a global `firebase-tools` install (for example
`npx firebase-tools deploy --only hosting`). `web/firebase.json` handles the
SPA rewrite and sets `no-cache` on `sw.js` and `item_bank.json` so updates
are picked up. Even so, a stale service worker can serve the previous page
for one visit after a deploy.

## Repository layout

- `item_bank/`: `biology/` and `chemistry/` hold the items as JSONL (9 and
  30). Also `schema.json` for one item, `diagrams/` (3 SVGs) and
  `misconceptions/taxonomy.json` (an empty skeleton for now).
- `apps/prototype-cli/`: `retrieval.py` (matching), `refusal.py`
  (answer-or-refuse decision and flag log), `main.py` (terminal loop),
  `tests/`. This is the reference logic; `web/src/retrieval.ts` and
  `refusal.ts` are a TypeScript port of these two files with the same
  behavior.
- `web/`: React + TypeScript (Vite) PWA. Includes the service worker, the
  on-device Simplify feature (`src/tier1.ts`, `src/Simplify.tsx`), the
  escalation client (`src/api.ts`), the device-local answer cache
  (`src/answerCache.ts`) and the offline flag queue (`src/flagQueue.ts`).
- `api/`: FastAPI backend with `POST /escalate`, `POST /flags` and
  `GET /healthz`. `gemini_client.py` runs the two-model cross-check and judge
  step. `db.py` supports Postgres and SQLite, with the `flagged_questions`
  and `flag_receipts` tables; the old `flagged_items` table is no longer
  written.
- `scripts/`: `build_item_bank_json.py` (builds the web item bank),
  `generate_placeholder_icons.py` (one-off generator for the placeholder PWA
  icons) and `tier2_live_check.py` (a manual live check of the deployed API:
  warm-up, CORS, validation, and up to 3 escalation questions; it costs
  Gemini quota, so run it sparingly).
- `docs/`: `PRD.md`, `architecture.md`, and `screenshots/`.
- `render.yaml`: Render Blueprint for `api/`.

## Known limitations

- **Render free tier.** The service sleeps when idle and takes roughly 50
  seconds to cold start (Render's own figure). The web client gives up on an
  escalation after 30 seconds, so the first one after idle can come back as
  "flagged"; try again once the service has woken up.
- **Gemini free tier.** Calls sometimes stall until the 8 s timeout or
  return 503 "high demand" errors. In live testing many escalations failed
  fast with a 502 or took 15-25 seconds, and one took 25.8 seconds. Quota is
  also limited. A failure shows the flagged message, never an answer.
- **Same-family models.** Both Tier 2 models are Gemini, so they can agree on
  a wrong answer. Example from testing: net ATP per glucose, where NCERT
  gives 38 but newer sources give about 30-32.
- **Disagreement and judge failure look the same.** Both are stored as
  `disagreed`; the table cannot tell them apart yet.
- **One card for four situations.** The UI shows the same "NO VERIFIED
  ANSWER — flagged" card for an out-of-syllabus question, a model that is not
  confident, models that disagreed, and a service failure. Out-of-syllabus
  questions (for example "how did the paralympics start?") are queued for
  review with reason `model_refused`. Distinct states are planned.
- **Review pipeline is partial.** Questions are stored, counted and
  de-duplicated, but only on an exact match after normalization; clustering
  of near-duplicates is not built. There is no reviewer tool yet, so nothing
  is promoted into the item bank, automatically or otherwise. By design,
  nothing ever will be without a human check.
- **Abuse and privacy.** The queue stores the question text the student
  typed, with no user identifiers, and free-text questions can contain
  anything. `/flags` has only a best-effort per-IP rate limit, held in memory
  on one instance, and it reads the first `X-Forwarded-For` entry, which a
  client can spoof.
- **Free-tier hosting.** Neon's free tier and Render's free tier both have
  cold starts and usage limits.
- **On-device model cache.** When the service worker updates, its cleanup
  step deletes every cache except the app's own, which includes the
  downloaded `transformers.js` model. Simplify then has to download the model
  again.
- **Small item bank.** 39 items, and 4 of the 9 Biology items are still
  marked `verified_by: pending` in the data even though the app labels every
  item bank match `VERIFIED`.

## Roadmap

- Distinct UI states for out-of-syllabus, not confident, disagreed and
  service failure
- A reviewer tool with approve, edit and reject, plus an export script that
  produces schema-valid `item_bank/` entries
- Clustering of near-duplicate flagged questions
- A third Tier 2 model with 2-of-3 agreement, still failing closed on
  contradiction
- A bigger item bank across more chapters
- "Explain further" on answers
- Voice input and output using WASM Whisper and the Web Speech API (not
  shipped; the app is text-only today)
- Spaced repetition
- Testing on low-RAM phones

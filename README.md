# NEET Prep Engine — v0 prototype

v0 scope only (see `docs/PRD.md` §8 "Phased scope"): text-only, NEET Biology,
no voice, no diagrams, no escalation, no cloud calls. A typed question is
matched against a small verified item bank using keyword/fuzzy text matching
(Python standard library only — no LLM, no network). A match above the
confidence threshold is answered and labeled `VERIFIED`; anything else is
refused and logged for later review rather than guessed.

See `docs/architecture.md` for how this fits the larger Tier 0/1/2/3 design —
v0 is just the Tier 0 deterministic core (item bank + matching), running
alone.

## Requirements

Python 3.9+. No third-party packages (see `requirements.txt`).

## Run the prototype

```
cd apps/prototype-cli
python main.py
```

Type a NEET Biology question at the `>` prompt. Type `quit` or `exit` to
stop.

- A confident match prints `[VERIFIED]` with the answer, confidence score,
  and source.
- Anything else prints `[REFUSED]` and appends the question to
  `apps/prototype-cli/flagged_questions.jsonl` (git-ignored local file) for
  human review later — it never guesses.

## Run the tests

```
python -m unittest discover -s apps/prototype-cli/tests -p "test_*.py" -v
```

Covers: a clear match, a near-miss (typos) that should still match, and a
clearly unrelated question that should refuse.

## Layout

- `item_bank/` — `schema.json` for one question item, `misconceptions/taxonomy.json`
  (empty skeleton, populated separately), `biology/neet_bio_items.jsonl` with
  5 example items, and `chemistry/*.jsonl` (seeded separately; picked up
  automatically once present).
- `apps/prototype-cli/` — `retrieval.py` (matching), `refusal.py`
  (answer/refuse decision + flag log), `main.py` (terminal loop), `tests/`.
  Reference logic — the web app in `web/` is a TypeScript port of these two
  files, same behavior.
- `scripts/build_item_bank_json.py` — builds `web/public/item_bank.json`
  from `item_bank/*/*.jsonl`. `scripts/generate_placeholder_icons.py` —
  one-off PWA icon generator (stdlib only), already run; replace
  `web/public/icons/*.png` with real artwork before a real launch.
- `web/` — React + TypeScript (Vite) PWA. Installable, works offline after
  first load (service worker caches the app shell + `item_bank.json`).
- `api/` — FastAPI escalation backend (`POST /escalate`), calls Gemini
  Flash-Lite, logs every escalation to a local SQLite `flagged_items` table
  (Tier 3 human review queue per `docs/architecture.md`).
- `knowledge_graph/`, `data_pipeline/`, `models/` — placeholders for later
  stages (v1+); empty for now.
- `docs/` — `PRD.md`, `architecture.md`.

## Web app + API (deployable, PWA + Cloud Run)

A second, deployable v0 surface: the same Tier 0 matching/refusal logic as
`apps/prototype-cli` (`web/src/retrieval.ts` / `refusal.ts` are direct
TypeScript ports of `retrieval.py` / `refusal.py` — verified to produce
identical confidence scores on the same inputs), running as an
installable, offline-capable PWA. `api/` is an optional Tier 2-style
escalation backend: the web app calls it **only** when local retrieval
confidence is below threshold **and** the browser reports it's online
(`navigator.onLine`); offline, it refuses and flags locally instead, per
`docs/architecture.md` §4. Every escalation — successful or not attempted
— either gets answered-and-logged, or the client logs the refusal locally
(`localStorage`); nothing is silently dropped.

### Rebuild the item bank JSON

```
python scripts/build_item_bank_json.py
```

Globs `item_bank/biology/*.jsonl` and `item_bank/chemistry/*.jsonl`, tags
each item with a derived `subject` field (from its source folder — not
part of `schema.json` itself), and writes `web/public/item_bank.json`.
Re-run this any time a source `.jsonl` file changes — the output is a
build artifact (git-ignored), not hand-edited. Chemistry items are picked
up automatically once `item_bank/chemistry/*.jsonl` exists; no code
changes needed in `retrieval.ts`/`refusal.ts`, which are subject-agnostic.

### Run web/ locally

```
cd web
npm install
npm run dev
```

Opens on http://localhost:5173. To test escalation, also run `api/` (below)
and copy `web/.env.example` to `web/.env.local` with `VITE_API_BASE_URL`
pointing at it. Without a running backend (or offline), low-confidence
questions fall back to the local "NO VERIFIED ANSWER — flagged" message —
no network call is attempted when `navigator.onLine` is false.

### API key setup

`api/` needs a Gemini API key to serve `/escalate`. To get one:

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and
   sign in with a Google account.
2. Click "Create API key" (choose or create a GCP project if prompted).
3. Copy the key.
4. In `api/`, copy `.env.example` to `.env` (git-ignored, never committed —
   see `api/.gitignore` and the root `.gitignore`) and set
   `GEMINI_API_KEY=<your key>`.

Some newly-issued keys are restricted from older pinned model IDs (you may
see `404 ... no longer available to new users` for
`gemini-2.5-flash-lite`/`gemini-2.5-flash`). If that happens, also set
`GEMINI_MODEL=gemini-flash-latest` in `.env` to use the current alias
instead of pinning a specific dated model.

### Run api/ locally

```
cd api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY`, then:

```
uvicorn main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/healthz` → `{"status":"ok"}`.

### Deploy api/ to Cloud Run

Assumes `gcloud` is already authenticated and the project is already set
(`gcloud config set project YOUR_PROJECT_ID`). Region `asia-south1`
(Mumbai) matches the PRD's India-only v1 user base — change if you deploy
elsewhere.

```
cd api
gcloud run deploy neet-prep-api \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars GEMINI_API_KEY=YOUR_GEMINI_API_KEY,ALLOWED_ORIGINS=https://YOUR-WEB-APP-URL
```

`--source .` builds the `Dockerfile` via Cloud Build and deploys in one
step — no separate `gcloud builds submit`. `gcloud` prints a Service URL
when it finishes; that's your API base URL. `ALLOWED_ORIGINS` is a
comma-separated CORS allowlist — set it to the web app's real URL once you
know it (loosen to `*` only while iterating). For anything beyond
tonight's prototype, move `GEMINI_API_KEY` into Secret Manager
(`--set-secrets` instead of `--set-env-vars`) rather than a plaintext env
var.

Smoke test once deployed:

```
curl -X POST "<SERVICE_URL>/escalate" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the function of ribosomes?"}'
```

### Deploy web/ as a static site

**Choice: Firebase Hosting**, not Cloud Storage + Cloud Run — it's one CLI
tool and one command (`firebase deploy`), gives HTTPS + CDN + SPA
rewrites + custom cache headers out of the box, and needs no load
balancer to get HTTPS on a clean URL (a Cloud Storage static site does).
Fastest path to a working, installable PWA tonight.

```
cd web
npm run build
npm install -g firebase-tools   # if not already installed
firebase login                  # if not already logged in
```

Edit `web/.firebaserc` and replace `YOUR_GCP_PROJECT_ID` with your actual
project ID (the same one `gcloud` is configured with — if it isn't already
a Firebase project, run `firebase projects:addfirebase YOUR_GCP_PROJECT_ID`
once, or do it from the Firebase console).

```
firebase deploy --only hosting
```

Prints a `https://YOUR_PROJECT_ID.web.app` URL. Set that as
`ALLOWED_ORIGINS` on the Cloud Run service (redeploy `api/` with the
updated value, or `gcloud run services update`), and set it as
`VITE_API_BASE_URL` in `web/.env.local` before your next `npm run build` +
`firebase deploy` if you want escalation working from the deployed site.

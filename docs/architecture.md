# architecture.md — Offline-First JEE/NEET Prep Engine

Scope: NEET first, JEE Main second, JEE Advanced cloud-gated. India, Hindi/English/Hinglish first. This document covers system architecture only — file/folder structure and build instructions come later, on request.

---

## 1. System overview

```
┌─────────────────────────────── ON-DEVICE (always works, no internet) ───────────────────────────────┐
│                                                                                                        │
│  Voice/Text Input → STT (on-device) → Intent + Query                                                  │
│                                              │                                                          │
│                                              ▼                                                          │
│                              ┌───────────────────────────────┐                                         │
│                              │   DETERMINISTIC CORE (Tier 0) │  ← primary answer path, ~0 cost, ~0 risk│
│                              │  - Knowledge graph            │                                         │
│                              │  - Item bank (verified Qs)    │                                         │
│                              │  - Misconception taxonomy     │                                         │
│                              │  - Symbolic solver (CAS)      │                                         │
│                              │  - Spaced-repetition scheduler│                                         │
│                              │  - Diagram renderer (SVG)     │                                         │
│                              └───────────────┬───────────────┘                                         │
│                                     match?    │   no match / low confidence                             │
│                              ┌────────yes─────┴────no─────────┐                                        │
│                              ▼                                 ▼                                       │
│              ┌───────────────────────────┐      ┌──────────────────────────────┐                       │
│              │  Tier 1: Local LLM (skin)  │      │  Queue for escalation         │                       │
│              │  Gemma 4 E2B/E4B (or       │      │  (Tier 2, needs internet)     │                       │
│              │  Gemma 3 4B fallback)      │      │  or local honest refusal      │                       │
│              │  + Qwen2.5-Math-1.5B       │      │  if no internet available     │                       │
│              │    (algebra/calc co-model) │      └──────────────┬─────────────────┘                     │
│              │  Grounded rephrase only —  │                     │                                      │
│              │  never invents facts       │                     │                                      │
│              └─────────────┬──────────────┘                     │                                      │
│                             ▼                                    │                                      │
│                     TTS (on-device) → spoken/written answer      │                                      │
│                     + provenance label (verified / AI-generated) │                                      │
└────────────────────────────────────────────────────────────────┼──────────────────────────────────────┘
                                                                    │  (only when online)
┌───────────────────────────────────────────────────────────────  ▼  ──────────────────────────────────┐
│  CLOUD / SERVER (optional, rationed, never required for the app to function)                            │
│                                                                                                          │
│  Tier 2: Escalation models                                                                              │
│   - JEE Main hard physics/maths → DeepSeek-R1-Distill-Qwen-7B (server-side, not on-device)              │
│   - JEE Advanced (always routed here, never attempted on-device)                                        │
│   - Novel/unmatched doubts of any kind                                                                  │
│                                                                                                          │
│  Cross-check: two independent models answer; if they agree → serve with normal confidence;               │
│  if they disagree → flag for human review, do not serve either answer as verified                       │
│                                                                                                          │
│  ▼                                                                                                       │
│  Tier 3: Human review queue                                                                             │
│   - Gate for anything being PROMOTED into the permanent offline item bank                                │
│   - NOT a gate for every live answer — that's what the cross-check tier is for                           │
│   - Reviewer tool: approve / edit / reject in <60 seconds per item                                       │
│                                                                                                          │
│  ▼                                                                                                       │
│  Approved item → written back into offline item bank → syncs to all devices → available forever, free   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Model tiering — final recommendation

| Tier | Component | Model | Runs where | RAM budget | Role |
|---|---|---|---|---|---|
| 0 | Deterministic core | N/A (graph + item bank + CAS) | On-device | negligible | Primary answer path. Source of truth. |
| 1a | Local LLM — interface/rephrasing/factual (Bio, Inorganic Chem, NCERT) | **Gemma 4 E2B (QAT mobile build)**, fallback Gemma 3 4B Q4_K_M on lower-RAM devices | On-device | ~1.5–3GB | Understands doubt phrasing, rephrases *retrieved* verified content in student's language. Never generates unretrieved facts. |
| 1b | Local math/algebra co-model | **Qwen2.5-Math-1.5B (Q4_K_M/Q8_0)** | On-device | ~1–1.6GB | Parses word problems into solvable form, explains steps. Final arithmetic always cross-checked against the symbolic solver, not trusted alone. |
| 2 | Escalation — hard JEE Main physics/maths | **DeepSeek-R1-Distill-Qwen-7B** | Server-side only | N/A (not on student device) | Used only when online, only for questions the local tiers can't confidently answer. Never shipped on-device. |
| 2 | Escalation — JEE Advanced (all questions) | Frontier-class API model(s), cross-checked pair | Server-side only | N/A | Advanced is permanently cloud-gated per current hardware constraints (see decision log below). |
| 3 | Human review | Subject-matter reviewers | N/A | N/A | Gates promotion into the permanent item bank; not a per-question requirement. |

**Device tiering (be explicit about this in-product, don't hide it):**
- **Baseline (3–4GB RAM):** Tier 0 + Gemma 4 E2B + Qwen2.5-Math-1.5B. This is the product's core promise and must work fully offline.
- **Enhanced (6–8GB+ RAM, opt-in):** adds Gemma 4 E4B or a locally-run 7B-class model for users with better hardware. Never required, never assumed.

---

## 3. Decision log (so this doesn't get relitigated later)

- **JEE Advanced is cloud-gated, not on-device, as of this version.** Reasoning: Advanced-level problems require multi-concept integration that small (1–4B) on-device models handle unreliably, and unreliable-with-confidence is the one failure mode this product cannot afford. Revisit this decision as on-device model efficiency improves — check again in 12–18 months, don't design the roadmap around a hoped-for breakthrough.
- **DeepSeek-R1-Distill-Qwen-7B is not shipped on-device by default.** Documented minimum viable specs for usable quality at this size are 8GB+ RAM even on mobile-optimized runtimes; the target device class is 3–4GB. Using it server-side avoids the tradeoff entirely.
- **Facts live in the item bank, not in model weights.** Any fine-tuning of Tier 1 models is for phrasing, language, and retrieval-grounded explanation — not for memorizing subject content. This is the same principle as the original architecture discussion: the model is the interface, not the brain.
- **Human review gates the item bank, not every live answer.** Per-answer human review does not scale with users; per-fact human review (once, before it becomes permanent/offline/free-forever) does. Live-answer trust is instead built via cross-model agreement at Tier 2.

---

## 4. Data flow summary

1. Student speaks or types a doubt.
2. On-device STT transcribes (Hindi/English/Hinglish).
3. Deterministic core attempts a match against the tagged item bank / knowledge graph.
4. **Match found, high confidence:** Tier 1 model rephrases the verified solution in the student's language/level; TTS speaks it; answer is labeled as verified.
5. **No match / low confidence, online:** query goes to Tier 2 (cross-checked pair). If they agree, answer is served labeled "AI-generated, pending verification." If they disagree, or confidence is still low, the app says so honestly and queues the item.
6. **No match / low confidence, offline:** app states it doesn't have a verified answer, queues the doubt locally, and syncs it for escalation next time the device is online. No guess is given.
7. Queued items above a confidence/impact threshold go to human review (Tier 3) before being promoted into the permanent item bank.
8. Promoted items sync to the offline item bank on all devices on next connectivity — the whole user base benefits from one verified answer, permanently, offline.

---

## 5. Storage & sync sketch

- **Item bank:** structured, versioned, tagged (concept, sub-concept, difficulty, misconception-per-wrong-option, exam tier: NEET/Mains/Advanced, provenance, verified-by, verified-date).
- **On-device store:** the full current item bank for the student's chosen exam/subject scope, small enough to ship in the app bundle and update incrementally (delta syncs, not full re-downloads) — critical given the target user has intermittent/no connectivity.
- **Sync protocol:** opportunistic — whenever the device gets any connectivity (even briefly, even on a friend's/school's wifi), pull item bank deltas and push the local escalation/flag queue. Never block core app function on this.
- **Diagram assets:** rendered from structured parameters at request time (SVG templates), not stored as pre-rendered images — keeps the item bank light and translatable.

---

## 6. Non-negotiables carried into this architecture

- No confident wrong answers: refusal + flag beats a guess, at every tier.
- Every answer is labeled with its provenance (verified item bank vs AI-generated-pending-verification).
- The app fully functions with zero internet, indefinitely, at the baseline device tier.
- Voice in/out is default, not opt-in, at the baseline tier.

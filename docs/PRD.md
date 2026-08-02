# Product Requirements Document — Offline JEE/NEET Prep Engine

Version: v0.1 (draft, pre-build)
Scope: NEET first. India only. Not for accreditation. Not charity-funded.

---

## 1. Problem statement

Millions of JEE/NEET aspirants in India cannot afford a coaching centre, a paid ed-tech subscription, or even reliable internet access, but have the ambition and drive to compete. Existing solutions (Allen, Physics Wallah, Unacademy, etc.) require money, connectivity, or both. Free content (YouTube, NCERT, NPTEL) already exists but doesn't solve the actual bottleneck: diagnosis of what to study next, sequencing, accurate doubt resolution, and accountability. This product provides that layer, running fully offline on cheap hardware, at zero marginal cost per student.

## 2. Target user

A NEET (then JEE Main) aspirant with:
- A basic Android phone, 3–4GB RAM class, limited storage.
- Intermittent or no internet access.
- Comfort speaking Hindi, English, or Hinglish rather than typing, especially technical content.
- No access to a coaching centre, tutor, or paid subscription.
- Real ambition and study drive — this is not a passive/low-engagement user profile by assumption.

Explicitly **not** the target for v1: JEE Advanced aspirants, students in other exam tracks, non-Hindi/English-first language groups, students with reliable broadband/flagship devices (they are already well-served by existing products).

## 3. Goals (v1)

1. A student can ask a NEET doubt (Biology first, then Physics/Chemistry) by voice or text, in Hindi/English/Hinglish, and get a correct, sourced answer — fully offline, on a 3–4GB RAM device.
2. The system never gives a confident wrong answer. When uncertain, it says so and flags the question instead of guessing.
3. Diagrams (biological structures, simple physics setups) render step-by-step, labeled, in the student's language, in text and voice.
4. Every answer is labeled by provenance: pulled from the verified item bank, or AI-generated-pending-verification.
5. The app functions with zero internet for its entire core loop; connectivity is an optional enhancement, never a dependency.

## 4. Non-goals (v1 — explicitly out of scope)

- JEE Advanced question support (cloud-gated per architecture.md; not attempted on-device, not a v1 promise even online).
- Any exam other than NEET.
- Languages beyond Hindi/English/Hinglish.
- Handwriting/image understanding (parked — see Stage 5 in the roadmap doc; too high-risk to ship before the deterministic core and review loop are proven).
- Marketing, distribution, monetization mechanics — this PRD covers product only.
- Accreditation or certification of any kind.
- Any use of student data for profiling, targeted advertising, or undisclosed model training.

## 5. Functional requirements

### 5.1 Doubt resolution
- FR1: Accept a doubt via voice (on-device STT) or typed text, in Hindi, English, or Hinglish.
- FR2: Match the doubt against the tagged item bank / knowledge graph.
- FR3: If matched with high confidence, return the verified answer, rephrased at the student's level/language by the local model, with voice output.
- FR4: If unmatched or low-confidence, and online: escalate per the cross-model-check flow (architecture.md §4). If the two models agree, serve labeled as "AI-generated, pending verification." If they disagree, do not serve either — refuse and flag.
- FR5: If unmatched or low-confidence, and offline: state plainly that no verified answer is available, queue the doubt for sync, do not guess.
- FR6: Every response carries a visible/audible provenance label.

### 5.2 Diagrams
- FR7: Render step-by-step, labeled diagrams for the top N most-requested diagram types in NEET Biology/Physics (start with a defined list: cell structures, human organ systems, simple circuits, ray diagrams, plant structures — finalize exact list against actual PYQ frequency).
- FR8: Diagrams generate from structured parameters (deterministic renderer), not free-form image generation.
- FR9: Diagram explanations available in text and voice, synced to the visual reveal.

### 5.3 Adaptive practice
- FR10: Spaced-repetition scheduling of item-bank questions based on the student's response history.
- FR11: Misconception tagging on wrong answers — track which misconception a student is repeating, not just whether they got it wrong.

### 5.4 Review & verification
- FR12: Any item promoted from an escalation answer into the permanent offline item bank must pass human review first.
- FR13: Reviewer tooling supports approve/edit/reject in under 60 seconds per item.
- FR14: Approved items sync to all devices on next connectivity.

### 5.5 Language
- FR15: Technical vocabulary in Hindi output matches official exam-paper translation conventions (English terms retained inline), not literary Hindi.
- FR16: Devanagari and Roman script both supported for Hindi text output, user-selectable.

## 6. Non-functional requirements

| Requirement | Target |
|---|---|
| Device baseline | 3–4GB RAM Android, works fully offline |
| App + on-device model footprint | Aim for ≤2–3GB total install (item bank + Gemma 4 E2B + Qwen2.5-Math-1.5B), track this as a hard budget, not an afterthought |
| Response latency (on-device, matched query) | Target sub-3-second response on baseline hardware — validate empirically, don't assume |
| STT accuracy | Measure real word-error-rate on real Hinglish physics/bio speech, on real baseline devices, before defaulting to voice-first UX |
| Refusal rate | Track explicitly as a first-class metric; expect it to be high early (Stage 1–2) and treat a falling refusal rate over time as a core health signal |
| Data handling | No under-18 personal data leaves the device without verifiable parental consent (see compliance note, §9) |
| Uptime dependency on cloud | Zero — app must be 100% functional with no internet, indefinitely |

## 7. Success metrics

**Primary:** score improvement per hour of engaged practice, measured against a control group. This is the number that proves the product works — not DAU, not minutes in app, not questions asked.

**Supporting:**
- On-device match rate (% of doubts resolved without escalation) — should trend up as item bank matures.
- Refusal rate — should trend down as item bank matures, but should never be forced down by loosening the confidence bar.
- Escalation cross-model agreement rate.
- Time from flagged item to human-reviewed resolution (SLA target, e.g. 48 hours).
- D30 retention by language/script preference (Devanagari vs Roman).

**Explicitly not primary:** DAU, session length, lectures/diagrams viewed.

## 8. Phased scope (ties to the build roadmap)

- **v0 (internal only):** text-only, English/Hindi, NEET Biology, no voice, no diagrams, no escalation. Tested on you + a handful of real students.
- **v1 (first real release):** adds voice (Hindi/English/Hinglish), diagram rendering, escalation + review loop, NEET Physics/Chemistry.
- **v2:** JEE Main added (same engine, new item bank), Bengali/Telugu/Tamil/Marathi language expansion begins, enhanced device tier (7B-class local models for 8GB+ devices).
- **v3+:** JEE Advanced (cloud-gated, permanently, unless hardware constraint changes), handwriting/image understanding (R&D track), other exams.

## 9. Compliance note (do not skip)

Under India's DPDP Rules, anyone under 18 is a "child," and processing their personal data requires verifiable parental consent — self-declaration checkboxes are not sufficient. This PRD's v0/v1 scope should stay within: (a) locally-stored, on-device-only data with no server transmission, or (b) a small internal test group of consenting adults/parent-consented minors, until a verifiable consent mechanism is built. **Cloud escalation (FR4) must not go live for real under-18 users until this is resolved** — treat this as a hard release gate, not a parallel workstream.

## 10. Open questions carried into build

- Exact diagram type list and frequency, sourced from real PYQ analysis (needed before FR7 can be scoped precisely).
- Real on-device latency and STT accuracy numbers — currently targets, not measurements.
- Item-bank tagging throughput (hours per item at what reviewer rate) — needed to budget Stage 0 realistically.
- Confidence-threshold tuning for the match/escalate/refuse decision (FR3–FR5) — will need real user testing to calibrate, not a fixed number set in advance.

## 11. References

- `architecture.md` — system architecture, model tiering, data flow.
- Roadmap & build pipeline doc — staged build order and cost analysis.
- Founder position statement — non-negotiables and open hesitations this PRD must respect.

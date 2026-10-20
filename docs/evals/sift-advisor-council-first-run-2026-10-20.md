# Sift first-run and release sequence: Advisor council record

**Date:** 2026-10-20  
**Mode:** Codex Advisor council; Gemini review first, then an independent GPT-6.1 Sol verdict and assessment of Gemini's view.  
**Question:** Which next work should lead: usability/recruitment, client compatibility, or release-control verification?

## Attributed conclusions

**Gemini 4 Argon** recommended deterministic compatibility coverage first, followed by refreshing the opt-in recruitment issue and checking release gates. Its concern was that support claims should be backed by named client paths before release.

**GPT-6.1 Sol** agreed that compatibility claims should stay scoped, then gave a separate verdict: prioritize first-run usability because there are no user observations, and additional passing integrations alone will not reveal onboarding friction. Sol placed multi-client compatibility and release-control checks after usability.

These are separate recommendations, not a vote. The active work sequence follows Sol on ordering: publish a corrected, inference-free task and feedback path first, then verify additional named-client behavior and run a non-publishing release-control rehearsal. Recruitment remains opt-in and capped at three sessions.

## Use and limits

This council affected work sequencing only. It did not authorize inference spending, participant contact, a stable release, or a change to Sift's algorithm. No provider/model-quality run was part of this consultation. The recommendation is based on the absence of user observations in this project state and should be revisited if that evidence changes.

## Outcome after the decision

PR #20 shipped the corrected README/protocol task and refreshed issue #13. PR #22 later added a second deterministic client smoke while first-run recruitment remained open. At the latest check on 2026-10-20, issue #13 still had zero comments and no sessions had run. Thus the documentation path and compatibility coverage improved, but the council's usability question remains unresolved until opt-in participants try the flow; the extra client smoke is not substitute evidence.

## Receipt provenance

The original council call completed through the bundled Codex Advisor caller during this Codex session. The session reported usage of **Gemini 4 Argon: 3,347 prompt / 211 completion tokens** and **GPT-6.1 Sol: 821 prompt / 294 completion tokens**. This file is an attributed summary preserved from the session handoff; the full raw answers and request packet were not saved in the repository, so the wording above is a paraphrase, not a transcript. Do not treat it as a verbatim or independently replayable receipt.

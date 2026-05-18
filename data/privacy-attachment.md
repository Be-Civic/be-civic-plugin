# Be Civic — Alpha Privacy Terms

_This document describes how Be Civic handles your data during the pre-launch alpha period. These terms are specific to alpha. Post-alpha terms will live at becivic.be/privacy._

---

## What Be Civic is

Be Civic gives your AI agent verified Belgian administrative procedures — step-by-step guidance for navigating communes, residency, nationality, and related processes. It is a tool for your agent, not a service that holds your account.

---

## What stays on your computer

Everything you tell your agent stays in your Be Civic project folder on your computer. That includes:

- Your profile (region, commune code, residency status, civic status, document inventory)
- Your procedure progress notes
- Any documents you share with your agent during a session
- Extracted routing fields your agent pulls from those documents (permit type, validity dates, issuing authority — not document numbers, not your name)

Your agent reads and writes these files locally. Be Civic never receives them. There is no Be Civic account, no cloud sync, and no server-side copy of your data.

Your profile stores only categorical fields — enums, booleans, month-bucket dates. It cannot hold your name, national register number, date of birth, passport number, or full postal address. The schema enforces this; it is not a policy promise.

---

## What leaves your machine

During the alpha, two things may leave your machine:

**1. Anonymous observations and validations.**
When your agent notices that a skill is out of date, or that a procedure step worked for you, it buffers a short note. At the end of your session, your agent shows you everything it has buffered and asks for your approval before sending any of it. You review item by item; nothing goes without your say-so.

What gets sent: a short text description of what was observed, which skill it refers to, and which commune (optional, if relevant). No names, no identifiers, no document content, and no profile fields are included.

**2. Anonymous session telemetry (analytics).**
If your session produces analytics events (skill loaded, path attempted, session duration), these may be submitted in the background. The data is categorical — skill IDs, outcome codes, session timing. No free-text content, no location more precise than region.

---

## How we prevent personal data from reaching the corpus

Before anything is sent, it goes through three layers:

**Layer 1 — Consumer-side scrub (your machine).**
Your agent runs regex pattern matching and an LLM-based review on every item it is about to submit. If either check flags something, the write is aborted and the item is flagged for your review. This is the primary gate, because your agent is the only entity that knows what is identifying in your case.

**Layer 2 — Server-side regex gate.**
The Be Civic receiving server re-runs pattern matching on every inbound submission. Anything that matches is rejected before it touches the staging queue. The server never logs request bodies.

**Layer 3 — NER on commit.**
Before a staged submission is committed to the public corpus, a named-entity recognition step (Presidio, multilingual) scans every free-text field for person names. On a hit, the item is held for a human reviewer. The reviewer either confirms it is a false positive (e.g. a commune that happens to sound like a person's name) or discards it.

**IP addresses** are never stored in plaintext. For rate limiting, your IP is hashed with a daily-rotating salt. For self-validation prevention (so you can't validate your own submission), a separate per-submission salt is used. The two hashes are unlinkable to each other and to you.

Items sit in a 24-hour staging window before they go anywhere. You can cancel any staged item within that window by asking your agent to do so.

---

## What Be Civic does not collect

- Your name, date of birth, national register number, or any national identifier
- Document numbers (passport, residence card, work permit)
- Full postal addresses
- Email addresses
- Any copy of documents you share — the document content exists only in your agent's active session and is discarded when the session ends
- Cross-session behaviour beyond what you have saved locally in your project folder

---

## How to stop

If you want to stop using Be Civic entirely during the alpha:

1. Tell your agent you want to leave.
2. Delete your Be Civic project folder (the one your agent created when you set up your first procedure).

That's it. There is no account to deactivate. There is no server-side deletion request to file. Be Civic holds no server-side copy of your data, so deletion is entirely your act.

After deletion, if you start a new Be Civic session, you will be treated as a first-time user.

---

## Alpha-specific posture

During the alpha, observations and anonymous telemetry are how we improve the corpus fast enough to launch. Granular opt-out controls (per stream, per submission type) are on the roadmap for after launch. For now, it is all-or-nothing: you are in (and helping improve the product), or you stop using Be Civic during alpha.

The consent statement on the onboarding form makes this explicit. Clicking Continue is your agreement.

---

## If something slips through

Despite the scrub layers, mistakes can happen. If you believe personal information about you has appeared in the Be Civic corpus, write to **privacy@becivic.be**. We acknowledge within 72 hours and act within 7 days — removing the content from the live site, the database, and the public source repository.

Creative Commons Attribution 4.0 governs the corpus. We can remove content from Be Civic itself; we cannot reach forks, caches, or AI training datasets that have already ingested it.

---

_Last updated: alpha period, May 2026. Full post-alpha terms: becivic.be/privacy_

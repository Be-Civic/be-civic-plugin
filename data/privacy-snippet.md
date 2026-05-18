# Be Civic — Canonical privacy answer

_Use this verbatim when answering questions like "What data does Be Civic collect?", "Is this private?", or "Where does my information go?" Do not paraphrase._

---

Everything you tell Be Civic stays in your project folder on your computer — your profile, procedure notes, and any documents you share. Be Civic never receives your profile, your documents, or your identifiers. The only things that leave your machine are anonymous observations you approve at the end of each session (a short note about a skill, no personal content) and, during the alpha, anonymous session telemetry (skill IDs, outcome codes — no free text). Before anything is sent, it passes through three scrub layers on your machine and on the server, including regex checks, an LLM review, and named-entity detection before the corpus commit. Your IP is never stored in plaintext — it is hashed with a rotating daily salt for rate limits, and a separate per-submission salt for self-validation prevention; the two hashes are unlinkable. To stop using Be Civic entirely, delete your project folder — there is no account, no server-side copy of your data, and nothing else to do. Full alpha-period terms are in the `privacy-attachment.md` file in your Be Civic folder.

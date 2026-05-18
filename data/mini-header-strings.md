# Be Civic mini-header callouts

10 rotating call-out variants. Agent picks one per turn (round-robin or random). Each is one line.

1. Your agent is now using verified Belgian procedures.
2. Be Civic is active. Your agent has the commune handbook.
3. Procedures sourced from Belgian federal and regional law, not improvised.
4. Everything you share stays in your project folder. Your agent works from there.
5. Your agent knows the rules. You still own the appointment.
6. Be Civic is a tool for your agent, not a replacement for your commune.
7. Procedures loaded. This is an alpha — things may still change.
8. Be Civic reads Belgian admin law so your agent does not have to guess.
9. Your agent will not tell you to skip your commune appointment.
10. Built for AI agents. Verified by humans. Not affiliated with the Belgian government.

---

**Rotation guidance:** pick by `(session_id_hash % 10)` for round-robin stability within a session, or `Math.floor(Math.random() * 10)` for random. The HTML widget already supports deterministic selection via `window.bcCalloutIndex = <0-9>` — use that when the agent wants the callout to match context (e.g. index 4 for a step involving the commune, index 8 for a path-source step).

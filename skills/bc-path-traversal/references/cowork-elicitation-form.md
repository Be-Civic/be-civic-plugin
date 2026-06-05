# Cowork elicitation form — runtime mechanics

How to render a multi-section structured-intake form mid-session in Cowork (Pattern A — the chrome-locked elicitation form). Read this JIT, when you are about to elicit several fields at once and a single AskUserQuestion is the wrong shape (the harness §11 routes you here). For 2–4 categorical choices in chat, use AskUserQuestion instead. The branded first-contact onboarding widget is a separate, fully-built HTML asset owned by `bc-onboarding` — do not rebuild it from this.

Both patterns sit on top of the same primitive, `mcp__visualize__show_widget`. This file covers **Pattern A only** — the elicitation form that inherits Cowork's native `.elicit-*` chrome (auto-wired selection states, submit, "answers come back as a chat message"). It cannot be branded; it is designed to feel native to the assistant, which is exactly right for routine mid-session intake.

## The two-call pattern (non-negotiable)

1. **Once per session:** call `mcp__visualize__read_me` with `modules: ["elicitation"]` to load the elicitation spec + `.elicit-*` CSS into working memory. Skip on later forms in the same session — but the FIRST elicitation form of the session MUST do this. **Agents that skip this step produce broken forms because the `.elicit-*` CSS isn't loaded** — the form renders plain (washed-out text, near-invisible borders). This is the single most-skipped step.
2. Call `mcp__visualize__show_widget` with the form HTML as `widget_code`.

(This is the OPPOSITE of the shipped Be Civic widgets — the access widget and the about-you onboarding form are pre-built, self-contained HTML, so for THOSE you skip `read_me`. The rule flips here because you are authoring the form HTML yourself from the skeleton below, so the `.elicit-*` chrome must be loaded.)

## HTML skeleton (emit byte-for-byte; only the body varies)

```html
<form class="elicit">
  <div class="elicit-header">
    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M11.586 2a1.5 1.5 0 0 1 1.06.44l2.914 2.914a1.5 1.5 0 0 1 .44 1.06V16.5a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.492-1.347L4 16.5v-13A1.5 1.5 0 0 1 5.5 2zM5.5 3a.5.5 0 0 0-.5.5v13a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5V7h-2.5A1.5 1.5 0 0 1 11 5.5V3zM12 5.5a.5.5 0 0 0 .5.5h2.293L12 3.207z"/></svg>
    <span>[SUBJECT] details</span>
  </div>
  <div class="elicit-body">
    <!-- one .elicit-group per question -->
    <div class="elicit-group">
      <label class="elicit-question">…question text…</label>
      <div class="elicit-pills" data-name="field_name" data-multi="false">
        <button type="button" class="elicit-pill" data-value="…">Option A</button>
        …
      </div>
    </div>
  </div>
  <div class="elicit-footer">
    <button type="button" class="elicit-skip">Skip</button>
    <button type="button" class="elicit-submit">Continue</button>
  </div>
</form>
```

The header SVG and any dropzone SVG are fixed chrome — emit verbatim. Substituting a different icon breaks the visual contract.

## Field-group formats

Pick the control by the shape of the answer:

- **Plain pills** (≤4-word labels): roles, yes/no, single categorical choices.
- **Cards** (icon + one-line subtitle): tone-rich choices where the subtitle disambiguates.
- **Preview tiles:** output / layout pickers.
- **`<input type="range">`:** scales (e.g. a 0–10 self-rating).
- **`<input type="date" class="elicit-date">`:** deadlines, dates.
- **`<textarea class="elicit-textarea">`:** free text (the user describing their situation).
- **`.elicit-files` + dropzone:** file upload.

## Wiring rules (non-negotiable)

- Each choice container: `<div class="elicit-pills" data-name="X" data-multi="false|true">`.
- Each option: `<button type="button" class="elicit-pill" data-value="…">`.
- **Use `data-multi="true"` when answers can genuinely co-apply** (several document statuses the user holds at once; a person born in Belgium *and* with a Belgian family link). Reserve `data-multi="false"` for genuinely exclusive fields. This is the same MECE / multi-select discipline the harness §11 applies to AskUserQuestion — a user who can't pick two true options types "2+3" into a free-text box and corrupts the field.
- Escape hatch: `data-other` on the last option + a paired `<input type="text" class="elicit-other" data-for="X" hidden>`.
- **No `onclick`, no `<script>`, no inline `background`/`border` on pills.** The `.elicit-*` chrome wires selection + submit automatically; adding your own JS fights it.
- Selection colour is blue by default; add `data-accent="warning|danger|success"` only with a semantic reason.

## Reading the response

Answers come back as the user's **next chat message**, in the shape:

```
[Subject] details — Field: value · Field2: a, b · Deadline: 2026-06-01
```

Parse it field-by-field. Multi-select fields arrive comma-joined (`a, b`). If the message is `(Skipped the form — proceed with defaults or ask me in plain text)`, the user hit Skip — fall back to chat (AskUserQuestion for the must-haves, prose for the rest).

## Inference first

Don't fire the form for questions context already answers. A one-question form beats five where four are already in `profile.json` or the parked-document queue. Read the profile + the procedure's `inputs:` first, then only ask for what's genuinely unknown.

## Worked example — multi-field situation/intake form

A routine intake form: several `.elicit-group`s mixing a textarea, single-select pills, a multi-select with an "Other" escape hatch, a range, and a date. (Adapted from the Riverside Family Health intake example; the same structure carries any mid-session Be Civic elicitation — e.g. routing fields a procedure declares, plus a batch of document statuses.)

```html
<form class="elicit">
  <div class="elicit-header">
    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M11.586 2a1.5 1.5 0 0 1 1.06.44l2.914 2.914a1.5 1.5 0 0 1 .44 1.06V16.5a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.492-1.347L4 16.5v-13A1.5 1.5 0 0 1 5.5 2zM5.5 3a.5.5 0 0 0-.5.5v13a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5V7h-2.5A1.5 1.5 0 0 1 11 5.5V3zM12 5.5a.5.5 0 0 0 .5.5h2.293L12 3.207z"/></svg>
    <span>Your situation</span>
  </div>
  <div class="elicit-body">

    <div class="elicit-group">
      <label class="elicit-question">In a sentence, what are you trying to sort out?</label>
      <textarea class="elicit-textarea" data-name="goal" placeholder="e.g. I want to apply for Belgian nationality"></textarea>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">How long have you been a registered resident?</label>
      <div class="elicit-pills" data-name="residency_duration" data-multi="false">
        <button type="button" class="elicit-pill" data-value="Under 5 years">Under 5 years</button>
        <button type="button" class="elicit-pill" data-value="5 years or more">5 years or more</button>
        <button type="button" class="elicit-pill" data-value="Not sure">Not sure</button>
      </div>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">Which documents do you already have to hand?</label>
      <div class="elicit-pills" data-name="documents_held" data-multi="true">
        <button type="button" class="elicit-pill" data-value="None">None</button>
        <button type="button" class="elicit-pill" data-value="Residence certificate">Residence certificate</button>
        <button type="button" class="elicit-pill" data-value="Birth certificate">Birth certificate</button>
        <button type="button" class="elicit-pill" data-value="Proof of integration">Proof of integration</button>
        <button type="button" class="elicit-pill" data-value="Other" data-other>Other</button>
      </div>
      <input type="text" class="elicit-other" data-for="documents_held" placeholder="Which document?" hidden>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">How confident are you about your timeline?</label>
      <div style="display: flex; align-items: center; gap: 12px;">
        <span style="font-size: 12px; color: var(--color-text-tertiary);">Not at all</span>
        <input type="range" data-name="timeline_confidence" min="0" max="10" step="1" value="5" style="flex: 1;">
        <span style="font-size: 12px; color: var(--color-text-tertiary);">Very</span>
      </div>
    </div>

    <div class="elicit-group">
      <label class="elicit-question">Is there a deadline you're working towards?</label>
      <input type="date" class="elicit-date" data-name="deadline">
    </div>

  </div>
  <div class="elicit-footer">
    <button type="button" class="elicit-skip">Skip</button>
    <button type="button" class="elicit-submit">Continue</button>
  </div>
</form>
```

That form returns, e.g.:

```
Your situation details — goal: I want to apply for Belgian nationality · residency_duration: 5 years or more · documents_held: Residence certificate, Birth certificate · timeline_confidence: 7 · deadline: 2026-09-01
```

Map each field onto the procedure's routing inputs / the parked-document queue. Categorical fields that belong in `profile.json` follow the harness §15 privacy discipline (NIS5 / region / status enums only — never raw addresses, ID numbers, or exact dates of birth); free-text and dates stay in working memory or `MEMORY.md`, not the routing stores.

## A note on light/dark mode

The elicitation chrome adapts to light/dark automatically — that is one reason to stay inside Pattern A for routine intake. Use CSS variables (`var(--color-text-tertiary)`, etc.) for any inline accents so they stay mode-aware.

## Source

Ported from the Be Civic dev-docs reference `cowork-form-mechanism.md` + `cowork-form-examples.md` (Henry's 2026-05-17 Cowork conversations, captured during the W24 onboarding rebuild). This file ships the Pattern A runtime mechanics into the plugin so a working-session skill can reach them just-in-time; the branded Pattern B onboarding widget is `bc-onboarding`'s already-shipped HTML.

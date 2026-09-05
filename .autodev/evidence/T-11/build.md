# T-11 — Pexels chrome pass: build evidence

| AC | Result |
| --- | --- |
| AC1 fetched once, then local | Three images pulled by `scripts/fetch-chrome.py` into `frontend/public/chrome/`, served at `/chrome/*.jpg` (200, `image/jpeg`). **Playwright recorded every request the app made: zero left the machine.** |
| AC2 credited | `credits.json` with creator, licence, source, photographer URL, alt text and **why that image was chosen** — Adrien Olichon (empty auditorium), Resource Boy (black chalk texture), Charlotte May (retro film projector). |
| AC3 committed | Images and credits are in git — generic, so a fresh clone looks right — while title art stays in gitignored `data/`. |
| AC4 every skin | Verified in `system`, `nocturne` and `paperback`: photographs sit under token-driven scrims, and the page ground changes per skin while the imagery only supplies texture. |
| AC5 dressed surfaces | The ground behind the carousel, the empty state, and a Seen-archive banner. |
| **AC6 colour-literal rule** | Re-run across **every** ticket's CSS: `hex: NONE · hsl: NONE · hued rgba: NONE`, 151 token references, and 3 neutral black/white alphas for shadows and scrims. |
| **AC7 traversal regression** | Re-run because this ticket touched the static tree — the condition T-2 recorded. `../../.env`, `../../.git/config`, `../../../../etc/passwd` and `chrome/../../.env` all return the SPA shell with **0 secrets**. |
| AC8 no key | `PEXELS_API_KEY` blanked: the script exits 1 saying what is missing and that the app renders fine without it. Verified without editing the real `.env` permanently. |

Idempotent: a second run prints *"already here, skipped"* for every slot — no quota spent, no
committed file churned.

## The defect this ticket found

Introducing `--ink-over-art` for text over photographs, I **used the token but never defined
it** — the insertion anchor no longer matched because T-8 had edited that part of `:root`.
CSS does not complain about an undefined custom property; `var()` silently falls back, so the
banner heading rendered in `--ink` (near-black, `rgb(26,24,21)`) over a dark photograph.

It was caught because the test asserted the **computed colour** rather than checking the
stylesheet said the right thing. After the fix, all three skins report
`rgb(255, 255, 255)`, and the title-page hero — which shares the token — does too.

Worth keeping: **an undefined CSS custom property fails silently and looks like a styling
choice.** Assert computed values, not source text.

## Why a token instead of `#fff`

Text over a photograph cannot use `--ink`: in a light skin that is near-black, and near-black
over a dark still is unreadable. But leaving a bare `#fff` would have broken the rule every
other ticket has kept. A token satisfies both — the value is fixed by the medium, and a skin
can still override it.

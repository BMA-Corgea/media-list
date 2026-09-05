# T-8 — Spin the wheel: build evidence

| AC | Result |
| --- | --- |
| AC1 it spins, and decelerates | 11 wedges, fixed pointer. Sampling the transform every 400ms through a spin: **110°/sample early → 9°/sample late**. Fast off the line, long tail — measured, not asserted. |
| **AC2 honest landing** | See below — chi-square, with a negative control. Across **5,000 spins at random list sizes the pointer landed on a non-winner 0 times**, and the rotation always increases so the wheel never appears to rewind. |
| AC3 reveal uses the art | *Super Mario 64* · `game · 1996` · cover art · the `why` quoted · **Open it** / **Spin again**. |
| AC4 scoped by kind | Filtered to games: **3 wedges**, and the pick came back `game · …`. |
| AC5 · 2 titles | 2 wedges, spins, reveals. |
| AC5 · 1 title | **No wedges and no spin.** The button reads *"Well, obviously"* and reveals it directly — no theatre for a foregone conclusion. |
| AC5 · none of that kind | *"Nothing to spin for — Nothing in live-action is queued."*, spin disabled. |
| AC6 reduced motion | **101 ms to reveal**, labelled *"Picked at random:"* — the same picker, no theatre. |
| AC7 no double spin | Disabled during the spin, re-enabled after. A `setTimeout` backstop releases it if `transitionend` never fires (a tab hidden mid-spin). |
| AC8 skin-driven | No hex or hsl literals; the only `rgba()` is shadow alpha with no hue. Segment tints are `--wheel-a…d` tokens with a dark-mode set, so a skin restyles the wheel too. |

Zero `pageerror`s and zero console errors throughout.

## AC2 — and a correction to how it was measured

The spec said *"10,000 picks must be uniform, max deviation under 5%."* Run at n=11 that
produced a **7.91% max deviation and a fail** — but the code was fine and **the criterion was
wrong**. With 11 buckets and N=10,000 the expected count is 909 with σ≈29, so a 5% bound is
1.6σ; the *largest* of 11 deviations exceeds 1.6σ most of the time by pure chance.

Rather than raise N until it passed — which would be tuning the test to the answer — the test
was replaced with the correct one, **chi-square goodness-of-fit at p = 0.01**:

| n | N | χ² | critical | verdict |
| --- | --- | --- | --- | --- |
| 2 | 10,000 | 0.67 | 6.63 | uniform |
| 3 | 10,000 | 1.51 | 9.21 | uniform |
| 5 | 10,000 | 6.30 | 13.28 | uniform |
| 10 | 50,000 | 12.93 | 21.67 | uniform |
| 11 | 50,000 | 4.46 | 23.21 | uniform |
| 15 | 50,000 | 12.93 | 29.14 | uniform |
| 20 | 100,000 | 19.40 | 36.19 | uniform |

**Negative control** — a deliberately skewed picker (`Math.random()**1.3`) at n=11 scored
**χ² = 3390.12** against the same 23.21 threshold. The test can fail, which is the only thing
that makes the passes worth anything.

## Why the winner is chosen first

The RNG picks the index, *then* the rotation is computed to land on it. Reading a result off
wherever the animation stops makes fairness a property of the easing curve — untestable
without a browser and impossible to reason about. `pickIndex` and `rotationFor` are DOM-free
exports precisely so 100,000 draws can be checked in node.

The landing angle is jittered inside the winning wedge (bounded to 70% of its width, so it can
never reach a neighbour) — two spins never stop on an identical pixel.

## Gaps
Chromium only. The deceleration is measured from sampled transforms, not from a frame capture.

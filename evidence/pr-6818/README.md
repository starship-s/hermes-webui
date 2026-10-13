# Terminal settlement comparison for PR #6818

[PR #6818](https://github.com/nesquena/hermes-webui/pull/6818) bounds the session snapshot delivered at normal turn completion. These captures use the real WebUI server and browser with a deterministic Gateway Runs API fixture. No live provider or personal transcript is involved.

- Before: upstream `330f0936baa03dcdd6694454464dedaf28ba7062`.
- After: candidate `d6cd327333d3d8fd3da533e46a7839c7ff161058`, based on that upstream revision.
- Chromium 153.0.8010.12, viewport 1280×720, DPR 1, no CPU throttling.
- Alternating user/assistant Markdown history, 2,048 content bytes per row. Initial load contains 30 rows.
- Each revision has one cold and six subsequent samples at both 100 and 6,000 historical rows. Each sample uses a fresh browser context within the same browser process. All 28 samples completed without browser errors or failed assets.
- Normal composer submission, real chat-start and SSE routes, live reasoning/tool activity, and actual terminal-event dispatch. The renderer and terminal handler were not directly invoked by the driver.

## Warm results

Payload units are decimal kB. Nearest-rank p95 over six samples is the maximum observed, not a stable population-tail estimate.

| History rows | Revision | Terminal payload median | Handler median | Handler p95 |
|---:|---|---:|---:|---:|
| 100 | Before | 217.980 kB | 160.65 ms | 184.20 ms |
| 100 | After | 62.788 kB | 62.65 ms | 66.50 ms |
| 6,000 | Before | 12,944.288 kB | 7,574.05 ms | 8,615.60 ms |
| 6,000 | After | 62.797 kB | 66.15 ms | 69.20 ms |

At 6,000 historical rows, completion-to-first-settled-frame opportunity fell from 8,271.95 ms median / 9,541.30 ms p95 to 73.95 ms median / 83.60 ms p95. The browser previously received and rendered all 6,002 rows. The candidate receives 30 terminal rows and retains its 32 loaded/new rows, with an authoritative total of 6,002.

The screenshots show the final answer after settlement at the same viewport. They show content continuity, not the duration of the preceding stall; timing comes from browser instrumentation. `measurements.csv` contains the individual scalar measurements, including cold samples.

## Scope and limitations

The synchronous handler measurement wraps real `done` dispatch; first-settled-frame timing uses `performance.now()` inside requestAnimationFrame and is a paint opportunity, not proof of displayed pixels. Browser Long Tasks are observed separately. The candidate still produced a 72 ms p95 Long Task, so this is not a claim that all main-thread stalls are gone.

The comparison does not measure physical-phone performance, every history shape, or native-agent execution with a live provider. Host load was not controlled. Persistence/reconciliation work before terminal delivery remains outside the handler measurement and is not claimed fixed. The exact fixture is generated history, not a recording of a user conversation.

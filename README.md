# Active-session switch rendering evidence

Public-safe deterministic fixture evidence for the Hermes WebUI active-session rendering PR.

- Baseline: current upstream `master` at `7a3646bafdb0b4659bc573ca4d5a54c5dfa377e1`
- Patched: `68e6a9e3f6ae5280890439b1bf16c5b90df25a48`
- Browser: Chromium with Pixel 5 mobile emulation
- CPU: 4x DevTools throttling
- Fixture: 4,410 messages, 2,882 tool calls, and 129 authoritative live-scene rows
- Synchronization: first visible switch/loading frame is `t=0`

The image and video use generated benchmark content only.

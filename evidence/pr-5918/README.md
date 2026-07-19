# PR #5918 typography evidence

Real Hermes WebUI instances were captured from current `origin/master` and the rebased PR candidate using the same neutral two-message session.

- Desktop viewport: `1440×900`, DPR 1
- Mobile viewport: `390×844`, DPR 1
- Default captures verify visual parity.
- Custom captures apply the documented runtime typography contract:
  - `--font-ui: "Trebuchet MS", sans-serif`
  - `--font-conversation: Georgia, serif`
  - `--font-mono: "Courier New", monospace`
- `metrics.json` records viewport dimensions and browser-computed font families for body UI, conversation prose, inline code, fenced `pre`, and fenced `code`.
- The fixture contains only neutral synthetic content.

"""Follow-up regressions for #6524: navigation and rejected draft authority.

Use the real pre-navigation await/guard and draft helpers in Node. The DOM and
HTTP transport are seams, not a browser end-to-end test. Backend cases use the
real compression migration and draft POST dispatch against temporary files.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_composer_draft_sidecar_regressions import (
    _build_pre_compression_migration_state,
    _post_json,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("status", [404, 409, 503])
@pytest.mark.parametrize("superseded", [False, True])
def test_failed_preswitch_save_keeps_capture_and_reaches_navigation_guard(status, superseded):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    source = (ROOT / "static/sessions.js").read_text(encoding="utf-8")
    helpers = source[source.index("let _draftSaveTimer = null;"):
                     source.index("function _restoreComposerDraft(")]
    start = source.index("async function loadSession(")
    # Stop at the destructive navigation boundary; the real guard must decide
    # whether it is safe to reach it, even when the save rejects.
    prefix = source[start:source.index("  const _keepStaleUntilLoaded", start)]
    script = r"""
const vm = require('node:vm');
const state = {warnings: [], posts: [], reached: [], stopped: 0};
const input = {value: 'captured draft'};
const attachment = {name: 'fixture.txt', path: '/fixture.txt'};
const S = {session: {session_id: 'old', composer_draft: {}},
           pendingFiles: [attachment], messages: []};
let rejectPost;
const context = vm.createContext({
  S, INFLIGHT: {}, window: {}, console: {warn: (...a) => state.warnings.push(a)},
  $: () => input, clearTimeout, setTimeout,
  _loadingSessionId: null, _loadSessionGeneration: 0,
  _rearmActiveSessionStream() {}, _sessionVisitHasUnreadState: () => false,
  stopApprovalPolling() {}, hideApprovalCard() {},
  stopSessionStream() {state.stopped++;}, _updateYoloPill() {},
  api(path, opts) {
    state.posts.push(JSON.parse(opts.body));
    return new Promise((resolve, reject) => {rejectPost = reject;});
  },
  reached: state.reached,
});
vm.runInContext(HELPERS + '\n' + PREFIX + '\nreached.push(sid);\n}', context);
(async () => {
  const pending = vm.runInContext("loadSession('target')", context);
  // Mutations during the await must not change the captured failure payload.
  input.value = 'typed later';
  S.pendingFiles.push({name: 'later.txt'});
  if (SUPERSEDED) {
    context._loadingSessionId = 'newest';
    context._loadSessionGeneration++;
    S.session = {session_id: 'newest', composer_draft: {text: 'newest input'}};
  }
  const error = Object.assign(new Error('fixture save failed'), {
    status: STATUS,
    body: JSON.stringify({code: 'draft_authority_unconfirmed', session_id: 'old'}),
  });
  rejectPost(error);
  try {await pending;} catch (e) {state.error = e.message;}
  state.draft = S.session.composer_draft;
  state.known = vm.runInContext('Array.from(_composerDraftKnownPayloadSessions)', context);
  state.loading = context._loadingSessionId;
  state.visible = input.value;
  process.stdout.write(JSON.stringify(state));
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    script = ("const HELPERS = " + json.dumps(helpers) + ";\n"
              + "const PREFIX = " + json.dumps(prefix) + ";\n"
              + "const SUPERSEDED = " + json.dumps(superseded) + ";\n"
              + "const STATUS = " + str(status) + ";\n" + script)
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert "error" not in state, state
    assert state["reached"] == ([] if superseded else ["target"])
    assert state["loading"] == ("newest" if superseded else "target")
    assert len(state["warnings"]) == 1
    assert state["posts"][0] == {"session_id": "old", "text": "captured draft",
                                 "files": [{"name": "fixture.txt", "path": "/fixture.txt",
                                            "size": None, "type": ""}]}
    if not superseded:
        assert state["posts"][1] == {"session_id": "old", "text": "typed later",
                                     "files": [{"name": "fixture.txt", "path": "/fixture.txt",
                                                "size": None, "type": ""},
                                               {"name": "later.txt", "path": "", "size": None, "type": ""}]}
    else:
        assert len(state["posts"]) == 1
    assert state["known"] == ["old"]
    assert state["visible"] == "typed later"
    assert state["draft"] == ({"text": "newest input"} if superseded else {
        "text": "captured draft", "files": [{"name": "fixture.txt", "path": "/fixture.txt"}]})


@pytest.mark.parametrize("invalid", ["parent", "profile", "missing"])
def test_rejected_continuation_cannot_redirect_stale_autosave(tmp_path, monkeypatch, invalid):
    models, routes, directory, old_sid, child_sid, _ = _build_pre_compression_migration_state(
        tmp_path, monkeypatch)
    try:
        # Exact reported order: compress, clear the continuation's parent link,
        # save a NEWER draft, then autosave against the archived parent.
        child = models.get_session(child_sid)
        if invalid == "parent":
            child.parent_session_id = None
        if invalid == "profile":
            child.profile = "other-profile"
        child.save(touch_updated_at=False, skip_index=True)
        models._save_session_draft(child_sid, {"text": "newer continuation draft", "files": []})
        if invalid == "missing":
            (directory / f"{child_sid}.json").unlink()
        models.SESSIONS.clear()
        status, body = _post_json(monkeypatch, routes, "/api/session/draft", {
            "session_id": old_sid, "text": "stale parent autosave", "files": []})
        assert status == 409
        assert body["code"] == "draft_authority_unconfirmed"
        assert body["session_id"] == old_sid
        # The actual client helper must not convert this rejection into a child
        # POST that bypasses the server's failed authority validation.
        node = shutil.which("node")
        if not node:
            pytest.skip("node not available")
        source = (ROOT / "static/sessions.js").read_text(encoding="utf-8")
        helper = source[source.index("function _safeDraftSessionId("):
                        source.index("function _composerDraftResponseSessionId(")]
        result = subprocess.run([node, "-e", helper + "\nprocess.stdout.write(JSON.stringify("
            + "_parseSessionMovedDraftError({body:" + json.dumps(json.dumps(body)) + "})));"],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) is None
        assert json.loads((directory / ".drafts" / f"{child_sid}.json").read_text())["text"] == "newer continuation draft"
        assert not (directory / ".drafts" / f"{old_sid}.json").exists()
    finally:
        with routes.LOCK:
            routes.SESSIONS.clear()
        from api import streaming
        with streaming.SESSION_AGENT_LOCKS_LOCK:
            streaming.SESSION_AGENT_LOCKS.pop(old_sid, None)
            streaming.SESSION_AGENT_LOCKS.pop(child_sid, None)

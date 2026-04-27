"""Behavioural tests for expired-auth handling in the JS api() layer.

String-presence tests caught that api() *mentions* 401 redirects, but the live bug was
semantic: after setting window.location.href, api() resolved with undefined. Callers like
loadSession() then kept executing their normal error UI path instead of cleanly stopping
for re-authentication.

AuthRedirectError and _redirectToLogin live in static/ui.js; api() and _LOGIN_PATH live
in static/workspace.js. The Node driver reads both files and extracts the relevant symbols.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
WORKSPACE_JS_PATH = REPO_ROOT / "static" / "workspace.js"
UI_JS_PATH = REPO_ROOT / "static" / "ui.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

# ---------------------------------------------------------------------------
# Shared driver scaffolding
# ---------------------------------------------------------------------------

_EXTRACT_HELPER = r"""
const fs = require('fs');
const srcWorkspace = fs.readFileSync(process.argv[2], 'utf8');
const srcUi = fs.readFileSync(process.argv[3], 'utf8');

function extractTopLevel(name, kind='function', src=srcWorkspace) {
  const re = kind === 'class'
    ? new RegExp('class\\s+' + name + '\\b')
    : new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\(');
  const start = src.search(re);
  if (start < 0) return '';
  // Find the opening brace for the declaration body, not a default parameter
  // like opts={} inside the signature.
  const sigEnd = kind === 'class' ? -1 : src.indexOf('){', start);
  let i = sigEnd >= 0 ? sigEnd + 1 : src.indexOf('{', start);
  let depth = 1; i++;
  while (depth > 0 && i < src.length) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') depth--;
    i++;
  }
  return src.slice(start, i);
}
"""

_EVAL_AND_RUN = r"""
const loginPathMatch = srcWorkspace.match(/const _LOGIN_PATH\s*=[^\n]+;/);
eval([
  extractTopLevel('AuthRedirectError', 'class', srcUi),
  extractTopLevel('_redirectToLogin', 'function', srcUi),
  loginPathMatch ? loginPathMatch[0] : '',
  extractTopLevel('api', 'function', srcWorkspace),
].join('\n'));

(async () => {
  try {
    const value = await api('/api/session?session_id=abc');
    console.log(JSON.stringify({ outcome: 'resolved', value, redirectedTo: global.redirectedTo }));
  } catch (e) {
    console.log(JSON.stringify({
      outcome: 'rejected',
      name: e && e.name,
      authRedirect: !!(e && e.authRedirect),
      redirectedTo: global.redirectedTo,
    }));
  }
})();
"""

# Fetch mocks -----------------------------------------------------------------

_FETCH_401 = (
    "{\n"
    "    ok: false,\n"
    "    status: 401,\n"
    "    headers: { get: () => 'application/json' },\n"
    "    text: async () => '{\"error\":\"Authentication required\"}',\n"
    "  }"
)

_FETCH_REDIRECTED_TO_LOGIN = (
    "{\n"
    "    ok: true,\n"
    "    status: 200,\n"
    "    redirected: true,\n"
    "    url: 'https://example.test/login',\n"
    "    headers: { get: () => 'text/html' },\n"
    "    text: async () => '<html>Login</html>',\n"
    "  }"
)


def _build_driver(pathname, search, href_val, fetch_body):
    """Return a complete Node.js driver string for api() auth-redirect tests."""
    location_block = (
        "global.redirectedTo = null;\n"
        "global.window = {\n"
        "  location: {\n"
        f"    pathname: {json.dumps(pathname)},\n"
        f"    search: {json.dumps(search)},\n"
        "    hash: '',\n"
        "    set href(v) { global.redirectedTo = v; },\n"
        f"    get href() {{ return {json.dumps(href_val)}; }},\n"
        "  }\n"
        "};\n"
        "global.location = global.window.location;\n"
        "global.URL = URL;\n"
        "\n"
        "global.fetch = async function() {\n"
        f"  return {fetch_body};\n"
        "};\n"
    )
    return _EXTRACT_HELPER + "\n" + location_block + "\n" + _EVAL_AND_RUN


def _run_driver(tmp_path, driver_src):
    driver = tmp_path / "auth_redirect_driver.js"
    driver.write_text(driver_src, encoding="utf-8")
    result = subprocess.run(
        [NODE, str(driver), str(WORKSPACE_JS_PATH), str(UI_JS_PATH)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_api_rejects_instead_of_resolving_after_401_redirect(tmp_path):
    payload = _run_driver(tmp_path, _build_driver(
        pathname='/chat',
        search='?session_id=abc',
        href_val='https://example.test/chat?session_id=abc',
        fetch_body=_FETCH_401,
    ))
    assert payload["outcome"] == "rejected"
    assert payload["name"] == "AuthRedirectError"
    assert payload["authRedirect"] is True
    assert payload["redirectedTo"] == "/login?next=%2Fchat%3Fsession_id%3Dabc"


def test_api_rejects_after_401_redirect_on_subpath_mount(tmp_path):
    """Redirect URL must be relative to the subpath mount, not the server root."""
    payload = _run_driver(tmp_path, _build_driver(
        pathname='/hermes/chat',
        search='?session_id=abc',
        href_val='https://example.test/hermes/chat?session_id=abc',
        fetch_body=_FETCH_401,
    ))
    assert payload["outcome"] == "rejected"
    assert payload["name"] == "AuthRedirectError"
    assert payload["authRedirect"] is True
    assert payload["redirectedTo"] == "/hermes/login?next=%2Fhermes%2Fchat%3Fsession_id%3Dabc"


def test_api_rejects_on_html_redirect_to_login(tmp_path):
    """Transparent redirect to /login (status 200, res.redirected=true) must be detected."""
    payload = _run_driver(tmp_path, _build_driver(
        pathname='/chat',
        search='?session_id=abc',
        href_val='https://example.test/chat?session_id=abc',
        fetch_body=_FETCH_REDIRECTED_TO_LOGIN,
    ))
    assert payload["outcome"] == "rejected"
    assert payload["name"] == "AuthRedirectError"
    assert payload["authRedirect"] is True
    assert payload["redirectedTo"] == "/login?next=%2Fchat%3Fsession_id%3Dabc"


def test_api_does_not_redirect_on_non_login_redirect(tmp_path):
    """A transparent redirect to a path that merely contains 'login' but is not /login
    (e.g. /hermes/users/login-history) must NOT trigger an auth redirect."""
    fetch_body = (
        "{\n"
        "    ok: true,\n"
        "    status: 200,\n"
        "    redirected: true,\n"
        "    url: 'https://example.test/hermes/users/login-history',\n"
        "    headers: { get: () => 'application/json' },\n"
        "    json: async () => ({ result: 'ok' }),\n"
        "  }"
    )
    payload = _run_driver(tmp_path, _build_driver(
        pathname='/hermes/chat',
        search='?session_id=abc',
        href_val='https://example.test/hermes/chat?session_id=abc',
        fetch_body=fetch_body,
    ))
    assert payload["outcome"] == "resolved"
    assert payload["redirectedTo"] is None

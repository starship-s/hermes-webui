"""Regression: WebUI AIAgent call sites must use platform='webui', not 'cli'.

These are static source-level checks that will catch any future regression where
a developer accidentally reverts the platform kwarg back to 'cli'.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent

STREAMING_PY = (REPO_ROOT / "api" / "streaming.py").read_text(encoding="utf-8")
ROUTES_PY    = (REPO_ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_streaming_uses_webui_platform():
    """api/streaming.py must pass platform='webui' when constructing AIAgent."""
    assert "platform='webui'" in STREAMING_PY, (
        "streaming.py AIAgent construction must use platform='webui'"
    )
    assert "platform='cli'" not in STREAMING_PY, (
        "streaming.py must not pass platform='cli' to AIAgent"
    )


def test_routes_uses_webui_platform_for_all_agent_calls():
    """api/routes.py must use platform='webui' for all AIAgent instantiations."""
    webui_count = len(re.findall(r'platform\s*=\s*["\']webui["\']', ROUTES_PY))
    cli_count   = len(re.findall(r'platform\s*=\s*["\']cli["\']', ROUTES_PY))
    assert cli_count == 0, (
        f"routes.py still has {cli_count} platform='cli' AIAgent call(s); convert to 'webui'"
    )
    assert webui_count >= 2, (
        f"routes.py expected ≥2 platform='webui' calls, found {webui_count}"
    )

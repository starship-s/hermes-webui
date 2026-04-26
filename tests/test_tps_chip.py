"""
Tests for TPS chip fixes (fix/tps-chip-active-session-toggle).

Covers:
1. GlobalMeter.get_session_stats() returns stream_id for SSE isolation
2. Per-session stats don't bleed between concurrent streams
3. end_session() removes a session from active tracking
4. Frontend: #tpsStat is hidden by default in index.html
5. Frontend: settingsShowTpsChip checkbox exists in index.html
6. Frontend: hermes-show-tps-chip localStorage key used in panels.js
7. Frontend: _hideTpsChip helper defined in messages.js
8. Frontend: metering handler guards on session + stream match in messages.js
9. CSS: hidden TPS chip remains in layout so titlebar spacing matches master
"""
import sys
import os
import pathlib
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

REPO_ROOT   = pathlib.Path(__file__).parent.parent
INDEX_HTML  = (REPO_ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
MESSAGES_JS = (REPO_ROOT / 'static' / 'messages.js').read_text(encoding='utf-8')
PANELS_JS   = (REPO_ROOT / 'static' / 'panels.js').read_text(encoding='utf-8')
BOOT_JS     = (REPO_ROOT / 'static' / 'boot.js').read_text(encoding='utf-8')
STYLE_CSS   = (REPO_ROOT / 'static' / 'style.css').read_text(encoding='utf-8')


# ── Python / API tests ────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_meter():
    """Return a new GlobalMeter instance isolated from the module singleton."""
    from api.metering import GlobalMeter
    return GlobalMeter()


def test_get_session_stats_includes_stream_id(fresh_meter):
    """get_session_stats() must embed stream_id so the frontend can verify SSE origin."""
    sid = 'test-stream-abc'
    fresh_meter.begin_session(sid)
    stats = fresh_meter.get_session_stats(sid)
    assert stats['stream_id'] == sid, 'stream_id missing from get_session_stats() result'


def test_get_session_stats_returns_standard_keys(fresh_meter):
    """get_session_stats() result must include the standard tps/high/low/active keys."""
    sid = 'test-stream-xyz'
    fresh_meter.begin_session(sid)
    stats = fresh_meter.get_session_stats(sid)
    for key in ('tps', 'high', 'low', 'active'):
        assert key in stats, f'missing key {key!r} in get_session_stats() result'


def test_get_stats_does_not_include_stream_id(fresh_meter):
    """get_stats() must NOT include stream_id (unchanged global API)."""
    sid = 'test-stream-global'
    fresh_meter.begin_session(sid)
    stats = fresh_meter.get_stats()
    assert 'stream_id' not in stats, 'stream_id unexpectedly present in get_stats()'


def test_end_session_removes_from_active(fresh_meter):
    """end_session() must immediately remove the session so it no longer contributes TPS."""
    sid = 'test-stream-end'
    fresh_meter.begin_session(sid)
    # Record some tokens so the session is 'active'
    fresh_meter.record_token(sid, 100)
    time.sleep(0.05)
    fresh_meter.record_token(sid, 150)
    stats_before = fresh_meter.get_stats()
    assert stats_before['active'] >= 1

    fresh_meter.end_session(sid, 150)
    stats_after = fresh_meter.get_stats()
    assert stats_after['active'] == 0, 'session still counted as active after end_session()'


def test_two_sessions_have_isolated_tps(fresh_meter):
    """get_session_stats() must return each stream's own TPS, not the global average."""
    sid_a, sid_b = 'stream-A', 'stream-B'
    fresh_meter.begin_session(sid_a)
    fresh_meter.begin_session(sid_b)

    fresh_meter.record_token(sid_a, 1)
    fresh_meter.record_token(sid_b, 1)
    time.sleep(0.05)
    fresh_meter.record_token(sid_a, 2)
    fresh_meter.record_token(sid_b, 10)

    stats_a = fresh_meter.get_session_stats(sid_a)
    stats_b = fresh_meter.get_session_stats(sid_b)
    global_stats = fresh_meter.get_stats()

    assert stats_a['stream_id'] == sid_a
    assert stats_b['stream_id'] == sid_b
    assert stats_a['tps'] >= 0
    assert stats_b['tps'] >= 0
    assert stats_a['tps'] != stats_b['tps'], 'per-session TPS should differ for different token counts'
    expected_global = round((stats_a['tps'] + stats_b['tps']) / 2, 1)
    assert abs(global_stats['tps'] - expected_global) <= 0.2


def test_two_sessions_have_isolated_high_low(fresh_meter):
    """HIGH/LOW in get_session_stats() must be scoped to the requested stream."""
    sid_a, sid_b = 'stream-A', 'stream-B'
    fresh_meter.begin_session(sid_a)
    fresh_meter.begin_session(sid_b)

    fresh_meter.record_token(sid_a, 1)
    fresh_meter.record_token(sid_b, 1)
    time.sleep(0.05)
    fresh_meter.record_token(sid_a, 2)
    fresh_meter.record_token(sid_b, 12)

    stats_a = fresh_meter.get_session_stats(sid_a)
    stats_b = fresh_meter.get_session_stats(sid_b)

    assert stats_a['tps'] != stats_b['tps']
    assert stats_a['high'] == stats_a['tps']
    assert stats_a['low'] == stats_a['tps']
    assert stats_b['high'] == stats_b['tps']
    assert stats_b['low'] == stats_b['tps']
    assert stats_a['high'] != stats_b['high']
    assert stats_a['low'] != stats_b['low']


# ── Frontend static tests ─────────────────────────────────────────────────────

def test_tps_chip_hidden_by_default():
    """#tpsStat must have the hidden attribute so it starts invisible."""
    assert 'id="tpsStat" hidden' in INDEX_HTML, (
        '#tpsStat must have the hidden attribute — chip should start invisible'
    )


def test_settings_tps_chip_checkbox_exists():
    """Settings panel must include the settingsShowTpsChip checkbox."""
    assert 'id="settingsShowTpsChip"' in INDEX_HTML, (
        'Missing settingsShowTpsChip checkbox in settings panel'
    )


def test_settings_tps_chip_label_is_user_friendly():
    """Settings copy should describe the user-visible behavior, not implementation jargon."""
    assert 'Show response speed in title bar' in INDEX_HTML
    assert "settings_label_tps_chip: 'Show response speed in title bar'" in (REPO_ROOT / 'static' / 'i18n.js').read_text(encoding='utf-8')
    assert 'Live TPS chip in titlebar' not in INDEX_HTML


def test_panels_js_reads_tps_chip_localstorage():
    """panels.js must read hermes-show-tps-chip from localStorage to initialise the checkbox."""
    assert 'hermes-show-tps-chip' in PANELS_JS, (
        "panels.js does not reference 'hermes-show-tps-chip' localStorage key"
    )


def test_panels_js_writes_tps_chip_localstorage():
    """panels.js change handler must write hermes-show-tps-chip to localStorage."""
    assert "localStorage.setItem('hermes-show-tps-chip'" in PANELS_JS, (
        "panels.js does not write 'hermes-show-tps-chip' to localStorage on change"
    )


def test_messages_js_hide_tps_chip_helper():
    """messages.js must define _hideTpsChip() helper."""
    assert 'function _hideTpsChip()' in MESSAGES_JS, (
        'Missing _hideTpsChip() helper in messages.js'
    )


def test_messages_js_metering_guards_session():
    """metering handler must guard on S.session.session_id === activeSid."""
    assert 'S.session.session_id!==activeSid' in MESSAGES_JS, (
        'metering handler missing session guard (S.session.session_id!==activeSid)'
    )


def test_messages_js_metering_ignores_nonmatching_stream_without_hiding():
    """Background stream metering must not hide the viewed active stream's chip."""
    assert 'if(d.stream_id!==streamId) return;' in MESSAGES_JS
    assert 'if(d.stream_id&&d.stream_id!==streamId){_hideTpsChip();return;}' not in MESSAGES_JS


def test_messages_js_metering_guards_preference():
    """metering handler must gate on hermes-show-tps-chip localStorage preference."""
    assert "hermes-show-tps-chip" in MESSAGES_JS, (
        "metering handler does not check 'hermes-show-tps-chip' preference"
    )


def test_messages_js_done_hides_chip():
    """done event handler must call _hideTpsChip()."""
    assert '_hideTpsChip()' in MESSAGES_JS, (
        'messages.js does not call _hideTpsChip() — chip will persist after stream ends'
    )


def test_boot_cancel_stream_hides_chip():
    """Guaranteed cancelStream cleanup path must hide TPS even if SSE cancel never arrives."""
    assert "if(typeof _hideTpsChip==='function') _hideTpsChip();" in BOOT_JS


def test_css_tps_chip_hidden_preserves_titlebar_slot():
    """Hidden TPS text should remain in flex layout so mobile title alignment matches master."""
    assert '.tps-chip[hidden]{display:block;visibility:hidden;}' in STYLE_CSS
    assert '.tps-chip[hidden]{display:none;}' not in STYLE_CSS


def test_messages_js_hidden_chip_uses_placeholder_text():
    """Idle/disabled chip should be invisible but keep the same width as the live counter slot."""
    assert "el.textContent='0.0 t/s · 0.0 high';" in MESSAGES_JS


def test_messages_js_does_not_add_mobile_specific_tps_layout():
    """Keep TPS rendering aligned with master; do not add separate mobile titlebar layout logic."""
    assert "matchMedia('(max-width:520px)')" not in MESSAGES_JS

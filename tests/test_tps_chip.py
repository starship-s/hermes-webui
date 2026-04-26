"""Static tests for TPS chip visibility toggle (#tps-chip-toggle)."""
import os

_SRC = os.path.join(os.path.dirname(__file__), "..")


def _read(name):
    return open(os.path.join(_SRC, name), encoding="utf-8").read()


class TestTpsChipHtml:
    """The TPS chip element must exist and be hidden by default."""

    def test_tps_chip_element_exists(self):
        html = _read("static/index.html")
        assert 'id="tpsStat"' in html, "index.html must contain #tpsStat element"

    def test_tps_chip_hidden_by_default(self):
        html = _read("static/index.html")
        # The element must carry the hidden attribute so it starts invisible
        idx = html.find('id="tpsStat"')
        assert idx != -1, "#tpsStat not found"
        tag_start = html.rfind('<', 0, idx)
        tag_end = html.find('>', idx)
        tag = html[tag_start:tag_end + 1]
        assert 'hidden' in tag, "#tpsStat must carry the hidden attribute by default"

    def test_tps_chip_settings_checkbox_exists(self):
        html = _read("static/index.html")
        assert 'id="settingsShowTpsChip"' in html, (
            "index.html must contain #settingsShowTpsChip checkbox"
        )

    def test_tps_chip_i18n_label_referenced(self):
        html = _read("static/index.html")
        assert 'settings_label_tps_chip' in html or 'settingsShowTpsChip' in html, (
            "Settings panel must reference the TPS chip toggle"
        )


class TestTpsChipI18n:
    """The TPS chip i18n keys must exist in all locales."""

    def test_tps_chip_label_key_present(self):
        src = _read("static/i18n.js")
        count = src.count("settings_label_tps_chip")
        assert count >= 2, (
            f"settings_label_tps_chip must appear in at least 2 locales, found {count}"
        )

    def test_tps_chip_desc_key_present(self):
        src = _read("static/i18n.js")
        count = src.count("settings_desc_tps_chip")
        assert count >= 2, (
            f"settings_desc_tps_chip must appear in at least 2 locales, found {count}"
        )


class TestTpsChipPanelsJs:
    """panels.js must initialize the TPS chip toggle from localStorage."""

    def test_reads_hermes_show_tps_chip_key(self):
        src = _read("static/panels.js")
        assert "hermes-show-tps-chip" in src, (
            "panels.js must read/write 'hermes-show-tps-chip' localStorage key"
        )

    def test_settingsShowTpsChip_initialized(self):
        src = _read("static/panels.js")
        assert "settingsShowTpsChip" in src, (
            "panels.js must reference settingsShowTpsChip"
        )

    def test_persists_on_change(self):
        src = _read("static/panels.js")
        idx = src.find("hermes-show-tps-chip")
        block = src[max(0, idx - 20):idx + 300]
        assert "localStorage.setItem" in block, (
            "panels.js must persist hermes-show-tps-chip to localStorage on change"
        )

    def test_calls_hideTpsChip_when_turned_off(self):
        src = _read("static/panels.js")
        idx = src.find("settingsShowTpsChip")
        block = src[idx:idx + 400]
        assert "_hideTpsChip" in block, (
            "panels.js must call _hideTpsChip() when the toggle is turned off"
        )


class TestTpsChipMessagesJs:
    """messages.js must define _hideTpsChip and call it at stream end."""

    def test_hideTpsChip_defined(self):
        src = _read("static/messages.js")
        assert "function _hideTpsChip(" in src, (
            "messages.js must define _hideTpsChip()"
        )

    def test_hideTpsChip_sets_hidden_attribute(self):
        src = _read("static/messages.js")
        idx = src.find("function _hideTpsChip(")
        block = src[idx:idx + 200]
        assert "setAttribute('hidden'" in block or 'setAttribute("hidden"' in block, (
            "_hideTpsChip must set the hidden attribute on #tpsStat"
        )

    def test_metering_hides_on_terminal_state(self):
        src = _read("static/messages.js")
        idx = src.find("addEventListener('metering'")
        block = src[idx:idx + 500]
        assert "_terminalStateReached" in block, (
            "metering handler must check _terminalStateReached before showing chip"
        )
        assert "_hideTpsChip" in block, (
            "metering handler must call _hideTpsChip() on terminal state"
        )

    def test_metering_respects_localstorage_toggle(self):
        src = _read("static/messages.js")
        idx = src.find("addEventListener('metering'")
        block = src[idx:idx + 500]
        assert "hermes-show-tps-chip" in block, (
            "metering handler must check hermes-show-tps-chip localStorage key"
        )

    def test_metering_unhides_chip_when_active(self):
        src = _read("static/messages.js")
        idx = src.find("addEventListener('metering'")
        block = src[idx:idx + 900]
        assert "removeAttribute('hidden')" in block or "removeAttribute(\"hidden\")" in block, (
            "metering handler must call removeAttribute('hidden') to show chip when streaming"
        )

    def test_done_calls_hideTpsChip(self):
        src = _read("static/messages.js")
        done_idx = src.find("addEventListener('done'")
        block = src[done_idx:done_idx + 3500]
        assert "_hideTpsChip" in block, (
            "done handler must call _hideTpsChip()"
        )

    def test_apperror_calls_hideTpsChip(self):
        src = _read("static/messages.js")
        idx = src.find("addEventListener('apperror'")
        block = src[idx:idx + 2600]
        assert "_hideTpsChip" in block, (
            "apperror handler must call _hideTpsChip()"
        )

    def test_cancel_calls_hideTpsChip(self):
        src = _read("static/messages.js")
        idx = src.find("addEventListener('cancel'")
        block = src[idx:idx + 2200]
        assert "_hideTpsChip" in block, (
            "cancel handler must call _hideTpsChip()"
        )

    def test_handleStreamError_calls_hideTpsChip(self):
        src = _read("static/messages.js")
        idx = src.find("function _handleStreamError(")
        block = src[idx:idx + 1600]
        assert "_hideTpsChip" in block, (
            "_handleStreamError must call _hideTpsChip()"
        )


class TestTpsChipBootJs:
    """cancelStream in boot.js must call _hideTpsChip."""

    def test_cancelStream_calls_hideTpsChip(self):
        src = _read("static/boot.js")
        idx = src.find("async function cancelStream(")
        block = src[idx:idx + 750]
        assert "_hideTpsChip" in block, (
            "cancelStream must call _hideTpsChip() if available"
        )


class TestTpsChipSessionsJs:
    """sessions.js must hide the TPS chip on session switch and new session."""

    def test_newSession_calls_hideTpsChip(self):
        src = _read("static/sessions.js")
        idx = src.find("async function newSession(")
        block = src[idx:idx + 2200]
        assert "_hideTpsChip" in block, (
            "newSession must call _hideTpsChip() to reset the chip"
        )

    def test_loadSession_calls_hideTpsChip(self):
        src = _read("static/sessions.js")
        idx = src.find("async function loadSession(")
        block = src[idx:idx + 1200]
        assert "_hideTpsChip" in block, (
            "loadSession must call _hideTpsChip() when switching sessions"
        )


class TestTpsChipMobileCss:
    """CSS must hide the TPS chip space on mobile and center the title."""

    def test_mobile_tps_chip_hidden_is_display_none(self):
        css = _read("static/style.css")
        # In the mobile media query block, hidden chip must use display:none
        # to remove reserved space (vs desktop which uses visibility:hidden)
        mobile_idx = css.find("max-width:")
        assert mobile_idx != -1, "No mobile media query found"
        mobile_block = css[mobile_idx:mobile_idx + 3000]
        assert ".tps-chip[hidden]{display:none}" in mobile_block or (
            ".tps-chip[hidden]" in mobile_block and "display:none" in mobile_block
        ), "Mobile CSS must set .tps-chip[hidden]{display:none} to remove reserved space"

    def test_mobile_centers_title_when_chip_hidden(self):
        css = _read("static/style.css")
        assert "justify-content:center" in css, (
            "CSS must center the titlebar content when TPS chip is hidden on mobile"
        )
        assert ":has(>.tps-chip[hidden])" in css or "tps-chip[hidden]" in css, (
            "CSS must use :has selector or equivalent to detect hidden TPS chip"
        )

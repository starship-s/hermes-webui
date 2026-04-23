"""Regression test: first streaming segment must render through renderMd().

Bug: In _scheduleRender(), the ternary for segmentStart===0 used raw
parsed.displayText, bypassing renderMd().  This meant the first segment
(before any tool call) showed unformatted text — no bold, no code blocks,
no lists — while later segments rendered correctly through renderMd().

Fix: Changed the ternary so segmentStart===0 also routes through renderMd().
"""
import pathlib
import re

REPO = pathlib.Path(__file__).parent.parent


def _read(rel):
    return (REPO / rel).read_text(encoding='utf-8')


class TestFirstSegmentMarkdown:
    """Verify _scheduleRender applies renderMd to the first segment."""

    def test_schedule_render_uses_rendermd_for_first_segment(self):
        """The segmentStart===0 branch must call renderMd, not use raw text."""
        src = _read('static/messages.js')
        # Find _scheduleRender function body
        m = re.search(r'function _scheduleRender\(\)\{.*?\n  \}', src, re.DOTALL)
        assert m, "_scheduleRender not found"
        fn = m.group(0)

        # The first-segment branch (segmentStart===0) should call renderMd
        # on parsed.displayText, not use it raw.
        first_seg_branch = re.search(
            r'segmentStart===0\s*\?\s*\((.*?)\)\s*:', fn, re.DOTALL
        )
        assert first_seg_branch, (
            "segmentStart===0 ternary branch not found — expected "
            "`segmentStart===0 ? (renderMd ? renderMd(parsed.displayText) : ...)`"
        )
        branch = first_seg_branch.group(1)
        assert 'renderMd' in branch, (
            "First segment (segmentStart===0) must route through renderMd(). "
            f"Got instead: {branch!r}"
        )

    def test_both_segment_branches_use_rendermd(self):
        """Both the first-segment and later-segment branches should reference renderMd."""
        src = _read('static/messages.js')
        m = re.search(r'function _scheduleRender\(\)\{.*?\n  \}', src, re.DOTALL)
        assert m, "_scheduleRender not found"
        fn = m.group(0)

        # Count renderMd references in the segment rendering logic
        # There should be at least two: one for segmentStart===0, one for the else
        segText_line = re.search(r'const segText\s*=.*?;', fn, re.DOTALL)
        assert segText_line, "const segText assignment not found"
        assignment = segText_line.group(0)

        rendermd_count = len(re.findall(r'renderMd', assignment))
        assert rendermd_count >= 2, (
            f"Expected renderMd referenced at least twice in segText assignment "
            f"(once per branch), found {rendermd_count} in: {assignment!r}"
        )

    def test_no_raw_displayText_without_rendermd(self):
        """parsed.displayText must never appear as the sole RHS (raw) in the ternary."""
        src = _read('static/messages.js')
        m = re.search(r'function _scheduleRender\(\)\{.*?\n  \}', src, re.DOTALL)
        assert m, "_scheduleRender not found"
        fn = m.group(0)

        # The old bug had: segmentStart===0 ? parsed.displayText : ...
        # The fix wraps it: segmentStart===0 ? (renderMd ? renderMd(parsed.displayText) : parsed.displayText) : ...
        bad_pattern = re.search(
            r'segmentStart===0\s*\?\s*parsed\.displayText\s*:', fn
        )
        assert not bad_pattern, (
            "segmentStart===0 branch uses raw parsed.displayText without "
            "renderMd wrapper — markdown will not render for the first segment"
        )

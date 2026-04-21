"""
Tests for code block &quot; double-encoding bug.

Root cause: the autolink pass in renderMd() was matching URLs inside
<pre><code> blocks and calling esc() on already-escaped content, turning
&quot; into &amp;quot; which the browser renders as literal &quot; text.

The fix moves the _pre_stash (which protects <pre> blocks) to run BEFORE
the autolink pass, so URLs inside code blocks are never autolinked.
"""
import re
import subprocess
import os
import tempfile

UI_JS = os.path.join(os.path.dirname(__file__), '..', 'static', 'ui.js')


def get_ui_js():
    return open(UI_JS, encoding='utf-8').read()


def _extract_renderMd_test_script(test_body):
    """Build a standalone Node script with esc + renderMd + test assertions."""
    src = get_ui_js()
    # Find renderMd function boundaries
    fn_start = src.index('function renderMd(raw){')
    depth = 0
    fn_end = fn_start
    for i in range(fn_start, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                fn_end = i + 1
                break
    rendermd_fn = src[fn_start:fn_end]
    # Find esc function (may span multiple lines due to object literal)
    esc_match = re.search(r"const esc=s=>String\(s\?\?''\)\.replace\(/\[&<>\"'\]/g,c=>\(\{[^}]+\}\[c\]\)\);", src)
    if not esc_match:
        # Fallback: find line-by-line
        for line in src.splitlines():
            if line.startswith('const esc='):
                esc_fn = line
                break
    else:
        esc_fn = esc_match.group(0)
    return esc_fn + '\n' + rendermd_fn + '\n' + test_body


def _run_node_test(test_body):
    """Write test script to temp file and run with node. Returns (returncode, stdout, stderr)."""
    script = _extract_renderMd_test_script(test_body)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(script)
        f.flush()
        tmppath = f.name
    try:
        result = subprocess.run(
            ['node', tmppath],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        os.unlink(tmppath)


class TestCodeBlockQuotEscape:

    def test_js_syntax_valid(self):
        """ui.js must pass node --check after the fix."""
        result = subprocess.run(
            ['node', '--check', UI_JS],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"node --check failed:\n{result.stderr}"

    def test_pre_stash_before_autolink(self):
        """_pre_stash must be populated BEFORE the autolink regex runs."""
        src = get_ui_js()
        pre_stash_pos = src.index('_pre_stash=[]')
        # The autolink pass is the one preceded by the "Autolink:" comment
        autolink_comment = src.index('Autolink: convert plain URLs')
        assert pre_stash_pos < autolink_comment, \
            "_pre_stash must be initialised before the autolink pass"

    def test_pre_stash_before_safe_tags_escape(self):
        """_pre_stash must be populated BEFORE the SAFE_TAGS escape pass."""
        src = get_ui_js()
        pre_stash_pos = src.index('_pre_stash=[]')
        safe_tags_pos = src.index('SAFE_TAGS')
        assert pre_stash_pos < safe_tags_pos, \
            "_pre_stash must be initialised before the SAFE_TAGS escape pass"

    def test_autolink_does_not_match_inside_pre_blocks(self):
        """Verify structurally that _pre_stash runs before the autolink regex."""
        src = get_ui_js()
        autolink_start = src.index('Autolink: convert plain URLs')
        pre_stash_init = src.index('_pre_stash=[]')
        assert pre_stash_init < autolink_start, \
            "_pre_stash must run before autolink to protect code block URLs"

    def test_no_double_encoding_structure(self):
        """Verify the _pre_stash regex captures <pre> blocks."""
        src = get_ui_js()
        pre_stash_block_start = src.index('_pre_stash=[]')
        pre_stash_block = src[pre_stash_block_start:pre_stash_block_start + 400]
        assert '<pre>' in pre_stash_block, \
            "pre-stash regex must match <pre> blocks"
        assert '\\x00E' in pre_stash_block, \
            "pre-stash must use \\x00E tokens"

    def test_restore_still_after_paragraph_split(self):
        """_pre_stash restore must still happen after the paragraph split."""
        src = get_ui_js()
        restore_pos = src.rindex('_pre_stash[+i]')
        split_pos = src.rindex('const parts=s.split(')
        paragraph_join = src.index("}).join('\\n');", split_pos)
        assert restore_pos > paragraph_join, \
            "_pre_stash must be restored after the paragraph split/join"

    def test_pre_stash_covers_pre_header(self):
        """The stash regex must still cover pre-header divs."""
        src = get_ui_js()
        pre_stash_block_start = src.index('_pre_stash=[]')
        pre_stash_block = src[pre_stash_block_start:pre_stash_block_start + 400]
        assert 'pre-header' in pre_stash_block, \
            "pre-stash regex must cover pre-header divs"

    def test_pre_stash_covers_mermaid(self):
        """The stash regex must still cover mermaid blocks."""
        src = get_ui_js()
        pre_stash_block_start = src.index('_pre_stash=[]')
        pre_stash_block = src[pre_stash_block_start:pre_stash_block_start + 400]
        assert 'mermaid-block' in pre_stash_block, \
            "pre-stash regex must cover mermaid blocks"

    def test_pre_stash_covers_katex(self):
        """The stash regex must still cover katex blocks."""
        src = get_ui_js()
        pre_stash_block_start = src.index('_pre_stash=[]')
        pre_stash_block = src[pre_stash_block_start:pre_stash_block_start + 400]
        assert 'katex-block' in pre_stash_block, \
            "pre-stash regex must cover katex blocks"

    def test_node_rendermd_no_double_escape(self):
        """Integration: renderMd must not produce &amp;quot; for code blocks with quotes."""
        test_body = r"""
const input = '```\ncurl -sL "https://example.com/file" -o /tmp/file\n```';
const output = renderMd(input);
// Must NOT contain double-encoded entities
if (output.includes('&amp;quot;')) {
  console.error('FAIL: double-encoded &amp;quot; found in output');
  process.exit(1);
}
// Must NOT autolink URLs inside <pre> blocks
if (/<pre><code>[^]*<a href=/.test(output)) {
  console.error('FAIL: autolinked URL found inside <pre><code>');
  process.exit(1);
}
// Must contain properly escaped code block
if (!output.includes('<pre><code>')) {
  console.error('FAIL: no <pre><code> in output');
  process.exit(1);
}
console.log('PASS');
"""
        rc, stdout, stderr = _run_node_test(test_body)
        assert rc == 0, f"renderMd test failed:\nstdout: {stdout}\nstderr: {stderr}"
        assert 'PASS' in stdout, f"renderMd test did not PASS:\nstdout: {stdout}\nstderr: {stderr}"

    def test_node_rendermd_url_in_code_not_autolinked(self):
        """Integration: URLs inside code blocks must not become <a> tags."""
        test_body = r"""
const input = '```\nVisit https://example.com for info\n```';
const output = renderMd(input);
// Extract the <pre> block content
const preMatch = output.match(/<pre><code>([^]*?)<\/code><\/pre>/);
if (preMatch && preMatch[1].includes('<a ')) {
  console.error('FAIL: URL inside code block was autolinked:', preMatch[1]);
  process.exit(1);
}
console.log('PASS');
"""
        rc, stdout, stderr = _run_node_test(test_body)
        assert rc == 0, f"URL autolink test failed:\nstdout: {stdout}\nstderr: {stderr}"
        assert 'PASS' in stdout, f"URL autolink test did not PASS:\nstdout: {stdout}\nstderr: {stderr}"

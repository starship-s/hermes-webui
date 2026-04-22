"""Tests for slash command echo (#840) — user message shown in chat after /skills, /help, etc."""
import os

_SRC = os.path.join(os.path.dirname(__file__), "..")


def _read(name):
    return open(os.path.join(_SRC, name), encoding="utf-8").read()


class TestExecuteCommandReturnValue:
    """executeCommand() now returns null or {noEcho:bool} instead of true/false."""

    def test_execute_command_returns_null_on_no_match(self):
        src = _read("static/commands.js")
        idx = src.find("function executeCommand(")
        block = src[idx:idx + 400]
        # Must return null (not false) when no command matched
        assert "return null;" in block, (
            "executeCommand must return null when no command found (not false)"
        )

    def test_execute_command_returns_noecho_object(self):
        src = _read("static/commands.js")
        assert "return {noEcho:" in src, (
            "executeCommand must return {noEcho:...} when a command runs"
        )

    def test_no_echo_flag_on_clear(self):
        src = _read("static/commands.js")
        # Find the clear command entry
        idx = src.find("name:'clear'")
        assert idx >= 0
        entry = src[idx:idx + 100]
        assert "noEcho:true" in entry, "/clear must have noEcho:true"

    def test_no_echo_flag_on_new(self):
        src = _read("static/commands.js")
        idx = src.find("name:'new'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/new must have noEcho:true"

    def test_no_echo_flag_on_stop(self):
        src = _read("static/commands.js")
        idx = src.find("name:'stop'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/stop must have noEcho:true"

    def test_no_echo_flag_on_retry(self):
        src = _read("static/commands.js")
        idx = src.find("name:'retry'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/retry must have noEcho:true"

    def test_no_echo_flag_on_undo(self):
        src = _read("static/commands.js")
        idx = src.find("name:'undo'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/undo must have noEcho:true"

    def test_no_echo_flag_on_voice(self):
        src = _read("static/commands.js")
        idx = src.find("name:'voice'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/voice must have noEcho:true"

    def test_no_echo_flag_on_theme(self):
        src = _read("static/commands.js")
        idx = src.find("name:'theme'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho:true" in entry, "/theme must have noEcho:true"

    def test_no_echo_flag_on_model(self):
        src = _read("static/commands.js")
        idx = src.find("name:'model'")
        assert idx >= 0
        entry = src[idx:idx + 130]
        assert "noEcho:true" in entry, "/model must have noEcho:true"

    def test_skills_has_no_noecho(self):
        """Commands that produce chat responses must NOT have noEcho."""
        src = _read("static/commands.js")
        idx = src.find("name:'skills'")
        assert idx >= 0
        entry = src[idx:idx + 100]
        assert "noEcho" not in entry, "/skills must echo — no noEcho flag"

    def test_help_has_no_noecho(self):
        src = _read("static/commands.js")
        idx = src.find("name:'help'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho" not in entry, "/help must echo — no noEcho flag"

    def test_status_has_no_noecho(self):
        src = _read("static/commands.js")
        idx = src.find("name:'status'")
        assert idx >= 0
        entry = src[idx:idx + 80]
        assert "noEcho" not in entry, "/status must echo — no noEcho flag"


class TestSendSlashIntercept:
    """send() in messages.js must push user message for echo-worthy commands."""

    def test_send_checks_noecho_flag(self):
        src = _read("static/messages.js")
        idx = src.find("Slash command intercept")
        block = src[idx:idx + 1400]
        assert "_cmd.noEcho" in block or "cmd.noEcho" in block, (
            "send() must check the command's noEcho flag before pushing user message (#840)"
        )

    def test_send_pushes_user_message_for_echo_commands(self):
        src = _read("static/messages.js")
        idx = src.find("Slash command intercept")
        block = src[idx:idx + 1400]
        assert "role:'user'" in block and "content:text" in block, (
            "send() must push {role:'user', content:text} for echo-worthy slash commands (#840)"
        )

    def test_send_pushes_user_message_before_running_handler(self):
        """Ordering fix: cmdHelp-style handlers push their assistant response
        synchronously.  The user message must be pushed BEFORE the handler
        runs so S.messages ends up [user, assistant] — not [assistant, user]
        which would display in reverse chronological order."""
        src = _read("static/messages.js")
        idx = src.find("Slash command intercept")
        block = src[idx:idx + 1400]
        user_push_pos = block.find("role:'user'")
        handler_call_pos = block.find("_cmd.fn(")
        if handler_call_pos == -1:
            handler_call_pos = block.find("cmd.fn(")
        assert user_push_pos != -1, "user message push not found in intercept block"
        assert handler_call_pos != -1, "handler invocation not found in intercept block"
        assert user_push_pos < handler_call_pos, (
            "User message must be pushed BEFORE the handler runs — otherwise "
            "sync handlers like cmdHelp push the assistant response first and "
            "the chat displays in reverse chronological order."
        )

    def test_send_rolls_back_user_push_on_handler_optout(self):
        """If a handler returns false (opt-out — e.g. /reasoning <level>),
        the pre-pushed user message must be rolled back so the normal send path
        can add it cleanly for forwarding to the agent."""
        src = _read("static/messages.js")
        idx = src.find("Slash command intercept")
        block = src[idx:idx + 1400]
        assert "S.messages.length=_lenBefore" in block, (
            "send() must use S.messages.length=_lenBefore on handler opt-out "
            "to roll back the user echo push, avoiding the fragility of pop() "
            "which could remove a wrong message if a handler pushed one first."
        )
        assert "===false" in block or "=== false" in block, (
            "opt-out must be detected by handler returning === false"
        )


def test_compress_has_no_echo_flag():
    """compress is action-only — it resets S.messages internally; echo would flicker."""
    src = _read("static/commands.js")
    import re
    m = re.search(r"\{name:'compress'[^}]+\}", src)
    assert m, "compress entry not found in COMMANDS"
    assert 'noEcho:true' in m.group(), f"compress missing noEcho:true: {m.group()}"


def test_compact_has_no_echo_flag():
    """compact is an alias for compress — same noEcho requirement."""
    src = _read("static/commands.js")
    import re
    m = re.search(r"\{name:'compact'[^}]+\}", src)
    assert m, "compact entry not found in COMMANDS"
    assert 'noEcho:true' in m.group(), f"compact missing noEcho:true: {m.group()}"


def test_title_with_args_pushes_confirmation_message():
    """When /title <name> succeeds, cmdTitle pushes an assistant confirmation bubble."""
    src = _read("static/commands.js")
    # After the rename API call succeeds, an assistant message is pushed
    idx = src.find("title_set")
    segment = src[idx: idx + 300]
    assert 'S.messages.push' in segment, "cmdTitle success path must push an assistant message"
    assert "role:'assistant'" in segment, "cmdTitle confirmation must have role:assistant"


def test_personality_with_args_pushes_confirmation_message():
    """When /personality <name> succeeds, cmdPersonality pushes an assistant confirmation bubble."""
    src = _read("static/commands.js")
    # Find the set-personality success path (after the clear/none/default branch)
    # S.messages.push comes BEFORE the personality_set toast
    idx = src.find("personality_set')+`**${name}**`")
    assert idx != -1, "cmdPersonality confirmation push not found in source"
    segment = src[max(0, idx-100): idx + 200]
    assert 'S.messages.push' in segment, "cmdPersonality success path must push an assistant message"
    assert "role:'assistant'" in segment, "cmdPersonality confirmation must have role:assistant"


class TestSlashEchoRollback:
    """Regression tests for the S.messages.pop() → length-snapshot rollback fix.

    The original code used S.messages.pop() to undo the user echo push when a
    slash-command handler opted out (returned false). This was fragile: if a
    handler had pushed an assistant message synchronously before returning false,
    pop() would remove the assistant message instead of the user echo.

    The fix snapshots S.messages.length before the push and rolls back to that
    length, which correctly removes all messages added by the echo+handler path
    regardless of how many were inserted.
    """

    def test_send_uses_length_snapshot_for_rollback(self):
        """send() must use S.messages.length = _lenBefore for rollback, not pop()."""
        src = _read("static/messages.js")
        # Find the slash command intercept block
        idx = src.find("Slash command intercept")
        assert idx != -1, "Slash command intercept block not found in messages.js"
        block = src[idx:idx + 2000]
        # The fix uses length assignment instead of pop()
        assert "_lenBefore" in block, (
            "send() must capture S.messages.length as _lenBefore before the "
            "user echo push for correct rollback"
        )
        assert "S.messages.length=_lenBefore" in block, (
            "Rollback must use S.messages.length=_lenBefore instead of "
            "S.messages.pop() to correctly handle cases where a handler has "
            "pushed additional messages before returning false"
        )

    def test_send_no_longer_uses_pop_for_rollback(self):
        """The old S.messages.pop() pattern must no longer appear in the
        slash command rollback path (it should use length-snapshot instead)."""
        src = _read("static/messages.js")
        idx = src.find("Slash command intercept")
        assert idx != -1
        block = src[idx:idx + 2000]
        # Find the "opt-out" rollback line
        optout_idx = block.find("===false")
        assert optout_idx != -1, "Opt-out detection (===false) not found"
        rollback_block = block[optout_idx:optout_idx + 200]
        assert "S.messages.pop()" not in rollback_block, (
            "The slash-command rollback must not use S.messages.pop() — "
            "use S.messages.length=_lenBefore instead so that a handler "
            "that pushed an assistant message does not lose it on rollback"
        )

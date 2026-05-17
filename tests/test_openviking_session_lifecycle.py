"""Regression tests for WebUI memory-session lifecycle commits.

These tests pin the OpenViking/Holographic batch-extraction lifecycle wiring:
completed turns and session boundaries must be able to commit the same WebUI
session more than once across reopen/continue flows.
"""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
STREAMING_SRC = (REPO / "api" / "streaming.py").read_text(encoding="utf-8")
CONFIG_SRC = (REPO / "api" / "config.py").read_text(encoding="utf-8")
ROUTES_SRC = (REPO / "api" / "routes.py").read_text(encoding="utf-8")


def test_session_lifecycle_allows_reopen_then_second_commit(monkeypatch):
    """A session can be committed, reopened/re-registered, and committed again.

    This is the reopened t2 gap: commit_session_memory() unregisters the agent
    after a successful boundary commit so a repeated boundary with no new work is
    not duplicated.  When the user later continues the same WebUI session, the
    streaming cache-hit path must mark/register the agent again; the next
    boundary must then flush the new turn instead of treating the old commit as
    final.
    """
    import api.session_lifecycle as lifecycle
    from api import config as cfg

    with lifecycle._pending_lock:
        old_pending = dict(lifecycle._pending_agents)
        old_dirty = set(lifecycle._dirty_sessions)
        lifecycle._pending_agents.clear()
        lifecycle._dirty_sessions.clear()
    with lifecycle._committing_lock:
        old_committing = set(lifecycle._committing_sessions)
        lifecycle._committing_sessions.clear()
    with cfg.SESSION_AGENT_CACHE_LOCK:
        old_cache = cfg.SESSION_AGENT_CACHE.copy()
        cfg.SESSION_AGENT_CACHE.clear()

    calls: list[str] = []

    class Agent:
        def commit_memory_session(self):
            calls.append("commit")

    try:
        agent = Agent()
        with cfg.SESSION_AGENT_CACHE_LOCK:
            cfg.SESSION_AGENT_CACHE["sid-t2"] = (agent, "sig")
        lifecycle.register_agent("sid-t2", agent)
        lifecycle.mark_session_active("sid-t2")
        lifecycle.commit_session_memory("sid-t2")
        assert calls == ["commit"]

        # The first successful commit clears the dirty marker.  A second
        # boundary with no new turn should not duplicate the same commit, even
        # though the cached agent is still reachable.
        lifecycle.commit_session_memory("sid-t2")
        assert calls == ["commit"]

        # Reopened/cached sessions are marked and registered again before the
        # next turn; the following boundary must commit the new lifetime too.
        lifecycle.register_agent("sid-t2", agent)
        lifecycle.mark_session_active("sid-t2")
        lifecycle.commit_session_memory("sid-t2")
        assert calls == ["commit", "commit"]
    finally:
        with lifecycle._pending_lock:
            lifecycle._pending_agents.clear()
            lifecycle._pending_agents.update(old_pending)
            lifecycle._dirty_sessions.clear()
            lifecycle._dirty_sessions.update(old_dirty)
        with lifecycle._committing_lock:
            lifecycle._committing_sessions.clear()
            lifecycle._committing_sessions.update(old_committing)
        with cfg.SESSION_AGENT_CACHE_LOCK:
            cfg.SESSION_AGENT_CACHE.clear()
            cfg.SESSION_AGENT_CACHE.update(old_cache)


def test_streaming_re_registers_reused_cached_agents_for_later_lifecycle_commits():
    reuse_idx = STREAMING_SRC.index("Re-register reused cached agents with lifecycle tracking")
    block = STREAMING_SRC[reuse_idx : reuse_idx + 1200]

    assert "from api.session_lifecycle import register_agent" in block
    assert "register_agent(session_id, agent)" in block
    assert block.index("register_agent(session_id, agent)") < block.index("_refresh_cached_agent_runtime"), (
        "cache-hit turns must re-register the agent before continuing, so a "
        "post-turn or later boundary commit can find it even after a prior "
        "commit unregistered the session"
    )


def test_streaming_commits_completed_non_ephemeral_turns_after_session_save():
    commit_idx = STREAMING_SRC.index("# Auto-commit memory after each completed non-ephemeral turn")
    save_idx = STREAMING_SRC.rindex("s.save()", 0, commit_idx)
    done_idx = STREAMING_SRC.index("put('done'", commit_idx)

    assert save_idx < commit_idx < done_idx, (
        "completed turns must save the updated transcript before triggering the "
        "memory commit, and commit before emitting terminal done"
    )
    block = STREAMING_SRC[commit_idx : done_idx]
    assert "commit_session_memory(getattr(s, 'session_id', session_id), agent)" in block


def test_compression_rotation_marks_continuation_session_dirty_for_post_turn_commit():
    rotation_idx = STREAMING_SRC.index("register_agent failed during compression rotation")
    block = STREAMING_SRC[max(0, rotation_idx - 500) : rotation_idx + 200]

    assert "from api.session_lifecycle import mark_session_active, register_agent" in block
    assert "register_agent(new_sid, agent)" in block
    assert "mark_session_active(new_sid)" in block
    assert block.index("register_agent(new_sid, agent)") < block.index("mark_session_active(new_sid)")


def test_new_session_boundary_commits_previous_session_id():
    prev_idx = ROUTES_SRC.index('prev_sid = body.get("prev_session_id")')
    block = ROUTES_SRC[prev_idx : prev_idx + 1400]

    assert "from api.session_lifecycle import commit_session_memory" in block
    assert "commit_session_memory(prev_sid)" in block
    assert block.index("commit_session_memory(prev_sid)") < block.index("s = new_session("), (
        "the previous session must be committed before creating the replacement session"
    )


def test_cache_eviction_collects_evicted_agents_and_commits_outside_cache_lock():
    evict_idx = STREAMING_SRC.index("Evicted LRU agent from cache")
    block = STREAMING_SRC[max(0, evict_idx - 1000) : evict_idx + 700]

    assert "_evicted_agents.append((evicted_sid, _evicted_agent))" in block
    assert "for _evicted_sid, _evicted_agent in _evicted_agents:" in block
    assert "commit_session_memory(_evicted_sid, _evicted_agent)" in block
    assert block.index("_evicted_agents.append") < block.index("for _evicted_sid"), (
        "LRU eviction should collect agents under the cache lock, then commit "
        "after leaving the lock to avoid blocking other cache users"
    )


def test_explicit_evict_helper_commits_before_cache_pop():
    helper_idx = CONFIG_SRC.index("def _evict_session_agent")
    block = CONFIG_SRC[helper_idx : helper_idx + 700]

    assert "commit_session_memory(session_id)" in block
    assert "SESSION_AGENT_CACHE.pop(session_id, None)" in block
    assert block.index("commit_session_memory(session_id)") < block.index("SESSION_AGENT_CACHE.pop(session_id, None)")

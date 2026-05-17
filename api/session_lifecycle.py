"""
Session lifecycle management for Hermes WebUI.

Owns session-end logic: committing accumulated memory to batch-extraction
providers (OpenViking, Holographic) before an agent is rotated out or the
server shuts down.
"""

import atexit
import logging
import threading

logger = logging.getLogger(__name__)

_committing_sessions: set = set()
_committing_lock = threading.Lock()

_pending_agents: dict = {}
_dirty_sessions: set = set()
_pending_lock = threading.Lock()


def mark_session_active(session_id: str) -> None:
    """Mark a session as having new work that should be committed.

    WebUI can hit multiple lifecycle boundaries for one completed turn:
    post-turn commit, then a new-session boundary with ``prev_session_id``,
    then later LRU eviction or shutdown.  The dirty bit lets the first boundary
    flush the turn while later boundaries skip until another turn reopens the
    same session and marks it dirty again.
    """
    if not session_id:
        return
    with _pending_lock:
        _dirty_sessions.add(session_id)


def register_agent(session_id: str, agent) -> None:
    if session_id and agent is not None:
        with _pending_lock:
            _pending_agents[session_id] = agent


def unregister_agent(session_id: str) -> None:
    with _pending_lock:
        _pending_agents.pop(session_id, None)


def commit_session_memory(session_id: str, agent=None) -> None:
    if not session_id:
        return

    # Re-entrancy guard: avoid overlapping commits for the same session from
    # concurrent lifecycle paths (e.g., two rapid boundary events).
    with _committing_lock:
        if session_id in _committing_sessions:
            logger.debug("session %s commit already in progress, skipping", session_id)
            return
        _committing_sessions.add(session_id)

    try:
        with _pending_lock:
            is_dirty = session_id in _dirty_sessions
        if not is_dirty:
            logger.debug("session %s has no uncommitted turns, skipping commit", session_id)
            return

        if agent is None:
            from api.config import SESSION_AGENT_CACHE, SESSION_AGENT_CACHE_LOCK
            with SESSION_AGENT_CACHE_LOCK:
                cached = SESSION_AGENT_CACHE.get(session_id)
            agent = cached[0] if cached else None
            if agent is None:
                # Fallback to lifecycle registry if cache lookup misses.
                # This covers resumed sessions where the cache key may rotate
                # but the active agent was re-registered for this session.
                with _pending_lock:
                    agent = _pending_agents.get(session_id)

        if agent is None:
            logger.debug("no cached/registered agent for session %s, skipping commit", session_id)
            return

        if not hasattr(agent, 'commit_memory_session'):
            logger.debug("agent for session %s has no commit_memory_session, skipping", session_id)
            return

        try:
            agent.commit_memory_session()
            with _pending_lock:
                _dirty_sessions.discard(session_id)
                _pending_agents.pop(session_id, None)
            logger.info("committed memory for session %s", session_id)
        except AttributeError:
            logger.debug("commit_memory_session not available on agent for session %s", session_id)
        except Exception:
            logger.exception("commit_memory_session failed for session %s", session_id)
    finally:
        with _committing_lock:
            _committing_sessions.discard(session_id)


def drain_all_on_shutdown() -> None:
    with _pending_lock:
        sids = list(_pending_agents.keys())
    for sid in sids:
        try:
            commit_session_memory(sid)
        except Exception:
            logger.exception("shutdown drain failed for session %s", sid)
    logger.info("shutdown drain complete: %d sessions processed", len(sids))


atexit.register(drain_all_on_shutdown)

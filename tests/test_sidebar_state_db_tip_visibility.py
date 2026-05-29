"""Regression tests for sidebar state.db tip visibility.

A long WebUI conversation can compress/continue into a newer state.db session
that has no WebUI sidecar JSON yet. The sidebar must not suppress this tip
as a "duplicate" of the older sidecar row from the same lineage.
"""

import sqlite3
import time

import pytest

import api.models as models
import api.routes as routes
from api.agent_sessions import (
    _project_agent_session_rows,
    read_session_lineage_metadata,
)
from api.models import SESSIONS, STREAMS, Session


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    index_file = session_dir / "_index.json"
    state_db = tmp_path / "state.db"
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", index_file)
    monkeypatch.setattr(models, "_active_state_db_path", lambda: state_db)
    SESSIONS.clear()
    STREAMS.clear()
    yield state_db
    SESSIONS.clear()
    STREAMS.clear()


def _ensure_state_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            session_source TEXT,
            title TEXT,
            model TEXT,
            started_at REAL NOT NULL,
            message_count INTEGER DEFAULT 0,
            parent_session_id TEXT,
            ended_at REAL,
            end_reason TEXT
        );
        """
    )
    return conn


def _insert_state_row(conn, sid, *, title=None, parent=None, ended_at=None,
                       end_reason=None, started_at=None, source='webui',
                       session_source=None):
    conn.execute(
        """
        INSERT INTO sessions
        (id, source, session_source, title, model, started_at, message_count,
         parent_session_id, ended_at, end_reason)
        VALUES (?, ?, ?, ?, 'openai/gpt-5', ?, 2, ?, ?, ?)
        """,
        (sid, source, session_source, title or sid, started_at or time.time(),
         parent, ended_at, end_reason),
    )
    conn.commit()


def _save_webui_session(sid, *, title, updated_at):
    session = Session(
        session_id=sid,
        title=title,
        messages=[{"role": "user", "content": "hello"},
                  {"role": "assistant", "content": "hi"}],
        updated_at=updated_at,
    )
    session.save(touch_updated_at=False)
    return session


class TestDuplicateWebuiStateProjection:
    def test_lineage_tip_not_suppressed_when_tip_differs_from_sidecar(self):
        """A WebUI-origin state.db tip row must not be suppressed as a
        duplicate of an older sidecar from the same lineage."""
        represented = {"stale_sidecar_id", "root_id"}
        state_tip = {
            "session_id": "tip_id",
            "source_tag": "webui",
            "raw_source": "webui",
            "session_source": "webui",
            "_lineage_root_id": "root_id",
            "_lineage_tip_id": "tip_id",
        }
        assert routes._is_duplicate_webui_state_projection(state_tip, represented) is False

    def test_older_segment_still_suppressed_when_tip_is_represented(self):
        """An older state.db segment should still be suppressed when the
        lineage tip is already represented by a WebUI sidecar."""
        represented = {"root_id", "tip_id"}
        older_segment = {
            "session_id": "older_id",
            "source_tag": "webui",
            "raw_source": "webui",
            "session_source": "webui",
            "_lineage_root_id": "root_id",
        }
        assert routes._is_duplicate_webui_state_projection(older_segment, represented) is True

    def test_lineage_tip_suppressed_when_it_matches_represented_sidecar(self):
        """A tip row that matches a represented sidecar should be suppressed."""
        represented = {"same_id", "root_id"}
        same_tip = {
            "session_id": "same_id",
            "source_tag": "webui",
            "raw_source": "webui",
            "session_source": "webui",
            "_lineage_root_id": "root_id",
            "_lineage_tip_id": "same_id",
        }
        assert routes._is_duplicate_webui_state_projection(same_tip, represented) is True

    def test_non_webui_source_never_suppressed(self):
        """External sessions (CLI, messaging, etc.) must never be suppressed."""
        represented = {"root_id"}
        external = {
            "session_id": "ext_id",
            "source_tag": "cli",
            "raw_source": "cli",
            "session_source": "cli",
            "_lineage_root_id": "root_id",
            "_lineage_tip_id": "ext_id",
        }
        assert routes._is_duplicate_webui_state_projection(external, represented) is False

    def test_tip_without_lineage_root_is_suppressed_if_session_id_represented(self):
        """A state.db row without _lineage_root_id should still be
        suppressed if its session_id is directly in represented_webui_ids."""
        represented = {"existing_sidecar_id"}
        state_row = {
            "session_id": "existing_sidecar_id",
            "source_tag": "webui",
            "raw_source": "webui",
            "session_source": "webui",
        }
        assert routes._is_duplicate_webui_state_projection(state_row, represented) is True


class TestStateDbTipProjectionAgentSessions:
    def test_projected_rows_include_tip_for_continuation_chain(
        self,
    ):
        """_project_agent_session_rows collapses a compression chain into one
        row pointing at the latest importable segment."""
        root = {
            "id": "root",
            "source": "webui",
            "title": "Chain root",
            "model": "gpt-5",
            "started_at": 1000,
            "message_count": 5,
            "actual_message_count": 5,
            "actual_user_message_count": 2,
            "parent_session_id": None,
            "ended_at": 1050,
            "end_reason": "compression",
            "last_activity": 1050,
        }
        mid = {
            "id": "mid",
            "source": "webui",
            "title": "Chain mid",
            "model": "gpt-5",
            "started_at": 1060,
            "message_count": 5,
            "actual_message_count": 5,
            "actual_user_message_count": 2,
            "parent_session_id": "root",
            "ended_at": 1100,
            "end_reason": "compression",
            "last_activity": 1100,
        }
        tip = {
            "id": "tip",
            "source": "webui",
            "title": "Chain tip",
            "model": "gpt-5",
            "started_at": 1110,
            "message_count": 10,
            "actual_message_count": 10,
            "actual_user_message_count": 4,
            "parent_session_id": "mid",
            "ended_at": None,
            "end_reason": None,
            "last_activity": 1200,
        }
        projected = _project_agent_session_rows([root, mid, tip])
        by_id = {row["id"]: row for row in projected}
        assert "tip" in by_id
        assert by_id["tip"]["_lineage_root_id"] == "root"
        assert by_id["tip"]["_lineage_tip_id"] == "tip"
        assert by_id["tip"]["_compression_segment_count"] == 3
        assert "root" not in by_id
        assert "mid" not in by_id


class TestLineageMetadataTipDiscovery:
    def test_read_session_lineage_metadata_discovers_tip_for_stale_sidecar(
        self, _isolate,
    ):
        """read_session_lineage_metadata should discover the lineage tip
        by walking down continuation children, so a stale sidecar knows
        its _lineage_tip_id."""
        conn = _ensure_state_db(_isolate)
        t0 = time.time() - 200
        try:
            _save_webui_session("root", title="Hermes WebUI", updated_at=t0)
            _save_webui_session("mid", title="Hermes WebUI #2", updated_at=t0 + 50)

            _insert_state_row(
                conn,
                "root",
                started_at=t0,
                ended_at=t0 + 10,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "mid",
                parent="root",
                started_at=t0 + 20,
                ended_at=t0 + 100,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "tip",
                parent="mid",
                started_at=t0 + 110,
                source="webui",
            )

            metadata = read_session_lineage_metadata(_isolate, {"mid"})
            mid_meta = metadata.get("mid")
            assert mid_meta is not None
            assert mid_meta.get("_lineage_tip_id") == "tip"
        finally:
            conn.close()

    def test_lineage_metadata_includes_tip_for_chain_with_no_sidecar_at_tip(
        self, _isolate,
    ):
        """A three-segment chain where only root and mid have sidecar JSON
        should still propagate _lineage_tip_id pointing to the state.db tip."""
        conn = _ensure_state_db(_isolate)
        t0 = time.time() - 300
        try:
            _save_webui_session("root", title="Hermes WebUI", updated_at=t0)
            _save_webui_session("stale_mid", title="Hermes WebUI #2", updated_at=t0 + 50)

            _insert_state_row(
                conn,
                "root",
                started_at=t0,
                ended_at=t0 + 10,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "stale_mid",
                parent="root",
                started_at=t0 + 20,
                ended_at=t0 + 100,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "fresh_tip",
                parent="stale_mid",
                started_at=t0 + 110,
                source="webui",
            )

            metadata = read_session_lineage_metadata(
                _isolate, {"stale_mid", "root"}
            )
            stale_meta = metadata.get("stale_mid")
            assert stale_meta is not None
            assert stale_meta.get("_lineage_tip_id") == "fresh_tip"

            root_meta = metadata.get("root")
            assert root_meta is not None
            assert root_meta.get("_lineage_tip_id") == "fresh_tip"
            assert root_meta.get("_compression_segment_count") == 3
        finally:
            conn.close()

    def test_sessions_endpoint_promotes_lineage_tip_to_stale_sidecar(
        self, _isolate,
    ):
        """/api/sessions should enrich stale WebUI sidecars with the
        _lineage_tip_id from a state.db continuation tip."""
        conn = _ensure_state_db(_isolate)
        t0 = time.time() - 200
        try:
            _save_webui_session("root", title="Hermes WebUI", updated_at=t0)
            _save_webui_session(
                "mid_stale", title="Hermes WebUI #2", updated_at=t0 + 20
            )

            _insert_state_row(
                conn,
                "root",
                started_at=t0,
                ended_at=t0 + 10,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "mid_stale",
                parent="root",
                started_at=t0 + 15,
                ended_at=t0 + 80,
                end_reason="compression",
            )
            _insert_state_row(
                conn,
                "tip_fresh",
                source="webui",
                parent="mid_stale",
                started_at=t0 + 90,
            )

            rows_by_id = {
                row["session_id"]: row for row in models.all_sessions()
            }

            mid = rows_by_id.get("mid_stale")
            assert mid is not None
            assert mid.get("_lineage_tip_id") == "tip_fresh", (
                "stale sidecar should learn its lineage tip from state.db"
            )
        finally:
            conn.close()


class TestPromoteStateDbLineageTips:
    def test_promote_copies_tip_id_to_stale_sidecar(self):
        """_promote_state_db_lineage_tips should copy _lineage_tip_id
        from a state.db tip row onto a stale sidecar sharing the same root."""
        webui_sessions = [
            {
                "session_id": "stale_sidecar",
                "_lineage_root_id": "root_id",
                "_compression_segment_count": 2,
            },
        ]
        state_db_rows = [
            {
                "session_id": "fresh_tip",
                "source_tag": "webui",
                "raw_source": "webui",
                "session_source": "webui",
                "_lineage_root_id": "root_id",
                "_lineage_tip_id": "fresh_tip",
                "_compression_segment_count": 3,
            },
        ]
        routes._promote_state_db_lineage_tips(webui_sessions, state_db_rows)
        assert webui_sessions[0]["_lineage_tip_id"] == "fresh_tip"
        assert webui_sessions[0]["_compression_segment_count"] == 3

    def test_promote_does_not_overwrite_existing_tip(self):
        """If a sidecar already has _lineage_tip_id, promote should not
        overwrite it."""
        webui_sessions = [
            {
                "session_id": "sidecar",
                "_lineage_root_id": "root_id",
                "_lineage_tip_id": "existing_tip",
                "_compression_segment_count": 2,
            },
        ]
        state_db_rows = [
            {
                "session_id": "newer_tip",
                "source_tag": "webui",
                "raw_source": "webui",
                "session_source": "webui",
                "_lineage_root_id": "root_id",
                "_lineage_tip_id": "newer_tip",
                "_compression_segment_count": 4,
            },
        ]
        routes._promote_state_db_lineage_tips(webui_sessions, state_db_rows)
        assert webui_sessions[0]["_lineage_tip_id"] == "existing_tip"

    def test_promote_ignores_non_webui_state_rows(self):
        """_promote_state_db_lineage_tips should only copy _lineage_tip_id
        from WebUI-origin state.db rows."""
        webui_sessions = [
            {
                "session_id": "sidecar",
                "_lineage_root_id": "root_id",
            },
        ]
        state_db_rows = [
            {
                "session_id": "cli_tip",
                "source_tag": "cli",
                "raw_source": "cli",
                "session_source": "cli",
                "_lineage_root_id": "root_id",
                "_lineage_tip_id": "cli_tip",
                "_compression_segment_count": 3,
            },
        ]
        routes._promote_state_db_lineage_tips(webui_sessions, state_db_rows)
        assert "_lineage_tip_id" not in webui_sessions[0]
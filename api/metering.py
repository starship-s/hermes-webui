"""
Hermes Web UI -- Streaming performance metering.

Tracks Tokens Per Second (TPS) across all active WebUI sessions, and the
HIGH/LOW TPS values observed over the past 60 minutes.  Metering data is
emitted via SSE events so the header label can update live during a stream.

Architecture
────────────
Each streaming session is tracked independently.  TPS per session is:

    session_tps = total_tokens / (last_token_ts - first_token_ts)

The global tps is the average of all currently active sessions' TPS values.
This correctly represents the system's real-time capacity regardless of how
many sessions are running or how long each has been streaming.

For HIGH/LOW tracking, get_stats() keeps the original global 60-minute
watermarks, while get_session_stats(stream_id) keeps per-stream watermarks for
the titlebar display. Idle periods are skipped so low does not collapse to 0.

The ticker in streaming.py calls get_interval() — it returns 1.0 when sessions
are actively receiving tokens so the header updates at 1 Hz, and 10.0 when idle
so the ticker exits and no idle readings are emitted.

Usage from api/streaming.py
─────────────────────────────
  from api.metering import meter

  meter().begin_session(stream_id)                     # stream starts
  meter().record_token(stream_id, running_output)     # per output token
  meter().record_reasoning(stream_id, running_reasoning_len)  # per reasoning token

The SSE `metering` event payload:
  {
    "tps": 47.3,    # current TPS for this stream in get_session_stats()
    "high": 52.1,   # highest TPS for this stream in the past 60 minutes
    "low":  31.4,   # lowest TPS for this stream (excl. readings < 1 tps)
    "active": 1,    # sessions currently streaming
  }
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

_HOUR_SECS = 3600.0   # rolling window for HIGH/LOW tracking
_STALE_SECS = 60.0    # consider a session inactive after this


@dataclass
class _SessionMeter:
    output_tokens: int = 0
    reasoning_tokens: int = 0
    first_token_ts: float = 0.0   # time.monotonic() of first token received
    last_token_ts: float = 0.0    # time.monotonic() of last token received
    readings: list[tuple[float, float]] = field(default_factory=list)  # per-stream rolling HIGH/LOW history

    def total_tokens(self) -> int:
        return self.output_tokens + self.reasoning_tokens

    def tps(self) -> float:
        if self.first_token_ts == 0.0 or self.last_token_ts <= self.first_token_ts:
            return 0.0
        return self.total_tokens() / (self.last_token_ts - self.first_token_ts)


class GlobalMeter:
    """Thread-safe global streaming meter.

    Tracks per-session TPS, averages them for a global tps, and maintains a
    60-minute rolling history of global tps snapshots for HIGH/LOW reporting.
    """

    __slots__ = (
        '_lock',
        '_sessions',        # stream_id -> _SessionMeter
        '_readings',        # [(monotonic_ts, tps), ...] rolling 60-minute history
        '_window_start',    # monotonic ts of current window
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionMeter] = {}
        self._readings: list[tuple[float, float]] = []
        self._window_start: float = time.monotonic()

    # ── Public API ────────────────────────────────────────────────────────────

    def begin_session(self, stream_id: str) -> None:
        with self._lock:
            self._sessions[stream_id] = _SessionMeter()

    def get_interval(self) -> float:
        """Return 1.0 when sessions are actively receiving tokens, 10.0 when idle.

        Used by the streaming ticker to run at 1 Hz during work and exit when
        there is nothing to measure.
        """
        now = time.monotonic()
        with self._lock:
            # Only count sessions that have received at least one token recently.
            active_sids = {
                sid for sid, s in self._sessions.items()
                if s.first_token_ts > 0 and (now - s.last_token_ts) <= _STALE_SECS
            }
            return 1.0 if active_sids else 10.0

    def record_token(self, stream_id: str, running_output_tokens: int) -> None:
        now = time.monotonic()
        with self._lock:
            s = self._sessions.get(stream_id)
            if s is None:
                return
            if s.first_token_ts == 0.0:
                s.first_token_ts = now
            s.last_token_ts = now
            s.output_tokens = running_output_tokens

    def record_reasoning(self, stream_id: str, running_reasoning_tokens: int) -> None:
        now = time.monotonic()
        with self._lock:
            s = self._sessions.get(stream_id)
            if s is None:
                return
            if s.first_token_ts == 0.0:
                s.first_token_ts = now
            s.last_token_ts = now
            s.reasoning_tokens = running_reasoning_tokens

    def end_session(self, stream_id: str, final_output_tokens: int, input_tokens: int = 0) -> None:
        with self._lock:
            self._sessions.pop(stream_id, None)

    def get_session_stats(self, stream_id: str) -> dict:
        """Return stats for one streaming session.

        All display values (`tps`, `high`, and `low`) are scoped to
        *stream_id* so one active session cannot bleed its live counter or
        watermarks into another session's titlebar. The `active` count remains
        global so the frontend can still know how many streams are alive.
        """
        stats = self.get_stats()
        now = time.monotonic()
        with self._lock:
            s = self._sessions.get(stream_id)
            if s is None or s.first_token_ts == 0.0 or (now - s.last_token_ts) > _STALE_SECS:
                session_tps = 0.0
                session_high = 0.0
                session_low = 0.0
            else:
                session_tps = s.tps()
                cutoff = now - _HOUR_SECS
                s.readings = [(ts, v) for ts, v in s.readings if ts > cutoff]
                if session_tps > 0:
                    s.readings.append((now, session_tps))
                active_readings = [v for _, v in s.readings if v >= 1.0]
                session_high = max(active_readings) if active_readings else 0.0
                session_low = min(active_readings) if active_readings else 0.0
        stats['tps'] = round(session_tps, 1)
        stats['high'] = round(session_high, 1)
        stats['low'] = round(session_low, 1)
        stats['stream_id'] = stream_id
        return stats

    def get_stats(self) -> dict:
        now = time.monotonic()
        with self._lock:
            # Prune stale sessions
            stale = [
                sid for sid, s in self._sessions.items()
                if s.first_token_ts > 0 and (now - s.last_token_ts) > _STALE_SECS
            ]
            for sid in stale:
                self._sessions.pop(sid, None)

            # Reset window if everything went stale
            if not self._sessions:
                self._window_start = now

            # Compute global tps: average of per-session TPS values
            active = [s for s in self._sessions.values() if s.first_token_ts > 0]
            if active:
                global_tps = sum(s.tps() for s in active) / len(active)
            else:
                global_tps = 0.0

            # Prune readings older than 1 hour
            cutoff = now - _HOUR_SECS
            self._readings = [(ts, v) for ts, v in self._readings if ts > cutoff]

            # Only record this snapshot for HIGH/LOW if there is active work.
            # This prevents idle periods from flooding the history and keeps
            # HIGH/LOW meaningful for the past hour of actual throughput.
            if global_tps > 0:
                self._readings.append((now, global_tps))

            # HIGH/LOW from the past hour (skip near-zero idle readings)
            active_readings = [v for _, v in self._readings if v >= 1.0]
            high = max(active_readings) if active_readings else 0.0
            low = min(active_readings) if active_readings else 0.0

            return {
                'tps': round(global_tps, 1),
                'high': round(high, 1),
                'low': round(low, 1),
                'active': len(self._sessions),
            }


# ── Module-level singleton ─────────────────────────────────────────────────────

_meter = GlobalMeter()


def meter() -> GlobalMeter:
    return _meter

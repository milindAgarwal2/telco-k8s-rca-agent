"""Durable persistence for :class:`~rca_agent.models.incident.IncidentReport`.

One row per incident in the ``incidents`` table (schema owned by
:mod:`rca_agent.store.db`). Query-worthy fields are mirrored into typed columns
(``incident_id``, ``created_at``, ``status``, ``resolved_at``,
``affected_resource``, ``namespace``, ``severity``) while the full record is
stored in the ``payload`` JSONB column via ``model_dump(mode="json")``. The
payload is the source of truth for reload: :meth:`IncidentStore.load_recent`
and :meth:`IncidentStore.get` reconstruct reports with
``IncidentReport.model_validate(payload)`` so every field -- including the
nested ``hypotheses``, ``evidence``, ``citations``, ``service_area`` and
``related_incidents`` that live only in the payload -- round-trips faithfully
(Req 2.5).

Writes go through :meth:`IncidentStore.upsert`, an INSERT ... ON CONFLICT
(incident_id) DO UPDATE so re-persisting the same incident after a mutation
updates the existing row in place (Req 2.1). All queries use the pooled
connection from :meth:`rca_agent.store.db.Database.connection` and parameterized
``%s`` placeholders -- values are never string-formatted into SQL.
"""
from __future__ import annotations

import logging

from psycopg.types.json import Json

from rca_agent.models.incident import IncidentReport
from rca_agent.store.db import Database

logger = logging.getLogger("rca_agent.store")


_UPSERT_SQL = """
    INSERT INTO incidents (
        incident_id,
        created_at,
        status,
        resolved_at,
        affected_resource,
        namespace,
        severity,
        payload
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (incident_id) DO UPDATE SET
        status            = EXCLUDED.status,
        resolved_at       = EXCLUDED.resolved_at,
        affected_resource = EXCLUDED.affected_resource,
        namespace         = EXCLUDED.namespace,
        severity          = EXCLUDED.severity,
        payload           = EXCLUDED.payload,
        updated_at        = now()
"""

_LOAD_RECENT_SQL = """
    SELECT payload FROM incidents
    ORDER BY created_at DESC
    LIMIT %s
"""

_GET_SQL = """
    SELECT payload FROM incidents
    WHERE incident_id = %s
"""

_COUNT_SQL = "SELECT count(*) FROM incidents"


class IncidentStore:
    """Read/write access to the durable ``incidents`` table.

    Constructed with a connected :class:`~rca_agent.store.db.Database`; all
    methods borrow a pooled connection via ``db.connection()`` and commit after
    writes.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, report: IncidentReport) -> None:
        """Insert or update the row for ``report`` (keyed on ``incident_id``).

        The full record is stored in the ``payload`` JSONB column via
        ``model_dump(mode="json")``; the typed columns are a query-friendly
        subset populated from the report fields. ``severity`` is an enum, so its
        ``.value`` (a str) is stored in the typed column (the payload already
        serializes it as a str). On conflict the existing row is updated in
        place and ``updated_at`` is refreshed to ``now()`` (Req 2.1).
        """
        payload = report.model_dump(mode="json")
        params = (
            report.incident_id,
            report.created_at,
            report.status,
            report.resolved_at,
            report.affected_resource,
            report.namespace,
            report.severity.value,
            Json(payload),
        )
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT_SQL, params)
            conn.commit()
        logger.debug("Upserted incident %s", report.incident_id)

    def load_recent(self, limit: int = 200) -> list[IncidentReport]:
        """Return the most recent incidents, newest first (Req 3.1).

        Reads the ``payload`` JSONB column and reconstructs each report with
        ``IncidentReport.model_validate`` so the full record round-trips. The
        in-memory cache and the webhook both list newest-first, so the rows are
        ordered by ``created_at DESC``.
        """
        with self._db.connection() as conn, conn.cursor() as cur:
            cur.execute(_LOAD_RECENT_SQL, (limit,))
            rows = cur.fetchall()
        return [IncidentReport.model_validate(row[0]) for row in rows]

    def get(self, incident_id: str) -> IncidentReport | None:
        """Return the incident with ``incident_id`` or None if absent."""
        with self._db.connection() as conn, conn.cursor() as cur:
            cur.execute(_GET_SQL, (incident_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return IncidentReport.model_validate(row[0])

    def count(self) -> int:
        """Return the total number of persisted incidents."""
        with self._db.connection() as conn, conn.cursor() as cur:
            cur.execute(_COUNT_SQL)
            row = cur.fetchone()
        return int(row[0]) if row is not None else 0

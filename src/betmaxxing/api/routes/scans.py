"""Scan endpoints."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from betmaxxing.config import get_settings
from betmaxxing.domain.models import ScanResult
from betmaxxing.engine.scan import run_scan
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.repositories import ScanRepository

router = APIRouter(tags=["scans"])


def _execute(save: bool) -> ScanResult:
    settings = get_settings()
    result = run_scan(settings)
    if save:
        create_all(settings)
        with session_scope(settings) as session:
            ScanRepository(session).save(result)
    return result


@router.post("/scans", response_model=ScanResult)
def create_scan(save: bool = Query(default=True)) -> ScanResult:
    """Run a scan now. Returns candidates, ``NO_BET`` or ``DATA_UNAVAILABLE``."""
    return _execute(save)


@router.get("/scans", response_model=list[dict])
def list_scans(limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    settings = get_settings()
    create_all(settings)
    with session_scope(settings) as session:
        rows = ScanRepository(session).latest(limit)
        return [
            {
                "scan_id": r.scan_id,
                "status": r.status,
                "mode": r.mode,
                "generated_at": r.generated_at.isoformat(),
                "candidate_count": r.candidate_count,
                "rejection_count": r.rejection_count,
                "config_fingerprint": r.config_fingerprint,
            }
            for r in rows
        ]


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str) -> dict[str, Any]:
    settings = get_settings()
    create_all(settings)
    with session_scope(settings) as session:
        row = ScanRepository(session).get(scan_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"scan {scan_id} introuvable")
        return dict(row.document)


@router.get("/scans/{scan_id}/rejections")
def get_rejections(scan_id: str) -> list[dict[str, Any]]:
    """The ``No bet`` view: every dropped selection with its explicit code."""
    settings = get_settings()
    create_all(settings)
    with session_scope(settings) as session:
        rows = ScanRepository(session).rejections_for(scan_id)
        return [
            {
                "event_canonical_id": r.event_canonical_id,
                "event_label": r.event_label,
                "selection_key": r.selection_key,
                "code": r.code,
                "detail": r.detail,
            }
            for r in rows
        ]


@router.get("/scans/{scan_id}/export.csv")
def export_scan_csv(scan_id: str) -> StreamingResponse:
    """Flat CSV of a scan's candidates, for audit outside the app."""
    settings = get_settings()
    create_all(settings)
    with session_scope(settings) as session:
        row = ScanRepository(session).get(scan_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"scan {scan_id} introuvable")
        document = dict(row.document)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "scan_id",
            "event",
            "competition",
            "start_time_utc",
            "market",
            "period",
            "line",
            "selection",
            "bookmaker",
            "decimal_odds",
            "observed_at",
            "implied_raw",
            "implied_novig",
            "model_probability",
            "probability_lower",
            "probability_upper",
            "fair_odds",
            "ev",
            "ev_conservative",
            "min_acceptable_odds",
            "data_quality",
            "model_id",
            "validation_status",
            "config_fingerprint",
        ]
    )
    for candidate in document.get("candidates", []):
        value = candidate["value"]
        event = candidate["event"]
        selection = candidate["selection"]
        writer.writerow(
            [
                document["scan_id"],
                f"{event['home']['name']} vs {event['away']['name']}",
                event["competition"],
                event["start_time_utc"],
                selection["market"],
                selection["period"],
                selection.get("line", ""),
                selection["label"],
                candidate["bookmaker"],
                value["decimal_odds"],
                candidate["observed_at"],
                value["implied_probability_raw"],
                value.get("implied_probability_novig", ""),
                value["model_probability"],
                value["model_probability_lower"],
                value["model_probability_upper"],
                value["fair_odds"],
                value["ev"],
                value["ev_conservative"],
                value["min_acceptable_odds"],
                candidate["data_quality"]["score"],
                candidate["model_id"],
                candidate["probability"]["validation_status"],
                candidate["config_fingerprint"],
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="scan-{scan_id}.csv"'},
    )

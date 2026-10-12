"""Detection runs, incident de-duplication, workflow and investigation (PostgreSQL)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AnomalyDetection, Incident
from app.services.anomaly_detection.service import get_settings_row, run_detection
from app.services.ingestion.sample_data import generate_sample_csv
from app.services.ingestion.service import import_billing_file
from app.services.investigation.service import investigate
from tests.factories import add_daily_series, make_import

END = date(2026, 10, 11)
GPU_DAYS = (END - timedelta(days=4), END - timedelta(days=3))
NAT_DAY = END - timedelta(days=11)
EC2 = "Amazon Elastic Compute Cloud"
VPC = "Amazon Virtual Private Cloud"


@pytest.fixture()
def sample_loaded(db: Session) -> None:
    content = generate_sample_csv(END).encode()
    imported = import_billing_file(
        db, filename="sample.csv", content=content, settings=get_settings(), today=END
    )
    assert imported.status == "completed"


def _total_scope_only(db: Session) -> None:
    """Synthetic single-service series would otherwise also raise a service-level incident."""
    get_settings_row(db).scopes = ["total"]
    db.commit()


def _incident(db: Session, scope_type: str, scope_value: str) -> Incident:
    return db.scalars(
        select(Incident).where(
            Incident.scope_type == scope_type, Incident.scope_value == scope_value
        )
    ).one()


def test_sample_data_produces_exactly_the_injected_incidents(
    db: Session, sample_loaded: None
) -> None:
    outcome = run_detection(db)
    run = outcome.run
    assert run.status == "completed", run.error
    assert run.points_insufficient_history == 0

    incidents = db.scalars(select(Incident).order_by(Incident.id)).all()
    found = {(i.scope_type, i.scope_value, i.start_date, i.end_date) for i in incidents}
    assert found == {
        ("total", "", NAT_DAY, NAT_DAY),
        ("service", VPC, NAT_DAY, NAT_DAY),
        ("total", "", *GPU_DAYS),
        ("service", EC2, *GPU_DAYS),
    }
    assert len(outcome.new_incident_ids) == 4

    gpu = _incident(db, "service", EC2)
    assert gpu.detection_count == 2  # two consecutive days grouped into one incident
    assert gpu.severity == "high"
    assert gpu.kind == "spike"
    detection = db.scalars(
        select(AnomalyDetection).where(AnomalyDetection.incident_id == gpu.id)
    ).first()
    assert detection is not None
    # Evidence is persisted with every detection.
    assert detection.thresholds["pct_threshold"] == "25.00"
    assert len(detection.evidence["baseline_values"]) == detection.baseline_points
    assert detection.expected_cost > 0 and detection.observed_cost > detection.expected_cost


def test_rerunning_detection_never_duplicates(db: Session, sample_loaded: None) -> None:
    run_detection(db)
    incidents_before = db.scalar(select(func.count()).select_from(Incident))
    detections_before = db.scalar(select(func.count()).select_from(AnomalyDetection))

    second = run_detection(db)
    assert second.new_incident_ids == []
    assert second.run.anomalies_detected == detections_before
    assert db.scalar(select(func.count()).select_from(Incident)) == incidents_before
    assert db.scalar(select(func.count()).select_from(AnomalyDetection)) == detections_before


def test_resolved_incident_is_not_reopened_or_duplicated(db: Session, sample_loaded: None) -> None:
    run_detection(db)
    gpu = _incident(db, "service", EC2)
    gpu.status = "resolved"
    db.commit()
    outcome = run_detection(db)
    assert outcome.new_incident_ids == []
    db.refresh(gpu)
    assert gpu.status == "resolved"
    assert (
        db.scalar(select(func.count()).select_from(Incident).where(Incident.scope_value == EC2))
        == 1
    )


def test_new_day_after_resolution_opens_a_new_incident(db: Session) -> None:
    _total_scope_only(db)
    imp = make_import(db)
    start = date(2026, 8, 1)
    add_daily_series(db, imp, start, ["100"] * 40 + ["400"])  # spike on day 41
    db.commit()
    first = run_detection(db)
    assert len(first.new_incident_ids) == 1
    incident = db.get(Incident, first.new_incident_ids[0])
    incident.status = "resolved"
    db.commit()

    add_daily_series(db, imp, start + timedelta(days=41), ["450"])  # adjacent new spike
    db.commit()
    second = run_detection(db)
    assert len(second.new_incident_ids) == 1  # a new event after resolution
    assert second.new_incident_ids[0] != incident.id


def test_adjacent_days_extend_an_open_incident(db: Session) -> None:
    _total_scope_only(db)
    imp = make_import(db)
    start = date(2026, 8, 1)
    add_daily_series(db, imp, start, ["100"] * 40 + ["400"])
    db.commit()
    first = run_detection(db)
    add_daily_series(db, imp, start + timedelta(days=41), ["420"])
    db.commit()
    second = run_detection(db)
    assert second.new_incident_ids == []
    incident = db.get(Incident, first.new_incident_ids[0])
    db.refresh(incident)
    assert incident.detection_count == 2
    assert incident.end_date == start + timedelta(days=41)
    assert [e.event_type for e in incident.events] == ["created", "detection_added"]


def test_insufficient_history_is_reported_not_detected(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), ["100"] * 5 + ["5000"])
    db.commit()
    outcome = run_detection(db)
    assert outcome.new_incident_ids == []
    assert outcome.run.anomalies_detected == 0
    assert outcome.run.points_insufficient_history > 0
    assert any("not enough history" in note for note in outcome.run.notes or [])


def test_empty_dataset_run_completes(db: Session) -> None:
    outcome = run_detection(db)
    assert outcome.run.status == "completed"
    assert outcome.run.series_evaluated == 0


def test_investigation_of_gpu_spike_identifies_new_resource(
    db: Session, sample_loaded: None
) -> None:
    run_detection(db)
    result = investigate(db, _incident(db, "service", EC2))
    assert result.confidence == "high"
    resources = next(d for d in result.dimensions if d.dimension == "resource_id")
    top = resources.contributors[0]
    assert top.key == "i-0f3e9a7c5b1d2468a"
    assert top.is_new and top.usage is not None and top.usage.driver == "new"
    assert top.share_of_increase_pct is not None and top.share_of_increase_pct > 95
    regions = next(d for d in result.dimensions if d.dimension == "region")
    assert regions.contributors[0].key == "us-west-2" and regions.contributors[0].is_new
    titles = [s.title for s in result.suggestions]
    assert "Confirm resource i-0f3e9a7c5b1d2468a is expected" in titles
    assert "Check activity in region us-west-2" in titles
    assert any(point.is_anomaly for point in result.chart)


def test_investigation_of_nat_spike_is_usage_driven(db: Session, sample_loaded: None) -> None:
    run_detection(db)
    result = investigate(db, _incident(db, "service", VPC))
    usage_types = next(d for d in result.dimensions if d.dimension == "usage_type")
    top = usage_types.contributors[0]
    assert top.key == "NatGateway-Bytes"
    assert top.usage is not None and top.usage.driver == "usage"
    # The resource mixes GB and Hrs, so it is not compared at resource level.
    resources = next(d for d in result.dimensions if d.dimension == "resource_id")
    assert resources.contributors[0].usage.driver == "mixed_units"
    assert any("usage-driven" in text for text in result.explanations)
    assert any(s.title.startswith("Review data transfer") for s in result.suggestions)
    assert not any("not available" in text for text in result.explanations)


def test_incident_api_workflow(client: TestClient, db: Session, sample_loaded: None) -> None:
    run = client.post("/api/v1/anomalies/runs").json()
    assert run["status"] == "completed" and run["incidents_created"] == 4

    listing = client.get("/api/v1/incidents?status=open").json()
    assert listing["total"] == 4
    incident_id = listing["items"][0]["id"]
    assert client.get("/api/v1/incidents/counts").json() == {
        "open": 4,
        "acknowledged": 0,
        "resolved": 0,
    }

    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["detections"] and detail["events"][0]["event_type"] == "created"
    assert client.get(f"/api/v1/incidents/{incident_id}/investigation").status_code == 200

    ack = client.post(f"/api/v1/incidents/{incident_id}/acknowledge", json={"actor": "dev"})
    assert ack.json()["status"] == "acknowledged" and ack.json()["acknowledged_by"] == "dev"
    again = client.post(f"/api/v1/incidents/{incident_id}/acknowledge", json={"actor": "dev"})
    assert again.status_code == 409

    note = client.post(
        f"/api/v1/incidents/{incident_id}/notes", json={"actor": "dev", "body": "Checking"}
    )
    assert note.status_code == 201
    blank = client.post(
        f"/api/v1/incidents/{incident_id}/resolve", json={"actor": "dev", "resolution_note": " "}
    )
    assert blank.status_code == 422
    resolved = client.post(
        f"/api/v1/incidents/{incident_id}/resolve",
        json={"actor": "dev", "resolution_note": "Test instance terminated."},
    ).json()
    assert resolved["status"] == "resolved"
    assert [e["event_type"] for e in resolved["events"]][-3:] == [
        "acknowledged",
        "note",
        "resolved",
    ]
    reopened = client.post(f"/api/v1/incidents/{incident_id}/reopen", json={"actor": "dev"})
    assert reopened.json()["status"] == "open"


def test_detection_settings_api(client: TestClient) -> None:
    settings = client.get("/api/v1/anomalies/settings").json()
    assert settings["scopes"] == ["total", "service"]
    settings.pop("updated_at")
    settings["pct_threshold"] = "40"
    settings["scopes"] = ["service", "project", "service"]
    updated = client.put("/api/v1/anomalies/settings", json=settings)
    assert updated.status_code == 200, updated.json()
    assert updated.json()["scopes"] == ["service", "project"]
    assert updated.json()["pct_threshold"] == "40.00"

    settings["min_history_days"] = 60  # greater than the 28-day baseline window
    assert client.put("/api/v1/anomalies/settings", json=settings).status_code == 422


def test_investigation_narrates_only_material_contributors(
    db: Session, sample_loaded: None
) -> None:
    run_detection(db)
    total = db.scalars(
        select(Incident).where(Incident.scope_type == "total", Incident.start_date == NAT_DAY)
    ).one()
    result = investigate(db, total)
    # Small organic changes (e.g. BigQuery, CloudFront) stay in the tables but are not narrated.
    narrative = " ".join(result.explanations + [s.title for s in result.suggestions])
    assert "analytics-warehouse" not in narrative
    assert "E2QWRUHAPOMQZL" not in narrative
    assert "NatGateway-Bytes" in narrative
    services = next(d for d in result.dimensions if d.dimension == "service")
    assert services.contributors[0].key == VPC
    assert len(services.contributors) > 1  # minor contributors remain visible

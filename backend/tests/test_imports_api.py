"""Integration tests for the billing import workflow (API + PostgreSQL)."""

import csv
import io
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AllocationRule, BillingImport, BillingRecord
from app.services.ingestion.sample_data import SAMPLE_COLUMNS, generate_sample_rows
from app.services.normalization.allocation import reapply_allocation_rules

HEADER = "usage_date,provider,service,resource_id,currency,cost,project\n"


def upload(client: TestClient, content: str | bytes, filename: str = "billing.csv", **form):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return client.post("/api/v1/imports", files={"file": (filename, data, "text/csv")}, data=form)


def test_successful_upload_persists_records(client: TestClient, db: Session) -> None:
    response = upload(
        client,
        HEADER + "2026-10-01,aws,EC2,i-1,USD,10.10,web\n2026-10-02,aws,EC2,i-1,USD,0.000000015,\n",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "completed"
    assert body["source"] == "upload"
    assert (body["rows_total"], body["rows_inserted"], body["rows_duplicate"]) == (2, 2, 0)
    assert body["currencies"] == ["USD"]
    assert (body["date_start"], body["date_end"]) == ("2026-10-01", "2026-10-02")

    costs = db.scalars(select(BillingRecord.cost).order_by(BillingRecord.usage_date)).all()
    assert costs == [Decimal("10.10000000"), Decimal("0.00000002")]
    assert (
        db.scalar(select(BillingRecord.project).where(BillingRecord.resource_id == "i-1").limit(1))
        == "web"
    )


def test_identical_file_is_rejected_with_409(client: TestClient, db: Session) -> None:
    content = HEADER + "2026-10-01,aws,EC2,i-1,USD,10,web\n"
    first = upload(client, content)
    assert first.status_code == 201
    second = upload(client, content, filename="renamed.csv")
    assert second.status_code == 409
    assert second.json()["error"]["details"] == {"import_id": first.json()["id"]}
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == 1
    assert db.scalar(select(func.count()).select_from(BillingImport)) == 1


def test_overlapping_file_skips_existing_records(client: TestClient, db: Session) -> None:
    upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,10,web\n")
    response = upload(
        client,
        HEADER + "2026-10-01,aws,EC2,i-1,USD,10.00,web\n2026-10-02,aws,EC2,i-1,USD,11,web\n",
    )
    body = response.json()
    assert response.status_code == 201
    assert (body["rows_inserted"], body["rows_duplicate"]) == (1, 1)
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == 2


def test_invalid_file_returns_422_with_errors_and_stores_nothing(
    client: TestClient, db: Session
) -> None:
    response = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,10,web\nbad,aws,EC2,,USD,x,\n")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "import_validation_failed"
    details = error["details"]
    assert details["status"] == "failed"
    assert details["rows_invalid"] == 1
    assert {(e["line"], e["column"]) for e in details["errors"]} == {
        (3, "usage_date"),
        (3, "cost"),
    }
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == 0
    # The failed attempt is tracked and can be fetched later.
    stored = client.get(f"/api/v1/imports/{details['id']}").json()
    assert stored["status"] == "failed" and len(stored["errors"]) == 2


def test_failed_file_can_be_retried_after_fixing(client: TestClient) -> None:
    bad = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,oops,web\n")
    assert bad.status_code == 422
    good = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n")
    assert good.status_code == 201


def test_non_csv_and_oversized_uploads_are_rejected(client: TestClient, monkeypatch) -> None:
    assert upload(client, "x", filename="evil.exe").status_code == 415
    assert upload(client, "x", filename="../../etc/passwd").status_code == 415

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    response = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_filename_is_sanitized(client: TestClient) -> None:
    response = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n", "..\\..\\a<b>.csv")
    assert response.status_code == 201
    assert response.json()["filename"] == "a_b_.csv"


def test_list_get_and_delete_import(client: TestClient, db: Session) -> None:
    created = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n").json()
    listing = client.get("/api/v1/imports?limit=10").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == created["id"]

    assert client.delete(f"/api/v1/imports/{created['id']}").status_code == 204
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == 0
    assert client.get(f"/api/v1/imports/{created['id']}").status_code == 404


def test_sample_data_loads_once_and_is_marked_sample(client: TestClient) -> None:
    first = client.post("/api/v1/imports/sample")
    assert first.status_code == 201, first.json()
    body = first.json()
    assert body["source"] == "sample"
    assert body["rows_inserted"] > 1000
    again = client.post("/api/v1/imports/sample")
    assert again.status_code == 409
    assert "up to date" in again.json()["error"]["message"]


def test_older_sample_is_topped_up_without_duplicates(client: TestClient, db: Session) -> None:
    """Sample data loaded before AI/multi-cloud lines existed gains only the new records."""
    end = date(2026, 10, 11)
    rows = generate_sample_rows(end)
    older = [r for r in rows if not r["model"] and r["provider"] in ("aws", "gcp")]
    buffer = io.StringIO()
    columns = [c for c in SAMPLE_COLUMNS if c != "model"]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(older)
    first = upload(client, buffer.getvalue(), is_sample="true")
    assert first.status_code == 201, first.json()
    total_before = db.scalar(select(func.sum(BillingRecord.cost)))

    update = client.post("/api/v1/imports/sample")
    assert update.status_code == 201, update.json()
    body = update.json()
    assert body["rows_inserted"] == len(rows) - len(older)
    assert body["rows_duplicate"] == len(older)
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == len(rows)
    providers = set(db.scalars(select(BillingRecord.provider).distinct()))
    assert {"azure", "openai", "anthropic"} <= providers
    added = sum(Decimal(r["cost"]) for r in rows) - sum(Decimal(r["cost"]) for r in older)
    assert db.scalar(select(func.sum(BillingRecord.cost))) == total_before + added
    assert client.post("/api/v1/imports/sample").status_code == 409


def test_sample_update_refuses_data_that_does_not_match(client: TestClient) -> None:
    upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n", is_sample="true")
    response = client.post("/api/v1/imports/sample")
    assert response.status_code == 409
    assert "double-counting" in response.json()["error"]["message"]


def test_sample_flag_on_upload(client: TestClient) -> None:
    response = upload(client, HEADER + "2026-10-01,aws,EC2,i-1,USD,1,web\n", is_sample="true")
    assert response.json()["source"] == "sample"


def test_schema_and_template_endpoints(client: TestClient) -> None:
    schema = client.get("/api/v1/imports/schema").json()
    required = {f["name"] for f in schema["fields"] if f["required"]}
    assert required == {"usage_date", "provider", "service", "currency", "cost"}
    template = client.get("/api/v1/imports/template.csv")
    assert template.headers["content-type"].startswith("text/csv")
    assert template.text.splitlines()[0].startswith("usage_date,provider")
    # The template itself must be importable.
    assert upload(client, template.text).status_code == 201


def test_allocation_rules_fill_missing_tags_only(client: TestClient, db: Session) -> None:
    db.add(
        AllocationRule(
            name="NAT to platform",
            match_field="resource_id",
            match_operator="prefix",
            match_value="NAT-",
            project="platform",
            environment="production",
            priority=10,
        )
    )
    db.commit()
    upload(
        client,
        HEADER + "2026-10-01,aws,VPC,nat-123,USD,1,\n2026-10-01,aws,VPC,nat-456,USD,2,tagged\n",
    )
    rows = dict(db.execute(select(BillingRecord.resource_id, BillingRecord.project)).all())
    assert rows == {"nat-123": "platform", "nat-456": "tagged"}

    db.execute(AllocationRule.__table__.delete())
    db.commit()
    # Both records lose rule-assigned values (nat-456 kept its project tag only).
    assert reapply_allocation_rules(db) == 2
    rows = dict(db.execute(select(BillingRecord.resource_id, BillingRecord.project)).all())
    assert rows == {"nat-123": None, "nat-456": "tagged"}

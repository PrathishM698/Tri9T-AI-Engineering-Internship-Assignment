"""End-to-end regression test using the actual supplied CT-200 PDFs."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base

DATA = Path(__file__).resolve().parents[1] / "data"
V1 = DATA / "ct200_manual.pdf"
V2 = DATA / "ct200_manual_v2.pdf"

@pytest.mark.skipif(not (V1.exists() and V2.exists()), reason="Actual CT-200 PDFs not bundled")
def test_real_manual_v1_to_v2_marks_generated_cases_stale(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    monkeypatch.setattr(main, "GENERATED_STORE", tmp_path / "generated.json")
    client = TestClient(main.app)
    try:
        for label, pdf in [("v1", V1), ("v2", V2)]:
            with pdf.open("rb") as stream:
                response = client.post(
                    "/documents/ingest",
                    params={"document_key": "integration-ct200", "version_label": label},
                    files={"file": (pdf.name, stream, "application/pdf")},
                )
            assert response.status_code == 200, response.text

        sections = client.get("/documents/integration-ct200/sections", params={"version": "v1"}).json()["sections"]
        assert len(sections) == 8
        assert any(section["heading"].startswith("5 Data Management") for section in sections)

        search = client.get("/search", params={
            "q": "Battery Life Under Typical Use",
            "document_key": "integration-ct200",
            "version": "v1",
        }).json()
        battery_node = next(item for item in search["results"] if "Battery Life" in item["heading"])
        selection_response = client.post("/selections", json={
            "name": "Battery life v1 selection", "node_ids": [battery_node["id"]]
        })
        assert selection_response.status_code == 201, selection_response.text
        selection_id = selection_response.json()["id"]

        generation = client.post("/generations", json={"selection_id": selection_id})
        assert generation.status_code == 201, generation.text
        assert len(generation.json()["test_cases"]) in (3, 4, 5)

        retrieval = client.get("/generations", params={"selection_id": selection_id})
        assert retrieval.status_code == 200, retrieval.text
        result = retrieval.json()["generations"][0]
        assert result["staleness"]["is_stale"] is True
        assert result["staleness"]["items"][0]["source_version"] == "v1"
        assert result["staleness"]["items"][0]["latest_version"] == "v2"
    finally:
        main.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

"""Studio API tests (plan §8): CRUD, and the server-enforced approve gate."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.studio import get_repo
from app.config import settings
from app.kg.loader import load_kcs
from app.main import app
from app.studio.repo import DraftRepo


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    repo = DraftRepo(":memory:")
    app.dependency_overrides[get_repo] = lambda: repo
    monkeypatch.setattr(settings, "graph_output_dir", tmp_path / "generated")
    yield TestClient(app)
    app.dependency_overrides.clear()
    repo.close()


def _create_empty(client: TestClient) -> str:
    resp = client.post("/api/studio/drafts", data={"role": "warehouse_operative"})
    assert resp.status_code == 200
    return resp.json()["draft_id"]


def _prov(doc_id: str = "01-ppe-manual-handling") -> dict:
    return {
        "doc_id": doc_id,
        "heading": "1. PPE",
        "excerpt": "Operatives must wear the PPE specified for the zone.",
    }


def _kc_body(kc_id: str, domain: str = "safety") -> dict:
    return {
        "id": kc_id,
        "name": f"KC {kc_id}",
        "domain": domain,
        "description": "desc",
        "provenance": _prov(),
    }


def test_create_empty_draft(client: TestClient) -> None:
    draft_id = _create_empty(client)
    got = client.get(f"/api/studio/drafts/{draft_id}").json()
    assert got["kcs"] == []
    assert got["status"] == "draft"


def test_create_seeded_draft_has_full_graph(client: TestClient) -> None:
    resp = client.post(
        "/api/studio/drafts",
        data={"role": "warehouse_operative", "seed_from_graph": "true"},
    )
    draft = resp.json()
    assert len(draft["kcs"]) == 25
    assert len(draft["edges"]) == 11


def test_get_missing_draft_404(client: TestClient) -> None:
    assert client.get("/api/studio/drafts/nope").status_code == 404


def test_add_kc_and_duplicate_conflict(client: TestClient) -> None:
    draft_id = _create_empty(client)
    resp = client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.001"))
    assert resp.status_code == 200
    kcs = resp.json()["kcs"]
    assert kcs[0]["id"] == "SAF.001"
    assert kcs[0]["origin"] == "manual"
    dup = client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.001"))
    assert dup.status_code == 409


def test_patch_kc_marks_edited(client: TestClient) -> None:
    draft_id = _create_empty(client)
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.001"))
    resp = client.patch(
        f"/api/studio/drafts/{draft_id}/kcs/SAF.001",
        json={"name": "PPE selection and correct use per zone"},
    )
    kc = resp.json()["kcs"][0]
    assert kc["name"] == "PPE selection and correct use per zone"
    assert kc["origin"] == "edited"


def test_delete_kc_prunes_edges(client: TestClient) -> None:
    draft_id = _create_empty(client)
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.002"))
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.003"))
    client.post(
        f"/api/studio/drafts/{draft_id}/edges",
        json={"source_kc_id": "SAF.002", "target_kc_id": "SAF.003"},
    )
    resp = client.delete(f"/api/studio/drafts/{draft_id}/kcs/SAF.002")
    body = resp.json()
    assert [kc["id"] for kc in body["kcs"]] == ["SAF.003"]
    assert body["edges"] == []


def test_add_and_delete_edge(client: TestClient) -> None:
    draft_id = _create_empty(client)
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.002"))
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.003"))
    add = client.post(
        f"/api/studio/drafts/{draft_id}/edges",
        json={"source_kc_id": "SAF.002", "target_kc_id": "SAF.003"},
    )
    assert len(add.json()["edges"]) == 1
    rem = client.delete(
        f"/api/studio/drafts/{draft_id}/edges",
        params={"source_kc_id": "SAF.002", "target_kc_id": "SAF.003"},
    )
    assert rem.json()["edges"] == []


def test_validation_endpoint_reports_blockers(client: TestClient) -> None:
    draft_id = _create_empty(client)
    # missing-provenance KC (empty excerpt)
    body = _kc_body("SAF.001")
    body["provenance"]["excerpt"] = ""
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=body)
    result = client.get(f"/api/studio/drafts/{draft_id}/validation").json()
    assert result["ok"] is False
    assert any(i["code"] == "missing_provenance" for i in result["issues"])


def test_approve_rejects_invalid_and_writes_nothing(client: TestClient, tmp_path: Path) -> None:
    # A KC with no excerpt is a missing-provenance blocker → not approvable.
    draft_id = _create_empty(client)
    body = _kc_body("SAF.001")
    body["provenance"]["excerpt"] = ""
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=body)

    approve = client.post(f"/api/studio/drafts/{draft_id}/approve")
    assert approve.status_code == 422
    assert any(i["code"] == "missing_provenance" for i in approve.json()["detail"]["issues"])
    # nothing materialized, status unchanged
    assert not (tmp_path / "generated").exists()
    assert client.get(f"/api/studio/drafts/{draft_id}").json()["status"] == "draft"


def test_seeded_draft_from_committed_graph_has_real_provenance(client: TestClient) -> None:
    # The committed graph.yaml carries real provenance now, so re-opening it for review
    # comes back approvable without a human having to re-attach every source by hand.
    resp = client.post(
        "/api/studio/drafts",
        data={"role": "warehouse_operative", "seed_from_graph": "true"},
    )
    draft_id = resp.json()["draft_id"]
    result = client.get(f"/api/studio/drafts/{draft_id}/validation").json()
    assert result["ok"] is True


def test_approve_valid_draft_materializes_yaml(client: TestClient, tmp_path: Path) -> None:
    draft_id = _create_empty(client)
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.002"))
    client.post(f"/api/studio/drafts/{draft_id}/kcs", json=_kc_body("SAF.003"))
    client.post(
        f"/api/studio/drafts/{draft_id}/edges",
        json={"source_kc_id": "SAF.002", "target_kc_id": "SAF.003"},
    )
    approve = client.post(f"/api/studio/drafts/{draft_id}/approve")
    assert approve.status_code == 200
    body = approve.json()
    assert body["status"] == "approved"

    written = Path(body["path"])
    assert written.exists()
    kcs = {kc.id: kc for kc in load_kcs(written)}  # materialized YAML loads in the loader
    assert kcs["SAF.003"].prerequisites == ["SAF.002"]
    assert client.get(f"/api/studio/drafts/{draft_id}").json()["status"] == "approved"


# --- SOP extraction wiring (pipeline itself is contract-tested elsewhere) ---


def test_list_sops_returns_corpus(client: TestClient) -> None:
    sops = client.get("/api/studio/sops").json()
    ids = {s["doc_id"] for s in sops}
    assert "01-ppe-manual-handling" in ids
    assert "06-picking-packing-dg-coldchain" in ids
    assert all(s["chars"] > 0 for s in sops)


def test_extract_requires_documents(client: TestClient) -> None:
    resp = client.post("/api/studio/drafts/extract", data={"role": "warehouse_operative"})
    assert resp.status_code == 400


def test_extract_from_selected_sop_starts_extracting(client: TestClient) -> None:
    resp = client.post(
        "/api/studio/drafts/extract",
        data={"role": "warehouse_operative", "sop_ids": "01-ppe-manual-handling"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "extracting"
    assert body["source_docs"] == ["01-ppe-manual-handling"]

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from umami_api.storage import PostgresStore, digest

CSV = (b"quantity,unit,time_h,biological_replicate,technical_replicate,value,origin\n"
       b"biomass_concentration,g/L,0,1,1,0.1,PHYSICAL\n"
       b"biomass_concentration,mg/L,12,1,1,5200,PHYSICAL\n"
       b"biomass_concentration,g/L,12,2,1,5.0,PHYSICAL\n"
       b"ph,pH,12,1,1,4.8,PHYSICAL\n")


@pytest.fixture
def proj(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    assay = client.post(f"{base}/assays", headers=headers, json={
        "key": "dcw", "name": "DCW", "quantity_kind": "biomass_concentration",
        "unit": "g/L"}).json()
    scientist, _ = make_member("scientist")
    return {"url": f"{base}/projects/{project['id']}", "owner": headers,
            "scientist": scientist, "assay": assay["id"], "base": base,
            "project": project["id"]}


def upload(client, p, content=CSV, origin="PHYSICAL", who="scientist", **params):
    return client.post(f"{p['url']}/artifacts", headers={**p[who], "Content-Type": "text/csv"},
                       content=content, params={"name": "results.csv", "origin": origin,
                                                "description": "CRO batch 7 export, emailed",
                                                **params})


def test_upload_download_and_ingest_physical_results(client, proj, database):
    response = upload(client, proj)
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert artifact["sha256"] == digest(CSV) and artifact["store"] == "postgres"
    assert artifact["provenance"]["recorded_by_kind"] == "human"
    content = client.get(f"{proj['url']}/artifacts/{artifact['id']}/content", headers=proj["owner"])
    assert content.content == CSV and content.headers["x-result-origin"] == "PHYSICAL"
    ingest = client.post(f"{proj['url']}/artifacts/{artifact['id']}/ingest",
                         headers=proj["scientist"],
                         json={"assay_map": {"biomass_concentration": proj["assay"]},
                               "sample_prefix": "batch7 "})
    assert ingest.status_code == 201, ingest.text
    assert ingest.json()["measurement_count"] == 3
    again = client.post(f"{proj['url']}/artifacts/{artifact['id']}/ingest",
                        headers=proj["scientist"],
                        json={"assay_map": {"biomass_concentration": proj["assay"]}})
    assert again.status_code == 409
    rows = client.get(f"{proj['url']}/measurements", headers=proj["owner"],
                      params={"origin": "PHYSICAL"}).json()
    assert sorted(r["value_canonical"] for r in rows) == [0.1, 5.0, 5.2]
    assert all(r["provenance"].startswith(f"artifact:{artifact['id']}") for r in rows)
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("UPDATE artifact_blobs SET content = 'x'"))


def test_file_labels_cannot_relabel_provenance(client, proj):
    artifact = upload(client, proj, origin="SIMULATED").json()
    response = client.post(f"{proj['url']}/artifacts/{artifact['id']}/ingest",
                           headers=proj["scientist"],
                           json={"assay_map": {"biomass_concentration": proj["assay"]}})
    assert response.status_code == 409


def test_upload_rules(client, proj, make_member):
    assert upload(client, proj, description="").status_code == 400  # physical needs provenance
    assert client.post(f"{proj['url']}/artifacts", headers={**proj["scientist"],
                       "Content-Type": "application/x-msdownload"}, content=b"MZ",
                       params={"name": "x.exe", "origin": "SIMULATED"}).status_code == 400
    agent, _ = make_member("agent", kind="agent")
    assert upload(client, proj, who="owner", origin="SIMULATED").status_code == 201
    proj["agent"] = agent
    assert upload(client, proj, who="agent", origin="SIMULATED").status_code == 403
    big = upload(client, proj, content=b"a" * (11 * 1024 * 1024), origin="SIMULATED")
    assert big.status_code == 413


def test_postgres_store_detects_corruption(database):
    store = PostgresStore()
    with database.session() as session:
        sha = store.put(session, b"hello")
        assert store.get(session, sha) == b"hello"
        assert store.put(session, b"hello") == sha

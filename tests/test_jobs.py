"""Tests du motif job (file de calcul asynchrone), Hub'Eau simulé :
dépôt, statut, résultat avec provenance, bascule automatique des
demandes trop grosses, échecs, plafonds."""

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from card_api import hubeau, jobs
from card_api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_hubeau(monkeypatch):
    """Chronique synthétique de 30 ans, saisonnière (cf. test_extract)."""
    def fake_fetch(station, refresh=False):
        if station.startswith("X"):
            raise hubeau.StationInconnue(f"aucune chronique QmnJ pour {station!r}")
        dates = pd.date_range("1990-01-01", "2019-12-31", freq="D")
        doy = dates.dayofyear.to_numpy()
        rng = np.random.default_rng(abs(hash(station)) % 2**32)
        q = 10 + 8 * np.sin(2 * np.pi * (doy - 30) / 365.25) \
            + rng.lognormal(0, 0.3, len(dates))
        return pd.DataFrame({"id": station, "date": dates, "Q": q})
    monkeypatch.setattr(hubeau, "fetch_chronicle", fake_fetch)


def _wait_done(job_id, timeout=30.0):
    """Interroge le statut jusqu'à l'état final (les workers tournent
    en arrière-plan : il faut attendre AVANT la fin du test pour que
    le simulateur Hub'Eau reste en place)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/v1/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} jamais terminé")


def test_job_trend_matches_sync():
    params = {"stations": "K0550010,F7000001", "cards": "QA"}
    sync = client.get("/v1/trend",
                      params={**params, "series": "true"}).json()

    r = client.post("/v1/jobs",
                    json={"endpoint": "trend", "series": True, **params})
    assert r.status_code == 202
    jid = r.json()["job"]
    assert r.headers["location"] == f"/v1/jobs/{jid}"

    status = _wait_done(jid)
    assert status["status"] == "done"
    res = client.get(f"/v1/jobs/{jid}/result")
    assert res.status_code == 200
    body = res.json()
    assert body["data"] == sync["data"]                 # même calcul exact
    assert body["series"] == sync["series"]     # séries extraites jointes
    prov = body["job"]
    assert prov["id"] == jid
    assert prov["data_fetched_at"]
    assert prov["params"]["endpoint"] == "trend"


def test_oversized_request_becomes_job():
    stations = ",".join(f"K{i:07d}" for i in range(11))   # > plafond sync
    r = client.get("/v1/extract", params={"stations": stations, "cards": "QA"})
    assert r.status_code == 202
    jid = r.json()["job"]
    assert _wait_done(jid)["status"] == "done"
    data = client.get(f"/v1/jobs/{jid}/result").json()["data"]["QA"]
    assert len({row["id"] for row in data}) == 11


def test_failed_job_surfaces_error():
    r = client.post("/v1/jobs", json={
        "endpoint": "extract", "stations": "X0000000", "cards": "QA"})
    jid = r.json()["job"]
    status = _wait_done(jid)
    assert status["status"] == "failed"
    assert "X0000000" in status["error"]
    assert client.get(f"/v1/jobs/{jid}/result").status_code == 409


def test_job_validation_and_unknown():
    too_many = [f"K{i:07d}" for i in range(jobs.JOB_STATIONS + 1)]
    assert client.post("/v1/jobs", json={
        "endpoint": "extract", "stations": too_many,
        "cards": "QA"}).status_code == 422
    assert client.post("/v1/jobs", json={
        "endpoint": "resample", "stations": "K0550010",
        "cards": "QA"}).status_code == 422
    assert client.post("/v1/jobs", json={
        "endpoint": "trend", "stations": "K0550010",
        "cards": "BFI-LH"}).status_code == 422       # fiche non 'series'
    assert client.get("/v1/jobs/deadbeef").status_code == 404


def test_stations_meta_joined_sync_and_job(monkeypatch):
    """stations_meta=true joint les fiches du référentiel Hub'Eau au
    résultat, en synchrone comme en job : résultat autoportant."""
    def fake_ref(libelle=None, code=None, departement=None, size=20):
        return [{"code_station": c, "longitude_station": 1.0,
                 "latitude_station": 45.0} for c in code.split(",")]
    monkeypatch.setattr(hubeau, "search_stations", fake_ref)

    params = {"stations": "K0550010,F7000001", "cards": "QA"}
    r = client.get("/v1/extract", params={**params, "stations_meta": "true"})
    assert {s["code_station"] for s in r.json()["stations_meta"]} \
        == {"K0550010", "F7000001"}
    assert "stations_meta" not in client.get("/v1/extract",
                                             params=params).json()

    r = client.post("/v1/jobs", json={"endpoint": "trend",
                                      "stations_meta": True, **params})
    jid = r.json()["job"]
    assert _wait_done(jid)["status"] == "done"
    body = client.get(f"/v1/jobs/{jid}/result").json()
    assert {s["code_station"] for s in body["stations_meta"]} \
        == {"K0550010", "F7000001"}
    assert body["job"]["params"]["stations_meta"] is True    # provenance


def test_job_delete_dismiss():
    """DELETE /v1/jobs/{id} : le ticket vaut capacité de suppression ;
    un job en cours n'est pas annulable (409)."""
    r = client.post("/v1/jobs", json={
        "endpoint": "extract", "stations": "K0550010", "cards": "QA"})
    jid = r.json()["job"]
    _wait_done(jid)
    assert client.delete(f"/v1/jobs/{jid}").status_code == 204
    assert client.get(f"/v1/jobs/{jid}").status_code == 404
    assert client.delete(f"/v1/jobs/{jid}").status_code == 404

    fake = {"id": "cafe0000cafe0000", "status": "running"}
    (jobs.jobs_dir() / fake["id"]).mkdir()
    jobs._save(fake)
    assert client.delete(f"/v1/jobs/{fake['id']}").status_code == 409
    jobs.delete(fake["id"])


def test_health_reports_queue_disk_and_data():
    body = client.get("/v1/health").json()
    assert set(body["jobs"]) == {"queued", "running"}
    assert body["disk"]["free_gb"] > 0
    assert set(body["data"]) == {"total_mb", "cache_mb", "jobs_mb"}
    assert body["data"]["total_mb"] >= body["data"]["jobs_mb"]

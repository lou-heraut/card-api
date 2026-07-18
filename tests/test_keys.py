"""Tests des clés de priorité : quota levé, plafonds relevés, tête de
file, 401 explicite pour une clé inconnue, jeton haché (jamais en
clair sur disque), listing « mes jobs » par clé ; et du retry
Hub'Eau."""

import time

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from card_api import hubeau, jobs, keys, usage
from card_api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_hubeau(monkeypatch):
    def fake_fetch(station, refresh=False):
        dates = pd.date_range("1990-01-01", "2019-12-31", freq="D")
        rng = np.random.default_rng(abs(hash(station)) % 2**32)
        q = 10 + rng.lognormal(0, 0.3, len(dates))
        return pd.DataFrame({"id": station, "date": dates, "Q": q})
    monkeypatch.setattr(hubeau, "fetch_chronicle", fake_fetch)


@pytest.fixture
def token():
    return keys.add("Testeuse, labo X")


def _wait_done(job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/v1/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} jamais terminé")


def test_unknown_key_is_explicit_401():
    r = client.get("/v1/extract",
                   params={"stations": "K0550010", "cards": "QA"},
                   headers={"X-API-Key": "n-importe-quoi"})
    assert r.status_code == 401
    assert "inconnue" in r.json()["detail"]


def test_key_bypasses_rate_limit(monkeypatch, token):
    monkeypatch.setattr(usage, "RATE_LIGHT", 1)
    params = {"code": "X"}
    monkeypatch.setattr(hubeau, "search_stations",
                        lambda *a, **k: [])
    assert client.get("/v1/stations", params=params).status_code == 200
    assert client.get("/v1/stations", params=params).status_code == 429
    r = client.get("/v1/stations", params={**params, "key": token})
    assert r.status_code == 200                    # la clé saute le quota


def test_key_raises_job_caps_and_priority(token):
    stations = ",".join(f"K{i:07d}" for i in range(jobs.JOB_STATIONS + 1))
    base = {"stations": stations, "cards": "QA", "start": "2015-01-01"}
    # sans clé : au-delà du plafond public
    assert client.get("/v1/extract", params=base).status_code == 422
    # avec clé : accepté, et le job est prioritaire (tête de file)
    r = client.get("/v1/extract", params={**base, "key": token})
    assert r.status_code == 202
    jid = r.json()["job"]
    assert jobs.load(jid)["priority"] == -1
    assert _wait_done(jid, timeout=120)["status"] == "done"


def test_token_never_stored_in_clear(token):
    """Le jeton n'existe qu'à l'affichage de création : sur disque,
    seul son hachage (sous le préfixe) ; perdu = réémettre."""
    stored = (hubeau.data_dir() / "keys.json").read_text()
    assert token not in stored
    assert token[:keys.PREFIX] in stored
    info = keys.lookup(token)
    assert info["name"] == "Testeuse, labo X"
    assert info["prefix"] == token[:keys.PREFIX]
    assert keys.lookup(token[:keys.PREFIX] + "x" * 24) is None


def test_revoke_by_prefix_name_or_token(token):
    assert "révoquée" in keys.revoke(token[:4])          # préfixe abrégé
    token = keys.add("Testeuse, labo X")
    assert "révoquée" in keys.revoke(token)              # jeton complet
    token = keys.add("Testeuse, labo X")
    assert "révoquée" in keys.revoke("Testeuse, labo X")  # nom exact
    assert keys.lookup(token) is None


def test_job_list_by_key(token):
    """GET /v1/jobs : réservé aux porteurs de clé, ne montre que les
    jobs déposés avec cette clé ; le job stocke le préfixe, jamais le
    jeton ni le nom."""
    assert client.get("/v1/jobs").status_code == 401     # pas de liste publique
    stations = ",".join(f"K{i:07d}" for i in range(jobs.SYNC_STATIONS + 1))
    r = client.get("/v1/extract",
                   params={"stations": stations, "cards": "QA"},
                   headers={"X-API-Key": token})
    jid = r.json()["job"]
    anon = client.get("/v1/extract",
                      params={"stations": stations, "cards": "QA"})
    _wait_done(jid)
    _wait_done(anon.json()["job"])

    on_disk = (jobs.jobs_dir() / jid / "job.json").read_text()
    assert token not in on_disk and "Testeuse" not in on_disk
    assert jobs.load(jid)["key"] == token[:keys.PREFIX]

    body = client.get("/v1/jobs", headers={"X-API-Key": token}).json()
    assert body["key"] == token[:keys.PREFIX]
    listed = {j["job"] for j in body["jobs"]}
    assert jid in listed and anon.json()["job"] not in listed
    mine = next(j for j in body["jobs"] if j["job"] == jid)
    assert mine["endpoint"] == "extract"
    assert mine["stations"] == jobs.SYNC_STATIONS + 1


def test_hubeau_retry_then_clean_failure(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"ok": 1}], "next": None}

    class _StubClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ReadTimeout("lent")
            return _Resp()

    monkeypatch.setattr(hubeau.httpx, "Client", _StubClient)
    monkeypatch.setattr(hubeau.time, "sleep", lambda s: None)
    assert hubeau._fetch_all("http://x", {}) == [{"ok": 1}]   # 2 retries
    assert calls["n"] == 3

    calls["n"] = -10                       # jamais assez de tentatives
    with pytest.raises(hubeau.HubEauIndisponible, match="réessayez"):
        hubeau._fetch_all("http://x", {})


def test_hubeau_down_maps_to_504(monkeypatch):
    def down(station, refresh=False):
        raise hubeau.HubEauIndisponible("Hub'Eau ne répond pas : réessayez")
    monkeypatch.setattr(hubeau, "fetch_chronicle", down)
    r = client.get("/v1/extract",
                   params={"stations": "K0550010", "cards": "QA"})
    assert r.status_code == 504
    assert r.headers.get("retry-after") == "300"

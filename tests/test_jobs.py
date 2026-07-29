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


# Champs qui n'existent QUE dans un résultat de job, et pourquoi. Un job
# produit un artefact gelé, qu'on archive et qu'on cite : la verbosité y
# est utile là où elle alourdirait une réponse immédiate. Toute autre
# différence entre les deux portes est un défaut.
PROPRES_AU_JOB = {"job", "data_fingerprints", "ltp_seed"}


@pytest.mark.parametrize("endpoint", ["extract", "trend"])
def test_les_deux_portes_rendent_le_meme_contrat(endpoint):
    """Le job et l'appel direct doivent rendre la MÊME enveloppe.

    Ce test comparait les données seulement (`body["data"]`), jamais le
    contrat. Quatre divergences vivaient dans cet angle mort, mesurées le
    2026-07-29 : `stations_omitted` et `stations_requested` absents du
    job, `data_fetched_at` imbriqué au lieu d'être à la racine, et surtout
    `period.start` différent, `START_DEFAUT` n'étant pas appliqué par un
    POST direct. Cette dernière est la plus grave : un crash se voit, une
    fenêtre temporelle silencieusement différente, non.

    Le vrai sujet n'est pas ces quatre écarts mais leur cause, deux
    implémentations de la même chaîne. Ce test est le garde-fou qui rend
    la divergence impossible à réintroduire sans le voir rougir.
    """
    params = {"stations": "K0550010,F7000001", "cards": "QA"}
    sync = client.get(f"/v1/{endpoint}", params=params).json()

    jid = client.post("/v1/jobs",
                      json={"endpoint": endpoint, **params}).json()["job"]
    assert _wait_done(jid)["status"] == "done"
    job = client.get(f"/v1/jobs/{jid}/result").json()

    assert set(job) - set(sync) == PROPRES_AU_JOB
    assert set(sync) - set(job) == set()
    # Les champs communs disent la même chose. Trois exceptions : les
    # données elles-mêmes, comparées par le test voisin, et
    # `data_fetched_at`, qui vaut l'instant courant tant qu'aucune
    # chronique n'est en cache (repli documenté de `fetched_at`). Deux
    # calculs successifs le rendent donc légitimement différent d'une
    # seconde ; ce qui compte est qu'il soit là, et à la racine.
    for cle in set(sync) & set(job):
        if cle in ("data", "meta", "series", "data_fetched_at"):
            continue
        assert job[cle] == sync[cle], cle
    assert job["data_fetched_at"] and sync["data_fetched_at"]


def test_oversized_request_becomes_job():
    stations = ",".join(f"K{i:07d}" for i in range(11))   # > plafond sync
    r = client.get("/v1/extract", params={"stations": stations, "cards": "QA"})
    assert r.status_code == 202
    jid = r.json()["job"]
    assert _wait_done(jid)["status"] == "done"
    data = client.get(f"/v1/jobs/{jid}/result").json()["data"]["QA"]
    assert len({row["id"] for row in data}) == 11


@pytest.mark.parametrize("chemin", ["/v1/extract.csv", "/v1/trend.csv",
                                    "/v1/trend/figure"])
def test_oversized_request_becomes_job_in_every_representation(chemin):
    """La bascule en file valait pour le JSON seulement : le CSV et la
    figure rendaient 500 (2026-07-29). Une demande trop grosse doit
    annoncer son ticket dans le medium demandé, quel qu'il soit."""
    stations = ",".join(f"K{i:07d}" for i in range(11))   # > plafond sync
    r = client.get(chemin, params={"stations": stations, "cards": "QA"})
    assert r.status_code == 202
    jid = r.headers["location"].rsplit("/", 1)[-1]
    assert jid in r.text                        # le ticket, lisible en clair
    assert _wait_done(jid)["status"] == "done"


def test_failed_job_surfaces_error():
    """Un job dont TOUTES les stations sont muettes échoue, et le dit.

    Ce test affirmait qu'un job sur station inconnue échoue, sans préciser
    « toutes ». Il est resté vert le 2026-07-29, quand une station muette a
    cessé d'être fatale en synchrone : il ne décrivait plus le
    comportement voulu mais l'oubli de le porter côté job, et rien ne
    distinguait les deux. Un test qui protège l'ancien comportement et qui
    passe encore après un changement de comportement est un signal
    d'arrêt.
    """
    r = client.post("/v1/jobs", json={
        "endpoint": "extract", "stations": "X0000000", "cards": "QA"})
    jid = r.json()["job"]
    status = _wait_done(jid)
    assert status["status"] == "failed"
    assert "X0000000" in status["error"]
    assert client.get(f"/v1/jobs/{jid}/result").status_code == 409


@pytest.mark.parametrize("endpoint", ["extract", "trend"])
def test_job_avec_une_station_muette_aboutit(endpoint):
    """Le cas signalé : vingt stations, une échelle limnimétrique parmi
    elles, et le job mourait à la sixième. La correction avait été portée
    côté synchrone seulement."""
    stations = ["K0550010", "X0000001", "F7000001"]
    jid = client.post("/v1/jobs", json={
        "endpoint": endpoint, "stations": stations,
        "cards": "QA"}).json()["job"]
    assert _wait_done(jid)["status"] == "done"
    res = client.get(f"/v1/jobs/{jid}/result")
    assert res.status_code == 200
    body = res.json()
    assert body["stations"] == ["K0550010", "F7000001"]
    assert body["stations_requested"] == stations
    (omise,) = body["stations_omitted"]
    assert omise["code_station"] == "X0000001"
    assert omise["reason"] == "no_series"


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

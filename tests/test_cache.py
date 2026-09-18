"""Le disque du service : fraîcheur, aller-retour, écriture atomique.

Ces tests ne touchent pas au réseau : `cache.py` ne connaît que des
fichiers.
"""

import gzip
import os
import time

import pandas as pd

from card_api import cache


def _copie(tmp_path, station="K0550010", contenu=b"x"):
    d = tmp_path / "chroniques"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{station}.csv.gz"
    f.write_bytes(contenu)
    return f


def test_la_fraicheur_respecte_la_duree_de_vie(monkeypatch, tmp_path):
    """Un seul critère de fraîcheur, posé à un seul endroit.

    Le routage des demandes et le téléchargement appellent tous les deux
    `is_fresh` : s'ils jugeaient chacun de leur côté, une demande annoncée
    immédiate pourrait partir pour une minute de téléchargements.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    f = _copie(tmp_path)
    assert cache.is_fresh("K0550010")
    vieux = time.time() - cache.MAX_AGE - 10
    os.utime(f, (vieux, vieux))
    assert not cache.is_fresh("K0550010")
    assert not cache.is_fresh("K9999999")           # jamais téléchargée


def test_la_date_de_collecte_est_celle_du_fichier(monkeypatch, tmp_path):
    """C'est ce que le service publie sous `data_fetched_at` : quand la
    donnée a été lue CHEZ HUB'EAU, pas quand le calcul a tourné."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    assert cache.collected_at("K0550010") is None
    f = _copie(tmp_path)
    instant = time.time() - 3600
    os.utime(f, (instant, instant))
    date = cache.collected_at("K0550010")
    assert date.endswith("+00:00")
    assert abs(pd.Timestamp(date).timestamp() - instant) < 1


def test_l_aller_retour_garde_les_types(monkeypatch, tmp_path):
    """Un code de station tout-numérique relu en int64 ne serait plus
    détecté comme identifiant de série, la détection se faisant par
    type : la chronique perdrait son identité en passant par le cache."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    df = pd.DataFrame({
        "code_station": "0123456789",
        "date": pd.date_range("2020-01-01", periods=5, freq="D"),
        "Q": [1.5, 2.5, 3.5, 4.5, 5.5],
    })
    cache.store_chronicle("0123456789", df)
    relu = cache.load_chronicle("0123456789")
    assert not pd.api.types.is_integer_dtype(relu["code_station"])
    assert relu["code_station"].iloc[0] == "0123456789"
    assert pd.api.types.is_datetime64_any_dtype(relu["date"])
    assert relu["Q"].tolist() == df["Q"].tolist()


def test_l_ecriture_est_atomique_et_compressee(monkeypatch, tmp_path):
    """Deux demandes simultanées sur la même station peuvent télécharger
    deux fois, c'est du gaspillage acceptable ; lire un fichier à moitié
    écrit ne l'est pas. D'où le temporaire puis le renommage, et la
    vérification qu'il ne reste rien derrière.

    La compression est vérifiée parce qu'elle est FRAGILE : pandas la
    déduit du suffixe, que le nom temporaire n'a pas. Demandée
    explicitement, mais rien ne le dirait si elle sautait, sinon un cache
    dix fois plus gros.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    df = pd.DataFrame({"code_station": "K0550010",
                       "date": pd.date_range("2020-01-01", periods=3),
                       "Q": [1.0, 2.0, 3.0]})
    cache.store_chronicle("K0550010", df)

    octets = cache.chronicle_path("K0550010").read_bytes()
    assert octets[:2] == b"\x1f\x8b"                  # en-tête gzip
    assert b"K0550010" in gzip.decompress(octets)
    assert sorted(p.name for p in cache.chronicles_dir().iterdir()) \
        == ["K0550010.csv.gz"]


def test_le_temoin_de_lecture_se_met_a_jour(monkeypatch, tmp_path):
    """La date du témoin EST l'information : elle doit avancer à chaque
    lecture, sinon l'éviction jugerait sur la première."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    _copie(tmp_path)
    assert cache.last_read("K0550010") is None

    cache.mark_read("K0550010")
    temoin = cache.read_marker("K0550010")
    vieux = temoin.stat().st_mtime - 86400
    os.utime(temoin, (vieux, vieux))

    cache.mark_read("K0550010")
    assert temoin.stat().st_mtime > vieux
    assert cache.last_read("K0550010").endswith("+00:00")


def test_une_demande_marque_la_lecture_un_rafraichissement_non(monkeypatch,
                                                              tmp_path):
    """La distinction sur laquelle repose toute l'éviction.

    Le rafraîchissement périodique réécrit les copies, donc écrase leur
    date de collecte. S'il marquait aussi les lectures, toutes les entrées
    paraîtraient consultées en permanence et rien ne sortirait jamais du
    cache : la station que personne n'a jamais redemandée resterait là
    pour toujours.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    from card_api import hubeau

    brut = [{"code_station": "K0550010", "date_obs_elab": "1990-01-01",
             "resultat_obs_elab": 272000.0}]
    monkeypatch.setattr(hubeau, "_fetch_all", lambda url, params: brut)

    hubeau.fetch_chronicle("K0550010", refresh=True)
    assert cache.is_fresh("K0550010")                 # la copie est là
    assert cache.last_read("K0550010") is None        # personne ne l'a lue

    hubeau.fetch_chronicle("K0550010")                # servie depuis le cache
    assert cache.last_read("K0550010") is not None
    # Et la comptabilité ne salit pas les données : `chroniques/` garde une
    # entrée par fichier, les témoins vivent dans `lectures/`.
    assert [p.name for p in cache.chronicles_dir().iterdir()] \
        == ["K0550010.csv.gz"]

    # Une demande qui doit télécharger marque aussi : on vient de la
    # payer, elle ne doit pas passer pour jamais lue.
    cache.chronicle_path("K0550010").unlink()
    cache.read_marker("K0550010").unlink()
    hubeau.fetch_chronicle("K0550010")
    assert cache.last_read("K0550010") is not None

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
    """Une copie en cache, posée là où le cache l'attend.

    Le nom se demande à `cache.chronicle_path` et ne se fabrique pas ici :
    il porte une marque de format, et un test qui recopierait la règle
    cesserait de vérifier le vrai chemin le jour où elle change.
    """
    f = cache.chronicle_path(station)
    f.parent.mkdir(parents=True, exist_ok=True)
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
    vieux = time.time() - cache.MAX_AGE_DAYS * 86400 - 10
    os.utime(f, (vieux, vieux))
    assert not cache.is_fresh("K0550010")
    assert not cache.is_fresh("K9999999")           # jamais téléchargée


def test_la_requete_peut_exiger_plus_frais(monkeypatch, tmp_path):
    """`max_age` est un nombre de JOURS, et `0` n'est pas l'absence.

    Confondre les deux servirait une copie à qui demande explicitement une
    lecture neuve, ce qui est exactement le contraire de ce qu'il demande.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    f = _copie(tmp_path)
    vieux = time.time() - 10 * 86400                # copie de dix jours
    os.utime(f, (vieux, vieux))
    assert cache.is_fresh("K0550010")               # défaut : plus large
    assert cache.is_fresh("K0550010", max_age=30)
    assert not cache.is_fresh("K0550010", max_age=2)

    os.utime(f, None)                               # copie de l'instant
    assert cache.is_fresh("K0550010", max_age=1)
    assert not cache.is_fresh("K0550010", max_age=0)


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
        == [cache.chronicle_path("K0550010").name]


def test_le_registre_avance_la_date_et_compte_les_lectures(monkeypatch,
                                                          tmp_path):
    """Trois faits par entrée, dont deux qu'un fichier seul ne porterait pas.

    Le compte est la raison d'être de la table : le journal d'usage
    enregistre le NOMBRE de stations d'une requête, jamais leurs codes,
    donc « quelles entrées sont les plus consultées » ne se dérive de rien
    d'autre.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    assert cache.last_read("K0550010") is None
    assert cache.read_age("K0550010") is None
    assert cache.read_count("K0550010") == 0

    cache.mark_read("K0550010")
    date1, n1 = cache._ligne("K0550010")
    assert n1 == 1
    assert cache.read_age("K0550010") < 5
    assert cache.last_read("K0550010").endswith("+00:00")
    assert (tmp_path / "cache.db").exists()

    time.sleep(0.01)                                # horloge, pas patience
    cache.mark_read("K0550010")
    date2, n2 = cache._ligne("K0550010")
    assert date2 > date1                            # la date avance
    assert n2 == 2                                  # et le compte monte

    cache.forget("K0550010")                        # la copie est évincée
    assert cache.last_read("K0550010") is None      # le registre la suit
    assert cache.read_count("K0550010") == 0


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
    # entrée par fichier, le registre vit dans `cache.db`.
    assert [p.name for p in cache.chronicles_dir().iterdir()] \
        == [cache.chronicle_path("K0550010").name]

    # Une demande qui doit télécharger marque aussi : on vient de la
    # payer, elle ne doit pas passer pour jamais lue.
    cache.chronicle_path("K0550010").unlink()
    cache.forget("K0550010")
    hubeau.fetch_chronicle("K0550010")
    assert cache.last_read("K0550010") is not None


def test_une_copie_au_format_perime_est_traitee_comme_absente(monkeypatch,
                                                              tmp_path):
    """Le cas n'est pas théorique : des copies d'avant le renommage
    `id` → `code_station` du 2026-07-28 existent encore sur des disques.

    Servie telle quelle, une telle copie ne donne pas une erreur claire
    mais un 422 sur des « dates dupliquées », le moteur ne reconnaissant
    aucune colonne identifiante et prenant deux cents stations pour une
    seule série. Tant que les copies vivaient un jour, le cas s'effaçait de
    lui-même ; l'âge accepté étant passé au mois, il peut durer.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    ancienne = pd.DataFrame({"id": ["K0550010"] * 3,
                             "date": pd.date_range("1990-01-01", periods=3),
                             "Q": [1.0, 2.0, 3.0]})
    ancienne.to_csv(cache.chronicle_path("K0550010"), index=False,
                    compression="gzip")
    assert cache.is_fresh("K0550010")                  # elle est là, fraîche
    assert cache.load_chronicle("K0550010") is None    # et inutilisable
    assert not cache.chronicle_path("K0550010").exists()

    # ... donc une demande la retélécharge au lieu d'échouer
    from card_api import hubeau
    monkeypatch.setattr(hubeau, "_fetch_all", lambda url, params: [
        {"code_station": "K0550010", "date_obs_elab": "1990-01-01",
         "resultat_obs_elab": 272000.0}])
    df = hubeau.fetch_chronicle("K0550010")
    assert list(df.columns) == ["code_station", "date", "Q"]


def test_une_copie_d_un_format_plus_ancien_n_est_pas_servie(monkeypatch,
                                                            tmp_path):
    """La marque de format est dans le NOM, donc une copie écrite par un
    client plus ancien n'est même pas trouvée : inoffensive par
    construction, là où un contrôle de contenu attraperait un cas et
    laisserait passer le suivant.

    L'éviction la ramasse sans attendre le délai de lecture : elle ne peut
    plus être servie, donc la garder ne fait que prendre de la place.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    ancienne = cache.chronicles_dir() / "K0550010.csv.gz"
    ancienne.write_bytes(b"x")

    assert not cache.is_fresh("K0550010")            # pas trouvée
    assert cache.cached_stations() == ["K0550010"]   # mais à rafraîchir
    assert cache.evict(10_000)["chroniques"] == 1    # et effacée d'office
    assert not ancienne.exists()

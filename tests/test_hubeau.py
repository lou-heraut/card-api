"""Le client Hub'Eau lui-même : ce qu'il redresse dans la donnée reçue.

Ces tests ne passent PAS par `fake_hubeau` de test_extract.py, qui
remplace `fetch_chronicle` en entier : ils vérifient justement ce que
cette fonction fait de la réponse brute, donc ils simulent un cran plus
bas, au niveau de `_fetch_all`.
"""
def test_le_doublon_de_site_de_hubeau_est_ecarte(monkeypatch):
    """Interrogé avec un code de SITE, Hub'Eau sert deux fois la même
    mesure : une ligne étiquetée avec la station qui l'a produite, une
    ligne sans étiquette. Vérifié sur K0114020 et K0018723 : à une date
    donnée les deux ne diffèrent que par `code_station` et `date_prod`,
    la valeur est identique.

    Non filtré, ce doublon faisait échouer toute demande sur un code de
    site par un 422 « dates dupliquées » venu de card, dont le message
    conseillait un paramètre Python inatteignable depuis HTTP. Or les
    anciens codes Banque Hydro sont des codes de site.
    """
    from card_api import hubeau

    brut = [
        {"code_station": "K011402001", "date_obs_elab": "1990-01-01",
         "resultat_obs_elab": 272000.0},
        {"code_station": None, "date_obs_elab": "1990-01-01",
         "resultat_obs_elab": 272000.0},
        {"code_station": "K011402001", "date_obs_elab": "1990-01-02",
         "resultat_obs_elab": 261000.0},
        {"code_station": None, "date_obs_elab": "1990-01-02",
         "resultat_obs_elab": 261000.0},
    ]
    monkeypatch.setattr(hubeau, "_fetch_all", lambda url, params: brut)
    df = hubeau.fetch_chronicle("K0114020", refresh=True)
    assert len(df) == 2, "la ligne sans code_station doit être écartée"
    assert not df.duplicated(subset=["code_station", "date"]).any()
    assert df["Q"].tolist() == [272.0, 261.0]


def test_repli_si_aucune_ligne_n_est_etiquetee(monkeypatch):
    """Mieux vaut la chronique telle quelle qu'une station soudainement
    introuvable : le filtre ne doit jamais tout retirer."""
    from card_api import hubeau

    brut = [{"code_station": None, "date_obs_elab": "1990-01-01",
             "resultat_obs_elab": 272000.0}]
    monkeypatch.setattr(hubeau, "_fetch_all", lambda url, params: brut)
    assert len(hubeau.fetch_chronicle("K0114020", refresh=True)) == 1

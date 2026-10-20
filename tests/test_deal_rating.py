from deal_rating import noter_affaire, noter_annonces


def test_seuils():
    assert noter_affaire(40, 100) == "excellente affaire"
    assert noter_affaire(50, 100) == "excellente affaire"
    assert noter_affaire(60, 100) == "bonne affaire"
    assert noter_affaire(75, 100) == "affaire normale"
    assert noter_affaire(85, 100) == "mauvaise affaire"
    assert noter_affaire(120, 100) == "mauvaise affaire"


def test_reference_inconnue():
    assert noter_affaire(50, None) is None
    assert noter_affaire(50, 0) is None


def test_lot():
    annonces = noter_annonces([{"prix": 30, "prix_reference": 100}, {"prix": 90}])
    assert annonces[0]["verdict"] == "excellente affaire"
    assert annonces[1]["verdict"] is None

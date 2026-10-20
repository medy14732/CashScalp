"""Verdict par annonce : compare le prix Cash Converters au prix de référence (ex. Amazon neuf)."""

# Seuils de remise minimale par rapport au prix de référence, du meilleur au pire.
# Un objet d'occasion se revend en général ~30 % sous le neuf, donc en dessous
# de 20 % de remise il ne reste quasiment pas de marge après frais de revente.
SEUILS = [
    (0.50, "excellente affaire"),
    (0.35, "bonne affaire"),
    (0.20, "affaire normale"),
]
VERDICT_MAUVAIS = "mauvaise affaire"


def remise(prix_cc, prix_reference):
    """Écart relatif : 0.4 signifie 40 % moins cher que la référence."""
    if prix_reference is None or prix_reference <= 0:
        return None
    return (prix_reference - prix_cc) / prix_reference


def noter_affaire(prix_cc, prix_reference, seuils=SEUILS):
    """Renvoie le verdict d'une annonce, ou None si le prix de référence est inconnu."""
    r = remise(prix_cc, prix_reference)
    if r is None:
        return None
    for seuil, verdict in seuils:
        if r >= seuil:
            return verdict
    return VERDICT_MAUVAIS


def noter_annonces(annonces, seuils=SEUILS):
    """Ajoute 'remise' et 'verdict' à chaque annonce (dict avec 'prix' et 'prix_reference')."""
    for a in annonces:
        a["remise"] = remise(a["prix"], a.get("prix_reference"))
        a["verdict"] = noter_affaire(a["prix"], a.get("prix_reference"), seuils)
    return annonces

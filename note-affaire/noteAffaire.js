// Verdict par annonce : compare le prix Cash Converters au prix de référence (ex. Amazon neuf).

// Remise minimale par rapport au prix de référence, du meilleur au pire verdict.
// Un objet d'occasion se revend en général ~30 % sous le neuf, donc en dessous
// de 20 % de remise il ne reste quasiment pas de marge après frais de revente.
export const SEUILS = [
  { remiseMin: 0.5, verdict: "excellente affaire" },
  { remiseMin: 0.35, verdict: "bonne affaire" },
  { remiseMin: 0.2, verdict: "affaire normale" },
];
export const VERDICT_MAUVAIS = "mauvaise affaire";

// Écart relatif : 0.4 signifie 40 % moins cher que la référence
export function calculerRemise(prix, prixReference) {
  if (prixReference == null || prixReference <= 0) return null;
  return (prixReference - prix) / prixReference;
}

// Renvoie le verdict, ou null si le prix de référence est inconnu
export function noterAffaire(prix, prixReference, seuils = SEUILS) {
  const remise = calculerRemise(prix, prixReference);
  if (remise === null) return null;
  return seuils.find((s) => remise >= s.remiseMin)?.verdict ?? VERDICT_MAUVAIS;
}

// Note tous les résultats d'une recherche d'un coup ({ prix, prixReference, ... })
export function noterAnnonces(annonces, seuils = SEUILS) {
  return annonces.map((a) => ({
    ...a,
    remise: calculerRemise(a.prix, a.prixReference),
    verdict: noterAffaire(a.prix, a.prixReference, seuils),
  }));
}

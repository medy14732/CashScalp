// Note chaque annonce Cash Converters par rapport à son prix Amazon,
// pour toute la liste de résultats d'un coup (et plus une par une).

import { prixAmazon } from "./prixAmazon.js";

export const NOTES = {
  EXCELLENTE: "excellente affaire",
  BONNE: "bonne affaire",
  NORMALE: "affaire normale",
  MAUVAISE: "mauvaise affaire",
  INCONNUE: "pas de prix Amazon",
};

export const REGLAGES_PAR_DEFAUT = {
  // Un article d'occasion se revend environ 65 % de son prix neuf sur Amazon
  decoteOccasion: 0.65,
  // Frais de revente (commission Vinted/2ememain, envoi…) en part du prix de revente
  fraisRevente: 0.1,
  // Seuils sur le rapport prix Cash Converters / prix Amazon
  seuils: { excellente: 0.4, bonne: 0.6, normale: 0.8 },
  // Nombre de recherches Amazon en même temps
  enParallele: 4,
};

const arrondi = (n) => Math.round(n * 100) / 100;

export function noter(prixCash, prixReference, reglages = REGLAGES_PAR_DEFAUT) {
  if (!prixReference) return { note: NOTES.INCONNUE, gain: null, rapport: null, prixRevente: null };
  const { decoteOccasion, fraisRevente, seuils } = { ...REGLAGES_PAR_DEFAUT, ...reglages };
  const rapport = prixCash / prixReference;
  const prixRevente = prixReference * decoteOccasion;
  const gain = prixRevente * (1 - fraisRevente) - prixCash;
  let note = NOTES.MAUVAISE;
  if (rapport <= seuils.excellente) note = NOTES.EXCELLENTE;
  else if (rapport <= seuils.bonne) note = NOTES.BONNE;
  else if (rapport <= seuils.normale) note = NOTES.NORMALE;
  return { note, gain: arrondi(gain), rapport: arrondi(rapport), prixRevente: arrondi(prixRevente) };
}

// annonces : [{ titre, prix, ... }] → mêmes annonces avec prixAmazon, note et gain,
// triées du meilleur gain au pire. Une erreur sur un article n'arrête pas les autres.
export async function evaluerAffaires(annonces, options = {}) {
  const reglages = { ...REGLAGES_PAR_DEFAUT, ...options.reglages };
  const cache = options.cache ?? new Map();
  const resultats = new Array(annonces.length);
  let suivant = 0;

  async function travailleur() {
    while (suivant < annonces.length) {
      const i = suivant++;
      const annonce = annonces[i];
      let reference = null;
      let erreur;
      try {
        reference = await prixAmazon(annonce.titre, { ...options, cache });
      } catch (e) {
        erreur = e.message;
      }
      resultats[i] = {
        ...annonce,
        prixAmazon: reference?.prix ?? null,
        lienAmazon: reference?.url ?? null,
        titreAmazon: reference?.titre ?? null,
        ...noter(annonce.prix, reference?.prix, reglages),
        ...(erreur && { erreur }),
      };
    }
  }

  const nb = Math.max(1, Math.min(reglages.enParallele, annonces.length));
  await Promise.all(Array.from({ length: nb }, travailleur));
  return resultats.sort((a, b) => (b.gain ?? -Infinity) - (a.gain ?? -Infinity));
}

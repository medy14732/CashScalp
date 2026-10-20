import { test } from "node:test";
import assert from "node:assert/strict";
import { noterAffaire, noterAnnonces } from "./noteAffaire.js";

test("chaque tranche de remise donne le bon verdict", () => {
  assert.equal(noterAffaire(40, 100), "excellente affaire");
  assert.equal(noterAffaire(50, 100), "excellente affaire");
  assert.equal(noterAffaire(60, 100), "bonne affaire");
  assert.equal(noterAffaire(75, 100), "affaire normale");
  assert.equal(noterAffaire(85, 100), "mauvaise affaire");
  assert.equal(noterAffaire(120, 100), "mauvaise affaire");
});

test("pas de verdict sans prix de référence", () => {
  assert.equal(noterAffaire(50, null), null);
  assert.equal(noterAffaire(50, 0), null);
});

test("toutes les annonces d'une recherche sont notées d'un coup", () => {
  const [a, b] = noterAnnonces([{ prix: 30, prixReference: 100 }, { prix: 90 }]);
  assert.equal(a.verdict, "excellente affaire");
  assert.equal(a.remise, 0.7);
  assert.equal(b.verdict, null);
});

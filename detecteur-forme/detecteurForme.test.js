import { test } from "node:test";
import assert from "node:assert/strict";
import { detecterForme, analyserProcesseur } from "./detecteurForme.js";

test("le Dell i7-1365U classé « ordinateurs de bureau » est un portable", () => {
  const r = detecterForme({
    titre: "(etat coque)PC Desktop DELL I7-1365U 16gb GB 256 SSD win 11",
    categorie: "ordinateurs de bureau",
    processeur: "Intel Core i7-1365U",
    memoire: "16 Go DDR4",
  });
  assert.equal(r.forme, "portable");
  assert.equal(r.categorieIncoherente, true);
  assert.equal(r.methodeEstimation, "modele-complet");
});

test("la tour Aero Cool i5-10400 RTX 3050 est une tour", () => {
  const r = detecterForme({
    titre: "PC Desktop Aero Cool I5-10400 RTX 3050 16gb GB 500gbn W",
    description: "Aero Cool Processeur I5-10400 Disque Dur 500gbn OS Win 11 Carte graphique RTX 3050 Mémoire RAM 16gb",
    categorie: "ordinateurs de bureau",
    processeur: "Intel Core i5-10400",
    carteGraphique: "GeForce RTX 3050",
  });
  assert.equal(r.forme, "tour");
  assert.equal(r.categorieIncoherente, false);
  assert.equal(r.methodeEstimation, "pieces");
});

test("suffixes des processeurs", () => {
  const cas = {
    "i5-1135G7": "portable", "i7-10750H": "portable", "i9-13980HX": "portable",
    "i5-10400": "bureau", "i9-13900K": "bureau", "i5-12400F": "bureau", "i5-8500T": "basse-conso",
    "Core Ultra 7 155H": "portable", "Core Ultra 7 258V": "portable", "Core Ultra 9 285K": "bureau",
    "Ryzen 5 7530U": "portable", "Ryzen 7 5800H": "portable", "Ryzen 9 7945HX": "portable",
    "Ryzen 7 5800X3D": "bureau", "Ryzen 5 5600G": "bureau", "Ryzen 5 3600": "bureau",
  };
  for (const [modele, attendu] of Object.entries(cas)) {
    assert.equal(analyserProcesseur(modele.toLowerCase())?.type, attendu, modele);
  }
});

test("mini-PC et tout-en-un", () => {
  assert.equal(detecterForme({ titre: "Dell OptiPlex 7070 Micro i5-9500T mini PC" }).forme, "mini-pc");
  assert.equal(detecterForme({ titre: "HP tout-en-un 24 pouces i5-10400T" }).forme, "tout-en-un");
});

test("« retour » ne déclenche pas « tour »", () => {
  assert.equal(detecterForme({ titre: "PC sans retour possible" }).forme, "inconnu");
});

test("ThinkPad avec Ryzen classé en bureau", () => {
  const r = detecterForme({ titre: "Lenovo ThinkPad E14 Ryzen 5 5500U 8Go", categorie: "ordinateurs de bureau" });
  assert.equal(r.forme, "portable");
  assert.equal(r.categorieIncoherente, true);
});

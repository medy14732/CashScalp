import { test } from "node:test";
import assert from "node:assert/strict";
import {
  nettoyerTitre, urlRecherche, lirePrix, lireResultatsAmazon, choisirReference, prixAmazon,
} from "./prixAmazon.js";
import { evaluerAffaires, noter, NOTES } from "./evaluerAffaires.js";

const resultat = ({ asin, titre, prix, sponsorise = false }) => `
<div data-asin="${asin}" data-component-type="s-search-result" class="s-result-item${sponsorise ? " AdHolder" : ""}">
  <h2 class="a-size-mini"><a href="/x/dp/${asin}"><span>${titre}</span></a></h2>
  <span class="a-price"><span class="a-offscreen">${prix}</span><span aria-hidden="true">${prix}</span></span>
</div>`;

const pageNokia = `<html><body>
${resultat({ asin: "B000000AD1", titre: "Nokia 3310 Téléphone", prix: "59,99 €", sponsorise: true })}
${resultat({ asin: "B000000CQ1", titre: "Coque pour Nokia 105", prix: "6,99 €" })}
${resultat({ asin: "B07X1KSHRC", titre: "Nokia 105 Téléphone Portable Débloqué Dual SIM - Noir", prix: "29,90 €" })}
</body></html>`;

test("nettoie le titre Cash Converters avant la recherche", () => {
  assert.equal(nettoyerTitre("GSM Nokia 105"), "nokia 105");
  assert.equal(nettoyerTitre("(etat coque) Console NINTENDO GameBoy..."), "nintendo gameboy");
  assert.equal(nettoyerTitre("iPhone 12 complète avec boîte"), "iphone 12");
  assert.equal(urlRecherche("GSM Nokia 105"), "https://www.amazon.fr/s?k=nokia%20105");
});

test("lit les prix au format français et anglais", () => {
  assert.equal(lirePrix("14,99 €"), 14.99);
  assert.equal(lirePrix("1 299,99 €"), 1299.99);
  assert.equal(lirePrix("1.299,99 €"), 1299.99);
  assert.equal(lirePrix("€1,299.99"), 1299.99);
  assert.equal(lirePrix(""), null);
});

test("ignore les résultats sponsorisés", () => {
  const r = lireResultatsAmazon(pageNokia);
  assert.deepEqual(r.map((x) => x.asin), ["B000000CQ1", "B07X1KSHRC"]);
  assert.equal(r[1].url, "https://www.amazon.fr/dp/B07X1KSHRC");
});

test("prend le téléphone, pas la coque", () => {
  const ref = choisirReference("GSM Nokia 105", lireResultatsAmazon(pageNokia));
  assert.equal(ref.asin, "B07X1KSHRC");
  assert.equal(ref.prix, 29.9);
});

test("pas de référence si aucun résultat ne ressemble à l'article", () => {
  const page = resultat({ asin: "B0000000Z1", titre: "Glacière électrique Mobicool", prix: "49,99 €" });
  assert.equal(choisirReference("Frigo Camping Campingaz", lireResultatsAmazon(page)), null);
});

test("note l'affaire selon le rapport prix Cash / prix Amazon", () => {
  assert.equal(noter(10, 100).note, NOTES.EXCELLENTE);
  assert.equal(noter(50, 100).note, NOTES.BONNE);
  assert.equal(noter(75, 100).note, NOTES.NORMALE);
  assert.equal(noter(95, 100).note, NOTES.MAUVAISE);
  assert.equal(noter(14.99, null).note, NOTES.INCONNUE);
  // 100 € neuf → revente 65 €, moins 10 % de frais = 58,50 €, payé 10 € → +48,50 €
  assert.equal(noter(10, 100).gain, 48.5);
});

test("évalue toute la liste d'un coup, triée par gain, avec cache", async () => {
  const pages = {
    "nokia%20105": pageNokia,
    "nintendo%20gameboy%20color": resultat({ asin: "B00000GBC1", titre: "Nintendo GameBoy Color Jaune", prix: "199,00 €" }),
  };
  let appels = 0;
  const telecharger = async (url) => {
    appels++;
    const cle = url.split("?k=")[1];
    if (!(cle in pages)) return { ok: false, status: 503 };
    return { ok: true, text: async () => pages[cle] };
  };
  const annonces = [
    { titre: "GSM Nokia 105", prix: 14.99 },
    { titre: "Console NINTENDO GameBoy Color", prix: 79.99 },
    { titre: "Frigo Camping Campingaz", prix: 39.99 },
    { titre: "GSM Nokia 105", prix: 19.99 },
  ];
  const r = await evaluerAffaires(annonces, { telecharger });

  assert.equal(appels, 3, "le deuxième Nokia réutilise le prix déjà trouvé");
  assert.deepEqual(r.map((a) => a.titre), [
    "Console NINTENDO GameBoy Color", "GSM Nokia 105", "GSM Nokia 105", "Frigo Camping Campingaz",
  ]);
  assert.equal(r[0].prixAmazon, 199);
  assert.equal(r[0].note, NOTES.BONNE);
  assert.equal(r[3].note, NOTES.INCONNUE);
  assert.match(r[3].erreur, /503/);
});

test("prixAmazon remonte l'erreur si Amazon bloque", async () => {
  await assert.rejects(
    prixAmazon("Nokia 105", { telecharger: async () => ({ ok: false, status: 503 }) }),
    /503/,
  );
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { lirePrix, versAnnonce, urlRecherche, rechercher } from "./cashConverters.js";

test("lecture des prix", () => {
  assert.equal(lirePrix("14,99 €"), 14.99);
  assert.equal(lirePrix("1 299,00 €"), 1299);
  assert.equal(lirePrix("1.299,00 €"), 1299);
  assert.equal(lirePrix(79.99), 79.99);
  assert.equal(lirePrix(""), null);
});

test("URL de recherche avec filtre magasin", () => {
  const url = new URL(urlRecherche("game boy", { page: 2, magasin: "arlon" }));
  assert.equal(url.searchParams.get("s"), "game boy");
  assert.equal(url.searchParams.get("q"), "Magasin-ARLON");
  assert.equal(url.searchParams.get("page"), "2");
});

test("un produit PrestaShop devient une annonce", () => {
  const annonce = versAnnonce({
    id_product: 42,
    name: "Console NINTENDO GameBoy Color",
    price: "79,99 €",
    price_amount: 79.99,
    url: "https://www.cashconverters.be/fr/consoles/42-console.html",
    features: [{ name: "Magasin", value: "ARLON" }, { name: "Etat", value: "Bon état" }],
  });
  assert.deepEqual(annonce, {
    id: 42,
    titre: "Console NINTENDO GameBoy Color",
    prix: 79.99,
    etat: "Bon état",
    magasin: "ARLON",
    lien: "https://www.cashconverters.be/fr/consoles/42-console.html",
  });
});

test("sans caractéristique « état », on prend la condition PrestaShop", () => {
  const annonce = versAnnonce({ name: "GSM Nokia 105", price: "14,99 €", condition: { label: "Utilisé" } });
  assert.equal(annonce.etat, "Utilisé");
  assert.equal(annonce.magasin, null);
});

test("la recherche parcourt toutes les pages", async () => {
  const pages = {
    1: { products: [{ name: "A", price: "1,00 €" }], pagination: { pages_count: 2 } },
    2: { products: [{ name: "B", price: "2,00 €" }], pagination: { pages_count: 2 } },
  };
  const fetchFn = async url => {
    const page = new URL(url).searchParams.get("page") ?? "1";
    return { ok: true, text: async () => JSON.stringify(pages[page]) };
  };
  const annonces = await rechercher("x", { fetchFn });
  assert.deepEqual(annonces.map(a => a.titre), ["A", "B"]);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { urlMagasin, filtrerParMagasin, marquerNouveaux, listerNouveautes } from "./nouveautes.js";

test("l'url filtre le magasin comme le site", () => {
  assert.equal(urlMagasin("Arlon"), "https://www.cashconverters.be/fr/2-categories?q=Magasin-ARLON");
  assert.equal(urlMagasin("la louviere"), "https://www.cashconverters.be/fr/2-categories?q=Magasin-LA-LOUVIERE");
  assert.equal(urlMagasin(), "https://www.cashconverters.be/fr/2-categories");
});

test("seuls les articles du magasin demandé restent", () => {
  const articles = [{ magasin: "ARLON" }, { magasin: "MONS" }, {}];
  assert.deepEqual(filtrerParMagasin(articles, "arlon"), [{ magasin: "ARLON" }]);
  assert.equal(filtrerParMagasin(articles).length, 3);
});

test("un article déjà vu n'est plus marqué nouveau", () => {
  const { articles, dejaVus } = marquerNouveaux([{ lien: "a" }, { lien: "b" }], ["a"]);
  assert.deepEqual(articles.map((a) => a.nouveau), [false, true]);
  assert.deepEqual(dejaVus.sort(), ["a", "b"]);
});

test("la deuxième recherche ne remonte que les vrais nouveaux", async () => {
  const fichierVus = join(await mkdtemp(join(tmpdir(), "nouveautes-")), "vus.json");
  let stock = [{ lien: "a", magasin: "ARLON" }];
  const recuperer = async () => stock;

  const premiere = await listerNouveautes(recuperer, { magasin: "ARLON", fichierVus });
  assert.deepEqual(premiere.map((a) => a.nouveau), [true]);

  stock = [{ lien: "b", magasin: "ARLON" }, ...stock];
  const seconde = await listerNouveautes(recuperer, { magasin: "ARLON", fichierVus });
  assert.deepEqual(seconde.map((a) => [a.lien, a.nouveau]), [["b", true], ["a", false]]);
});

// Option « nouveautés » : liste les derniers articles mis en ligne, filtrés par magasin,
// et marque ceux qu'on n'a encore jamais vus depuis la dernière recherche.
// La lecture du site vient du scraper de base ; ce module ne fait que le tri.
import { readFile, writeFile } from "node:fs/promises";

export const SITE = "https://www.cashconverters.be";

// Le site filtre un magasin avec ?q=Magasin-ARLON (vu sur la page catégories)
export function urlMagasin(magasin, chemin = "/fr/2-categories") {
  const url = new URL(chemin, SITE);
  if (magasin) url.searchParams.set("q", `Magasin-${normaliserMagasin(magasin)}`);
  return url.toString();
}

// « Arlon », « arlon » et « ARLON » désignent le même magasin
export function normaliserMagasin(magasin) {
  return magasin.trim().toUpperCase().replace(/\s+/g, "-");
}

// Garde les articles du magasin demandé (tous si aucun magasin)
export function filtrerParMagasin(articles, magasin) {
  if (!magasin) return articles;
  const cible = normaliserMagasin(magasin);
  return articles.filter((a) => a.magasin && normaliserMagasin(a.magasin) === cible);
}

// Ajoute nouveau: true aux articles jamais vus ; renvoie aussi la liste des vus à jour.
// Un article est reconnu par son lien, stable d'une visite à l'autre.
export function marquerNouveaux(articles, dejaVus) {
  const vus = new Set(dejaVus);
  const marques = articles.map((a) => ({ ...a, nouveau: !vus.has(a.lien) }));
  for (const a of articles) vus.add(a.lien);
  return { articles: marques, dejaVus: [...vus] };
}

export async function chargerDejaVus(fichier) {
  try {
    return JSON.parse(await readFile(fichier, "utf8"));
  } catch (e) {
    if (e.code === "ENOENT") return [];
    throw e;
  }
}

export async function sauverDejaVus(fichier, dejaVus) {
  await writeFile(fichier, JSON.stringify(dejaVus, null, 2));
}

// recupererArticles(url) vient du scraper de base et renvoie [{ titre, prix, magasin, lien, ... }]
export async function listerNouveautes(recupererArticles, { magasin, fichierVus = "deja-vus.json" } = {}) {
  const articles = filtrerParMagasin(await recupererArticles(urlMagasin(magasin)), magasin);
  const resultat = marquerNouveaux(articles, await chargerDejaVus(fichierVus));
  await sauverDejaVus(fichierVus, resultat.dejaVus);
  return resultat.articles;
}

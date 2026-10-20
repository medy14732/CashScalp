// Scraper Cash Converters : recherche par mot-clé.
//
// Le site (cashconverters.be) tourne sous PrestaShop. Une page de recherche
// demandée avec « Accept: application/json » renvoie les annonces en JSON
// (au lieu du HTML), ce qui évite de parser la page.
//
// Pour chaque annonce on garde : titre, prix, état, magasin et lien.

export const SITE_PAR_DEFAUT = "https://www.cashconverters.be/fr";

const ENTETES = {
  Accept: "application/json, text/javascript, */*; q=0.01",
  "X-Requested-With": "XMLHttpRequest",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
};

// Le nom des caractéristiques varie : on cherche par motif plutôt que par nom exact
const RE_MAGASIN = /magasin|boutique|store/i;
const RE_ETAT = /[ée]tat|grade|condition/i;

// « 1 299,99 € » -> 1299.99
export function lirePrix(texte) {
  if (typeof texte === "number") return texte;
  if (!texte) return null;
  const nombre = String(texte).replace(/[^\d,.]/g, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", ".");
  const valeur = parseFloat(nombre);
  return Number.isFinite(valeur) ? valeur : null;
}

function caracteristique(produit, motif) {
  const liste = produit.features ?? produit.grouped_features ?? [];
  const valeurs = Array.isArray(liste) ? liste : Object.values(liste);
  return valeurs.find(f => motif.test(f?.name ?? ""))?.value ?? null;
}

/** Transforme un produit PrestaShop (JSON) en annonce. */
export function versAnnonce(produit) {
  const conditionPrestashop = produit.condition && typeof produit.condition === "object"
    ? produit.condition.label
    : null;
  return {
    id: produit.id_product ?? null,
    titre: produit.name ?? null,
    prix: lirePrix(produit.price_amount ?? produit.price),
    etat: caracteristique(produit, RE_ETAT) ?? conditionPrestashop,
    magasin: caracteristique(produit, RE_MAGASIN),
    lien: produit.canonical_url ?? produit.url ?? null,
  };
}

export function urlRecherche(motCle, { page = 1, magasin, site = SITE_PAR_DEFAUT } = {}) {
  const url = new URL(`${site}/recherche`);
  url.searchParams.set("controller", "search");
  url.searchParams.set("s", motCle);
  // Filtre de PrestaShop, même format que sur le site : q=Magasin-ARLON
  if (magasin) url.searchParams.set("q", `Magasin-${magasin.toUpperCase()}`);
  if (page > 1) url.searchParams.set("page", String(page));
  return url.toString();
}

async function chargerPage(url, fetchFn) {
  const reponse = await fetchFn(url, { headers: ENTETES });
  if (!reponse.ok) throw new Error(`Cash Converters a répondu ${reponse.status} pour ${url}`);
  const texte = await reponse.text();
  try {
    return JSON.parse(texte);
  } catch {
    throw new Error(`Réponse inattendue (pas du JSON) pour ${url} : ${texte.slice(0, 120)}`);
  }
}

/**
 * Cherche un mot-clé et renvoie les annonces de toutes les pages.
 * @param {string} motCle
 * @param {object} [options]
 * @param {string} [options.magasin]   ex. « ARLON »
 * @param {number} [options.maxPages]  limite de pages à parcourir (5 par défaut)
 * @param {string} [options.site]      base du site, sans « / » final
 * @param {Function} [options.fetchFn] remplace fetch (pour les tests)
 */
export async function rechercher(motCle, { magasin, maxPages = 5, site = SITE_PAR_DEFAUT, fetchFn = fetch } = {}) {
  const annonces = [];
  for (let page = 1; page <= maxPages; page++) {
    const donnees = await chargerPage(urlRecherche(motCle, { page, magasin, site }), fetchFn);
    annonces.push(...(donnees.products ?? []).map(versAnnonce));
    const nbPages = donnees.pagination?.pages_count ?? 1;
    if (page >= nbPages) break;
  }
  return annonces;
}

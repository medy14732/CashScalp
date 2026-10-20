// Prix Amazon : le prix de référence de chaque article Cash Converters.
//
// Pour chaque annonce on cherche le titre sur Amazon, on garde le premier
// résultat qui ressemble vraiment à l'article (pas une coque ou un chargeur),
// et son prix devient la référence pour noter l'affaire et estimer le gain.

export const DOMAINE_PAR_DEFAUT = "www.amazon.fr";

// Mots du titre Cash Converters qui gênent la recherche Amazon
const MOTS_PARASITES = [
  "occasion", "reconditionné", "reconditionne", "très bon état", "tres bon etat", "bon état",
  "bon etat", "etat correct", "état correct", "complet", "complète", "avec boite", "sans boite",
  "avec boîte", "sans boîte", "nouveau", "gsm", "console",
];

// Résultats Amazon à écarter : des accessoires de l'article, pas l'article
const MOTS_ACCESSOIRES = [
  "coque", "housse", "étui", "etui", "chargeur", "câble", "cable", "protection", "verre trempé",
  "film", "support", "batterie de rechange", "adaptateur", "sacoche", "skin", "autocollant",
];

export function nettoyerTitre(titre) {
  let t = titre.toLowerCase();
  // « (etat coque) », « [lot] »… : remarques du vendeur, pas le nom du produit
  t = t.replace(/\([^)]*\)|\[[^\]]*\]/g, " ");
  for (const mot of MOTS_PARASITES) {
    t = t.replace(new RegExp(`(^|[^\\p{L}\\d])${mot}(?=$|[^\\p{L}\\d])`, "giu"), "$1 ");
  }
  return t.replace(/\.{2,}|…/g, " ").replace(/[^\p{L}\d+\-. ]/gu, " ").replace(/\s+/g, " ").trim();
}

export function urlRecherche(titre, domaine = DOMAINE_PAR_DEFAUT) {
  return `https://${domaine}/s?k=${encodeURIComponent(nettoyerTitre(titre))}`;
}

// « 1 299,99 € », « 14,99 € », « €14.99 » → 1299.99, 14.99, 14.99
export function lirePrix(texte) {
  if (!texte) return null;
  const brut = texte.replace(/[\s  €]/g, "").replace(/EUR/i, "");
  const m = brut.match(/\d[\d.,]*/);
  if (!m) return null;
  let n = m[0];
  if (/,\d{1,2}$/.test(n)) n = n.replace(/\./g, "").replace(",", ".");
  else n = n.replace(/,/g, "");
  const prix = Number.parseFloat(n);
  return Number.isFinite(prix) && prix > 0 ? prix : null;
}

function decoderHtml(s) {
  return s
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
}

// Lit la page de résultats Amazon : titre, prix et lien de chaque produit.
// Les résultats sponsorisés sont ignorés, ils ne suivent pas la recherche.
export function lireResultatsAmazon(html, domaine = DOMAINE_PAR_DEFAUT) {
  const blocs = html.split(/(?=<div[^>]*data-component-type="s-search-result")/).slice(1);
  const resultats = [];
  for (const bloc of blocs) {
    if (/AdHolder|puis-sponsored|Sponsorisé|Sponsored/i.test(bloc)) continue;
    const asin = bloc.match(/data-asin="([A-Z0-9]{10})"/)?.[1];
    const titre = bloc.match(/<h2[^>]*>([\s\S]*?)<\/h2>/)?.[1];
    const prix = lirePrix(bloc.match(/<span class="a-offscreen">([^<]+)<\/span>/)?.[1]);
    if (!asin || !titre || !prix) continue;
    resultats.push({ asin, titre: decoderHtml(titre), prix, url: `https://${domaine}/dp/${asin}` });
  }
  return resultats;
}

const mots = (s) => new Set(nettoyerTitre(s).split(" ").filter((m) => m.length > 1));

// Part des mots de l'annonce retrouvés dans le titre Amazon (0 à 1)
export function ressemblance(titreAnnonce, titreAmazon) {
  const a = mots(titreAnnonce);
  if (a.size === 0) return 0;
  const b = mots(titreAmazon);
  let communs = 0;
  for (const m of a) if (b.has(m)) communs++;
  return communs / a.size;
}

// Choisit le résultat Amazon qui correspond à l'annonce, ou null si aucun ne colle
export function choisirReference(titreAnnonce, resultats, seuil = 0.5) {
  const titreAnnonceBas = titreAnnonce.toLowerCase();
  let meilleur = null;
  for (const r of resultats) {
    const titreBas = r.titre.toLowerCase();
    const accessoire = MOTS_ACCESSOIRES.some((m) => titreBas.includes(m) && !titreAnnonceBas.includes(m));
    if (accessoire) continue;
    const score = ressemblance(titreAnnonce, r.titre);
    if (score >= seuil && (!meilleur || score > meilleur.score)) meilleur = { ...r, score };
  }
  return meilleur;
}

const ENTETES = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  "Accept-Language": "fr-FR,fr;q=0.9",
};

// Cherche le prix Amazon d'un article. `telecharger` est remplaçable pour les tests.
export async function prixAmazon(titre, { domaine = DOMAINE_PAR_DEFAUT, telecharger = fetch, cache } = {}) {
  const cle = nettoyerTitre(titre);
  // On garde la recherche en cours : deux annonces identiques ne font qu'une requête
  if (cache?.has(cle)) return cache.get(cle);
  const recherche = (async () => {
    const reponse = await telecharger(urlRecherche(titre, domaine), { headers: ENTETES });
    if (!reponse.ok) throw new Error(`Amazon a répondu ${reponse.status}`);
    return choisirReference(titre, lireResultatsAmazon(await reponse.text(), domaine));
  })();
  cache?.set(cle, recherche);
  // Une erreur (Amazon qui bloque) ne reste pas en cache : on pourra réessayer
  recherche.catch(() => cache?.delete(cle));
  return recherche;
}

// Détecteur de forme : tour, PC portable, mini-PC ou tout-en-un.
//
// But : ne pas estimer un PC portable « pièce par pièce » comme une tour.
// Le détecteur combine plusieurs indices (processeur, carte graphique,
// mots-clés, RAM) avec des poids. Le processeur est l'indice le plus fiable,
// la catégorie choisie par le vendeur est le moins fiable (elle est souvent fausse).

export const FORMES = {
  TOUR: "tour",
  PORTABLE: "portable",
  MINI_PC: "mini-pc",
  TOUT_EN_UN: "tout-en-un",
  INCONNU: "inconnu",
};

// Poids des indices : un processeur portable pèse plus qu'un mot dans le titre
const POIDS = { processeur: 5, gpu: 3, motCleFort: 4, motCle: 2, ram: 2, categorie: 1 };

// --- Processeurs -----------------------------------------------------------

// Intel Core i3/i5/i7/i9 : i7-1365U, i5-1135G7, i7-10750H, i5-10400, i9-13900K
const RE_INTEL_CORE = /\bi[3579][\s-]*(\d{4,5})([a-z]{0,2}\d?)(?![a-z0-9])/i;
// Intel Core Ultra : Ultra 7 155H, Ultra 5 125U, Ultra 7 258V, Ultra 9 285K
const RE_INTEL_ULTRA = /\bultra\s*[579]\s*(\d{3})([a-z]{0,2})(?![a-z0-9])/i;
// AMD Ryzen : Ryzen 7 5800H, Ryzen 5 7530U, Ryzen 7 5800X3D, Ryzen 5 5600G
const RE_RYZEN = /\bryzen\s*[3579]\s*(?:pro\s*)?(\d{4})([a-z0-9]{0,3})(?![a-z0-9])/i;

const SUFFIXES_INTEL_PORTABLE = /^(u|h|hq|hk|hs|hx|mq|m|y|p|g\d)$/i;
const SUFFIXES_INTEL_BUREAU = /^(|k|kf|ks|f|t|s|e|te)$/i;
const SUFFIXES_ULTRA_PORTABLE = /^(u|h|hx|v)$/i;
const SUFFIXES_ULTRA_BUREAU = /^(|k|kf|f|t)$/i;
const SUFFIXES_RYZEN_PORTABLE = /^(u|h|hs|hx)$/i;
const SUFFIXES_RYZEN_BUREAU = /^(|x|xt|x3d|g|ge|gt|f)$/i;

export function analyserProcesseur(texte) {
  const essais = [
    [RE_INTEL_CORE, SUFFIXES_INTEL_PORTABLE, SUFFIXES_INTEL_BUREAU],
    [RE_INTEL_ULTRA, SUFFIXES_ULTRA_PORTABLE, SUFFIXES_ULTRA_BUREAU],
    [RE_RYZEN, SUFFIXES_RYZEN_PORTABLE, SUFFIXES_RYZEN_BUREAU],
  ];
  for (const [re, portable, bureau] of essais) {
    const m = texte.match(re);
    if (!m) continue;
    const suffixe = m[2] ?? "";
    if (portable.test(suffixe)) return { type: "portable", modele: m[0] };
    if (bureau.test(suffixe)) {
      // Les processeurs T sont des modèles basse conso, typiques des mini-PC
      return { type: /^t/i.test(suffixe) ? "basse-conso" : "bureau", modele: m[0] };
    }
    return { type: "inconnu", modele: m[0] };
  }
  return null;
}

// --- Mots-clés ---------------------------------------------------------------

const MOTS_PORTABLE_FORTS = [
  "pc portable", "ordinateur portable", "laptop", "notebook", "ultrabook", "chromebook",
  "macbook", "latitude", "thinkpad", "elitebook", "probook", "zbook", "zenbook",
  "vivobook", "ideapad", "yoga", "xps 13", "xps 15", "xps 17", "inspiron 14",
  "inspiron 15", "inspiron 16", "pavilion 14", "pavilion 15", "envy x360", "aspire",
  "swift", "nitro 5", "predator helios", "rog strix g", "rog zephyrus", "tuf gaming f",
  "legion 5", "legion 7", "omen 15", "omen 16", "victus", "surface laptop", "galaxy book",
];
const MOTS_PORTABLE = ["portable", "batterie", "pouces", "écran 1", "touchpad", "pavé tactile", "charnière"];

const MOTS_TOUR_FORTS = [
  "tour", "tower", "unité centrale", "pc de bureau", "boîtier atx", "micro-atx",
  "optiplex", "prodesk", "elitedesk", "thinkcentre", "vostro desktop", "aerocool",
  "aero cool", "nzxt", "corsair", "cooler master", "be quiet", "fractal", "lian li",
];
const MOTS_TOUR = ["desktop", "alimentation", "watercooling", "ventirad"];

const MOTS_MINI_PC = ["mini pc", "mini-pc", "nuc", "mac mini", "sff", "tiny", "micro pc", "usff"];
const MOTS_TOUT_EN_UN = ["tout-en-un", "tout en un", "all-in-one", "all in one", "aio", "imac"];

// Recherche un mot entier (évite « tour » dans « retour » ou « aio » dans « aiolos »)
function contient(texte, mot) {
  const echappe = mot.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^\\p{L}\\d])${echappe}($|[^\\p{L}\\d])`, "iu").test(texte);
}

function motsTrouves(texte, liste) {
  return liste.filter(mot => contient(texte, mot));
}

// --- Détecteur ---------------------------------------------------------------

/**
 * @param {object} annonce
 * @param {string} [annonce.titre]
 * @param {string} [annonce.description]  la « fiche du vendeur »
 * @param {string} [annonce.categorie]    la catégorie choisie par le vendeur
 * @param {string} [annonce.processeur]
 * @param {string} [annonce.carteGraphique]
 * @param {string} [annonce.memoire]
 */
export function detecterForme(annonce) {
  const texte = [annonce.titre, annonce.description, annonce.processeur, annonce.carteGraphique, annonce.memoire]
    .filter(Boolean).join(" ").toLowerCase();

  const scores = { portable: 0, tour: 0, "mini-pc": 0, "tout-en-un": 0 };
  const indices = [];
  const ajouter = (forme, poids, raison) => {
    scores[forme] += poids;
    indices.push({ forme, poids, raison });
  };

  // 1. Processeur
  const cpu = analyserProcesseur(texte);
  if (cpu?.type === "portable") ajouter("portable", POIDS.processeur, `processeur mobile (${cpu.modele})`);
  if (cpu?.type === "bureau") ajouter("tour", POIDS.processeur, `processeur de bureau (${cpu.modele})`);
  if (cpu?.type === "basse-conso") ajouter("mini-pc", POIDS.motCle, `processeur basse conso (${cpu.modele})`);

  // 2. Carte graphique
  const gpu = (annonce.carteGraphique ?? texte).toLowerCase();
  if (/laptop gpu|max-q|mobile|\bmx\s?\d{3}\b|rtx\s?2050|rtx\s?3050\s?ti/.test(gpu)) {
    ajouter("portable", POIDS.gpu, "carte graphique pour portable");
  }

  // 3. Mémoire : la SO-DIMM se trouve dans les portables et les mini-PC
  if (/so-?dimm/.test(texte)) ajouter("portable", POIDS.ram, "RAM SO-DIMM");

  // 4. Mots-clés
  for (const mot of motsTrouves(texte, MOTS_PORTABLE_FORTS)) ajouter("portable", POIDS.motCleFort, `mot-clé « ${mot} »`);
  for (const mot of motsTrouves(texte, MOTS_PORTABLE)) ajouter("portable", POIDS.motCle, `mot-clé « ${mot} »`);
  for (const mot of motsTrouves(texte, MOTS_TOUR_FORTS)) ajouter("tour", POIDS.motCleFort, `mot-clé « ${mot} »`);
  for (const mot of motsTrouves(texte, MOTS_TOUR)) ajouter("tour", POIDS.motCle, `mot-clé « ${mot} »`);
  for (const mot of motsTrouves(texte, MOTS_MINI_PC)) ajouter("mini-pc", POIDS.motCleFort + 2, `mot-clé « ${mot} »`);
  for (const mot of motsTrouves(texte, MOTS_TOUT_EN_UN)) ajouter("tout-en-un", POIDS.motCleFort + 2, `mot-clé « ${mot} »`);

  // 5. Catégorie du vendeur (indice faible)
  const categorie = (annonce.categorie ?? "").toLowerCase();
  if (/bureau|desktop/.test(categorie)) ajouter("tour", POIDS.categorie, "catégorie du vendeur");
  if (/portable|laptop/.test(categorie)) ajouter("portable", POIDS.categorie, "catégorie du vendeur");

  // Décision
  const classement = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const [[forme, meilleur], [, second]] = classement;
  const total = Object.values(scores).reduce((s, v) => s + v, 0);

  let resultat = FORMES.INCONNU;
  let confiance = 0;
  if (meilleur > 0) {
    resultat = forme;
    confiance = Math.round((meilleur / total) * 100);
    if (meilleur - second < 2) confiance = Math.min(confiance, 50);
  }

  const categorieVendeur = /portable|laptop/.test(categorie) ? FORMES.PORTABLE
    : /bureau|desktop/.test(categorie) ? FORMES.TOUR : null;

  return {
    forme: resultat,
    confiance, // en %
    indices,
    // La catégorie du vendeur contredit la détection (ex. portable classé « ordinateurs de bureau »)
    categorieIncoherente: categorieVendeur !== null && resultat !== FORMES.INCONNU
      && categorieVendeur !== resultat && resultat !== FORMES.MINI_PC && resultat !== FORMES.TOUT_EN_UN,
    // Seule une tour se reconstruit pièce par pièce, le reste s'estime au modèle complet
    methodeEstimation: resultat === FORMES.TOUR ? "pieces" : "modele-complet",
  };
}

export const LIBELLES_FORME = {
  [FORMES.TOUR]: "PC de bureau (tour)",
  [FORMES.PORTABLE]: "PC portable",
  [FORMES.MINI_PC]: "Mini-PC",
  [FORMES.TOUT_EN_UN]: "PC tout-en-un",
  [FORMES.INCONNU]: "Format non déterminé",
};

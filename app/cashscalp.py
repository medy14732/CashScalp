#!/usr/bin/env python3
"""
cashscalp.py - Scalpeur pour Cash Converters Belgique (cashconverters.be)

Trouve les meilleures offres d'un magasin (ou d'une région) et d'une catégorie.
Aucune dépendance externe : Python 3.8+ suffit.

Exemples :
    python cashscalp.py                                  # mode interactif
    python cashscalp.py -m ARLON
    python cashscalp.py -m ARLON -c gsm --max 300
    python cashscalp.py -r luxembourg -c montres -k seiko
    python cashscalp.py -m ARLON -c informatique --comparer
    python cashscalp.py --lister-magasins
    python cashscalp.py --lister-categories
"""
import argparse
import csv
import html
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://www.cashconverters.be/fr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAI = 0.6          # secondes entre deux requêtes (rester poli avec le site)
PAR_PAGE = 100       # max accepté par le site
DOSSIER = os.path.dirname(os.path.abspath(__file__))

MAGASINS = [
    "ANS-ROCOURT", "ANTWERPEN", "ARLON", "ATH", "AYWAILLE", "BERCHEM STE-AGATHE",
    "BINCHE", "BOUGE (NAMUR)", "BRAINE l'ALLEUD", "BRUXELLES", "CORA Anderlecht",
    "COUILLET", "DROGENBOS", "ETTERBEEK", "EVERE", "FLERON", "FROYENNES",
    "GOSSELIES", "GRIVEGNEE", "HERSTAL", "HUY", "IXELLES", "JAMBES", "JETTE",
    "LA LOUVIERE", "LIEGE CENTRE", "MARCHE", "MONS", "MOUSCRON", "QUAREGNON",
    "SAINT-GILLES", "SAINT-JOSSE", "SAMBREVILLE", "SERAING", "SINT-AMANDSBERG",
    "TUBIZE", "VERVIERS", "WAVRE",
]

REGIONS = {
    "luxembourg": ["ARLON", "MARCHE"],
    "liege": ["ANS-ROCOURT", "AYWAILLE", "FLERON", "GRIVEGNEE", "HERSTAL", "HUY",
              "LIEGE CENTRE", "SERAING", "VERVIERS"],
    "namur": ["BOUGE (NAMUR)", "JAMBES", "SAMBREVILLE"],
    "hainaut": ["ATH", "BINCHE", "COUILLET", "FROYENNES", "GOSSELIES", "LA LOUVIERE",
                "MONS", "MOUSCRON", "QUAREGNON"],
    "bruxelles": ["BERCHEM STE-AGATHE", "BRUXELLES", "CORA Anderlecht", "DROGENBOS",
                  "ETTERBEEK", "EVERE", "IXELLES", "JETTE", "SAINT-GILLES", "SAINT-JOSSE"],
    "brabant-wallon": ["BRAINE l'ALLEUD", "TUBIZE", "WAVRE"],
    "flandre": ["ANTWERPEN", "SINT-AMANDSBERG"],
}

# Catégories principales (id-slug). La liste complète : --lister-categories
CATEGORIES = {
    "tout": "2-categories",
    "outillage-jardinage": "126-outillage-jardinage",
    "outillage": "127-outillage",
    "jardinage": "166-jardinage",
    "bijoux-montres": "130-bijoux-montres-",
    "montres": "131-montres",
    "bijouterie": "226-bijouterie",
    "electromenager": "132-electromenager",
    "petit-electromenager": "133-petit-electromenager",
    "informatique": "134-informatique",
    "ordinateurs-portables": "135-ordinateurs-portables",
    "ordinateurs-de-bureau": "164-ordinateurs-de-bureau",
    "tablettes": "140-tablettes-tactiles",
    "moniteurs": "162-moniteurs",
    "telephonie": "136-gsm-gps-telephonie",
    "gsm": "137-gsm",
    "montre-connectee": "209-montre-connectee",
    "jeux-video": "138-jeux-consoles-video",
    "consoles-sony": "139-consoles-sony",
    "consoles-nintendo": "158-consoles-nintendo",
    "consoles-xbox": "176-consoles-xbox",
    "jeux-playstation": "173-jeux-playstation",
    "jeux-nintendo": "200-jeux-nintendo",
    "hifi": "141-hifi",
    "enceintes": "142-enceintes",
    "photo-video": "143-photo-video-optique",
    "photo-numerique": "154-photo-numerique",
    "objectifs": "144-objectifs-photo",
    "tv-home-cinema": "147-tv-home-cinema-lecteurs-graveurs",
    "tv": "148-tv",
    "instruments": "150-instruments-de-musique",
    "guitares": "151-guitares",
    "sport": "152-sport",
    "velos": "157-velos-accessoires-velo",
    "luxe-maroquinerie": "215-sacs-maroquineries-luxes",
    "livres-jouets": "211-livres-jouets",
    "vinyles": "234-vinyles",
    "accessoires-informatique": "220-accessoires-informatique",
}

# Mots ignorés pour comparer les noms de produits
MOTS_VIDES = set("""
de du des la le les et en a au aux pour avec sans un une gsm smartphone telephone
portable ordinateur pc tablette console jeu jeux montre go gb to tb ram noir blanc
bleu rouge gris argent or rose vert batterie etat bon tres occasion neuf avec boite
""".split())


# --------------------------------------------------------------------------- catégories du site
FICHIER_CATEGORIES = os.path.join(DOSSIER, "categories.json")
SIGLES = {"gsm", "gps", "tv", "dvd", "cd", "k7", "mp3", "pda", "hp"}


def joli_nom(nom):
    """« gsm / gps / telephonie » -> « GSM / GPS / Telephonie » (mêmes mots que le site, juste mis en forme)."""
    nom = re.sub(r"\s+", " ", nom).strip()
    mots = [m.upper() if m.lower() in SIGLES else m for m in nom.split(" ")]
    nom = " ".join(mots)
    return nom[:1].upper() + nom[1:]


def categories_du_site():
    """Arborescence exacte du menu « Les catégories » de cashconverters.be (catégories > sous-catégories).
    En cas d'échec, on reprend la dernière copie enregistrée."""
    try:
        page = get(f"{BASE}/", json_attendu=False)
        bloc = page[page.index("categories-list--wrapper-scrollable"):]
        arbre, vus = [], set()
        for item in re.split(r'<div class="categories-list--item item-\d+">', bloc)[1:]:
            t = re.search(r'href="https://www\.cashconverters\.be/fr/(\d+-[a-z0-9-]+)" class="categories--title"'
                          r'.*?<span[^>]*>\s*([^<]+?)\s*</span>', item, re.S)
            if not t or t.group(1) in vus:
                continue
            vus.add(t.group(1))
            sous = []
            for slug, nom in re.findall(r'href="https://www\.cashconverters\.be/fr/(\d+-[a-z0-9-]+)"[^>]*>\s*([^<]+?)\s*</a>', item):
                if slug in vus or any(slug == s for s, _ in sous):
                    break                      # le menu se répète ensuite (version mobile) : on s'arrête
                sous.append((slug, joli_nom(html.unescape(nom))))
            arbre.append({"slug": t.group(1), "nom": joli_nom(html.unescape(t.group(2))), "sous": sous})
        if len(arbre) < 5:
            raise ValueError("menu des catégories introuvable")
        try:
            with open(FICHIER_CATEGORIES, "w", encoding="utf-8") as f:
                json.dump(arbre, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        return arbre
    except Exception:
        with open(FICHIER_CATEGORIES, encoding="utf-8") as f:
            return json.load(f)


# --------------------------------------------------------------------------- réseau
def lire(reponse):
    """Corps d'une réponse HTTP, décompressé si le site l'a envoyé en gzip (5 à 10x plus léger)."""
    import gzip
    import zlib
    corps = reponse.read()
    codage = (reponse.headers.get("Content-Encoding") or "").lower()
    if codage == "gzip":
        corps = gzip.decompress(corps)
    elif codage == "deflate":
        corps = zlib.decompress(corps)
    return corps.decode("utf-8", "replace")


def get(url, json_attendu=True, essais=3):
    entetes = {"User-Agent": UA, "Accept-Language": "fr-BE,fr;q=0.9", "Accept-Encoding": "gzip"}
    if json_attendu:
        entetes["Accept"] = "application/json, text/javascript, */*; q=0.01"
        entetes["X-Requested-With"] = "XMLHttpRequest"
    for n in range(essais):
        try:
            req = urllib.request.Request(url, headers=entetes)
            with urllib.request.urlopen(req, timeout=30) as r:
                corps = lire(r)
            time.sleep(DELAI)
            return json.loads(corps) if json_attendu else corps
        except Exception as e:  # réseau instable, 5xx, JSON coupé…
            if n == essais - 1:
                raise
            print(f"  ! erreur ({e}), nouvel essai…", file=sys.stderr)
            time.sleep(2 * (n + 1))


def echapper_facette(valeur):
    # PrestaShop sépare les valeurs par "-" : un tiret dans un nom s'écrit "\-"
    return valeur.replace("-", "\\-")


def url_liste(categorie_slug, magasins, page, tri, recherche=None):
    params = {"resultsPerPage": PAR_PAGE, "page": page, "from-xhr": ""}
    if recherche:  # moteur de recherche du site (ignore le filtre magasin)
        params.update(controller="search", s=recherche)
        return f"{BASE}/recherche?" + urllib.parse.urlencode(params)
    if magasins:
        params["q"] = "Magasin-" + "-".join(echapper_facette(m) for m in magasins)
    if tri:
        params["order"] = tri
    return f"{BASE}/{categorie_slug}?" + urllib.parse.urlencode(params)


# --------------------------------------------------------------------------- parsing
RE_ARTICLE = re.compile(
    r'data-id-product="(\d+)".*?storefront</i>\s*([^<]+?)\s*</span>', re.S)


def magasins_depuis_html(rendu):
    """id_product -> nom du magasin (absent du JSON, présent dans le HTML rendu)."""
    morceaux = rendu.split('<article class="product-miniature')
    res = {}
    for m in morceaux[1:]:
        mm = RE_ARTICLE.search('<article ' + m)
        if mm:
            res[mm.group(1)] = html.unescape(mm.group(2)).strip()
    return res


def nom_complet(p):
    """Le site coupe « name » à 60 caractères ; la description courte contient le nom entier."""
    nom = html.unescape(p.get("name", "")).strip()
    desc = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p.get("description_short") or ""))).strip()
    debut = re.sub(r"\W+", "", nom.lower())[:25]
    if len(desc) > len(nom) and len(desc) < 220 and re.sub(r"\W+", "", desc.lower()).startswith(debut):
        return desc
    return nom


def produit_vers_dict(p, magasin):
    image = ""
    try:
        image = p["cover"]["bySize"]["home_default"]["url"]
    except (KeyError, TypeError):
        pass
    prix = float(p.get("price_amount") or 0)
    prix_normal = float(p.get("regular_price_amount") or prix)
    remise = round((1 - prix / prix_normal) * 100, 1) if prix_normal > prix > 0 else 0.0
    return {
        "id": str(p["id_product"]),
        "nom": nom_complet(p),
        "prix": prix,
        "prix_normal": prix_normal,
        "remise_pct": remise,
        "categorie": p.get("category_name", ""),
        "magasin": magasin,
        "url": p.get("url", ""),
        "image": image,
        "reference": p.get("reference", ""),
    }


# --------------------------------------------------------------------------- scraping
def scraper(categorie_slug, magasins, tri=None, maximum=None, verbeux=True, progres=None,
            recherche=None):
    # Le site refuse (403) les filtres de plus de 3 magasins : on interroge par paquets de 3
    if magasins and len(magasins) > 3 and not recherche:
        paquets = [magasins[i:i + 3] for i in range(0, len(magasins), 3)]
        tous = []
        for n, paquet in enumerate(paquets):
            def prog(msg, frac, n=n):
                if progres:
                    progres(f"Magasins {n * 3 + 1}-{n * 3 + len(paquet)}/{len(magasins)} · {msg}",
                            (n + frac) / len(paquets))
            tous += scraper(categorie_slug, paquet, tri, None, verbeux, prog)
        return tous[:maximum] if maximum else tous
    produits, page = [], 1
    while True:
        d = get(url_liste(categorie_slug, magasins, page, tri, recherche))
        noms_mag = magasins_depuis_html(d.get("rendered_products", ""))
        for p in d.get("products", []):
            mag = noms_mag.get(str(p["id_product"]), magasins[0] if len(magasins) == 1 else "?")
            produits.append(produit_vers_dict(p, mag))
        pag = d.get("pagination", {})
        total, nb_pages = pag.get("total_items", 0), pag.get("pages_count", 1)
        if progres:
            progres(f"Page {page}/{nb_pages} - {len(produits)}/{total} articles",
                    page / max(nb_pages, 1))
        if verbeux:
            print(f"  page {page}/{nb_pages} - {len(produits)}/{total} articles", end="\r")
        if page >= nb_pages or not d.get("products") or (maximum and len(produits) >= maximum):
            break
        page += 1
    if verbeux:
        print()
    return produits[:maximum] if maximum else produits


def plat(texte):
    """Minuscules sans accents, ponctuation conservée (pour les filtres par type de produit)."""
    t = unicodedata.normalize("NFKD", texte.lower().replace(" ", " "))
    return "".join(c for c in t if not unicodedata.combining(c))


def normaliser(texte):
    t = unicodedata.normalize("NFKD", texte.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [m for m in re.findall(r"[a-z0-9]+", t) if m not in MOTS_VIDES and len(m) > 1]


def similarite(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def comparer_prix(produit, cache):
    """Cherche le même article dans tout le réseau et renvoie (médiane, nb)."""
    mots = normaliser(produit["nom"])[:6]
    if len(mots) < 2:
        return None, 0
    requete = " ".join(mots)
    if requete not in cache:
        url = f"{BASE}/recherche?" + urllib.parse.urlencode(
            {"controller": "search", "s": requete, "resultsPerPage": 50, "from-xhr": ""})
        try:
            cache[requete] = get(url).get("products", [])
        except Exception:
            cache[requete] = []
    prix = []
    for p in cache[requete]:
        if str(p["id_product"]) == produit["id"]:
            continue
        if similarite(mots, normaliser(p.get("name", ""))) >= 0.5:
            prix.append(float(p.get("price_amount") or 0))
    prix = [x for x in prix if x > 0]
    if len(prix) < 2:
        return None, len(prix)
    return statistics.median(prix), len(prix)


# --------------------------------------------------------------------------- suivi
def charger_vus(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sauver_vus(chemin, vus):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(vus, f, ensure_ascii=False)


# --------------------------------------------------------------------------- sorties
def score(p):
    """Plus c'est haut, plus l'affaire est bonne."""
    s = p["remise_pct"]
    if p.get("ecart_pct") is not None:
        s = max(s, p["ecart_pct"])
    if p.get("nouveau"):
        s += 5
    return s


def exporter_csv(produits, chemin):
    champs = ["score", "nouveau", "nom", "prix", "prix_normal", "remise_pct", "mediane_reseau",
              "ecart_pct", "nb_comparables", "categorie", "magasin", "url", "reference", "id"]
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for p in produits:
            w.writerow(p)


def exporter_html(produits, chemin, titre):
    lignes = []
    for p in produits:
        badges = ""
        if p.get("nouveau"):
            badges += '<span class="b n">NOUVEAU</span>'
        if p["remise_pct"] > 0:
            badges += f'<span class="b r">-{p["remise_pct"]:.0f}%</span>'
        if p.get("ecart_pct") is not None and p["ecart_pct"] > 0:
            badges += f'<span class="b c">{p["ecart_pct"]:.0f}% sous le réseau</span>'
        comp = (f'médiane réseau {p["mediane_reseau"]:.2f} € ({p["nb_comparables"]} annonces)'
                if p.get("mediane_reseau") else "")
        barre = (f'<s>{p["prix_normal"]:.2f} €</s> ' if p["remise_pct"] > 0 else "")
        lignes.append(f"""
<a class="carte" href="{html.escape(p['url'])}" target="_blank" rel="noopener"
   data-score="{p['score']:.1f}" data-prix="{p['prix']}" data-nom="{html.escape(p['nom'].lower())}">
  <img src="{html.escape(p['image'])}" loading="lazy" alt="">
  <div class="info">
    <div class="badges">{badges}</div>
    <div class="nom">{html.escape(p['nom'])}</div>
    <div class="prix">{barre}<b>{p['prix']:.2f} €</b></div>
    <div class="meta">{html.escape(p['magasin'])} · {html.escape(p['categorie'])}</div>
    <div class="meta">{comp}</div>
  </div>
</a>""")
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titre)}</title>
<style>
:root{{--bg:#f6f6f4;--card:#fff;--txt:#1d1d1b;--mut:#6b6b66;--acc:#c8102e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#222220;--txt:#eee;--mut:#a3a39c}}}}
body{{margin:0;font:15px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--txt)}}
header{{padding:16px;position:sticky;top:0;background:var(--bg);border-bottom:1px solid #8883;z-index:1}}
h1{{font-size:18px;margin:0 0 8px}}
input,select{{font:inherit;padding:6px 8px;border-radius:6px;border:1px solid #8886;background:var(--card);color:var(--txt)}}
.grille{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;padding:16px}}
.carte{{background:var(--card);border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;
  display:flex;flex-direction:column;box-shadow:0 1px 3px #0002}}
.carte img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff}}
.info{{padding:10px}} .nom{{font-weight:600;margin:4px 0}} .prix b{{font-size:18px;color:var(--acc)}}
.prix s{{color:var(--mut)}} .meta{{color:var(--mut);font-size:13px}}
.b{{display:inline-block;font-size:11px;font-weight:700;padding:2px 6px;border-radius:4px;margin-right:4px;color:#fff}}
.n{{background:#1a7f37}} .r{{background:var(--acc)}} .c{{background:#0b62c4}}
</style></head><body>
<header><h1>{html.escape(titre)}</h1>
<input id="f" placeholder="Filtrer par nom…">
<select id="t"><option value="score">Meilleures affaires</option><option value="pa">Prix croissant</option>
<option value="pd">Prix décroissant</option></select> <span id="nb"></span></header>
<div class="grille" id="g">{''.join(lignes)}</div>
<script>
const g=document.getElementById('g'),cs=[...g.children];
function maj(){{const q=document.getElementById('f').value.toLowerCase(),t=document.getElementById('t').value;
 const v=cs.filter(c=>c.dataset.nom.includes(q));
 v.sort((a,b)=>t=='pa'?a.dataset.prix-b.dataset.prix:t=='pd'?b.dataset.prix-a.dataset.prix:b.dataset.score-a.dataset.score);
 g.replaceChildren(...v);document.getElementById('nb').textContent=v.length+' articles';}}
document.getElementById('f').oninput=maj;document.getElementById('t').onchange=maj;maj();
</script></body></html>"""
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)


def afficher(produits, n):
    print(f"\n{'SCORE':>6}  {'PRIX':>9}  {'MAGASIN':<14} ARTICLE")
    print("-" * 90)
    for p in produits[:n]:
        tag = []
        if p.get("nouveau"):
            tag.append("NOUVEAU")
        if p["remise_pct"] > 0:
            tag.append(f"-{p['remise_pct']:.0f}%")
        if p.get("ecart_pct") is not None:
            sens = "sous" if p["ecart_pct"] >= 0 else "au-dessus de"
            tag.append(f"{abs(p['ecart_pct']):.0f}% {sens} la médiane réseau ({p['mediane_reseau']:.0f}€)")
        t = f" [{' | '.join(tag)}]" if tag else ""
        print(f"{p['score']:>6.1f}  {p['prix']:>8.2f}€  {p['magasin'][:14]:<14} {p['nom'][:50]}{t}")


# --------------------------------------------------------------------------- CLI
def trouver_magasin(nom):
    n = nom.strip().upper()
    for m in MAGASINS:
        if m.upper() == n:
            return m
    candidats = [m for m in MAGASINS if n in m.upper()]
    if len(candidats) == 1:
        return candidats[0]
    raise SystemExit(f"Magasin inconnu ou ambigu : '{nom}'. Voir --lister-magasins")


def trouver_categorie(nom):
    nom = nom.strip().lower()
    if nom in CATEGORIES:
        return CATEGORIES[nom]
    if re.fullmatch(r"\d+-[a-z0-9-]+", nom):      # id-slug direct, ex. 179-lecteurs-graveurs-dvd
        return nom
    candidats = [v for k, v in CATEGORIES.items() if nom in k]
    if len(candidats) == 1:
        return candidats[0]
    raise SystemExit(f"Catégorie inconnue ou ambiguë : '{nom}'. Voir --lister-categories")


def lister_categories():
    h = get(f"{BASE}/2-categories", json_attendu=False)
    vus = {}
    for slug, texte in re.findall(
            r'href="https://www\.cashconverters\.be/fr/(\d+-[a-z0-9-]+)"[^>]*>\s*([^<]{2,60}?)\s*<', h):
        vus.setdefault(slug, html.unescape(texte))
    print("Raccourcis : " + ", ".join(CATEGORIES))
    print("\nToutes les catégories (utilisables telles quelles avec -c) :")
    for slug in sorted(vus, key=lambda s: int(s.split("-")[0])):
        print(f"  {slug:<45} {vus[slug]}")


def mode_interactif(args):
    print("=== Cash Converters - scalpeur ===\n")
    print("Régions : " + ", ".join(REGIONS))
    choix = input("Magasin (ex. ARLON) ou région (ex. luxembourg) [ARLON] : ").strip() or "ARLON"
    if choix.lower() in REGIONS:
        args.region = choix.lower()
    else:
        args.magasin = [choix]
    print("\nCatégories : " + ", ".join(CATEGORIES))
    args.categorie = input("Catégorie [tout] : ").strip() or "tout"
    args.mots = input("Mots-clés (optionnel) : ").strip() or None
    pmax = input("Prix max en € (optionnel) : ").strip()
    args.prix_max = float(pmax.replace(",", ".")) if pmax else None
    args.comparer = input("Comparer les prix au reste du réseau ? (plus lent) [o/N] : ").strip().lower() == "o"
    return args


def rechercher(magasins, cat, zone, mots=None, exclure=None, prix_min=None, prix_max=None,
               maximum=None, comparer=False, max_comparaisons=60, nouveaux=False,
               sortie=DOSSIER, progres=None, verbeux=True, motif=None, sans=None, nom_cat=None):
    """Lance une recherche complète. Renvoie (produits, chemin_base_rapport, premier_passage).

    cat peut être une liste de catégories du site ; motif / sans sont des expressions régulières
    appliquées au nom (sans accents) pour créer des catégories plus fines (ex. « cartes graphiques »).
    """
    class A:  # petit conteneur pour garder le code du filtrage lisible
        pass
    args = A()
    args.max, args.mots, args.exclure = maximum, mots, exclure
    args.prix_min, args.prix_max, args.comparer = prix_min, prix_max, comparer
    args.max_comparaisons, args.nouveaux, args.sortie = max_comparaisons, nouveaux, sortie

    os.makedirs(args.sortie, exist_ok=True)
    # Tous les magasins + un produit précis : le moteur du site évite de tout télécharger
    recherche = mots if (mots and not magasins and cat == CATEGORIES["tout"]) else None
    if isinstance(cat, (list, tuple)):
        produits, vus_ids = [], set()
        for i, c in enumerate(cat):
            def prog(msg, frac, i=i):
                if progres:
                    progres(f"Rubrique {i + 1}/{len(cat)} · {msg}", (i + frac) / len(cat))
            for p in scraper(c, magasins, maximum=args.max, verbeux=verbeux, progres=prog):
                if p["id"] not in vus_ids:
                    vus_ids.add(p["id"])
                    produits.append(p)
    else:
        produits = scraper(cat, magasins, maximum=args.max, verbeux=verbeux, progres=progres,
                           recherche=recherche)
    if motif:
        produits = [p for p in produits if re.search(motif, plat(p["nom"]))]
    if sans:
        produits = [p for p in produits if not re.search(sans, plat(p["nom"]))]
    nom_cat = nom_cat or (cat if isinstance(cat, str) else cat[0]).split("-", 1)[1].strip("-")

    # filtres locaux
    if args.mots:
        req = normaliser(args.mots)
        produits = [p for p in produits if all(m in normaliser(p["nom"]) or m in p["nom"].lower()
                                               for m in req)]
    if args.exclure:
        exc = args.exclure.lower().split()
        produits = [p for p in produits if not any(m in p["nom"].lower() for m in exc)]
    if args.prix_min is not None:
        produits = [p for p in produits if p["prix"] >= args.prix_min]
    if args.prix_max is not None:
        produits = [p for p in produits if p["prix"] <= args.prix_max]

    # nouveautés depuis le dernier passage
    chemin_vus = os.path.join(args.sortie, f".vus_{re.sub(r'[^a-z0-9]+', '_', zone.lower())}.json")
    vus = charger_vus(chemin_vus)
    premier_passage = not vus
    maintenant = datetime.now().isoformat(timespec="seconds")
    for p in produits:
        p["nouveau"] = (not premier_passage) and p["id"] not in vus
        vus.setdefault(p["id"], maintenant)
    sauver_vus(chemin_vus, vus)

    # comparaison au réseau
    if args.comparer and produits:
        cibles = sorted(produits, key=lambda p: -p["prix"])[:args.max_comparaisons]
        if verbeux:
            print(f"→ Comparaison de {len(cibles)} articles au reste du réseau…")
        cache = {}
        for i, p in enumerate(cibles, 1):
            if progres:
                progres(f"Comparaison {i}/{len(cibles)} : {p['nom'][:40]}", i / len(cibles))
            if verbeux:
                print(f"  {i}/{len(cibles)} {p['nom'][:50]:<50}", end="\r")
            med, nb = comparer_prix(p, cache)
            p["nb_comparables"] = nb
            if med:
                p["mediane_reseau"] = round(med, 2)
                p["ecart_pct"] = round((1 - p["prix"] / med) * 100, 1)
        if verbeux:
            print()

    for p in produits:
        p["score"] = round(score(p), 1)
    produits.sort(key=lambda p: (-p["score"], p["prix"]))
    if args.nouveaux:
        produits = [p for p in produits if p["nouveau"]]

    os.makedirs(args.sortie, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M")
    base = os.path.join(args.sortie, f"cash_{re.sub(r'[^A-Za-z0-9]+', '_', zone)}_{re.sub(r'[^A-Za-z0-9]+', '_', nom_cat)}_{horodatage}")
    exporter_csv(produits, base + ".csv")
    exporter_html(produits, base + ".html",
                  f"Cash Converters · {zone} · {nom_cat} · {len(produits)} articles")

    return produits, base, premier_passage


def main():
    ap = argparse.ArgumentParser(description="Scalpeur Cash Converters Belgique")
    ap.add_argument("-m", "--magasin", action="append", help="magasin (répétable)")
    ap.add_argument("-r", "--region", choices=REGIONS, help="groupe de magasins")
    ap.add_argument("-c", "--categorie", default="tout", help="raccourci ou id-slug")
    ap.add_argument("-k", "--mots", help="mots-clés requis dans le nom (séparés par des espaces)")
    ap.add_argument("--exclure", help="mots à exclure du nom")
    ap.add_argument("--prix-min", type=float)
    ap.add_argument("--prix-max", type=float)
    ap.add_argument("--max", type=int, help="nombre max d'articles à récupérer")
    ap.add_argument("--comparer", action="store_true",
                    help="compare chaque article au même produit dans les autres magasins")
    ap.add_argument("--max-comparaisons", type=int, default=60)
    ap.add_argument("--nouveaux", action="store_true", help="n'afficher que les nouveaux articles")
    ap.add_argument("--top", type=int, default=30, help="lignes affichées dans la console")
    ap.add_argument("--sortie", default=DOSSIER, help="dossier des rapports")
    ap.add_argument("--lister-magasins", action="store_true")
    ap.add_argument("--lister-categories", action="store_true")
    args = ap.parse_args()

    if args.lister_magasins:
        print("\n".join(MAGASINS))
        for r, ms in REGIONS.items():
            print(f"\n[{r}] " + ", ".join(ms))
        return
    if args.lister_categories:
        lister_categories()
        return
    if len(sys.argv) == 1:
        args = mode_interactif(args)

    magasins = [trouver_magasin(m) for m in (args.magasin or [])]
    if args.region:
        magasins += [m for m in REGIONS[args.region] if m not in magasins]
    cat = trouver_categorie(args.categorie)
    zone = args.region or "-".join(magasins) or "tous"
    print(f"→ Magasins : {', '.join(magasins) or 'tous'}  |  Catégorie : {cat}")

    produits, base, premier_passage = rechercher(
        magasins, cat, zone, args.mots, args.exclure, args.prix_min, args.prix_max,
        args.max, args.comparer, args.max_comparaisons, args.nouveaux, args.sortie)
    afficher(produits, args.top)
    nb_nouveaux = sum(p["nouveau"] for p in produits)
    print(f"\n{len(produits)} articles · {nb_nouveaux} nouveaux depuis le dernier passage"
          + (" (premier passage : référence enregistrée)" if premier_passage else ""))
    print(f"Rapport HTML : {base}.html\nCSV          : {base}.csv")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompu.")

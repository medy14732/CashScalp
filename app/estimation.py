"""
estimation.py - Détails d'un article Cash Converters et estimation du bon plan.

Trois références de prix :
  - occasion      : médiane des annonces similaires dans les autres magasins Cash Converters
  - reconditionné : prix le plus bas chez Coolblue (offres « Reconditionné » / « Seconde Chance »)
  - neuf          : prix le plus bas chez Coolblue (offres neuves)
"""
import html
import json
import re
import statistics
import threading
import time
import unicodedata
import urllib.parse
import urllib.request

import cashscalp as cs

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# mots qui décrivent l'état, la couleur ou le type d'objet, pas le modèle précis
BRUIT = set("""
gsm smartphone telephone etat neuf bon tres excellent occasion batterie batteries boite boitier
sans avec chargeur cable griffe griffes rayure rayures prev ban snap r pour et de du des la le
les en un une couleur go gb to tb noir noire blanc blanche bleu bleue rouge gris grise argent
argente argentee or rose vert verte violet mauve jaune orange titanium titane black white blue
midnight starlight ciel complet complete console ordinateur portable pc laptop tablette tactile
appareil portatif sony microsoft nintendo montre connectee perceuse visseuse meuleuse scie
enceinte casque ecouteurs sans fil bluetooth edition version modele
marine nuit minuit sideral graphite platine bronze champagne lavande
moniteur ecran monitor televiseur incurve curved gaming gamer lcd led
""".split())
ACCESSOIRES = set("""
coque housse etui protection protege verre trempe film chargeur cable adaptateur support
bracelet station dock sacoche sac pochette manette skin stylet clavier souris facades
""".split())
VARIANTES = {"plus", "pro", "max", "mini", "ultra", "lite", "slim", "oled", "air", "fe", "se", "xl", "ti", "super", "xt"}
MARQUEUR_RECOND = ("reconditionn", "seconde chance", "deuxieme chance", "refurb")


def _canon(t):
    """Minuscules, sans accents, unités et synonymes harmonisés."""
    t = unicodedata.normalize("NFKD", t.lower().replace("\xa0", " "))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"playstation\s*(\d)", r"ps\1", t)
    t = re.sub(r"(\d+)\s*(go|gb)\b", r"\1", t)
    t = re.sub(r"(\d+)\s*(to|tb)\b", r"\1to", t)
    return t


_sans_accents = _canon


def mots_cles(nom):
    """« GSM(85%) Iphone 13 blanc 128 gb Batterie 85 % » -> ['iphone', '13', '128']"""
    t = _canon(nom)
    t = re.sub(r"\([^)]*\)", " ", t)              # (état neuf), (85%)…
    t = re.sub(r"batterie\s*\d+\s*%?", " ", t)
    t = re.sub(r"\d+\s*%", " ", t)
    t = re.sub(r"\d+\s*hz\b", " ", t)
    vus, res = set(), []
    for m in re.findall(r"[a-z0-9]+", t):
        if m in BRUIT or (len(m) < 2 and not m.isdigit()) or m in vus:
            continue
        vus.add(m)
        res.append(m)
    return res[:5]


# Requêtes simultanées autorisées par site : assez pour aller vite, pas assez pour se faire bloquer
LIMITES_SITES = {"www.cashconverters.be": 4, "www.coolblue.be": 6, "www.mediamarkt.be": 6,
                 "www.amazon.com.be": 2, "www.2ememain.be": 6, "www.marktplaats.nl": 4,
                 "www.kleinanzeigen.de": 2, "www.leboncoin.fr": 2, "www.kieskeurig.be": 3}
_semaphores, _verrou_sem = {}, threading.Lock()
_cache_reseau = {}


def limite(url):
    hote = urllib.parse.urlparse(url).hostname or ""
    with _verrou_sem:
        if hote not in _semaphores:
            _semaphores[hote] = threading.BoundedSemaphore(LIMITES_SITES.get(hote, 3))
        return _semaphores[hote]


def _get(url, accept_json=False):
    h = {"User-Agent": UA, "Accept-Language": "fr-BE,fr;q=0.9", "Accept-Encoding": "gzip"}
    if accept_json:
        h.update({"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    for essai in range(3):                 # le site peut refuser (403/429) ou traîner : on patiente
        try:
            with limite(url), urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
                return cs.lire(r)
        except Exception as e:
            code = getattr(e, "code", None)
            if essai == 2 or (code is not None and code not in (403, 429, 500, 502, 503, 504)):
                raise
            time.sleep(2 * (essai + 1))


def _correspond(requete, nom_candidat, accessoire_ok=False, seuil=0.6):
    c = set(re.findall(r"[a-z0-9]+", _canon(nom_candidat)))
    q = set(requete)
    if not q:
        return False

    def present(m):
        # « dhp482 » doit trouver « dhp482zj » ; « 13 » ne doit pas trouver « 130 »
        if m in c:
            return True
        return len(m) >= 4 and re.search(r"[a-z]", m) and any(x.startswith(m) for x in c)

    modeles = {m for m in q if any(ch.isdigit() for ch in m)}
    if not all(present(m) for m in modeles):                   # modèle / capacité obligatoires
        return False
    if not accessoire_ok and (c & ACCESSOIRES) - q:
        return False
    if (q & VARIANTES) != (c & VARIANTES):                     # iPhone 8 ≠ iPhone 8 Plus
        return False
    return sum(present(m) for m in q) / len(q) >= seuil


# --------------------------------------------------------------------------- fiche produit
def details_produit(url):
    h = _get(url)
    fin = len(h)
    for borne in ("product-accessories", "Article similaires"):
        i = h.find(borne)
        if i > 0:
            fin = min(fin, i)
    page = h[:fin]
    images = []
    for u in re.findall(r'data-image-large-src="([^"]+)"', page) + \
            re.findall(r'(https://www\.cashconverters\.be/\d+-large_default/[^"\s]+\.jpg)', page):
        if u not in images:
            images.append(u)
    texte = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", texte)))

    def entre(debut, fin_):
        m = re.search(re.escape(debut) + r"\s*(.*?)\s*(?:" + fin_ + ")", texte)
        return m.group(1).strip() if m else ""

    desc = ""
    m = re.search(r'<div class="product-description[^"]*">(.*?)</div>', page, re.S)
    if m:
        desc = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
    return {
        "images": images[:8],
        "marque": entre("Marque", "Modèle|Article|Magasin|$"),
        "modele": entre("Modèle", "Article|Magasin|Marque|$"),
        "adresse": entre("disponible dans le magasin:", "Numéro|Payement|$"),
        "telephone": entre("Numéro de téléphone:", "Payement|Plus d|$"),
        "paiement": entre("Payement acceptés:", "Plus d|$"),
        "garantie": "1 an" if "1 an de Garantie" in texte else "",
        "description": desc if desc and "Envie d'économiser" not in desc else "",
    }


# --------------------------------------------------------------------------- références de prix
def prix_occasion_reseau(id_produit, nom, requete=None, exclure=None, bornes=None, categorie=None,
                         verif=None, seuil=0.6):
    req = requete or mots_cles(nom)
    if len(req) < 2:
        return None
    url = f"{cs.BASE}/recherche?" + urllib.parse.urlencode(
        {"controller": "search", "s": " ".join(req), "resultsPerPage": 60, "from-xhr": ""})
    if url in _cache_reseau:                       # même modèle déjà cherché : pas de 2e requête
        produits = _cache_reseau[url]
    else:
        try:
            produits = json.loads(_get(url, accept_json=True)).get("products", [])
        except Exception:
            return None
        _cache_reseau[url] = produits
    prix, exemples = [], []
    for p in produits:
        if str(p["id_product"]) == str(id_produit):
            continue
        if exclure and re.search(exclure, _canon(p.get("name", ""))):
            continue
        if categorie and _canon(p.get("category_name", "")) != _canon(categorie):
            continue
        texte_p = cs.nom_complet(p)
        if _correspond(req, texte_p, seuil=seuil) and (not verif or verif(texte_p)):
            v = float(p.get("price_amount") or 0)
            if v > 0 and (not bornes or bornes[0] <= v <= bornes[1]):
                prix.append(v)
                exemples.append({"nom": texte_p, "prix": v, "url": p["url"]})
    if not prix:
        return None
    import prix as px
    st = px.stats_robustes(prix)
    st["exemples"] = sorted([e for e in exemples if st["min"] <= e["prix"] <= st["max"]], key=lambda e: e["prix"])[:5]
    st["_offres"] = [{**e, "source": "Cash Converters", "cle": "cashconverters"} for e in exemples]
    return st


CAPACITES = {"8", "16", "32", "64", "128", "256", "512", "1024"}


def prix_coolblue(nom):
    """Cherche d'abord le modèle exact ; à défaut, sans la capacité (estimation approchée)."""
    req = mots_cles(nom)
    if len(req) < 2:
        return None
    res = _coolblue(req)
    sans_cap = [m for m in req if m not in CAPACITES and not re.fullmatch(r"\d+to", m)]
    if res is not None and not (res["neuf"] or res["reconditionne"]) and len(sans_cap) >= 2 and sans_cap != req:
        res2 = _coolblue(sans_cap)
        if res2 and (res2["neuf"] or res2["reconditionne"]):
            res2["approx"] = True
            return res2
    return res


def _coolblue(req):
    url = "https://www.coolblue.be/fr/rechercher?" + urllib.parse.urlencode({"query": " ".join(req)})
    try:
        h = _get(url)
    except Exception:
        return None
    articles = []
    for bloc in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        try:
            d = json.loads(bloc)
        except ValueError:
            continue
        if d.get("@type") == "ItemList":
            articles += d.get("itemListElement", [])
    neuf, recond = [], []
    for a in articles:
        try:
            prix = float(a["offers"]["price"])
        except (KeyError, TypeError, ValueError):
            continue
        n = a.get("name", "")
        if not _correspond(req, n):
            continue
        e = {"nom": n, "prix": prix, "url": a.get("url", "")}
        (recond if any(k in _sans_accents(n) for k in MARQUEUR_RECOND) else neuf).append(e)
    neuf.sort(key=lambda e: e["prix"])
    recond.sort(key=lambda e: e["prix"])
    return {"neuf": neuf[:3], "reconditionne": recond[:3], "recherche": url, "approx": False}


def est_ordinateur(produit):
    c = _canon(produit.get("categorie") or "")
    return c in ("ordinateurs portables", "ordinateurs de bureau") or \
        bool(re.search(r"\b(pc portable|ordinateur portable|macbook|chromebook|all in one|pc gamer|pc de bureau)\b",
                       _canon(produit["nom"])))


def est_reference_modele(m):
    """« gc34g55twwp », « 24gm79g », « dhp482 » : identifiant précis du modèle (lettres + chiffres)."""
    return len(m) >= 4 and bool(re.search(r"[a-z]", m)) and bool(re.search(r"\d", m))


def variantes_requete(tokens):
    """Requêtes de plus en plus larges : modèle exact, puis sans les nombres secondaires, puis 3 puis 2 mots.
    Une variante ne perd jamais la référence du modèle : sans elle, ce ne serait plus le même produit."""
    refs = [m for m in tokens if est_reference_modele(m)]
    essais = [tokens]
    sans_nb = [m for i, m in enumerate(tokens) if i == 0 or not m.isdigit() or re.fullmatch(r"20\d\d", m)]
    sans_cap = [m for m in tokens if m not in CAPACITES and not re.fullmatch(r"\d+to", m)]
    for v in (sans_cap, sans_nb, tokens[:3], tokens[:2]):
        if len(v) >= 2 and v not in essais and all(r in v for r in refs):
            essais.append(v)
    return essais


def estimer(produit, complet=True):
    """produit : dict avec id, nom, prix, url, categorie. Renvoie détails + références + verdict.

    complet=False : version rapide pour la grille (sans fiche produit ni Amazon pour l'article lui-même).
    """
    import prix as px
    import fiche_tech as ft
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.time()
    prix = produit["prix"]
    bornes = px.bornes_pour(prix)
    ordi = est_ordinateur(produit)
    portable = ordi and "bureau" not in _canon(produit.get("categorie") or "") and not re.search(
        r"\b(tour|desktop|all in one|pc gamer|unite centrale)\b", _canon(produit["nom"]))

    tokens = ft.requete_modele(produit["nom"]) if ordi else mots_cles(produit["nom"])
    texte, exclure = " ".join(tokens), None
    # composant vendu seul (« Carte graphique MSI GTX 1650 Super ») : on cherche le modèle détecté
    if "accessoires informatique" in (produit.get("categorie") or ""):
        comps = px.detecter_composants(produit["nom"])
        if len(comps) == 1:
            tokens, texte, exclure = comps[0]["tokens"], comps[0]["texte"], comps[0]["exclure"]
    if ordi:                       # un portable ne doit pas être comparé à une housse ou un chargeur
        exclure = r"\b(chargeur|oplader|charger|adaptateur|adapter|housse|sacoche|sleeve|hoes|coque|etui|cover|clavier seul|batterie de remplacement|ecran de remplacement|dalle)\b"
    res = {"id": produit["id"], "mots_cles": tokens, "complet": complet}
    sources = None if complet else [k for k in px.SOURCES if k != "amazon"]

    with ThreadPoolExecutor(3) as ex:
        f_det = ex.submit(details_produit, produit["url"]) if complet else None
        try:
            res["details"] = f_det.result() if f_det else {}
        except Exception as e:
            res["details"] = {"erreur": str(e)}

    # fiche technique (ordinateurs) : nom + fiche du vendeur
    d = res["details"] if isinstance(res["details"], dict) else {}
    texte_complet = " ".join([produit["nom"], d.get("modele", ""), d.get("description", "")])
    specs, cpu = ft.fiche_technique(texte_complet, produit.get("categorie", "")) if ordi else ([], None)
    res["specs"] = specs
    if ordi and cpu and not cpu.get("cle"):   # « macbook air » + « m4 » : la puce fait partie du modèle
        for x in ft.indice_processeur(cpu):
            if x not in tokens:
                tokens.append(x)
        texte = " ".join(tokens)
    verif, seuil = None, 0.6
    if ordi:
        verif = ft.verificateur(texte_complet)   # même processeur, carte graphique, RAM, stockage, écran
        seuil = 1.0                              # et tous les mots du modèle (« yoga slim 7 », pas « ideapad slim 3 »)
        # un ordinateur d'occasion vaut rarement moins de la moitié ou plus du double d'un modèle identique
        bornes = (prix * 0.45, prix * 2.5)
        if cpu and cpu.get("cle"):
            # le processeur exact est vérifié dans chaque annonce : un accessoire ne peut pas passer,
            # inutile donc d'écarter les annonces « + chargeur »
            exclure = None
        if cpu and cpu.get("cle"):           # même gamme mais autre processeur : ce n'est plus la même machine
            exclure = (exclure + "|" if exclure else "") + r"\bi[3579]\s*-?\s*(?!" + re.escape(cpu["cle"]) + r")\d{4,5}"

    # 1) le même modèle, en élargissant la recherche tant que rien n'est trouvé
    boutiques, occ, approx = [], None, False
    if len(tokens) >= 2:
        for n, essai in enumerate(variantes_requete(tokens)):
            t_essai = texte if n == 0 else " ".join(essai)
            with ThreadPoolExecutor(2) as ex:
                f_occ = ex.submit(prix_occasion_reseau, produit["id"], produit["nom"], essai, exclure, bornes,
                                  produit.get("categorie") or None, verif, seuil)
                f_b = ex.submit(px.comparer_boutiques, t_essai, essai, exclure, sources, bornes, verif, seuil,
                                not (ordi and cpu and cpu.get("cle")))
                occ, boutiques = f_occ.result(), f_b.result()
            if occ or any(b.get("prix") or b.get("mediane") or b.get("reconditionne") for b in boutiques):
                # ordinateur cherché avec seulement « marque + gamme » (ex. hp victus) : configurations trop variées
                approx = n > 0 or (ordi and len(essai) <= 2)
                res["mots_cles"] = essai
                break
    res["occasion"] = occ
    res["approx"] = approx

    lignes = []
    if occ:
        lignes.append({"source": "Cash Converters (autres magasins)", "cle": "cashconverters", "type": "occasion",
                       **occ, "approx": approx})
    for b in boutiques:
        b["approx"] = approx
        lignes.append(b)
        if b.get("reconditionne"):
            r = b["reconditionne"]
            lignes.append({"source": b["source"], "cle": b["cle"], "type": "reconditionne", "prix": r["prix"],
                           "nom": r["nom"], "url": r["url"], "approx": approx})

    # 1 bis) toutes les annonces du même modèle, tous sites réunis
    if not approx:
        m = px.marche_occasion([l for l in lignes if l["type"] == "occasion"], "Marché de l'occasion · même modèle")
        if m:
            lignes.insert(0, m)

    # 2) ordinateurs : machines d'occasion avec le même processeur
    if ordi and cpu:
        lignes += px.ref_meme_processeur(cpu, portable, prix, produit["id"], verif, ft.texte_gpu(texte_complet))
    res["boutiques"] = lignes
    res["liens"] = px.liens_manuels(" ".join(res["mots_cles"]) or produit["nom"])

    # 3) PC fixe : chiffrage pièce par pièce
    res["composants"] = px.chiffrer_pc(produit, texte_complet) if px.est_pc_fixe(produit, texte_complet) else None

    for l in lignes:
        l.setdefault("pertinence", px.pertinence_site(l.get("cle")))

    # références retenues pour le verdict : même modèle d'abord, puis même processeur
    refs, choisies = {}, {}
    # une référence d'occasion ne compte que si elle est fiable : au moins 2 annonces aux prix cohérents
    occ_ok = [l for l in lignes if l["type"] == "occasion" and l.get("mediane") and l.get("nb", 0) >= 2
              and l.get("fiabilite") != "faible" and not l.get("approx")]
    # ordre : même modèle exact, puis même processeur, puis modèle proche
    # le « marché » (tous sites réunis) passe avant une source seule, à fiabilité égale
    rang_fiab = {"elevee": 0, "moyenne": 1}
    occ_ok.sort(key=lambda l: (l.get("approx", False), bool(l.get("meme_cpu")), -l["pertinence"],
                               rang_fiab.get(l.get("fiabilite"), 2), not l.get("marche"), -l.get("nb", 0)))
    if occ_ok:
        refs["occasion"] = occ_ok[0]["mediane"]
        choisies["occasion"] = occ_ok[0]
        res["base_occasion"] = {"source": occ_ok[0]["source"], "meme_cpu": occ_ok[0].get("meme_cpu"),
                                "approx": occ_ok[0].get("approx", False), "nb": occ_ok[0]["nb"],
                                "min": occ_ok[0]["min"], "max": occ_ok[0]["max"],
                                "fiabilite": occ_ok[0].get("fiabilite"), "sites": occ_ok[0].get("sites")}
    for type_ in ("reconditionne", "neuf"):
        # le prix le plus bas, mais seulement parmi les sites les plus sérieux qui ont le produit
        l_t = [l for l in lignes if l["type"] == type_ and l.get("prix") and not l.get("approx")]
        if l_t:
            meilleure = max(l["pertinence"] for l in l_t)
            choisies[type_] = min((l for l in l_t if l["pertinence"] == meilleure), key=lambda l: l["prix"])
            refs[type_] = choisies[type_]["prix"]
    if res["composants"]:          # un total incomplet fausserait le verdict : on l'écarte
        if res["composants"]["complet_occasion"]:
            refs["pieces_occasion"] = res["composants"]["total_occasion"]
        if res["composants"]["complet_neuf"]:
            refs["pieces_neuf"] = res["composants"]["total_neuf"]
    res["gains"] = {k: {"ref": v, "gain": round(v - prix, 2), "pct": round((1 - prix / v) * 100, 1)}
                    for k, v in refs.items() if v and v > 0}
    res["verdict"] = verdict(res["gains"])
    res["pertinence"] = pertinence(res["verdict"].get("base"), choisies, lignes, res["composants"])
    for l in res["boutiques"]:
        l.pop("_offres", None)
    if res.get("occasion"):
        res["occasion"].pop("_offres", None)
    res["duree"] = round(time.time() - t0, 1)
    return res


def verdict(gains):
    """On se fie d'abord à l'occasion, puis aux pièces d'occasion (PC), au reconditionné, au neuf."""
    regles = [("occasion", [(20, "excellent"), (8, "bon"), (-5, "correct")]),
              ("pieces_occasion", [(25, "excellent"), (10, "bon"), (-5, "correct")]),
              ("reconditionne", [(35, "excellent"), (20, "bon"), (5, "correct")]),
              ("neuf", [(55, "excellent"), (35, "bon"), (15, "correct")])]
    for base, seuils in regles:
        if base in gains:
            p = gains[base]["pct"]
            for s, note in seuils:
                if p >= s:
                    return {"note": note, "base": base, "pct": p}
            return {"note": "cher", "base": base, "pct": p}
    return {"note": "inconnu", "base": None}


def pertinence(base, choisies, lignes, composants=None):
    """Peut-on se fier au gain affiché ? Selon le sérieux du site, le nombre d'annonces
    et l'accord avec d'autres sites. Renvoie {niveau: fiable|moyen|faible, raisons: [...]}."""
    if not base:
        return {"niveau": None, "raisons": []}
    if base.startswith("pieces"):
        return {"niveau": "moyen" if composants and composants.get("complet_occasion") else "faible",
                "raisons": ["estimation pièce par pièce, à vérifier"]}
    ref = choisies[base]
    valeur = ref.get("mediane") or ref["prix"]
    raisons, points = [], ref["pertinence"]
    if not ref.get("marche"):
        raisons.append({3: "site sérieux", 2: "site correct"}.get(ref["pertinence"], "site peu pertinent"))
    # autres sites sérieux qui donnent à peu près le même prix (à 25 % près)
    accord = {l["source"] for l in lignes
              if l is not ref and l["type"] == ref["type"] and l["pertinence"] >= 2 and not l.get("approx")
              and l.get("cle") != ref.get("cle") and (l.get("mediane") or l.get("prix"))
              and abs((l.get("mediane") or l["prix"]) - valeur) <= 0.25 * valeur}
    if ref.get("marche"):          # le marché réunit déjà plusieurs sites : ce sont eux qui confirment
        accord = set(ref.get("sites") or [])
    if ref.get("marche"):
        points += 2 if len(accord) >= 3 else 1
        raisons.append(f"{len(accord)} sites réunis" + (" dont Cash Converters" if ref["pertinence"] >= 3 else ""))
    elif len(accord) >= 2:
        points += 2
        raisons.append(f"confirmé par {len(accord)} sites")
    elif accord:
        points += 1
        raisons.append("confirmé par 1 autre site")
    else:
        raisons.append("aucun autre site ne confirme")
    if ref["type"] == "occasion":
        nb = ref.get("nb", 0)
        points += 2 if nb >= 5 else 1 if nb >= 3 else 0
        raisons.append(f"{nb} annonce{'s' if nb > 1 else ''}")
        if ref.get("fiabilite") == "elevee":
            points += 1
        elif ref.get("fiabilite") == "faible":
            points -= 2
            raisons.append("prix très dispersés")
        if ref.get("meme_cpu"):
            points -= 1
            raisons.append("même configuration, pas le même modèle")
        niveau = "fiable" if points >= 7 else "moyen" if points >= 4 else "faible"
    else:
        niveau = "fiable" if points >= 4 else "moyen" if points >= 3 else "faible"
    return {"niveau": niveau, "raisons": raisons, "source": ref["source"]}


if __name__ == "__main__":
    import sys
    for nom in sys.argv[1:] or ["GSM(85%) état Iphone 13 blanc 128 gb Batterie 85 %"]:
        print(nom, "->", mots_cles(nom))
        print(json.dumps(prix_coolblue(nom), ensure_ascii=False, indent=1)[:800])
        print(json.dumps(prix_occasion_reseau("0", nom), ensure_ascii=False)[:400])

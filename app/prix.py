"""
prix.py - Prix de référence dans d'autres boutiques + chiffrage pièce par pièce des PC.

Boutiques lues automatiquement :
  neuf      : Coolblue.be, MediaMarkt.be, Amazon.com.be
  occasion  : 2ememain.be (annonces de particuliers en Belgique)
Boutiques qui bloquent les robots (lien de recherche seulement) : Fnac, Vinted, eBay.
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
from concurrent.futures import ThreadPoolExecutor

from cashscalp import lire
from estimation import ACCESSOIRES, MARQUEUR_RECOND, VARIANTES, _canon, UA, limite

_cache = {}
_verrou = threading.Lock()

MOTS_PC = r"\b(pc|ordinateur|laptop|portable|notebook|desktop|computer|gamer|unite centrale|tour gaming)\b"


# --------------------------------------------------------------------------- outils
def _get(url, json_attendu=False, entetes=None):
    h = {"User-Agent": UA, "Accept-Language": "fr-BE,fr;q=0.9", "Accept-Encoding": "gzip",
         "Accept": "application/json" if json_attendu else "text/html,*/*;q=0.8"}
    h.update(entetes or {})
    with limite(url), urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        corps = lire(r)
    return json.loads(corps) if json_attendu else corps


def _prix_texte(t):
    t = t.replace("\xa0", " ").replace("€", "").strip()
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(re.sub(r"[^\d.]", "", t))
    except ValueError:
        return None


def correspond(tokens, nom, exclure=None, seuil=0.6, accessoires=True):
    c = set(re.findall(r"[a-z0-9]+", _canon(nom)))
    q = set(tokens)
    if not q or (exclure and re.search(exclure, _canon(nom))):
        return False

    def present(m):
        if m in c:
            return True
        return len(m) >= 4 and re.search(r"[a-z]", m) and any(x.startswith(m) for x in c)

    if not all(present(m) for m in q if any(ch.isdigit() for ch in m)):
        return False
    if accessoires and (c & ACCESSOIRES) - q:
        return False
    if (q & VARIANTES) != (c & VARIANTES):
        return False
    return sum(present(m) for m in q) / len(q) >= seuil


def stats_robustes(valeurs):
    """Prix « habituel » fiable : on écarte les annonces aberrantes (hors 60 %–160 % de la médiane),
    puis on mesure l'écart entre les prix restants pour dire si la référence est fiable."""
    v = sorted(x for x in valeurs if x and x > 0)
    if not v:
        return None
    ecartes = 0
    for _ in range(2):
        m = statistics.median(v)
        if len(v) >= 3:
            garde = [x for x in v if m * 0.6 <= x <= m * 1.6]
            ecartes += len(v) - len(garde)
            v = garde or v
    m = statistics.median(v)
    dispersion = (v[-1] - v[0]) / m if m else 0
    fiab = "elevee" if len(v) >= 3 and dispersion <= 0.5 else "moyenne" if len(v) >= 2 and dispersion <= 0.8 else "faible"
    return {"mediane": round(m, 2), "min": v[0], "max": v[-1], "nb": len(v), "ecartes": ecartes,
            "dispersion": round(dispersion, 2), "fiabilite": fiab}


def mediane_robuste(valeurs):
    s = stats_robustes(valeurs)
    return s and s["mediane"]


def _ld_json_produits(page):
    """Produits d'une liste schema.org (Coolblue, MediaMarkt)."""
    res = []
    for bloc in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(bloc)
        except ValueError:
            continue
        if d.get("@type") != "ItemList":
            continue
        for e in d.get("itemListElement", []):
            e = e.get("item", e)
            try:
                res.append({"nom": html.unescape(e["name"]), "prix": float(e["offers"]["price"]),
                            "url": e.get("url", ""), "image": (e.get("image") or [""])[0]
                            if isinstance(e.get("image"), list) else e.get("image", "")})
            except (KeyError, TypeError, ValueError):
                pass
    return res


# --------------------------------------------------------------------------- boutiques
def coolblue(texte):
    url = "https://www.coolblue.be/fr/rechercher?" + urllib.parse.urlencode({"query": texte})
    return url, _ld_json_produits(_get(url))


def mediamarkt(texte):
    url = "https://www.mediamarkt.be/fr/search.html?" + urllib.parse.urlencode({"query": texte})
    return url, _ld_json_produits(_get(url))


def amazon(texte):
    url = "https://www.amazon.com.be/s?" + urllib.parse.urlencode({"k": texte})
    page = _get(url)
    if "s-search-result" not in page:          # page anti-robot au lieu des résultats
        raise RuntimeError("Amazon a refusé la recherche")
    res = []
    for bloc in re.findall(r'data-component-type="s-search-result"(.*?)(?=data-component-type="s-search-result"|$)',
                           page, re.S)[:30]:
        if "Sponsoris" in bloc[:4000]:
            continue
        t = re.search(r"<h2[^>]*>.*?<span[^>]*>(.*?)</span>", bloc, re.S)
        p = re.search(r'class="a-offscreen">([^<]+)<', bloc)
        lien = re.search(r'href="(/[^"]*?/dp/[A-Z0-9]{10})', bloc)
        img = re.search(r'<img class="s-image" src="([^"]+)"', bloc)
        if t and p:
            prix = _prix_texte(html.unescape(p.group(1)))
            if prix:
                res.append({"nom": html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip(), "prix": prix,
                            "url": "https://www.amazon.com.be" + lien.group(1) if lien else url,
                            "image": img.group(1) if img else ""})
    return url, res


def _annonces_adevinta(domaine, texte):
    """2ememain (BE) et Marktplaats (NL) : même plateforme, même API."""
    api = f"https://www.{domaine}/lrp/api/search?" + urllib.parse.urlencode({"query": texte, "limit": 60})
    url = f"https://www.{domaine}/q/" + urllib.parse.quote(texte) + "/"
    d = _get(api, json_attendu=True)
    res = []
    for x in d.get("listings", []):
        pi = x.get("priceInfo") or {}
        if pi.get("priceType") not in ("FIXED", "MIN_BID", "FAST_BID") or not pi.get("priceCents"):
            continue
        res.append({"nom": x.get("title", ""), "prix": pi["priceCents"] / 100,
                    "texte": x.get("title", "") + " " + (x.get("description") or "")[:800],
                    "vendeur": (x.get("sellerInformation") or {}).get("sellerId"),
                    "url": f"https://www.{domaine}" + x.get("vipUrl", ""),
                    "image": ((x.get("pictures") or [{}])[0].get("url") or ""),
                    "ville": (x.get("location") or {}).get("cityName", "")})
    return url, res


def deuxieme_main(texte):
    return _annonces_adevinta("2ememain.be", texte)


def marktplaats(texte):
    return _annonces_adevinta("marktplaats.nl", texte)


def kleinanzeigen(texte):
    """Kleinanzeigen.de : annonces de particuliers en Allemagne (HTML)."""
    url = "https://www.kleinanzeigen.de/s-" + urllib.parse.quote(texte.replace(" ", "-")) + "/k0"
    page = _get(url, entetes={"Accept-Language": "de-DE,de;q=0.9"})
    res = []
    for bloc in page.split('data-href="/s-anzeige/')[1:]:
        lien = bloc.split('"', 1)[0]
        m = re.search(r'<script type="application/ld\+json">(\{.*?\})</script>', bloc, re.S)
        prix = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)\s*€", re.sub(r"<script.*?</script>", "", bloc, flags=re.S))
        if not m or not prix:
            continue
        try:
            ld = json.loads(m.group(1))
        except ValueError:
            continue
        titre = html.unescape(ld.get("title", ""))
        if re.match(r"\s*(suche|tausche|biete tausch)\b", titre, re.I):
            continue
        res.append({"nom": titre, "prix": float(prix.group(1).replace(".", "")),
                    "texte": titre + " " + html.unescape(ld.get("description", "")),
                    "url": "https://www.kleinanzeigen.de/s-anzeige/" + lien})
    return url, res


def leboncoin(texte):
    """Leboncoin.fr : annonces de particuliers en France (données de la page)."""
    url = "https://www.leboncoin.fr/recherche?" + urllib.parse.urlencode({"text": texte})
    page = _get(url, entetes={"Accept-Language": "fr-FR,fr;q=0.9"})
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("Leboncoin a refusé la recherche")
    ads = (json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("searchData", {}) or {}).get("ads", [])
    res = []
    for a in ads:
        prix = (a.get("price") or [None])[0]
        if not prix:
            continue
        res.append({"nom": a.get("subject", ""), "prix": float(prix),
                    "texte": a.get("subject", "") + " " + (a.get("body") or "")[:800],
                    "vendeur": (a.get("owner") or {}).get("user_id"),
                    "url": a.get("url", url)})
    return url, res


def kieskeurig(texte):
    """Kieskeurig.be : comparateur belge, prix le plus bas parmi plusieurs boutiques."""
    url = "https://www.kieskeurig.be/search?" + urllib.parse.urlencode({"q": texte})
    page = _get(url)
    res = []
    for bloc in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(bloc)
        except ValueError:
            continue
        graphe = d.get("@graph", [d]) if isinstance(d, dict) else []
        for g in graphe:
            if g.get("@type") != "ItemList":
                continue
            for e in g.get("itemListElement", []):
                it = e.get("item", e)
                of = it.get("offers") or {}
                prix = of.get("lowPrice") or of.get("price")
                if it.get("name") and prix:
                    res.append({"nom": html.unescape(it["name"]), "prix": float(prix), "url": it.get("url", url),
                                "nb_boutiques": of.get("offerCount")})
    return url, res


SOURCES = {
    "coolblue": ("Coolblue", "neuf", coolblue),
    "mediamarkt": ("MediaMarkt", "neuf", mediamarkt),
    "kieskeurig": ("Kieskeurig.be", "neuf", kieskeurig),
    "amazon": ("Amazon.com.be", "neuf", amazon),
    "2ememain": ("2ememain", "occasion", deuxieme_main),
    "marktplaats": ("Marktplaats (NL)", "occasion", marktplaats),
    "kleinanzeigen": ("Kleinanzeigen (DE)", "occasion", kleinanzeigen),
    # Leboncoin : bloqué par son anti-robot (403) depuis le 20/10/2026, retiré pour ne pas ralentir
}
SOURCES_OCCASION = [k for k, v in SOURCES.items() if v[1] == "occasion"]

# Pertinence de chaque site comme référence de prix (3 = sérieux, 2 = correct, 1 = à prendre avec des pincettes).
# Un site absent de cette liste vaut 1 : on ne base jamais un gain sur une boutique inconnue.
PERTINENCE = {
    "cashconverters": 3,   # même réseau, même état « occasion contrôlée », prix réels en magasin
    "coolblue": 3, "mediamarkt": 3, "amazon": 3,       # grandes enseignes belges, prix neufs fiables
    "kieskeurig": 2,       # comparateur : le prix le plus bas peut venir d'une petite boutique inconnue
    "2ememain": 2, "marktplaats": 2,                   # annonces de particuliers : prix demandés, pas vendus
    "kleinanzeigen": 1,    # marché allemand : prix et habitudes différents de la Belgique
}


def pertinence_site(cle):
    return PERTINENCE.get(cle, 1)


def liens_manuels(texte):
    q = urllib.parse.quote_plus(texte)
    return [
        {"source": "Fnac", "url": f"https://www.fnac.be/SearchResult/ResultList.aspx?Search={q}"},
        {"source": "Vinted", "url": f"https://www.vinted.be/catalog?search_text={q}"},
        {"source": "eBay (ventes réussies)", "url": f"https://www.ebay.fr/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1"},
        {"source": "Google Shopping", "url": f"https://www.google.com/search?tbm=shop&q={q}"},
    ]


_brut = {}


def offres_brutes(cle, texte):
    """Résultats bruts d'une boutique pour une recherche (gardés en mémoire : une seule requête par texte)."""
    k = (cle, texte)
    with _verrou:
        if k in _brut:
            return _brut[k]
    fonction = SOURCES[cle][2]
    erreur = None
    for essai in range(2):                     # un 2e essai si la boutique a hoqueté
        try:
            res = fonction(texte)
            with _verrou:
                _brut[k] = res
            return res
        except Exception as e:
            erreur = type(e).__name__
            time.sleep(1.5)
    raise RuntimeError(erreur)


def interroger(cle, texte, tokens, exclure=None, bornes=None, verif=None, seuil=0.6, accessoires=True):
    """Interroge une boutique et résume les offres qui correspondent.

    bornes = (min, max) : garde-fou de prix. Un chargeur à 20 € n'est pas « le même produit »
    qu'un portable à 650 €, même si son titre cite « Lenovo Yoga ».
    """
    nom, type_, _ = SOURCES[cle]
    try:
        url, offres = offres_brutes(cle, texte)
    except Exception as e:
        return {"source": nom, "cle": cle, "type": type_, "erreur": str(e)}
    bons = [o for o in offres if correspond(tokens, o["nom"], exclure, seuil, accessoires)]
    vus, uniques = set(), []                   # un vendeur pro republie souvent la même annonce
    for o in bons:
        # même vendeur + même prix = même article republié (ex. « Nokia 105 (035) », « (133) »…)
        cle_o = (o.get("vendeur"), o["prix"]) if o.get("vendeur") else (_canon(o["nom"])[:60], o["prix"])
        if cle_o not in vus:
            vus.add(cle_o)
            uniques.append(o)
    bons = uniques
    if verif:                                  # specs exactes : processeur, RAM, stockage, écran…
        bons = [o for o in bons if verif(o.get("texte") or o["nom"])]
    if bornes:
        bons = [o for o in bons if bornes[0] <= o["prix"] <= bornes[1]]
    recond = [o for o in bons if any(m in _canon(o["nom"]) for m in MARQUEUR_RECOND)]
    neufs = [o for o in bons if o not in recond]
    res = {"source": nom, "cle": cle, "type": type_, "recherche": url, "nb": len(bons)}
    if type_ == "occasion":
        st = stats_robustes([o["prix"] for o in bons])
        if st:
            res.update(st)
            garde = [o for o in bons if st["min"] <= o["prix"] <= st["max"]]
            res["exemples"] = [{k: o[k] for k in ("nom", "prix", "url")} for o in sorted(garde, key=lambda o: o["prix"])[:4]]
            # toutes les annonces retenues, pour la référence « marché de l'occasion » (tous sites réunis)
            res["_offres"] = [{"nom": o["nom"], "prix": o["prix"], "url": o["url"], "source": nom, "cle": cle}
                              for o in bons]
    else:
        if neufs:
            meilleur = min(neufs, key=lambda o: o["prix"])
            res.update(prix=meilleur["prix"], nom=meilleur["nom"], url=meilleur["url"])
            if meilleur.get("nb_boutiques"):
                res["nb_boutiques"] = meilleur["nb_boutiques"]
        if recond:
            r = min(recond, key=lambda o: o["prix"])
            res["reconditionne"] = {"prix": r["prix"], "nom": r["nom"], "url": r["url"]}
    return res


def comparer_boutiques(texte, tokens, exclure=None, sources=None, bornes=None, verif=None, seuil=0.6,
                       accessoires=True):
    sources = sources or list(SOURCES)
    with ThreadPoolExecutor(len(sources)) as ex:
        return list(ex.map(lambda c: interroger(c, texte, tokens, exclure, bornes, verif, seuil, accessoires), sources))


def marche_occasion(lignes, libelle, **extra):
    """Réunit les annonces comparables de tous les sites en une seule référence (plus d'annonces = plus fiable)."""
    vues, offres = set(), []
    for l in lignes:
        for o in l.get("_offres", []):
            k = (o["source"], o["prix"], _canon(o["nom"])[:40])
            if k not in vues:
                vues.add(k)
                offres.append(o)
    # les sites peu pertinents ne comptent que s'il n'y a pas assez d'annonces sérieuses
    serieuses = [o for o in offres if pertinence_site(o.get("cle")) >= 2]
    if len(serieuses) >= 3 and len({o["source"] for o in serieuses}) >= 2:
        offres = serieuses
    sources = sorted({o["source"] for o in offres})
    if len(offres) < 3 or len(sources) < 2:
        return None
    st = stats_robustes([o["prix"] for o in offres])
    garde = [o for o in offres if st["min"] <= o["prix"] <= st["max"]]
    cles = {o.get("cle") for o in offres}
    return {"source": libelle, "cle": "marche", "type": "occasion", "marche": True, "sites": sources,
            "pertinence": max(pertinence_site(c) for c in cles),   # 3 seulement avec un site sérieux dedans
            "exemples": sorted(garde, key=lambda o: o["prix"])[:6], **st, **extra}


def bornes_pour(prix, type_="tous"):
    """Fourchette plausible pour un produit identique, vendu ailleurs, autour du prix Cash Converters."""
    if not prix:
        return None
    return (prix * 0.3, prix * 6)


# --------------------------------------------------------------------------- même processeur
PAS_PORTABLE = r"\b(tour|desktop|unite centrale|pc fixe|mini ?pc|all ?in ?one|ecran seul|moniteur)\b"
PAS_FIXE = r"\b(portable|laptop|notebook|chromebook|macbook|ultrabook)\b"
PAS_PC_COMPLET = r"\b(processeur seul|cpu seul|carte mere|ventirad|socket|tray|boxed|cooler)\b"


def ref_meme_processeur(cpu, portable, prix, id_produit=None, verif=None, gpu=""):
    """Prix d'occasion d'ordinateurs équipés du même processeur (2ememain + réseau Cash Converters)."""
    if not cpu or not cpu.get("cle") or not cpu.get("recherche"):
        return []
    import estimation
    tokens = [cpu["cle"]]
    exclure = (PAS_PORTABLE if portable else PAS_FIXE) + "|" + PAS_PC_COMPLET
    bornes = (prix * 0.3, prix * 3.5) if prix else None
    lignes = []
    with ThreadPoolExecutor(len(SOURCES_OCCASION)) as ex:
        recherche = (cpu["recherche"] + " " + gpu).strip()     # « i7-13700h rtx 4070 »
        res = list(ex.map(lambda c: interroger(c, recherche, tokens, exclure, bornes, verif, 0.6, False),
                          SOURCES_OCCASION))
    for r in res:
        if r.get("mediane") and r["nb"] >= 1:
            r.update(source=r["source"] + " · même configuration", meme_cpu=cpu["libelle"])
            lignes.append(r)
    occ = estimation.prix_occasion_reseau(id_produit or "0", cpu["recherche"], tokens, exclure, bornes,
                                          categorie="ordinateurs portables" if portable else "ordinateurs de bureau",
                                          verif=verif)
    if occ and occ["nb"] >= 1:
        lignes.append({"source": "Cash Converters · même configuration", "cle": "cashconverters", "type": "occasion",
                       "meme_cpu": cpu["libelle"], **occ})
    m = marche_occasion(lignes, "Marché de l'occasion · même configuration", meme_cpu=cpu["libelle"])
    return ([m] if m else []) + lignes


# --------------------------------------------------------------------------- PC pièce par pièce
FORFAIT_AUTRES = {"neuf": 170.0, "occasion": 85.0}   # carte mère + alimentation + boîtier + ventilation


PC_ENTIER = (r"(\bi[3579]\b|i[3579]\s*-?\s*\d{4,5}|\bryzen\b|\b(ram|ssd|nvme|hdd|windows|win ?1[01])\b"
             r"|\b(tuf gaming [afg]\d\d|[afg]1[4-7]|nitro|legion|loq|victus|omen|thin|zephyrus|rog strix g)\b)")


def _plain(t):
    t = unicodedata.normalize("NFKD", t.lower().replace("\xa0", " "))
    return "".join(c for c in t if not unicodedata.combining(c))


def detecter_composants(texte):
    """Repère processeur, carte graphique, RAM et stockage dans le nom / la fiche d'un PC."""
    t = _plain(texte)
    comps = []
    exclure_cpu = r"\b(rtx|gtx|ventirad|cooler|carte mere|motherboard|ram|ssd)\b|" + MOTS_PC
    m = re.search(r"\b(i[3579])\s*-?\s*(\d{4,5}[a-z]{0,2})\b", t)
    if m:
        comps.append({"type": "processeur", "libelle": f"Intel Core {m.group(1)}-{m.group(2).upper()}",
                      "texte": f"{m.group(1)}-{m.group(2)}", "tokens": [m.group(1), m.group(2)],
                      "exclure": exclure_cpu})
    else:
        m = re.search(r"\bryzen\s*([3579])\s*(\d{4}[a-z]{0,2})\b", t)
        if m:
            comps.append({"type": "processeur", "libelle": f"AMD Ryzen {m.group(1)} {m.group(2).upper()}",
                          "texte": f"ryzen {m.group(1)} {m.group(2)}", "tokens": ["ryzen", m.group(1), m.group(2)],
                          "exclure": exclure_cpu})
    g = (re.search(r"\b(rtx|gtx)\s*(\d{3,4})\s*(ti|super)?\b", t) or re.search(r"\b(rx)\s*(\d{3,4})\s*(xt)?\b", t)
         or re.search(r"\b(r[579])\s*(\d{3})\s*(x)?\b", t))
    if g:
        tokens = [g.group(1), g.group(2)] + ([g.group(3)] if g.group(3) else [])
        if re.fullmatch(r"r[579]", g.group(1)) and g.group(3):      # R9 390X s'écrit d'un bloc
            tokens = [g.group(1), g.group(2) + "x"]
        libelle = " ".join(x.upper() if x in ("rtx", "gtx", "rx", "xt", "x") or re.fullmatch(r"r[579]", x)
                           else x.capitalize() for x in tokens)
        comps.append({"type": "carte graphique",
                      "libelle": ("GeForce " if g.group(1) in ("rtx", "gtx") else "Radeon ") + libelle,
                      "texte": " ".join(tokens), "tokens": tokens,
                      "exclure": PC_ENTIER + r"|\b(waterblock|support|riser)\b|" + MOTS_PC})
    # tailles : « 16gb », « 500 go », « 1tb », « 500gbn » (faute de frappe fréquente)
    tailles = [(int(n), u) for n, u in re.findall(r"(\d{1,4})\s*(go|gb|to|tb)[a-z]?\b", t)]
    m_ram = re.search(r"(?:ram|memoire)\D{0,12}(\d{1,3})\s*(?:go|gb)|(\d{1,3})\s*(?:go|gb)\s*(?:de\s*)?(?:ram|ddr)", t)
    candidats_ram = [n for n, u in tailles if u in ("go", "gb") and n in (4, 8, 12, 16, 24, 32, 48, 64)]
    n_ram = int(next(x for x in m_ram.groups() if x)) if m_ram else (min(candidats_ram) if candidats_ram else None)
    if n_ram:
        ddr = "ddr5" if "ddr5" in t else "ddr3" if "ddr3" in t else "ddr4"
        comps.append({"type": "mémoire vive", "libelle": f"{n_ram} Go {ddr.upper()}", "texte": f"{n_ram}go {ddr}",
                      "tokens": [str(n_ram), ddr], "exclure": r"\b(so-?dimm)\b|" + PC_ENTIER[:-1] + r"|ssd\b)"})
    stock = [(n * 1000 if u in ("to", "tb") else n, n, u) for n, u in tailles
             if (u in ("to", "tb") and n <= 8) or (u in ("go", "gb") and n >= 120)]
    if stock:
        _, n, u = max(stock)
        ssd = bool(re.search(r"\b(ssd|nvme|m\.?2)\b", t))
        hdd = bool(re.search(r"\b(hdd|disque dur)\b", t)) and not ssd
        unite = "To" if u in ("to", "tb") else "Go"
        taille = f"{n}to" if unite == "To" else str(n)
        if hdd:
            comps.append({"type": "stockage", "libelle": f"Disque dur {n} {unite}", "texte": f"disque dur {n}{unite.lower()}",
                          "tokens": [taille, "disque", "dur"], "exclure": r"\b(externe|ssd|usb|portable)\b|" + MOTS_PC})
        else:
            comps.append({"type": "stockage", "libelle": f"SSD {n} {unite}", "texte": f"ssd {n}{unite.lower()}",
                          "tokens": [taille, "ssd"], "exclure": r"\b(externe|boitier|usb|cle|microsd)\b|" + MOTS_PC})
    return comps


def est_pc_fixe(produit, texte):
    t = _canon(produit.get("nom", "") + " " + texte)
    if re.search(r"\b(portable|laptop|notebook|macbook|chromebook)\b", t):
        return False
    return "bureau" in _canon(produit.get("categorie", "")) or bool(re.search(r"\b(pc|desktop|tour|unite centrale|gamer)\b", t))


def chiffrer_pc(produit, texte):
    comps = detecter_composants(texte)
    if not comps or not any(c["type"] in ("processeur", "carte graphique") for c in comps):
        return None

    def chiffrer(c):
        refs = comparer_boutiques(c["texte"], c["tokens"], c["exclure"])
        neufs = [r for r in refs if r.get("prix")]
        occ = next((r for r in refs if r["type"] == "occasion" and r.get("mediane")), None)
        best = min(neufs, key=lambda r: r["prix"]) if neufs else None
        return {
            "type": c["type"], "libelle": c["libelle"],
            "neuf": {"prix": best["prix"], "source": best["source"], "url": best["url"], "nom": best["nom"]} if best else None,
            "occasion": {"prix": occ["mediane"], "nb": occ["nb"], "source": occ["source"], "url": occ["recherche"]} if occ else None,
            "liens": liens_manuels(c["texte"]),
        }

    with ThreadPoolExecutor(4) as ex:
        lignes = list(ex.map(chiffrer, comps))
    complet_neuf = all(l["neuf"] for l in lignes)
    complet_occ = all(l["neuf"] or l["occasion"] for l in lignes)
    total_neuf = sum(l["neuf"]["prix"] for l in lignes if l["neuf"]) + FORFAIT_AUTRES["neuf"]
    # occasion manquante : on prend 55 % du neuf pour cette pièce
    total_occ = sum(l["occasion"]["prix"] if l["occasion"] else (l["neuf"]["prix"] * 0.55 if l["neuf"] else 0)
                    for l in lignes) + FORFAIT_AUTRES["occasion"]
    manquants = [l["libelle"] for l in lignes if not l["neuf"] and not l["occasion"]]
    return {"lignes": lignes, "autres": FORFAIT_AUTRES, "total_neuf": round(total_neuf, 2),
            "total_occasion": round(total_occ, 2), "manquants": manquants,
            "complet_neuf": complet_neuf, "complet_occasion": complet_occ}

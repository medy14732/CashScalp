"""
fiche_tech.py - Fiche technique d'un ordinateur à partir du texte de l'annonce.

Les annonces Cash Converters sont écrites à la main (« PC Portable Lenovo i5-1035G1 Geforce MX330
16 GB 512 gb ssd win 11 ») : on y repère processeur, carte graphique, RAM, stockage, écran, etc.
On en tire aussi le nom du modèle seul (« lenovo yoga slim 7 »), sans les specs qui gênent la recherche.
"""
import re
import unicodedata

import estimation


def plat(t):
    t = unicodedata.normalize("NFKD", t.lower().replace("\xa0", " "))
    return "".join(c for c in t if not unicodedata.combining(c))


TAILLES_RAM = {2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128}


def processeur(t):
    """Renvoie {libelle, cle, recherche} ; cle = identifiant précis du modèle (ex. « 1035g1 »)."""
    m = re.search(r"\bultra\s*([3579])\s*(\d{3}[a-z]{0,2})?\b", t)
    if m and "core" in t or m and "intel" in t:
        mod = m.group(2)
        return {"libelle": f"Intel Core Ultra {m.group(1)}" + (f" {mod.upper()}" if mod else ""),
                "cle": mod, "recherche": f"ultra {m.group(1)} {mod}" if mod else None}
    m = re.search(r"\bi([3579])\s*-?\s*(\d{4,5}[a-z]{0,2}\d?)\b", t)
    if m:
        mod = m.group(2)
        return {"libelle": f"Intel Core i{m.group(1)}-{mod.upper()}", "cle": mod,
                "recherche": f"i{m.group(1)}-{mod}"}
    m = re.search(r"\bryzen\s*([3579])\s*(pro\s*)?(\d{4}[a-z]{0,2}\d?)?\b", t)
    if m:
        mod = m.group(3)
        return {"libelle": f"AMD Ryzen {m.group(1)}" + (" Pro" if m.group(2) else "") + (f" {mod.upper()}" if mod else ""),
                "cle": mod, "recherche": f"ryzen {m.group(1)} {mod}" if mod else None}
    if re.search(r"\b(macbook|imac|apple|mac mini)\b", t):
        m = re.search(r"\bm([1-5])\s*(pro|max|ultra)?\b", t)
        if m:
            coeurs = re.search(r"(\d{1,2})\s*coeurs?", t)
            return {"libelle": f"Apple M{m.group(1)}" + (f" {m.group(2).capitalize()}" if m.group(2) else "")
                    + (f" ({coeurs.group(1)} cœurs)" if coeurs else ""), "cle": None, "recherche": None}
    m = re.search(r"\bsnapdragon\s*x\s*(elite|plus)?", t)
    if m:
        return {"libelle": "Qualcomm Snapdragon X" + (f" {m.group(1).capitalize()}" if m.group(1) else ""),
                "cle": None, "recherche": None}
    m = re.search(r"\b(celeron|pentium|athlon)\s*(silver|gold)?\s*([a-z]?\d{3,5}[a-z]?)?\b", t)
    if m:
        mod = m.group(3)
        return {"libelle": f"{'AMD' if m.group(1) == 'athlon' else 'Intel'} {m.group(1).capitalize()}"
                + (f" {m.group(2).capitalize()}" if m.group(2) else "") + (f" {mod.upper()}" if mod else ""),
                "cle": mod if mod and len(mod) >= 4 else None, "recherche": f"{m.group(1)} {mod}" if mod else None}
    m = re.search(r"\bi([3579])\b.{0,20}?(\d{1,2})\s*(?:th|e|eme|ème)?\s*gen", t)
    if m:
        return {"libelle": f"Intel Core i{m.group(1)} ({m.group(2)}e génération)", "cle": None, "recherche": None}
    m = re.search(r"\b(?:intel\s*(?:core)?\s*)i([3579])\b", t)
    if m:
        return {"libelle": f"Intel Core i{m.group(1)}", "cle": None, "recherche": None}
    return None


def carte_graphique(t):
    m = re.search(r"\b(rtx|gtx)\s*(\d{3,4})\s*(ti|super)?\b", t)
    if m:
        portable = " Laptop" if re.search(r"\blaptop\b", t) else ""
        return f"NVIDIA GeForce {m.group(1).upper()} {m.group(2)}" + (f" {m.group(3).capitalize()}" if m.group(3) else "") + portable
    m = re.search(r"\bmx\s*(\d{3})\b", t)
    if m:
        return f"NVIDIA GeForce MX{m.group(1)}"
    m = re.search(r"\brx\s*(\d{3,4})\s*(xt)?\b", t) or re.search(r"\br([579])\s*(\d{3})\s*(x)?\b", t)
    if m:
        return "AMD Radeon " + m.group(0).upper().replace("  ", " ")
    m = re.search(r"\barc\s*(a\d{3}m?)\b", t)
    if m:
        return f"Intel Arc {m.group(1).upper()}"
    m = re.search(r"\b(iris\s*xe|iris\s*plus|iris|uhd\s*(?:graphics)?\s*\d{0,3}|hd\s*graphics\s*\d{0,4}|intel\s*hd)\b", t)
    if m:
        nom = re.sub(r"^intel\s*", "", re.sub(r"\s+", " ", m.group(1)))
        return "Intel " + nom.title().replace("Uhd", "UHD").replace("Hd", "HD") + " (intégrée)"
    if re.search(r"radeon\s*(graphics|vega)", t):
        return "AMD Radeon (intégrée)"
    return None


def fiche_technique(texte, categorie=""):
    """Liste de {cle, libelle, valeur, icone} + infos utiles au calcul (processeur détaillé)."""
    t = plat(texte)
    t = re.sub(r"\s+", " ", t)
    specs = []

    def ajout(cle, libelle, valeur, icone):
        if valeur:
            specs.append({"cle": cle, "libelle": libelle, "valeur": valeur, "icone": icone})

    cpu = processeur(t)
    ajout("processeur", "Processeur", cpu and cpu["libelle"], "🧠")
    ajout("carte_graphique", "Carte graphique", carte_graphique(t), "🎮")

    tailles = [(int(n), u) for n, u in re.findall(r"(\d{1,4})\s*(go|gb|to|tb)[a-z]?\b", t)]
    m_ram = re.search(r"(?:ram|memoire)\D{0,12}(\d{1,3})\s*(?:go|gb)|(\d{1,3})\s*(?:go|gb)\s*(?:de\s*)?(?:ram|ddr)", t)
    ram = int(next(x for x in m_ram.groups() if x)) if m_ram else next(
        (n for n, u in tailles if u in ("go", "gb") and n in TAILLES_RAM and n <= 64), None)
    if not ram:
        m = re.search(r"(?:ram|memoire)\D{0,12}(\d{1,3})\b", t)
        if m and int(m.group(1)) in TAILLES_RAM:
            ram = int(m.group(1))
    if ram:
        ddr = re.search(r"\b(ddr[345]x?|lpddr[45]x?)\b", t)
        ajout("ram", "Mémoire vive", f"{ram} Go" + (f" {ddr.group(1).upper()}" if ddr else ""), "💾")
    stock = [(n * 1000 if u in ("to", "tb") else n, n, u) for n, u in tailles
             if (u in ("to", "tb") and n <= 8) or (u in ("go", "gb") and n >= 120 and n != ram)]
    if not stock and ram:                      # « 8 GB 256 » : la 2e taille sans unité est le stockage
        m = re.search(r"\b(?:go|gb)\s+(128|256|500|512|1000|1024)\b", t)
        if m:
            stock = [(int(m.group(1)), int(m.group(1)), "go")]
    if stock:
        _, n, u = max(stock)
        portable = "portable" in plat(categorie) or "macbook" in t
        genre = ("SSD" if re.search(r"\b(ssd|nvme|m\.?2)\b", t) else "Disque dur" if re.search(r"\bhdd\b", t)
                 else "eMMC" if "emmc" in t else "SSD" if portable      # sur un portable, « disque dur » veut dire SSD
                 else "Disque dur" if "disque dur" in t else "Stockage")
        ajout("stockage", "Stockage", f"{genre} {n} {'To' if u in ('to', 'tb') else 'Go'}", "🗄️")

    m = re.search(r"\b(1[0-8](?:[.,]\d)?)\s*(?:\"|''|pouces|inch|zoll|duim|po\b)", t) or re.search(r"\b(1[1-7][.,]\d)\b", t)
    ecran = f'{m.group(1).replace(".", ",")} pouces' if m else None
    details = [lib for motif, lib in [(r"\b4k\b|uhd\b", "4K"), (r"\b3k\b", "3K"), (r"\b2[.,]?8k\b", "2,8K"), (r"\b2k\b|qhd", "2K"),
                                      (r"\bfhd\b|full ?hd|1080p", "Full HD"), (r"\boled\b", "OLED"), (r"\bips\b", "IPS"),
                                      (r"tactile|touch|\bts\b|360", "tactile"), (r"\b(\d{3})\s*hz\b", None)]
               if re.search(motif, t) and lib]
    hz = re.search(r"\b(\d{3})\s*hz\b", t)
    if hz:
        details.append(f"{hz.group(1)} Hz")
    if ecran or details:
        ajout("ecran", "Écran", " · ".join(([ecran] if ecran else []) + details), "🖥️")

    m = re.search(r"\b(?:win(?:dows)?)\s*(1[01]|10|7|8)\s*(pro|home|famille)?\b", t)
    os_ = (f"Windows {m.group(1)}" + (f" {m.group(2).capitalize()}" if m.group(2) else "")) if m else \
        "macOS" if re.search(r"mac ?os|macbook|imac", t) else "ChromeOS" if "chrome" in t else \
        "Linux" if "linux" in t else "Sans système" if re.search(r"sans os|no os", t) else None
    ajout("systeme", "Système", os_, "💿")
    m = re.search(r"\b(azerty|qwertz|qwerty)u?\b", t)
    ajout("clavier", "Clavier", m and m.group(1).upper(), "⌨️")
    m = re.search(r"batterie\D{0,6}(\d{2,3})\s*%|\((\d{2,3})\s*%\)", t)
    ajout("batterie", "Batterie", m and f"{next(x for x in m.groups() if x)} % de capacité", "🔋")
    m = re.search(r"(watercooling|water cooling|aio\s*\d{3}|ventirad[^,;]{0,25}|ventilateurs?\s*rgb|refroidissement liquide)", t)
    ajout("refroidissement", "Refroidissement", m and m.group(1).strip().capitalize(), "🌀")
    m = re.search(r"(?:alim\w*\D{0,10})?\b(\d{3,4})\s*w\b", t)
    if m and (re.search(r"alim", t) or "bureau" in plat(categorie)):
        ajout("alimentation", "Alimentation", f"{m.group(1)} W", "🔌")
    m = re.search(r"\b(b[3-8]\d0m?|[hz][3-8]\d0|x[3-8]70e?|a[3-6]20)\b", t)
    if m and re.search(r"carte mere|asus|msi|gigabyte|asrock", t):
        ajout("carte_mere", "Carte mère", f"Chipset {m.group(1).upper()}", "🔲")
    m = re.search(r"\b(20[12]\d)\b", t)
    if m and re.search(r"macbook|imac|surface|thinkpad|xps", t):
        ajout("annee", "Année", m.group(1), "📅")
    return specs, cpu


COUPURE_SPECS = (r"\b(i[3579]\s*-?\s*\d{3,5}|i[3579]\b|ryzen|celeron|pentium|athlon|snapdragon|intel|amd|core|ultra\s*\d"
                 r"|geforce|rtx|gtx|radeon|\d+\s*(go|gb|to|tb)\b|win(dows)?\s*\d|ssd|hdd|ram\b|\d{1,2}\s*coeurs?"
                 r"|\d{2}[.,]\d|\d{2}\s*(\"|pouces))")


def requete_modele(nom):
    """« PC Portable (cash) Lenovo Yoga slim 7 14,5 3K OLED… » -> ['lenovo', 'yoga', 'slim', '7']"""
    t = plat(nom)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"^\W*(pc portable|ordinateur portable|pc|all in one|tout en un)\b(/tablette)?", " ", t)
    m = re.search(COUPURE_SPECS, t)
    prefixe = t[:m.start()] if m else t
    tokens = [x for x in estimation.mots_cles(prefixe) if x not in ("all", "in", "one", "tablette", "cash")]
    # « Victus 16 » -> « hp victus » : la marque aide beaucoup les boutiques
    for gamme, marque in GAMMES.items():
        if gamme in tokens and marque not in tokens:
            tokens.insert(0, marque)
            break
    return tokens[:4]


GAMMES = {g: m for m, gs in {
    "hp": "victus omen elitebook probook pavilion envy spectre zbook chromebook14",
    "lenovo": "ideapad thinkpad thinkbook yoga legion loq",
    "dell": "latitude inspiron xps vostro precision alienware",
    "acer": "aspire nitro swift predator travelmate spin",
    "asus": "zenbook vivobook rog tuf expertbook",
    "microsoft": "surface", "apple": "macbook imac",
    "msi": "katana thin modern prestige stealth raider"}.items() for g in gs.split()}


# --------------------------------------------------------------------------- comparaison stricte des specs
STOCK_NORMAL = {120: 128, 240: 256, 250: 256, 480: 512, 500: 512, 960: 1024, 1000: 1024, 2000: 2048}


def signature(texte):
    """Specs essentielles d'une annonce, normalisées pour être comparées entre elles."""
    t = re.sub(r"\s+", " ", plat(texte))
    sig = {"cpu_cle": None, "cpu_fam": None, "gpu": None, "ram": None, "stockage": None, "ecran": None}
    cpu = processeur(t)
    if cpu:
        sig["cpu_cle"] = cpu["cle"]
        fam = plat(cpu["libelle"])
        if cpu["cle"]:
            fam = fam.replace(plat(cpu["cle"]), "")
        sig["cpu_fam"] = re.sub(r"\(.*?\)|-|intel|amd|apple|qualcomm|core|\s+", "", fam) or None
    m = (re.search(r"\b(rtx|gtx)\s*(\d{3,4})\s*(ti|super)?\b", t) or re.search(r"\b(rx)\s*(\d{3,4})\s*(xt)?\b", t)
         or re.search(r"\b(mx)\s*(\d{3})()\b", t) or re.search(r"\b(arc)\s*(a\d{3})()\b", t))
    if m:
        sig["gpu"] = "".join(x for x in m.groups() if x)
    tailles = [(int(n), u) for n, u in re.findall(r"(\d{1,4})\s*(go|gb|to|tb)[a-z]?\b", t)]
    m_ram = re.search(r"(?:ram|memoire)\D{0,12}(\d{1,3})\s*(?:go|gb)|(\d{1,3})\s*(?:go|gb)\s*(?:de\s*)?(?:ram|ddr|lpddr)", t)
    sig["ram"] = int(next(x for x in m_ram.groups() if x)) if m_ram else next(
        (n for n, u in tailles if u in ("go", "gb") and n in TAILLES_RAM and n <= 64), None)
    if not sig["ram"]:                    # « i5 8 256gb » : RAM puis stockage, la RAM sans unité
        m = re.search(r"\b(4|8|12|16|24|32|64)\s*(?:go|gb)?\s*[/ ]\s*(128|256|500|512|1000|1024)\s*(?:go|gb|ssd)", t)
        if m:
            sig["ram"] = int(m.group(1))
    if not sig["ram"]:                    # « Mémoire RAM 32 » (sans unité)
        m = re.search(r"(?:ram|memoire)\D{0,12}(\d{1,3})\b", t)
        if m and int(m.group(1)) in TAILLES_RAM:
            sig["ram"] = int(m.group(1))
    stock = [n * 1000 if u in ("to", "tb") else n for n, u in tailles
             if (u in ("to", "tb") and n <= 8) or (u in ("go", "gb") and n >= 120 and n != sig["ram"])]
    if stock:
        go = max(stock)
        sig["stockage"] = STOCK_NORMAL.get(go, go)
    m = re.search(r"\b(1[0-8](?:[.,]\d)?)\s*(?:\"|''|pouces|inch|zoll|duim|po\b)", t) or re.search(r"\b(1[1-7][.,]\d)\b", t)
    if m:
        sig["ecran"] = float(m.group(1).replace(",", "."))
    return sig


def compatible(ref, cand):
    """True seulement si rien ne contredit : même processeur, même carte graphique,
    et même RAM / stockage / taille d'écran quand l'annonce comparée les indique."""
    if ref["cpu_cle"]:
        if cand["cpu_cle"] != ref["cpu_cle"]:          # processeur absent ou différent : pas la même machine
            return False
    elif ref["cpu_fam"]:
        if not cand["cpu_fam"] or cand["cpu_fam"] != ref["cpu_fam"]:
            return False
    if ref["gpu"] != cand["gpu"] and (ref["gpu"] or cand["gpu"]):
        if ref["gpu"] and cand["gpu"]:
            return False
        if cand["gpu"] and not ref["gpu"]:             # l'autre a une carte graphique dédiée, pas nous
            return False
        if ref["gpu"] and not cand["gpu"] and not ref["gpu"].startswith("mx"):
            return False                               # notre RTX doit être confirmée chez l'autre
    for k in ("ram", "stockage"):
        if ref[k] and cand[k] and ref[k] != cand[k]:
            return False
    if ref["ecran"] and cand["ecran"] and abs(ref["ecran"] - cand["ecran"]) > 0.35:
        return False
    return True


def verificateur(texte_ref):
    """Fonction texte -> bool, prête à filtrer les annonces d'une boutique."""
    ref = signature(texte_ref)
    return lambda texte: compatible(ref, signature(texte))


def indice_processeur(cpu):
    """Mots à ajouter à la recherche quand le processeur n'a pas de numéro précis (Apple M4, Snapdragon…)."""
    if not cpu:
        return []
    t = plat(cpu["libelle"])
    m = re.search(r"\bm([1-5])\b\s*(pro|max|ultra)?", t)
    if "apple" in t and m:
        return [f"m{m.group(1)}"] + ([m.group(2)] if m.group(2) else [])
    if "snapdragon" in t:
        return ["snapdragon"] + [x for x in ("elite", "plus") if x in t]
    m = re.search(r"ultra\s*([3579])", t)
    if m:
        return ["ultra", m.group(1)]
    m = re.search(r"\bi([3579])\b", t)
    if m:
        return [f"i{m.group(1)}"]
    m = re.search(r"(celeron|pentium|athlon)", t)
    return [m.group(1)] if m else []


def texte_gpu(texte):
    """« rtx4070 » -> « rtx 4070 » pour l'ajouter à une recherche."""
    g = signature(texte)["gpu"]
    if not g or g.startswith("mx"):
        return ""
    return re.sub(r"^([a-z]+)(\d+)(.*)$", r"\1 \2 \3", g).strip()

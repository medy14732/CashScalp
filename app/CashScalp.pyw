"""
CashScalp - application de bureau.
Démarre un petit serveur local et ouvre l'interface dans une fenêtre d'application Edge.
Le serveur s'arrête tout seul quand la fenêtre est fermée.
"""
import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# pythonw n'a pas de console : print() planterait sans ça
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import cashscalp as cs  # noqa: E402
import estimation  # noqa: E402

PORT = 8765
RAPPORTS = os.path.join(ICI, "rapports")
JOURNAL = os.path.join(ICI, "erreurs.log")
FAVORIS = os.path.join(ICI, "favoris.json")
DELAI_SANS_FENETRE = 150      # s sans signal de la page avant arrêt

ACC_INFO, ACC_JEUX = "220-accessoires-informatique", "219-accessoires-jeux-video"
PAS_UN_PC = r"\b(pc|ordinateur|portable|laptop|notebook|unite centrale|all ?in ?one)\b"

# Catégories « virtuelles » : plusieurs rubriques du site + filtre sur le nom de l'article
VIRTUELLES = {
    "composants": {"bases": [ACC_INFO], "nom": "composants",
                   "motif": r"(processeur|\bcpu\b|ryzen|\bi[3579][ -]?\d{4,5}|carte graphique|geforce|radeon|\brtx\b|\bgtx\b"
                            r"|\bddr[2345]\b|barrette|\bram\b|\bssd\b|nvme|disque dur|\bhdd\b|alimentation|ventila"
                            r"|ventirad|watercooling|refroidiss|carte mere|boitier pc|boitier atx)",
                   "sans": PAS_UN_PC + r"|chargeur|externe|usb"},
    "processeurs": {"bases": [ACC_INFO], "nom": "processeurs",
                    "motif": r"(processeur|\bcpu\b|intel core|\bcore i[3579]|\bi[3579][ -]?\d{4,5}|ryzen|xeon|pentium|celeron)",
                    "sans": PAS_UN_PC + r"|ventilateur|ventirad|cooler|refroidiss|carte mere|pate"},
    "cartes-graphiques": {"bases": [ACC_INFO, ACC_JEUX], "nom": "cartes graphiques",
                          "motif": r"(carte graphique|carte video|geforce|radeon|\brtx ?\d|\bgtx ?\d|\brx ?\d{3,4}\b|quadro)",
                          "sans": PAS_UN_PC + r"|support|riser|waterblock"},
    "ram": {"bases": [ACC_INFO], "nom": "memoire ram",
            "motif": r"(\bddr[2345]\b|barrette|so-?dimm|memoire vive|\bram\b)", "sans": PAS_UN_PC},
    "stockage": {"bases": [ACC_INFO], "nom": "stockage",
                 "motif": r"(\bssd\b|nvme|\bm\.?2\b|disque dur|\bhdd\b)", "sans": PAS_UN_PC + r"|boitier pour|adaptateur|externe|station|dock|usb"},
    "alimentations": {"bases": [ACC_INFO], "nom": "alimentations",
                      "motif": r"(alimentation|\bpsu\b)", "sans": PAS_UN_PC + r"|chargeur|adaptateur|usb|camera|imprimante"},
    "refroidissement": {"bases": [ACC_INFO], "nom": "refroidissement",
                        "motif": r"(ventilateur|ventirad|watercooling|water cooling|\baio\b|refroidiss|cooler|pate thermique)",
                        "sans": r"\b(portable|laptop|support)\b"},
    "cartes-meres": {"bases": [ACC_INFO], "nom": "cartes meres",
                     "motif": r"(carte mere|motherboard|\b(asus|msi|gigabyte|asrock)\b.*\b[abhxz][3-8][0-9]0[a-z]?\b)",
                     "sans": PAS_UN_PC + r"|tablette|graphique"},
    "boitiers": {"bases": [ACC_INFO], "nom": "boitiers pc",
                 "motif": r"(boitier (pc|atx|gamer|gaming|tour)|\btour (pc|atx|gamer|gaming)|\bchassis\b)",
                 "sans": r"(disque|externe|hdd|ssd|manette|telecommande)"},
    "souris": {"bases": [ACC_INFO, ACC_JEUX], "nom": "souris", "motif": r"\b(souris|mouse)\b",
               "sans": r"\b(tapis|mousepad|pad seul)\b"},
    "claviers": {"bases": [ACC_INFO, ACC_JEUX], "nom": "claviers", "motif": r"\b(clavier|keyboard)\b",
                 "sans": r"\b(piano|synthe|arrangeur|midi|etui|housse|ipad|tablette|cover|book)\b"},
    "casques": {"bases": [ACC_INFO, ACC_JEUX, "145-ipod-lecteurs-mp3-", "223-hifi-autres", "210-hifi-connecte",
                          "227-accessoires-telephonie"],
                "nom": "casques", "motif": r"\b(casque|headset|ecouteurs?|earbuds|airpods|headphones?)\b",
                "sans": r"\b(moto|velo|ski|chantier|vr|oculus|quest|realite|support|stand|etui|housse)\b"},
    "micros": {"bases": [ACC_INFO, ACC_JEUX, "186-pedales-effets-accordeurs-", "223-hifi-autres", "178-sono-autres",
                         "175-sono-mixage-lecture", "159-amplis-sono"],
               "nom": "micros", "motif": r"\b(micro|microphone|micros|mic)\b",
               "sans": r"(casque|headset|micro-?ondes?|micro ?sd|micro-?usb|microsoft|microscope|micro-?chaine|microfibre|micro ?casque)"},
    "webcams": {"bases": [ACC_INFO], "nom": "webcams", "motif": r"(webcam|camera web)", "sans": None},
}

# Sélecteur visuel : groupes > catégories, avec une icône chacun
CATEGORIES_UI = [
    {"groupe": "Tout", "icone": "✨", "items": [{"cle": "tout", "nom": "Toutes les catégories", "icone": "✨"}]},
    {"groupe": "Informatique", "icone": "💻", "items": [
        {"cle": "informatique", "nom": "Tout l'informatique", "icone": "💻"},
        {"cle": "ordinateurs-portables", "nom": "PC portables", "icone": "💻"},
        {"cle": "ordinateurs-de-bureau", "nom": "PC de bureau", "icone": "🖥️"},
        {"cle": "tablettes", "nom": "Tablettes", "icone": "📲"},
        {"cle": "moniteurs", "nom": "Écrans", "icone": "🖵"}]},
    {"groupe": "Composants PC", "icone": "🧩", "items": [
        {"cle": "composants", "nom": "Tous les composants", "icone": "🧩"},
        {"cle": "processeurs", "nom": "Processeurs", "icone": "🧠"},
        {"cle": "cartes-graphiques", "nom": "Cartes graphiques", "icone": "🎮"},
        {"cle": "ram", "nom": "Mémoire RAM", "icone": "💾"},
        {"cle": "stockage", "nom": "SSD & disques durs", "icone": "🗄️"},
        {"cle": "alimentations", "nom": "Alimentations", "icone": "🔌"},
        {"cle": "refroidissement", "nom": "Ventilation & refroidissement", "icone": "🌀"},
        {"cle": "cartes-meres", "nom": "Cartes mères", "icone": "🔲"},
        {"cle": "boitiers", "nom": "Boîtiers PC", "icone": "📦"}]},
    {"groupe": "Périphériques", "icone": "🖱️", "items": [
        {"cle": "souris", "nom": "Souris", "icone": "🖱️"},
        {"cle": "claviers", "nom": "Claviers", "icone": "⌨️"},
        {"cle": "casques", "nom": "Casques & écouteurs", "icone": "🎧"},
        {"cle": "micros", "nom": "Micros", "icone": "🎙️"},
        {"cle": "webcams", "nom": "Webcams", "icone": "📷"},
        {"cle": "accessoires-informatique", "nom": "Tous les accessoires", "icone": "🔧"}]},
    {"groupe": "Téléphonie", "icone": "📱", "items": [
        {"cle": "telephonie", "nom": "Toute la téléphonie", "icone": "📱"},
        {"cle": "gsm", "nom": "Smartphones", "icone": "📱"},
        {"cle": "montre-connectee", "nom": "Montres connectées", "icone": "⌚"}]},
    {"groupe": "Jeux vidéo", "icone": "🎮", "items": [
        {"cle": "jeux-video", "nom": "Tout le jeu vidéo", "icone": "🎮"},
        {"cle": "consoles-sony", "nom": "PlayStation", "icone": "🎮"},
        {"cle": "consoles-nintendo", "nom": "Nintendo", "icone": "🍄"},
        {"cle": "consoles-xbox", "nom": "Xbox", "icone": "🟩"},
        {"cle": "jeux-playstation", "nom": "Jeux PlayStation", "icone": "💿"},
        {"cle": "jeux-nintendo", "nom": "Jeux Nintendo", "icone": "💿"}]},
    {"groupe": "Image & son", "icone": "📺", "items": [
        {"cle": "tv-home-cinema", "nom": "TV & home cinéma", "icone": "📺"},
        {"cle": "tv", "nom": "Téléviseurs", "icone": "📺"},
        {"cle": "hifi", "nom": "Hi-fi", "icone": "🎵"},
        {"cle": "enceintes", "nom": "Enceintes", "icone": "🔊"},
        {"cle": "photo-numerique", "nom": "Appareils photo", "icone": "📸"},
        {"cle": "objectifs", "nom": "Objectifs", "icone": "🔭"}]},
    {"groupe": "Maison & outils", "icone": "🛠️", "items": [
        {"cle": "outillage", "nom": "Outillage", "icone": "🛠️"},
        {"cle": "jardinage", "nom": "Jardin", "icone": "🌿"},
        {"cle": "electromenager", "nom": "Électroménager", "icone": "🧺"},
        {"cle": "petit-electromenager", "nom": "Petit électroménager", "icone": "☕"}]},
    {"groupe": "Mode & luxe", "icone": "⌚", "items": [
        {"cle": "montres", "nom": "Montres", "icone": "⌚"},
        {"cle": "bijouterie", "nom": "Bijoux", "icone": "💍"},
        {"cle": "luxe-maroquinerie", "nom": "Maroquinerie de luxe", "icone": "👜"}]},
    {"groupe": "Loisirs", "icone": "🎸", "items": [
        {"cle": "instruments", "nom": "Instruments", "icone": "🎸"},
        {"cle": "sport", "nom": "Sport", "icone": "🏋️"},
        {"cle": "velos", "nom": "Vélos", "icone": "🚲"},
        {"cle": "livres-jouets", "nom": "Livres & jouets", "icone": "🧸"},
        {"cle": "vinyles", "nom": "Vinyles", "icone": "💽"}]},
]


# --------------------------------------------------------------------------- catégories exactes du site
ICONES_CAT = {"136": "📱", "134": "💻", "138": "🎮", "130": "⌚", "141": "🎵", "126": "🛠️", "143": "📷",
              "150": "🎸", "147": "📺", "132": "🧺", "152": "🚲", "171": "🌡️", "128": "🧴", "206": "💿", "211": "🧸"}
ICONES_MOTS = [("portable", "💻"), ("tablette", "📲"), ("bureau", "🖥️"), ("moniteur", "🖵"), ("imprimante", "🖨️"),
               ("accessoires informatique", "🖱️"), ("gsm", "📱"), ("gps", "🧭"), ("console", "🕹️"), ("jeux", "💿"),
               ("montre", "⌚"), ("bijou", "💍"), ("sac", "👜"), ("enceinte", "🔊"), ("casque", "🎧"), ("platine", "💽"),
               ("guitare", "🎸"), ("piano", "🎹"), ("percussion", "🥁"), ("vent", "🎷"), ("outillage", "🛠️"),
               ("jardin", "🌿"), ("objectif", "🔭"), ("photo", "📷"), ("camescope", "📹"), ("jumelle", "🔭"),
               ("tv", "📺"), ("home cinema", "🔈"), ("blu ray", "📀"), ("dvd", "📀"), ("velo", "🚲"), ("moto", "🏍️"),
               ("fitness", "🏋️"), ("golf", "⛳"), ("vinyle", "💽"), ("cd", "💿"), ("jouet", "🧸"), ("societe", "🎲"),
               ("bandes dessinees", "📚"), ("figurine", "🗿"), ("climatiseur", "❄️"), ("chauffage", "🔥"), ("animaux", "🐾")]
_categories_ui = None


def icone_pour(nom, defaut):
    n = cs.plat(nom)
    return next((i for mot, i in ICONES_MOTS if mot in n), defaut)


def categories_ui():
    """Le panneau « Quoi ? » reprend exactement les catégories du site Cash Converters."""
    global _categories_ui
    if _categories_ui is None:
        groupes = [{"groupe": "Tout", "icone": "✨", "items": [{"cle": "2-categories", "nom": "Toutes les catégories", "icone": "✨"}]}]
        for c in cs.categories_du_site():
            ic = ICONES_CAT.get(c["slug"].split("-")[0], "📦")
            items = [{"cle": c["slug"], "nom": "Tout : " + c["nom"], "icone": ic}]
            items += [{"cle": slug, "nom": nom, "icone": icone_pour(nom, ic)} for slug, nom in c["sous"]]
            groupes.append({"groupe": c["nom"], "icone": ic, "items": items})
        _categories_ui = groupes
    return _categories_ui

etat = {"dernier_signal": time.time(), "fenetre_vue": False}
jobs = {}
produits_connus = {}
estimations = {}
verrou_est = {}


# --------------------------------------------------------------------------- favoris
verrou_fav = threading.Lock()


def lire_favoris():
    try:
        with open(FAVORIS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def ecrire_favoris(liste):
    tmp = FAVORIS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FAVORIS)          # écriture atomique : pas de fichier à moitié écrit


def ajouter_favori(pid):
    with verrou_fav:
        favs = lire_favoris()
        if not any(f["id"] == pid for f in favs):
            p = produits_connus.get(pid)
            if not p:
                raise KeyError("article inconnu, relance la recherche")
            f = {k: v for k, v in p.items() if k != "estimation"}
            if pid in estimations:
                f["estimation"] = estimations[pid]["resume"]
            f["ajoute_le"] = time.strftime("%Y-%m-%d %H:%M")
            f["prix_ajout"] = p["prix"]
            favs.insert(0, f)
            ecrire_favoris(favs)
        return favs


def retirer_favori(pid):
    with verrou_fav:
        favs = [f for f in lire_favoris() if f["id"] != pid]
        ecrire_favoris(favs)
        return favs


def verifier_un(f):
    """Toujours en vente ? Au même prix ? (lecture de la page de l'article)"""
    try:
        req = urllib.request.Request(f["url"], headers={"User-Agent": estimation.UA, "Accept-Encoding": "gzip"})
        with estimation.limite(f["url"]), urllib.request.urlopen(req, timeout=20) as r:
            final, page = r.geturl(), cs.lire(r)
    except urllib.error.HTTPError as e:
        return {"etat": "vendu"} if e.code in (404, 410) else {"etat": "inconnu"}
    except Exception:
        return {"etat": "inconnu"}
    m = re.search(r"current-price-value'[^>]*content=\"([\d.]+)\"", page)
    if f["id"] not in final or not m:
        return {"etat": "vendu"}
    return {"etat": "dispo", "prix": float(m.group(1))}


def verifier_favoris():
    favs = lire_favoris()
    with ThreadPoolExecutor(6) as ex:
        res = dict(zip([f["id"] for f in favs], ex.map(verifier_un, favs)))
    with verrou_fav:                  # on garde le dernier prix vu dans le fichier
        favs = lire_favoris()
        for f in favs:
            r = res.get(f["id"])
            if r and r["etat"] == "dispo":
                f["prix"] = r["prix"]
            if r and r["etat"] != "inconnu":
                f["etat"] = r["etat"]
        ecrire_favoris(favs)
    return res


def journaliser(texte):
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texte + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- recherche
def lancer_job(params):
    jid = uuid.uuid4().hex[:10]
    etat["dernier_job"] = jid
    jobs[jid] = {"etat": "en_cours", "message": "Connexion à cashconverters.be…", "progression": 0}
    threading.Thread(target=travail, args=(jid, params), daemon=True).start()
    return jid


def travail(jid, p):
    job = jobs[jid]

    def progres(msg, frac):
        job["message"], job["progression"] = msg, round(frac, 3)
    try:
        zone = p.get("zone", "ARLON")
        if zone.startswith("region:"):
            region = zone.split(":", 1)[1]
            magasins, nom_zone = cs.REGIONS[region], region
        elif zone == "tous":
            magasins, nom_zone = [], "tous"
        else:
            magasins, nom_zone = [cs.trouver_magasin(zone)], zone
        cle = p.get("cat", "2-categories")
        virt = VIRTUELLES.get(cle)
        if re.fullmatch(r"\d+-[a-z0-9-]+", cle):        # catégorie du site, telle quelle
            cat, filtres = cle, {}
        elif virt:
            cat, filtres = virt["bases"], {"motif": virt["motif"], "sans": virt["sans"], "nom_cat": virt["nom"]}
        else:
            cat = cs.CATEGORIES.get(cle) or cs.CATEGORIES["tout"]
            filtres = {}

        def nombre(cle):
            v = (p.get(cle) or "").replace(",", ".").replace("€", "").strip()
            return float(v) if v else None

        produits, base, premier = cs.rechercher(
            magasins, cat, nom_zone, mots=(p.get("q") or "").strip() or None,
            prix_min=nombre("pmin"), prix_max=nombre("pmax"),
            nouveaux=p.get("nouveaux") == "1", sortie=RAPPORTS, progres=progres, verbeux=False, **filtres)
        for x in produits:
            produits_connus[x["id"]] = x
            if x["id"] in estimations:
                x["estimation"] = resume_estimation(estimations[x["id"]])
        job.update(etat="fini", produits=produits, premier=premier, progression=1,
                   rapport=base + ".html", message=f"{len(produits)} articles")
    except Exception as e:
        journaliser(traceback.format_exc())
        job.update(etat="erreur", message=f"{type(e).__name__} : {e}")


def resume_estimation(est):
    v = est.get("verdict", {})
    g = est.get("gains", {}).get(v.get("base") or "", {})
    return {"note": v.get("note"), "base": v.get("base"), "pct": v.get("pct"), "gain": g.get("gain"),
            "ref": g.get("ref")}


POOL = ThreadPoolExecutor(16)          # estimations groupées ; chaque site garde sa propre limite


def estimer(pid, complet=True):
    """complet=False : version rapide pour la grille ; complet=True : tout, pour la fiche."""
    def suffisant(e):
        return e is not None and (e.get("complet") or not complet)
    if suffisant(estimations.get(pid)):
        return estimations[pid]
    produit = produits_connus.get(pid)
    if not produit:
        raise KeyError("article inconnu, relance la recherche")
    verrou = verrou_est.setdefault(pid, threading.Lock())
    with verrou:
        if not suffisant(estimations.get(pid)):
            est = estimation.estimer(produit, complet=complet)
            est["resume"] = resume_estimation(est)
            estimations[pid] = est
    return estimations[pid]


def lot(jid, depuis=0):
    """Estime tous les articles d'une recherche en parallèle ; renvoie ceux finis depuis `depuis`."""
    job = jobs.get(jid)
    if not job or job.get("etat") != "fini":
        raise KeyError("recherche inconnue ou pas terminée")
    if "lot" not in job:
        suivi = {"total": len(job["produits"]), "faits": []}
        job["lot"] = suivi

        def un(p):
            try:
                if etat.get("dernier_job") == jid:          # recherche dépassée : on saute
                    estimer(p["id"], complet=False)
            except Exception:
                journaliser(traceback.format_exc())
            finally:
                suivi["faits"].append(p["id"])
        for p in job["produits"]:
            POOL.submit(un, p)
    suivi = job["lot"]
    faits = suivi["faits"][depuis:]
    return {"total": suivi["total"], "nb_faits": depuis + len(faits),
            "resultats": [{"id": i, "resume": estimations[i]["resume"]} for i in faits if i in estimations]}


# --------------------------------------------------------------------------- HTTP
class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _envoyer(self, code, corps, type_="application/json; charset=utf-8"):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        elif isinstance(corps, str):
            corps = corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _fichier(self, chemin, type_):
        try:
            with open(chemin, "rb") as f:
                self._envoyer(200, f.read(), type_)
        except OSError:
            self._envoyer(404, {"erreur": "introuvable"})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        etat["dernier_signal"] = time.time()
        try:
            if u.path in ("/", "/index.html"):
                return self._fichier(os.path.join(ICI, "web", "index.html"), "text/html; charset=utf-8")
            if u.path == "/logo.png":
                return self._fichier(os.path.join(ICI, "logo_256.png"), "image/png")
            if u.path == "/favicon.ico":
                return self._fichier(os.path.join(ICI, "cashscalp.ico"), "image/x-icon")
            if u.path == "/api/ping":
                etat["fenetre_vue"] = True
                return self._envoyer(200, {"ok": True, "app": "cashscalp"})
            if u.path == "/api/meta":
                return self._envoyer(200, {"magasins": cs.MAGASINS, "regions": cs.REGIONS,
                                           "categories": categories_ui()})
            if u.path == "/api/recherche":
                return self._envoyer(200, {"job": lancer_job(q)})
            if u.path == "/api/job":
                job = jobs.get(q.get("id", ""))
                return self._envoyer(200 if job else 404, job or {"erreur": "job inconnu"})
            if u.path == "/api/lot":
                return self._envoyer(200, lot(q.get("job", ""), int(q.get("depuis", 0) or 0)))
            if u.path == "/api/estimer":
                return self._envoyer(200, estimer(q.get("id", "")))
            if u.path == "/api/favoris":
                return self._envoyer(200, lire_favoris())
            if u.path == "/api/favori_ajouter":
                return self._envoyer(200, ajouter_favori(q.get("id", "")))
            if u.path == "/api/favori_retirer":
                return self._envoyer(200, retirer_favori(q.get("id", "")))
            if u.path == "/api/favoris_verifier":
                return self._envoyer(200, verifier_favoris())
            if u.path == "/api/rapport":
                job = jobs.get(q.get("id", ""))
                if job and job.get("rapport") and os.path.exists(job["rapport"]):
                    os.startfile(job["rapport"])
                return self._envoyer(200, {"ok": True})
            self._envoyer(404, {"erreur": "introuvable"})
        except Exception as e:
            journaliser(traceback.format_exc())
            self._envoyer(500, {"erreur": f"{type(e).__name__} : {e}"})


# --------------------------------------------------------------------------- fenêtre
def trouver_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            c = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(c):
                return c
    return shutil.which("msedge")


def ouvrir_fenetre(url):
    edge = trouver_edge()
    if edge:
        profil = os.path.join(ICI, "profil-fenetre")
        # fenêtre « nue » : sans extensions, synchronisation ni composants Edge (sinon le profil grossit à 1,5 Go)
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profil}", "--window-size=1380,900",
                          "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                          "--disable-sync", "--disable-component-update", "--disable-background-networking",
                          "--disk-cache-size=52428800", "--disable-features=msEdgeSidebarV2,EdgeCollections,"
                          "OptimizationGuideModelDownloading,OptimizationHints"])
    else:
        webbrowser.open(url)


def deja_lance(url):
    try:
        with urllib.request.urlopen(url + "api/ping", timeout=2) as r:
            return json.load(r).get("app") == "cashscalp"
    except Exception:
        return False


def surveiller(serveur):
    """Arrête le serveur quand plus aucune fenêtre ne donne signe de vie."""
    while True:
        time.sleep(10)
        limite = DELAI_SANS_FENETRE if etat["fenetre_vue"] else 300
        if time.time() - etat["dernier_signal"] > limite:
            serveur.shutdown()
            return


def main():
    url = f"http://127.0.0.1:{PORT}/"
    if deja_lance(url):
        ouvrir_fenetre(url)
        return
    for f in lire_favoris():          # les favoris restent consultables et estimables sans recherche
        produits_connus.setdefault(f["id"], f)
    serveur = ThreadingHTTPServer(("127.0.0.1", PORT), Gestionnaire)
    threading.Thread(target=surveiller, args=(serveur,), daemon=True).start()
    if "--sans-fenetre" not in sys.argv:
        ouvrir_fenetre(url)
    serveur.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        journaliser(traceback.format_exc())
        raise

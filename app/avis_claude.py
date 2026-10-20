"""
avis_claude.py - Avis de Claude sur un article : acheter, négocier ou éviter.

Appelé seulement quand on clique sur « Avis de Claude » dans la fiche (chaque appel est facturé
sur le compte API Anthropic, séparément de l'abonnement Claude).
La clé API est enregistrée sur ce PC, dans reglages.json, et n'est jamais envoyée ailleurs qu'à Anthropic.
"""
import inspect
import json
import os
import subprocess
import sys
import threading

ICI = os.path.dirname(os.path.abspath(__file__))
REGLAGES = os.path.join(ICI, "reglages.json")
MODELE = "claude-opus-5-5"

verrou = threading.Lock()
avis_connus = {}          # id article -> avis déjà donné (pas de second appel payant)

CONSIGNE = """Tu conseilles un revendeur belge qui achète des articles d'occasion chez Cash Converters \
pour les revendre (2ememain, Vinted, Marketplace) ou les garder. On te donne l'annonce, les prix \
de référence trouvés automatiquement (occasion, reconditionné, neuf) et la marge estimée.

Juge si le prix est pertinent et s'il faut l'acheter. Méfie-toi des références approximatives ou \
peu nombreuses : une comparaison avec un modèle proche ou une seule annonce ne prouve rien. \
Tiens compte de l'état, de la batterie, des accessoires manquants, de la garantie d'un an Cash \
Converters, de la facilité de revente et des frais (envoi, commission, temps).

Verdict : « acheter » si c'est clairement rentable, « negocier » si l'article est intéressant mais \
un peu cher (donne alors un prix cible), « eviter » sinon. Réponds en français, phrases courtes et \
simples, sans jargon."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["acheter", "negocier", "eviter"]},
        "raison": {"type": "string", "description": "une phrase, la raison principale"},
        "prix_cible": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "prix à proposer si negocier, sinon null"},
        "revente": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "prix de revente réaliste en occasion, ou null"},
        "points": {"type": "array", "items": {"type": "string"},
                   "description": "2 ou 3 points à vérifier ou à savoir, très courts"},
        "confiance": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
    },
    "required": ["verdict", "raison", "prix_cible", "revente", "points", "confiance"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- clé API
def lire_reglages():
    try:
        with open(REGLAGES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cle_api():
    return (lire_reglages().get("cle_anthropic") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def etat_cle():
    c = cle_api()
    return {"configuree": bool(c), "apercu": ("…" + c[-4:]) if c else ""}


def enregistrer_cle(cle):
    cle = (cle or "").strip()
    if cle and not cle.startswith("sk-ant-"):
        raise ValueError("cette clé ne ressemble pas à une clé Anthropic (elle commence par sk-ant-)")
    r = lire_reglages()
    if cle:
        r["cle_anthropic"] = cle
    else:
        r.pop("cle_anthropic", None)
    with open(REGLAGES, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return etat_cle()


# --------------------------------------------------------------------------- SDK
def _sdk():
    """Importe le SDK Anthropic ; l'installe (ou le met à jour) au premier usage s'il manque."""
    def a_jour():
        import anthropic
        return "fallbacks" in inspect.signature(anthropic.Anthropic(api_key="x").beta.messages.create).parameters
    try:
        if a_jour():
            import anthropic
            return anthropic
    except ImportError:
        pass
    with verrou:
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        drapeaux = {"creationflags": 0x08000000} if os.name == "nt" else {}   # pas de fenêtre noire
        r = subprocess.run([exe, "-m", "pip", "install", "-q", "-U", "anthropic"],
                           capture_output=True, text=True, **drapeaux)
        if r.returncode:
            raise RuntimeError("installation du module anthropic impossible : " + (r.stderr or r.stdout)[-300:])
        import importlib
        import anthropic
        importlib.reload(anthropic)
        return anthropic


# --------------------------------------------------------------------------- avis
def _fiche(produit, est):
    """Résumé compact de l'article et des références, pour Claude."""
    d = est.get("details") if isinstance(est.get("details"), dict) else {}
    refs = []
    for b in est.get("boutiques") or []:
        prix = b.get("prix") if b.get("prix") is not None else b.get("mediane")
        if prix is None:
            continue
        refs.append({k: v for k, v in {
            "source": b.get("source"), "type": b.get("type"), "prix": prix, "nom": b.get("nom"),
            "nb_annonces": b.get("nb"), "min": b.get("min"), "max": b.get("max"),
            "fiabilite": b.get("fiabilite"), "modele_proche": b.get("approx") or None,
            "meme_configuration": b.get("meme_cpu") or None}.items() if v not in (None, "")})
    comps = est.get("composants")
    return {
        "article": {"nom": produit.get("nom"), "prix": produit.get("prix"),
                    "prix_avant_remise": produit.get("prix_normal") if produit.get("remise_pct") else None,
                    "categorie": produit.get("categorie"), "magasin": produit.get("magasin"),
                    "marque": d.get("marque"), "modele": d.get("modele"),
                    "description_vendeur": (d.get("description") or "")[:1500],
                    "garantie": d.get("garantie") or "1 an"},
        "caracteristiques": [f"{s.get('libelle')}: {s.get('valeur')}" for s in est.get("specs") or []],
        "modele_recherche": " ".join(est.get("mots_cles") or []),
        "references": refs[:15],
        "pieces_pc": {"total_occasion": comps.get("total_occasion"), "total_neuf": comps.get("total_neuf"),
                      "complet": comps.get("complet_occasion")} if comps else None,
        "estimation_appli": {"verdict": est.get("verdict"), "gains": est.get("gains")},
    }


def avis(produit, est, relancer=False):
    pid = produit["id"]
    if pid in avis_connus and not relancer:
        return avis_connus[pid]
    cle = cle_api()
    if not cle:
        raise PermissionError("clé API manquante")
    anthropic = _sdk()
    client = anthropic.Anthropic(api_key=cle, max_retries=2, timeout=120)
    try:
        rep = client.beta.messages.create(
            model=MODELE,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=CONSIGNE,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(_fiche(produit, est), ensure_ascii=False)}],
        )
    except anthropic.AuthenticationError:
        raise PermissionError("clé API refusée par Anthropic : vérifie-la dans les réglages")
    except anthropic.PermissionDeniedError:
        raise PermissionError("cette clé n'a pas accès à l'API (crédit épuisé ou compte non activé ?)")
    except anthropic.RateLimitError:
        raise RuntimeError("trop de demandes d'un coup, réessaie dans une minute")
    except anthropic.APIConnectionError:
        raise RuntimeError("impossible de joindre Anthropic : vérifie la connexion internet")
    except anthropic.APIStatusError as e:
        if "credit" in str(e.message).lower():
            raise RuntimeError("crédit API épuisé : recharge-le sur console.anthropic.com")
        raise RuntimeError(f"erreur Anthropic ({e.status_code}) : {e.message}")
    if rep.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé de donner un avis sur cet article")
    texte = next((b.text for b in rep.content if b.type == "text"), "")
    res = json.loads(texte)
    u = rep.usage
    # prix publics Claude Opus 5.5 : 4 $ / million de jetons en entrée, 20 $ en sortie
    res["cout_usd"] = round((u.input_tokens * 4 + u.output_tokens * 20) / 1e6, 4)
    avis_connus[pid] = res
    return res

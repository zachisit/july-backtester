"""Task 2 — ticker normalization, Norgate<->Polygon candidate matching, and
identity-check scaffolding.

Never merge by raw ticker string alone. A Norgate symbol is matched to a
Polygon ticker only when a normalized candidate hits Polygon's active set;
the *price-continuity* half of the identity check runs later against overlap
data (see calibrate.identity_price_check).
"""
import re


def poly_candidates(t):
    """Polygon-form candidate tickers for a Norgate ticker `t`.

    Handles: exact, upper, dot/dash-stripped, preferred (ABR-D -> ABRpD),
    warrant (ACHR_W -> ACHR.WS), bare-W warrant (ADACW -> ADAC.WS),
    and dotted class shares (BRK-B -> BRK.B, the Polygon form).
    """
    t = str(t)
    c = {t, t.upper(), t.replace(".", "").replace("-", "")}
    # class-share / preferred with single trailing letter after '-'
    if "-" in t:
        base, cls = t.rsplit("-", 1)
        if len(cls) == 1 and cls.isalpha():
            c.add(f"{base}p{cls}")     # preferred form ABR-D -> ABRpD
            c.add(f"{base}.{cls}")     # class-share form BRK-B -> BRK.B
    # warrant suffixes
    if t.endswith("_W"):
        c.add(t[:-2] + ".WS")
    if t.endswith("W") and len(t) > 4 and not t.endswith("_W"):
        c.add(t[:-1] + ".WS")
    return c


def match_norgate_to_polygon(norgate_symbol, polygon_ticker_set):
    """Return (polygon_ticker, candidate_used) or (None, None)."""
    for cand in poly_candidates(norgate_symbol):
        if cand in polygon_ticker_set:
            return cand, cand
    return None, None


def norgate_heuristic_class(sym):
    """Best-effort security class for a Norgate symbol with no Polygon match.

    Used only to triage the unmatched tail into review vs exclude.
    """
    sym = str(sym)
    if re.search(r"-[A-Z]$", sym):
        return "preferred_or_class"
    if sym.endswith("_W") or (sym.endswith("W") and len(sym) > 4):
        return "warrant"
    if sym.endswith("U"):
        return "unit"
    if sym.endswith("R") and len(sym) > 3:
        return "rights"
    if sym.endswith(("F", "Y")):
        return "otc_foreign_adr"
    if sym.endswith("Q"):
        return "bankruptcy_otc"
    return "unknown"


# Norgate-internal symbols that are never tradeable instruments.
def is_norgate_nontradeable(sym):
    """True for Norgate breadth (#) and internal index ($) symbols."""
    sym = str(sym)
    return sym.startswith("#") or sym.startswith("$")

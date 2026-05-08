"""
El Salvador geographic dictionary — the source of truth for zone resolution.

Used by pulpo/normalize.py's multi-tier resolver.  The data is baked in as
plain Python so normalization is 100% offline and deterministic.

Sources: Wikipedia "List of municipalities of El Salvador", DIGESTYC / INE,
         own curation for tourist localities and development names.

Normalization: all lookup keys are accent-stripped lowercase (see _norm()).
"""
from __future__ import annotations
import unicodedata
import re
from typing import Optional

# ── Normalization helper ───────────────────────────────────────────────
def _norm(s: str) -> str:
    """Accent-strip, lowercase, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_ = nfkd.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", ascii_.lower()).strip()


# ── 14 departments ─────────────────────────────────────────────────────
DEPARTMENTS: dict[str, str] = {
    # normalized → canonical
    "ahuachapan":   "Ahuachapán",
    "santa ana":    "Santa Ana",
    "sonsonate":    "Sonsonate",
    "chalatenango": "Chalatenango",
    "la libertad":  "La Libertad",
    "san salvador": "San Salvador",
    "cuscatlan":    "Cuscatlán",
    "la paz":       "La Paz",
    "cabanas":      "Cabañas",
    "san vicente":  "San Vicente",
    "usulutan":     "Usulután",
    "san miguel":   "San Miguel",
    "morazan":      "Morazán",
    "la union":     "La Unión",
}

# ── 262 municipalities ─────────────────────────────────────────────────
# Format: (canonical_name, department)
# Sorted by department then name.
_MUNICIPALITIES_RAW: list[tuple[str, str]] = [
    # Ahuachapán (12)
    ("Ahuachapán",              "Ahuachapán"),
    ("Apaneca",                 "Ahuachapán"),
    ("Atiquizaya",              "Ahuachapán"),
    ("Concepción de Ataco",     "Ahuachapán"),
    ("El Refugio",              "Ahuachapán"),
    ("Guaymango",               "Ahuachapán"),
    ("Jujutla",                 "Ahuachapán"),
    ("San Francisco Menéndez",  "Ahuachapán"),
    ("San Lorenzo",             "Ahuachapán"),
    ("San Pedro Puxtla",        "Ahuachapán"),
    ("Tacuba",                  "Ahuachapán"),
    ("Turín",                   "Ahuachapán"),
    # Santa Ana (13)
    ("Candelaria de la Frontera", "Santa Ana"),
    ("Chalchuapa",              "Santa Ana"),
    ("Coatepeque",              "Santa Ana"),
    ("El Congo",                "Santa Ana"),
    ("El Porvenir",             "Santa Ana"),
    ("Masahuat",                "Santa Ana"),
    ("Metapán",                 "Santa Ana"),
    ("San Antonio Pajonal",     "Santa Ana"),
    ("San Sebastián Salitrillo","Santa Ana"),
    ("Santa Ana",               "Santa Ana"),
    ("Santa Rosa Guachipilín",  "Santa Ana"),
    ("Santiago de la Frontera", "Santa Ana"),
    ("Texistepeque",            "Santa Ana"),
    # Sonsonate (16)
    ("Acajutla",                "Sonsonate"),
    ("Armenia",                 "Sonsonate"),
    ("Caluco",                  "Sonsonate"),
    ("Cuisnahuat",              "Sonsonate"),
    ("Izalco",                  "Sonsonate"),
    ("Juayúa",                  "Sonsonate"),
    ("Nahuizalco",              "Sonsonate"),
    ("Nahulingo",               "Sonsonate"),
    ("Salcoatitán",             "Sonsonate"),
    ("San Antonio del Monte",   "Sonsonate"),
    ("San Julián",              "Sonsonate"),
    ("Santa Catarina Masahuat", "Sonsonate"),
    ("Santa Isabel Ishuatán",   "Sonsonate"),
    ("Santo Domingo de Guzmán", "Sonsonate"),
    ("Sonsonate",               "Sonsonate"),
    ("Sonzacate",               "Sonsonate"),
    # Chalatenango (33)
    ("Agua Caliente",           "Chalatenango"),
    ("Arcatao",                 "Chalatenango"),
    ("Azacualpa",               "Chalatenango"),
    ("Cancasque",               "Chalatenango"),
    ("Chalatenango",            "Chalatenango"),
    ("Citalá",                  "Chalatenango"),
    ("Comalapa",                "Chalatenango"),
    ("Concepción Quezaltepeque","Chalatenango"),
    ("Dulce Nombre de María",   "Chalatenango"),
    ("El Carrizal",             "Chalatenango"),
    ("El Paraíso",              "Chalatenango"),
    ("La Laguna",               "Chalatenango"),
    ("La Palma",                "Chalatenango"),
    ("La Reina",                "Chalatenango"),
    ("Las Vueltas",             "Chalatenango"),
    ("Nombre de Jesús",         "Chalatenango"),
    ("Nueva Concepción",        "Chalatenango"),
    ("Nueva Trinidad",          "Chalatenango"),
    ("Ojos de Agua",            "Chalatenango"),
    ("Potonico",                "Chalatenango"),
    ("San Antonio de la Cruz",  "Chalatenango"),
    ("San Antonio Los Ranchos", "Chalatenango"),
    ("San Fernando",            "Chalatenango"),
    ("San Francisco Lempa",     "Chalatenango"),
    ("San Francisco Morazán",   "Chalatenango"),
    ("San Ignacio",             "Chalatenango"),
    ("San Isidro Labrador",     "Chalatenango"),
    ("San Luis del Carmen",     "Chalatenango"),
    ("San Miguel de Mercedes",  "Chalatenango"),
    ("San Rafael",              "Chalatenango"),
    ("Santa Rita",              "Chalatenango"),
    ("Tejutla",                 "Chalatenango"),
    ("Las Flores",              "Chalatenango"),  # distinct from Las Flores, La Unión
    # La Libertad (22)
    ("Antiguo Cuscatlán",       "La Libertad"),
    ("Chiltiupán",              "La Libertad"),
    ("Ciudad Arce",             "La Libertad"),
    ("Colón",                   "La Libertad"),
    ("Comasagua",               "La Libertad"),
    ("Huizúcar",                "La Libertad"),
    ("Jayaque",                 "La Libertad"),
    ("Jicalapa",                "La Libertad"),
    ("La Libertad",             "La Libertad"),
    ("Nuevo Cuscatlán",         "La Libertad"),
    ("Quezaltepeque",           "La Libertad"),
    ("Sacacoyo",                "La Libertad"),
    ("San José Villanueva",     "La Libertad"),
    ("San Juan Opico",          "La Libertad"),
    ("San Matías",              "La Libertad"),
    ("San Pablo Tacachico",     "La Libertad"),
    ("Santa Tecla",             "La Libertad"),
    ("Talnique",                "La Libertad"),
    ("Tamanique",               "La Libertad"),
    ("Teotepeque",              "La Libertad"),
    ("Tepecoyo",                "La Libertad"),
    ("Zaragoza",                "La Libertad"),
    # San Salvador (19)
    ("Aguilares",               "San Salvador"),
    ("Apopa",                   "San Salvador"),
    ("Ayutuxtepeque",           "San Salvador"),
    ("Ciudad Delgado",          "San Salvador"),
    ("Cuscatancingo",           "San Salvador"),
    ("El Paisnal",              "San Salvador"),
    ("Guazapa",                 "San Salvador"),
    ("Ilopango",                "San Salvador"),
    ("Mejicanos",               "San Salvador"),
    ("Nejapa",                  "San Salvador"),
    ("Panchimalco",             "San Salvador"),
    ("Rosario de Mora",         "San Salvador"),
    ("San Marcos",              "San Salvador"),
    ("San Martín",              "San Salvador"),
    ("San Salvador",            "San Salvador"),
    ("Santiago Texacuangos",    "San Salvador"),
    ("Santo Tomás",             "San Salvador"),
    ("Soyapango",               "San Salvador"),
    ("Tonacatepeque",           "San Salvador"),
    # Cuscatlán (16)
    ("Candelaria",              "Cuscatlán"),
    ("Cojutepeque",             "Cuscatlán"),
    ("El Carmen",               "Cuscatlán"),
    ("Monte San Juan",          "Cuscatlán"),
    ("Oratorio de Concepción",  "Cuscatlán"),
    ("San Bartolomé Perulapía", "Cuscatlán"),
    ("San Cristóbal",           "Cuscatlán"),
    ("San Dionisio",            "Cuscatlán"),
    ("San Francisco Javier",    "Cuscatlán"),
    ("San José Guayabal",       "Cuscatlán"),
    ("San Pedro Perulapán",     "Cuscatlán"),
    ("San Ramón",               "Cuscatlán"),
    ("Santa Cruz Analquito",    "Cuscatlán"),
    ("Santa Cruz Michapa",      "Cuscatlán"),
    ("Suchitoto",               "Cuscatlán"),
    ("El Rosario",              "Cuscatlán"),
    # La Paz (22)
    ("Cuyultitán",              "La Paz"),
    ("Jerusalén",               "La Paz"),
    ("Mercedes La Ceiba",       "La Paz"),
    ("Olocuilta",               "La Paz"),
    ("Paraíso de Osorio",       "La Paz"),
    ("San Antonio Masahuat",    "La Paz"),
    ("San Emigdio",             "La Paz"),
    ("San Francisco Chinameca", "La Paz"),
    ("San Juan Nonualco",       "La Paz"),
    ("San Juan Talpa",          "La Paz"),
    ("San Juan Tepezontes",     "La Paz"),
    ("San Luis La Herradura",   "La Paz"),
    ("San Luis Talpa",          "La Paz"),
    ("San Miguel Tepezontes",   "La Paz"),
    ("San Pedro Masahuat",      "La Paz"),
    ("San Pedro Nonualco",      "La Paz"),
    ("San Rafael Obrajuelo",    "La Paz"),
    ("Santa María Ostuma",      "La Paz"),
    ("Santiago Nonualco",       "La Paz"),
    ("Tapalhuaca",              "La Paz"),
    ("Zacatecoluca",            "La Paz"),
    ("El Rosario",              "La Paz"),
    # Cabañas (9)
    ("Cinquera",                "Cabañas"),
    ("Guacotecti",              "Cabañas"),
    ("Ilobasco",                "Cabañas"),
    ("Jutiapa",                 "Cabañas"),
    ("San Isidro",              "Cabañas"),
    ("Sensuntepeque",           "Cabañas"),
    ("Tejutepeque",             "Cabañas"),
    ("Victoria",                "Cabañas"),
    ("Villa Victoria",          "Cabañas"),
    # San Vicente (13)
    ("Apastepeque",             "San Vicente"),
    ("Guadalupe",               "San Vicente"),
    ("San Cayetano Istepeque",  "San Vicente"),
    ("San Esteban Catarina",    "San Vicente"),
    ("San Ildefonso",           "San Vicente"),
    ("San Lorenzo",             "San Vicente"),
    ("San Sebastián",           "San Vicente"),
    ("San Vicente",             "San Vicente"),
    ("Santa Clara",             "San Vicente"),
    ("Santo Domingo",           "San Vicente"),
    ("Tecoluca",                "San Vicente"),
    ("Tepetitán",               "San Vicente"),
    ("Verapaz",                 "San Vicente"),
    # Usulután (23)
    ("Alegría",                 "Usulután"),
    ("Berlín",                  "Usulután"),
    ("California",              "Usulután"),
    ("Concepción Batres",       "Usulután"),
    ("El Triunfo",              "Usulután"),
    ("Ereguayquín",             "Usulután"),
    ("Estanzuelas",             "Usulután"),
    ("Jiquilisco",              "Usulután"),
    ("Jucuarán",                "Usulután"),
    ("Jucuapa",                 "Usulután"),
    ("Mercedes Umaña",          "Usulután"),
    ("Nueva Granada",           "Usulután"),
    ("Ozatlán",                 "Usulután"),
    ("Puerto El Triunfo",       "Usulután"),
    ("San Agustín",             "Usulután"),
    ("San Buenaventura",        "Usulután"),
    ("San Dionisio",            "Usulután"),
    ("San Francisco Javier",    "Usulután"),
    ("Santa Elena",             "Usulután"),
    ("Santa María",             "Usulután"),
    ("Santiago de María",       "Usulután"),
    ("Tecapán",                 "Usulután"),
    ("Usulután",                "Usulután"),
    # San Miguel (20)
    ("Carolina",                "San Miguel"),
    ("Chapeltique",             "San Miguel"),
    ("Chinameca",               "San Miguel"),
    ("Chirilagua",              "San Miguel"),
    ("Ciudad Barrios",          "San Miguel"),
    ("Comacarán",               "San Miguel"),
    ("El Tránsito",             "San Miguel"),
    ("Lolotique",               "San Miguel"),
    ("Moncagua",                "San Miguel"),
    ("Nueva Guadalupe",         "San Miguel"),
    ("Nuevo Edén de San Juan",  "San Miguel"),
    ("Quelepa",                 "San Miguel"),
    ("San Antonio",             "San Miguel"),
    ("San Gerardo",             "San Miguel"),
    ("San Jorge",               "San Miguel"),
    ("San Luis de la Reina",    "San Miguel"),
    ("San Miguel",              "San Miguel"),
    ("San Rafael Oriente",      "San Miguel"),
    ("Sesori",                  "San Miguel"),
    ("Uluazapa",                "San Miguel"),
    # Morazán (26)
    ("Arambala",                "Morazán"),
    ("Cacaopera",               "Morazán"),
    ("Chilanga",                "Morazán"),
    ("Corinto",                 "Morazán"),
    ("Delicias de Concepción",  "Morazán"),
    ("El Divisadero",           "Morazán"),
    ("El Rosario",              "Morazán"),
    ("Gualococti",              "Morazán"),
    ("Guatajiagua",             "Morazán"),
    ("Joateca",                 "Morazán"),
    ("Jocoaitique",             "Morazán"),
    ("Jocoro",                  "Morazán"),
    ("Lolotiquillo",            "Morazán"),
    ("Meanguera",               "Morazán"),
    ("Osicala",                 "Morazán"),
    ("Perquín",                 "Morazán"),
    ("San Carlos",              "Morazán"),
    ("San Fernando",            "Morazán"),
    ("San Francisco Gotera",    "Morazán"),
    ("San Isidro",              "Morazán"),
    ("San Simón",               "Morazán"),
    ("Sensembra",               "Morazán"),
    ("Sociedad",                "Morazán"),
    ("Torola",                  "Morazán"),
    ("Yamabal",                 "Morazán"),
    ("Yoloaiquín",              "Morazán"),
    # La Unión (18)
    ("Anamorós",                "La Unión"),
    ("Bolívar",                 "La Unión"),
    ("Concepción de Oriente",   "La Unión"),
    ("Conchagua",               "La Unión"),
    ("El Carmen",               "La Unión"),
    ("El Sauce",                "La Unión"),
    ("Intipucá",                "La Unión"),
    ("La Unión",                "La Unión"),
    ("Lislique",                "La Unión"),
    ("Meanguera del Golfo",     "La Unión"),
    ("Nueva Esparta",           "La Unión"),
    ("Pasaquina",               "La Unión"),
    ("Polorós",                 "La Unión"),
    ("San Alejo",               "La Unión"),
    ("San José Las Fuentes",    "La Unión"),
    ("Santa Rosa de Lima",      "La Unión"),
    ("Yayantique",              "La Unión"),
    ("Yucuaiquín",              "La Unión"),
]

# ── Tourist / coastal localities (not municipalities) ──────────────────
# zone_slug maps to the existing ZONE_PATTERNS slug where applicable.
_TOURIST_RAW: list[dict] = [
    {"name": "El Tunco",            "slug": "el-tunco",           "municipality": "Tamanique",        "department": "La Libertad",
     "extra_variants": ["tunco", "playa el tunco", "playa tunco"]},
    {"name": "El Sunzal",           "slug": "el-sunzal",          "municipality": "Tamanique",        "department": "La Libertad",
     "extra_variants": ["sunzal", "playa el sunzal"]},
    {"name": "El Zonte",            "slug": "el-zonte",           "municipality": "Chiltiupán",       "department": "La Libertad",
     "extra_variants": ["zonte", "playa el zonte", "playa zonte"]},
    {"name": "San Diego",           "slug": "san-diego",          "municipality": "La Libertad",      "department": "La Libertad",
     "extra_variants": ["playa san diego", "km 59", "k59", "km59"]},
    {"name": "Mizata",              "slug": "mizata",             "municipality": "Teotepeque",       "department": "La Libertad",
     "extra_variants": ["playa mizata"]},
    {"name": "Las Flores",          "slug": "las-flores",         "municipality": "Intipucá",         "department": "La Unión",
     "extra_variants": ["playa las flores", "playa la flores"]},
    {"name": "El Espino",           "slug": "el-espino",          "municipality": "Jucuarán",         "department": "Usulután",
     "extra_variants": ["playa espino", "playa el espino"]},
    {"name": "Punta Mango",         "slug": "punta-mango",        "municipality": "Intipucá",         "department": "La Unión",
     "extra_variants": ["puntamango"]},
    {"name": "El Cuco",             "slug": "el-cuco",            "municipality": "Chirilagua",       "department": "San Miguel",
     "extra_variants": ["playa el cuco", "playa cuco"]},
    {"name": "Conchagua",           "slug": "conchagua",          "municipality": "Conchagua",        "department": "La Unión",
     "extra_variants": ["playa el tamarindo", "tamarindo"]},
    {"name": "Jiquilisco",          "slug": "jiquilisco",         "municipality": "Jiquilisco",       "department": "Usulután",
     "extra_variants": ["bahia de jiquilisco", "bahia jiquilisco", "playa jiquilisco"]},
    {"name": "Costa del Sol",       "slug": "costa-del-sol",      "municipality": "San Luis La Herradura", "department": "La Paz",
     "extra_variants": ["costadelsol", "costa sol", "playa costa del sol"]},
    {"name": "Apaneca",             "slug": "apaneca",            "municipality": "Apaneca",          "department": "Ahuachapán",
     "extra_variants": []},
    {"name": "Planes de Renderos",  "slug": "planes-de-renderos", "municipality": "Panchimalco",      "department": "San Salvador",
     "extra_variants": ["renderos", "planes renderos"]},
    {"name": "Suchitoto",           "slug": "suchitoto",          "municipality": "Suchitoto",        "department": "Cuscatlán",
     "extra_variants": []},
    {"name": "Concepción de Ataco", "slug": "ataco",              "municipality": "Concepción de Ataco", "department": "Ahuachapán",
     "extra_variants": ["ataco", "pueblo ataco"]},
    {"name": "Juayúa",              "slug": "juayua",             "municipality": "Juayúa",           "department": "Sonsonate",
     "extra_variants": ["juayua"]},
    {"name": "Nahuizalco",          "slug": "nahuizalco",         "municipality": "Nahuizalco",       "department": "Sonsonate",
     "extra_variants": []},
    {"name": "Santa Ana",           "slug": "santa-ana",          "municipality": "Santa Ana",        "department": "Santa Ana",
     "extra_variants": ["santaana"]},
    {"name": "Metapán",             "slug": "metapan",            "municipality": "Metapán",          "department": "Santa Ana",
     "extra_variants": ["metapan"]},
    {"name": "Chalchuapa",          "slug": "chalchuapa",         "municipality": "Chalchuapa",       "department": "Santa Ana",
     "extra_variants": ["chalchupa", "chalchuapa"]},
    {"name": "Santa Tecla",         "slug": "santa-tecla",        "municipality": "Santa Tecla",      "department": "La Libertad",
     "extra_variants": ["nueva san salvador", "n.s.s."]},
    {"name": "San José Villanueva", "slug": "san-jose-villanueva","municipality": "San José Villanueva","department": "La Libertad",
     "extra_variants": ["san jose villanueva", "sanjose villanueva"]},
    {"name": "La Palma",            "slug": "la-palma",           "municipality": "La Palma",         "department": "Chalatenango",
     "extra_variants": []},
    {"name": "Tacuba",              "slug": "tacuba",             "municipality": "Tacuba",           "department": "Ahuachapán",
     "extra_variants": []},
    # Lake destinations (added 2026-05-08). Coatepeque + Ilopango are
    # vacation-property zones distinct from their namesake municipalities
    # (especially Ilopango, where the airport district is a separate
    # real-estate market). Variants list "lago" prefixes so a listing
    # text like "frente al lago de coatepeque" snaps cleanly.
    {"name": "Lago de Coatepeque",  "slug": "lago-coatepeque",    "municipality": "El Congo",         "department": "Santa Ana",
     "extra_variants": ["lago coatepeque", "lago de coatepeque", "playa coatepeque",
                        "lake coatepeque", "lake of coatepeque"]},
    {"name": "Lago de Ilopango",    "slug": "lago-ilopango",      "municipality": "Ilopango",         "department": "San Salvador",
     "extra_variants": ["lago ilopango", "lago de ilopango", "lago el ilopango",
                        "lake ilopango", "lake of ilopango"]},
]

# ── Pre-compiled lookup tables ─────────────────────────────────────────
# Built once at import time.

# Department lookup: normalized → canonical
DEPT_LOOKUP: dict[str, str] = dict(DEPARTMENTS)

# Municipality lookup: normalized → (canonical, department)
MUNI_LOOKUP: dict[str, tuple[str, str]] = {}
for _name, _dept in _MUNICIPALITIES_RAW:
    _key = _norm(_name)
    # Don't overwrite a more-specific entry (e.g. "San Francisco Morazán" vs "San Francisco Javier")
    if _key not in MUNI_LOOKUP:
        MUNI_LOOKUP[_key] = (_name, _dept)

# Tourist lookup: normalized variant → {"name", "slug", "municipality", "department"}
TOURIST_LOOKUP: dict[str, dict] = {}
for _t in _TOURIST_RAW:
    # canonical name
    TOURIST_LOOKUP[_norm(_t["name"])] = _t
    # extra variants
    for _v in _t.get("extra_variants", []):
        _vk = _norm(_v)
        if _vk not in TOURIST_LOOKUP:
            TOURIST_LOOKUP[_vk] = _t


def lookup_locality(text: str) -> Optional[tuple[str, str, str, str]]:
    """Look up a locality string. Returns (slug, municipality, department, confidence)
    or None if not found.

    confidence: 'specific' (tourist/zone level) | 'municipality' | 'department'
    """
    key = _norm(text)
    if not key:
        return None

    # Tourist localities first (most specific)
    if key in TOURIST_LOOKUP:
        t = TOURIST_LOOKUP[key]
        return (t["slug"], t["municipality"], t["department"], "specific")

    # Municipality
    if key in MUNI_LOOKUP:
        name, dept = MUNI_LOOKUP[key]
        slug = key.replace(" ", "-")
        return (slug, name, dept, "municipality")

    # Department
    if key in DEPT_LOOKUP:
        return (None, None, DEPT_LOOKUP[key], "department")

    return None


def parse_location_text(location_text: str) -> Optional[tuple[str, str, str, str]]:
    """Parse a structured location_text field.

    Brokers format this as comma-separated: "SubLoc, Municipality, Department, El Salvador"
    or "Municipality, Department, El Salvador" or just "Department, El Salvador".

    Returns (zone_slug, municipality, department, confidence) or None.
    """
    if not location_text:
        return None

    # Split and strip
    parts = [p.strip() for p in location_text.split(",")]
    # Drop "El Salvador", empty strings, and obvious non-location phrases
    _NOISE = {"el salvador", "sv", "", "el salvador c.a."}
    parts = [p for p in parts if _norm(p) not in _NOISE]

    if not parts:
        return None

    # Try each part from the end (department is usually last)
    dept_canon: Optional[str] = None
    dept_idx: int = -1
    for i in range(len(parts) - 1, -1, -1):
        key = _norm(parts[i])
        if key in DEPT_LOOKUP:
            dept_canon = DEPT_LOOKUP[key]
            dept_idx = i
            break

    if dept_canon is None:
        # No department found — try resolving each part as a locality
        for part in reversed(parts):
            result = lookup_locality(part)
            if result:
                return result
        return None

    # Department found — the part just before it is the municipality
    muni_str: Optional[str] = None
    if dept_idx > 0:
        muni_str = parts[dept_idx - 1].strip()

    if muni_str:
        muni_key = _norm(muni_str)
        # Try tourist first
        if muni_key in TOURIST_LOOKUP:
            t = TOURIST_LOOKUP[muni_key]
            return (t["slug"], t["municipality"], dept_canon, "specific")
        # Then municipality table
        if muni_key in MUNI_LOOKUP:
            muni_canon, _ = MUNI_LOOKUP[muni_key]
            slug = muni_key.replace(" ", "-")
            return (slug, muni_canon, dept_canon, "municipality")
        # Municipality not in table but we have the department
        return (None, muni_str.title(), dept_canon, "municipality")

    return (None, None, dept_canon, "department")

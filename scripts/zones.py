"""
Zone group definitions — single source of truth for the frontend filter UI.

The frontend reads these at "build time" (they're baked into web/index.html as a
JS constant by referencing this file as the authoritative list).

"No zone" is a SYNTHETIC group — it is NOT stored here.  It is computed at render
time from listings where `zone` is null/empty (i.e., zone could not be resolved
to any specific locality).  See web/index.html comments for how the frontend
handles it.

Membership decisions:
  - Surf City 1 / Surf City 2 boundary: the El Salvador Tourism Board markets
    La Libertad's surf beaches as "Surf City" collectively.  We split at the
    department boundary:  La Libertad west → SC1, eastern coast (San Miguel /
    La Unión) → SC2.  Source: Plan Nacional de Turismo 2023 "Surf City El Salvador".
  - Conchagua is in La Unión department, eastern coast.  It is sometimes listed
    as "Surf City 2" in tourism marketing because it's on the Gulf of Fonseca
    surf corridor (Bitcoin City axis).  Included in Surf City 2 for that reason.
    Flag for human review if this seems wrong.
  - la-libertad (zone slug) represents listings resolved only to the La Libertad
    department/municipality level — not to a specific tourist zone.  It is
    grouped under "Other coastal" because La Libertad is primarily a coastal
    department.  After zone resolution re-runs in production, most of these
    will resolve more specifically.
  - Municipality-level zones that appear after zone resolution (soyapango,
    tonacatepeque, acajutla, etc.) are grouped under "Inland" if the municipality
    is inland, or "Other coastal" if coastal.  Zones not explicitly listed
    fall through to "All zones" display with a hash-based color.
"""

ZONE_GROUPS: dict[str, dict] = {
    "surf-city-1": {
        "label": "Surf City 1",
        "zones": [
            "el-tunco",
            "el-sunzal",
            "el-zonte",
            "san-diego",
            "mizata",
        ],
    },
    "surf-city-2": {
        "label": "Surf City 2",
        "zones": [
            "el-cuco",
            "las-flores",
            "punta-mango",
            "el-espino",
            "conchagua",  # Gulf of Fonseca; see header comment
        ],
    },
    "other-coastal": {
        "label": "Other coastal",
        "zones": [
            "la-libertad",         # dept-level fallback for La Libertad listings
            "puerto-la-libertad",
            "jiquilisco",          # Bahía de Jiquilisco, Usulután
            "tamanique",           # La Libertad municipality
            "acajutla",            # Sonsonate coast
            "costa-del-sol",       # La Paz coast
            "san-luis-la-herradura",
        ],
    },
    "inland": {
        "label": "Inland",
        "zones": [
            "la-union",            # La Unión department (city)
            "san-salvador",        # San Salvador dept
            "ahuachapan",          # Ahuachapán dept
            "santa-ana",           # Santa Ana dept / municipality
            "sonsonate",           # Sonsonate dept / municipality
            "chalatenango",        # Chalatenango dept
            "la-paz",              # La Paz dept
            "tonacatepeque",       # San Salvador municipality
            "soyapango",           # San Salvador municipality
            "mejicanos",           # San Salvador municipality
            "nejapa",              # San Salvador municipality
            "apopa",               # San Salvador municipality
            "san-martin",          # San Salvador municipality
            "ilopango",            # San Salvador municipality
            "zacatecoluca",        # La Paz municipality
            "olocuilta",           # La Paz municipality
            "nueva-concepcion",    # Chalatenango municipality
            "cojutepeque",         # Cuscatlán municipality
            "suchitoto",           # Cuscatlán municipality
            "chalchuapa",          # Santa Ana municipality
            "santa-tecla",         # La Libertad municipality (inland)
            "izalco",              # Sonsonate municipality
            "armenia",             # Sonsonate municipality
            "ataco",               # Ahuachapán (Concepción de Ataco)
            "apaneca",             # Ahuachapán municipality
            "tacuba",              # Ahuachapán municipality
            "juayua",              # Sonsonate municipality
            "san-jose-villanueva", # La Libertad municipality
            "nahuizalco",          # Sonsonate municipality
            "acajutla",            # already in other-coastal; listed for completeness
            "tejutla",             # Chalatenango municipality
            "sesori",              # San Miguel municipality
            "usulutan",            # Usulután dept
            "san-miguel",          # San Miguel dept
        ],
    },
}

# Ordered list of group keys for the UI (bottom = "No zone" added by frontend)
ZONE_GROUP_ORDER = ["surf-city-1", "surf-city-2", "other-coastal", "inland"]

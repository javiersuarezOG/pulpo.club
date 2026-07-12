"""ig_campaign.py — "Tu pedazo de paraíso" campaign plan + queue builder.

The bilingual (🇸🇻 ES / 🇺🇸 EN) 14-post campaign Sebastian approved on
2026-07-10.  This module is the source of truth for the plan and turns a
day's spec into a real ig_queue.json item: it renders the 3 carousel
slides (via ig_campaign_poster) and assembles the bilingual caption +
first comment the publisher will post.

The full 14-post plan (days 201–214) is transcribed below from the
approved review board — one post per day, 2026-07-11 → 2026-07-24.  Seven
inspiration/wrap posts are design-only (solid-color cards); six Top-10
posts (days 202/204/206/208/210/212) use real, hand-inspected listing
photos already vetted for broker logos/watermarks (the source frames live
under ``web/data/ig_assets/campaign/_src/``).  Because every carousel
photo here was inspected by hand, this campaign does not depend on the
automated photo-gate being extended to homes/condos — that extension is
still the right productionized path for *future* auto-generated Top-10
posts, but is not a blocker for shipping this fixed, approved run.

The publisher picks the next due, approved item, so posts go live in
schedule order without further edits.  Re-running ``patch_queue`` for any
day is idempotent.

Bilingual on the wire: Instagram captions are one text field, so we join
ES then EN with a thin divider.  The caption keeps ``**bold**`` markers —
the admin preview renders them and ig_publish._caption_for_ig strips them
before the Graph API call.

CLI:

    python3 -m automation.ig_campaign --day 201 --render          # render PNGs only
    python3 -m automation.ig_campaign --day 201 --render --apply  # + patch ig_queue.json
    python3 -m automation.ig_campaign --all --render --apply      # build every day
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation._atomic import atomic_write_text
from automation.ig_campaign_poster import CATEGORY_COLORS, render_slide

QUEUE_PATH = Path("web/data/ig_queue.json")
ASSETS_ROOT = Path("web/data/ig_assets/campaign")

# Bilingual wire divider (ES ⁄ EN) — a thin, neutral separator.
DIV = "\n\n· · ·\n\n"


def _bilingual(es: str, en: str, tail: str = "") -> str:
    out = f"{es}{DIV}{en}"
    if tail:
        out = f"{out}\n\n{tail}"
    return out


# ── the plan ───────────────────────────────────────────────────────────
# Each post: day id, ISO schedule, category color key, ribbon label, the
# 3 slide specs (see ig_campaign_poster for slide types), and bilingual
# caption/comment/hashtags.  Day 1 is fully live below.

PLAN: list[dict] = [{'day': 201,
  'slug': 'd01_escasez',
  'kind': 'inspira',
  'color_key': 'insp_violet',
  'scheduled_for': '2026-07-11T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': 'El Salvador',  # multi-country-exempt: hand-written SV marketing copy (Sebas-approved campaign)
              'l1': 'La costa',
              'l2': 'no crece.',
              'punch': 'Pero la fila sí.'},
             {'t': 'stat',
              'big': '139',
              'label': 'de 1,916 propiedades a la venta\nestán de verdad frente al mar',
              'src': 'Datos Pulpo · jul 2026'},
             {'t': 'usp',
              'eyebrow': 'Cómo ayuda Pulpo',
              'title': 'Las tenemos todas.',
              'body': 'Rankeadas por valor, en un solo lugar. Vos escogés sin perder tiempo.'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L201.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'star': True,
              'badge': 'La Libertad · $195,000',
              'color_key': 'terrenos_playa'}],
  'capES': '**La tierra frente al mar no se fabrica. Y ya casi no queda.**\n'
           '\n'
           'De cada 1,916 propiedades a la venta en El Salvador, solo 139 están de verdad frente al mar. Menos '
           'del 8%.\n'
           '\n'
           'En Pulpo las tenemos todas juntas y rankeadas, para que veás las mejores sin revisar mil sitios.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': "**Oceanfront land isn't being made — and there's barely any left.**\n"
           '\n'
           'Of the 1,916 properties for sale in El Salvador, only 139 are truly oceanfront. Under 8%.\n'
           '\n'
           'At Pulpo we keep them all in one place, ranked, so you see the best without digging through a '
           'dozen sites.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Comparamos cada propiedad por precio, zona y acceso, y te mostramos solo las mejores.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo.\n'
           '\n'
           'pulpo.club',
  'comEN': 'We compare every property by price, location, and access, and show you only the best.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday.\n'
           '\n'
           'pulpo.club',
  'tags': '#ElSalvador #BienesRaices #FrenteAlMar #SurfCity #Terrenos #PlayasDeElSalvador #TuPedazoDeParaiso',
  'primary_listing_id': 'citymax_sc_terreno-residencial-en-venta-isla-san-blas',
  'listing_ids': ['citymax_sc_terreno-residencial-en-venta-isla-san-blas']},
 {'day': 202,
  'slug': 'd02_casas_playa',
  'kind': 'top10',
  'color_key': 'casas_playa',
  'scheduled_for': '2026-07-12T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH1a.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'Cerromar, El Sunzal · $975,000'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH1b.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'badge': 'Cocina abierta · vista al mar'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH1c.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'badge': 'Ver el Top 10 → pulpo.club'}],
  'capES': '**Casas de Playa · #1 — Cerromar, El Sunzal.**\n'
           '\n'
           'Casa moderna de 3 niveles en comunidad privada: piscina infinita, cocina abierta y el Pacífico de '
           'horizonte. A minutos de las mejores olas de Surf City, lista para entrar.\n'
           '\n'
           'Por qué está en el #1: la comparamos con las otras 175 casas de playa y gana en precio, zona y '
           'acceso.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Beach Homes · #1 — Cerromar, El Sunzal.**\n'
           '\n'
           'A modern three-story home in a gated community: infinity pool, open kitchen, the Pacific on the '
           "horizon. Minutes from Surf City's best waves, move-in ready.\n"
           '\n'
           "Why it's #1: we compared it against the other 175 beach homes and it wins on price, location, and "
           'access.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Casas de Playa 🏖️**\n'
           '1. Cerromar, El Sunzal — piscina infinita, vista al mar · $975,000\n'
           '2. El Sunzal — frente al mar · $900,000\n'
           '3. El Palmarcito, El Tunco — nueva, estrenala · $115,000\n'
           '4. El Zonte — vista panorámica · $350,000\n'
           '5. Costa del Sol — rancho frente al mar · $680,000\n'
           '…y 5 más.\n'
           '\n'
           'Solo 176 casas de playa en todo el país. Rankeadas. El Top 10 en tu correo cada domingo 👉 '
           'pulpo.club',
  'comEN': '**Top 10 Beach Homes 🏖️**\n'
           '1. Cerromar, El Sunzal — infinity pool, ocean view · $975,000\n'
           '2. El Sunzal — oceanfront · $900,000\n'
           '3. El Palmarcito, El Tunco — brand new · $115,000\n'
           '4. El Zonte — panoramic view · $350,000\n'
           '5. Costa del Sol — beachfront ranch · $680,000\n'
           '…and 5 more.\n'
           '\n'
           'Only 176 beach homes in the whole country. Ranked. The Top 10 in your inbox every Sunday 👉 '
           'pulpo.club',
  'tags': '#CasasDePlaya #BeachHomes #ElSunzal #SurfCity #ElSalvador #BienesRaices',
  'primary_listing_id': 'goodlife_new-ocean-view-home-in-gated-community-cerromar-el-sunzal',
  'listing_ids': ['goodlife_new-ocean-view-home-in-gated-community-cerromar-el-sunzal']},
 {'day': 203,
  'slug': 'd03_como_funciona',
  'kind': 'inspira',
  'color_key': 'insp_indigo',
  'scheduled_for': '2026-07-13T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': 'La vieja forma',
              'l1': '20 pestañas',
              'l2': 'abiertas.',
              'punch': 'Buscando la misma casa.'},
             {'t': 'compare',
              'eyebrow': 'Antes → Ahora',
              'bad': 'Encuentra24, ReMax, grupos de Face, el cuñado que “conoce a alguien”…',
              'good': 'Pulpo: todas juntas y rankeadas.',
              'note': 'Todas las propiedades de El Salvador, en un solo lugar.'},
             {'t': 'cta', 'big': '1 solo\nlugar', 'sub': 'pulpo.club · link en bio'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L203.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'El Tunco · $350,000',
              'color_key': 'casas_playa'}],
  'capES': '**Dejá de revisar 20 sitios para encontrar tu terreno.**\n'
           '\n'
           'Encuentra24, ReMax, grupos de Facebook, el conocido que “vende barato”… agotador.\n'
           '\n'
           'Pulpo junta TODAS las propiedades de El Salvador en un solo lugar y las ordena de mejor a peor. '
           'Vos abrís una sola página y ves lo mejor.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Stop checking 20 sites to find your land.**\n'
           '\n'
           'Encuentra24, ReMax, Facebook groups, the guy who “sells cheap”… exhausting.\n'
           '\n'
           'Pulpo pulls EVERY property in El Salvador into one place and ranks them best to worst. You open '
           'one page and see the best.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Una sola página, todo el mercado, rankeado por valor.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo.\n'
           '\n'
           'pulpo.club',
  'comEN': 'One page, the whole market, ranked by value.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday.\n'
           '\n'
           'pulpo.club',
  'tags': '#ElSalvador #BienesRaices #Terrenos #PulpoClub #SurfCity #TuPedazoDeParaiso',
  'primary_listing_id': 'oceanside_15561',
  'listing_ids': ['oceanside_15561']},
 {'day': 204,
  'slug': 'd04_terrenos_playa',
  'kind': 'top10',
  'color_key': 'terrenos_playa',
  'scheduled_for': '2026-07-14T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BP1a.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'star': True,
              'badge': 'El Tunco · vista al mar · $225,000'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BP1b.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'badge': '1,581 m² · $142/m²'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BP1c.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'badge': 'Ver el Top 10 → pulpo.club'}],
  'capES': '**Terrenos de Playa · #1 — El Tunco, vista al mar.**\n'
           '\n'
           '1,581 m² con el Pacífico de frente, a pasos de las olas de El Tunco. Plano, listo para tu casa — o '
           'para cuidarlo mientras Surf City sigue creciendo.\n'
           '\n'
           'Por qué está de primero: lo comparamos con 500 terrenos de playa y este gana en vista, precio y '
           'acceso.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Beach Land · #1 — El Tunco, ocean view.**\n'
           '\n'
           "1,581 m² facing the Pacific, steps from El Tunco's waves. Flat, ready for your house — or hold it "
           'while Surf City keeps growing.\n'
           '\n'
           "Why it's first: we compared it to 500 beach lots and it wins on view, price, and access.\n"
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Terrenos de Playa 🌊**\n'
           '1. El Tunco — vista al mar, 1,581 m² · $225,000\n'
           '2. Tamanique — vista al mar · $150,000 · $71/m²\n'
           '3. Julupe, El Zonte — acantilado, 1 mz · $450,000\n'
           '4. El Zonte — 11,000 v² vista al mar · $500,000\n'
           '5. Atami, Surf City · $148,000\n'
           '…y 5 más.\n'
           '\n'
           '501 terrenos de playa comparados. Rankeadas. El Top 10 en tu correo cada domingo 👉 pulpo.club',
  'comEN': '**Top 10 Beach Land 🌊**\n'
           '1. El Tunco — ocean view, 1,581 m² · $225,000\n'
           '2. Tamanique — ocean view · $150,000 · $71/m²\n'
           '3. Julupe, El Zonte — clifftop, 1 mz · $450,000\n'
           '4. El Zonte — 11,000 v² ocean view · $500,000\n'
           '5. Atami, Surf City · $148,000\n'
           '…and 5 more.\n'
           '\n'
           '501 beach lots compared. Ranked. The Top 10 in your inbox every Sunday 👉 pulpo.club',
  'tags': '#TerrenosDePlaya #BeachLand #ElTunco #SurfCity #ElSalvador #BienesRaices',
  'primary_listing_id': 'bienesraices_1529',
  'listing_ids': ['bienesraices_1529']},
 {'day': 205,
  'slug': 'd05_descubrimiento',
  'kind': 'inspira',
  'color_key': 'insp_blue',
  'scheduled_for': '2026-07-15T01:00:00+00:00',
  'slides': [{'t': 'stat',
              'big': '3.9M',
              'label': 'visitantes en 2024 — récord.\nEl mundo descubrió El Salvador.',
              'src': 'Visit El Salvador · 2024'},
             {'t': 'usp',
              'eyebrow': 'Lo que significa',
              'title': 'Más ojos, más valor.',
              'body': 'Cuando el mundo descubre un lugar, la buena tierra frente al mar se vuelve escasa.'},
             {'t': 'usp',
              'eyebrow': 'Tu ventaja',
              'title': 'Llegá primero.',
              'body': 'La diáspora y los de afuera ya están comprando. En Pulpo ves lo mejor antes que la fila '
                      'crezca.'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L205.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'La Libertad · $325,000',
              'color_key': 'casas_playa'}],
  'capES': '**El mundo entero está descubriendo El Salvador — 3.9 millones de visitantes en 2024, un '
           'récord.**\n'
           '\n'
           'Cuando un lugar así se pone de moda, la buena tierra frente al mar se vuelve escasa. Vos naciste '
           'aquí: llegás primero.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**The whole world is discovering El Salvador — a record 3.9 million visitors in 2024.**\n'
           '\n'
           'When a place takes off like this, good oceanfront land gets scarce. You were born here — you '
           'arrive first.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Nosotros juntamos todo el mercado y lo rankeamos, para que llegués primero a lo mejor.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo.\n'
           '\n'
           'pulpo.club',
  'comEN': 'We gather the whole market and rank it, so you get to the best first.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday.\n'
           '\n'
           'pulpo.club',
  'tags': '#ElSalvador #SurfCity #TuPedazoDeParaiso #PlayasDeElSalvador #SalvadorenosPorElMundo #BienesRaices',
  'primary_listing_id': 'citymax_sc_casa-en-venta-residencial-san-carlos-sonzacate',
  'listing_ids': ['citymax_sc_casa-en-venta-residencial-san-carlos-sonzacate']},
 {'day': 206,
  'slug': 'd06_casas_lago',
  'kind': 'top10',
  'color_key': 'casas_lago',
  'scheduled_for': '2026-07-16T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LH1a.jpg',
              'ribbon': 'CASAS DE LAGO',
              'star': True,
              'badge': 'Coatepeque · frente al lago · $1,000,000'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LH1c.jpg',
              'ribbon': 'CASAS DE LAGO',
              'badge': 'Jardín tropical hasta la orilla'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LH1b.jpg',
              'ribbon': 'CASAS DE LAGO',
              'badge': 'Ver el Top 10 → pulpo.club'}],
  'capES': '**Casas de Lago · #1 — Coatepeque, frente al agua.**\n'
           '\n'
           'Muelle propio sobre el agua más azul del país, jardín tropical que baja hasta la orilla, y las '
           'montañas de fondo. Los fines de semana en familia que no se olvidan.\n'
           '\n'
           'En todo el mercado existen solo 12 casas frente al lago — esta es la #1.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Lake Homes · #1 — Coatepeque, on the water.**\n'
           '\n'
           "A private dock over the country's bluest water, a tropical garden down to the shore, mountains "
           'behind. The family weekends you never forget.\n'
           '\n'
           'In the entire market there are only 12 lakefront homes — this is #1.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Casas frente al Lago 🌋💧**\n'
           '1. Coatepeque — muelle propio, jardín a la orilla · $1,000,000\n'
           '2. Coatepeque — 40 m de orilla · $590,000\n'
           '3. Frente al lago, 6 cuartos · $650,000\n'
           '4. 1,874 m² · $990,000\n'
           '…y más.\n'
           '\n'
           'Solo 12 casas de lago en todo el país. Rankeadas. El Top 10 en tu correo cada domingo 👉 pulpo.club',
  'comEN': '**Top 10 Lakefront Homes 🌋💧**\n'
           '1. Coatepeque — private dock, garden to the shore · $1,000,000\n'
           '2. Coatepeque — 40 m shoreline · $590,000\n'
           '3. Lakefront, 6 bd · $650,000\n'
           '4. 1,874 m² · $990,000\n'
           '…and more.\n'
           '\n'
           'Only 12 lake homes in the whole country. Ranked. The Top 10 in your inbox every Sunday 👉 '
           'pulpo.club',
  'tags': '#CasasDeLago #LagoDeCoatepeque #Coatepeque #ElSalvador #BienesRaices',
  'primary_listing_id': 'encuentra24_32059471',
  'listing_ids': ['encuentra24_32059471']},
 {'day': 207,
  'slug': 'd07_por_que_rankeado',
  'kind': 'inspira',
  'color_key': 'insp_cyan',
  'scheduled_for': '2026-07-17T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': 'No te mostramos todo.',
              'l1': 'Te mostramos',
              'l2': 'lo mejor.',
              'punch': 'Esa es la diferencia.'},
             {'t': 'usp',
              'eyebrow': 'Cómo rankeamos',
              'title': 'Precio · zona · acceso',
              'body': 'Comparamos cada propiedad del país con las demás de su tipo. Solo las mejores suben al '
                      'Top 10.'},
             {'t': 'cta', 'big': 'Sin perder\ntiempo', 'sub': 'en las malas · pulpo.club'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L207.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'star': True,
              'badge': 'Las Flores · $299,000',
              'color_key': 'terrenos_playa'}],
  'capES': '**No perdás tiempo viendo terrenos malos.**\n'
           '\n'
           'Pulpo compara cada propiedad de El Salvador —precio, zona, acceso, distancia al mar— contra las de '
           'su tipo, y solo sube las mejores.\n'
           '\n'
           'Cuando entrás, ya está filtrado: lo que ves, vale la pena. Así invertís tu tiempo solo en las '
           'mejores oportunidades.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Stop wasting time on bad lots.**\n'
           '\n'
           'Pulpo compares every property in El Salvador —price, location, access, distance to the water— '
           'against others of its kind, and only surfaces the best.\n'
           '\n'
           "By the time you arrive, it's filtered: what you see is worth it. So you spend your time only on "
           'the best opportunities.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Rankeadas por valor. El Top 10 en tu correo cada domingo, gratis.\n\npulpo.club',
  'comEN': 'Ranked by value. The Top 10 in your inbox every Sunday, free.\n\npulpo.club',
  'tags': '#ElSalvador #BienesRaices #PulpoClub #RankeadoPorValor #Terrenos #SurfCity',
  'primary_listing_id': 'oceanside_12809',
  'listing_ids': ['oceanside_12809']},
 {'day': 208,
  'slug': 'd08_apartamentos',
  'kind': 'top10',
  'color_key': 'apartamentos',
  'scheduled_for': '2026-07-18T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/AP1a.jpg',
              'ribbon': 'APARTAMENTOS',
              'star': True,
              'badge': 'Zonset, El Zonte · $445,694'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/AP1b.jpg',
              'ribbon': 'APARTAMENTOS',
              'badge': '2 cuartos · a pasos del mar'},
             {'t': 'detail',
              'eyebrow': 'Nuestra destacada',
              'price': '$445,694',
              'facts': '2 cuartos · piscina · playa a pasos',
              'loc': 'El Zonte · Bitcoin Beach'}],
  'capES': '**Apartamentos · #1 — Zonset, El Zonte.**\n'
           '\n'
           'Torre moderna en el corazón de Bitcoin Beach: 2 cuartos, piscina, y la playa a pasos. Cero '
           'mantenimiento de jardín — cerrás y te vas.\n'
           '\n'
           'Para tener El Zonte sin complicarte. Solo 29 apartamentos frente al mar en todo el país.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Apartments · #1 — Zonset, El Zonte.**\n'
           '\n'
           'A modern tower in the heart of Bitcoin Beach: 2 bedrooms, pool, the beach steps away. No yard to '
           'maintain — lock up and go.\n'
           '\n'
           'El Zonte without the hassle. Only 29 oceanfront apartments in the whole country.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Apartamentos frente al mar 🏝️**\n'
           '1. Zonset, El Zonte — 2 cuartos, piscina · $445,694\n'
           '2. Surf City, La Libertad — 3 cuartos, frente al mar · $538,020\n'
           '3. Loft El Encuentro — vista al océano · $326,500\n'
           '4. Costa del Sol — con piscina · $320,000\n'
           '…y más.\n'
           '\n'
           'Solo 29 apartamentos frente al mar. Rankeadas. El Top 10 en tu correo cada domingo 👉 pulpo.club',
  'comEN': '**Top 10 Oceanfront Apartments 🏝️**\n'
           '1. Zonset, El Zonte — 2 bd, pool · $445,694\n'
           '2. Surf City, La Libertad — 3 bd, oceanfront · $538,020\n'
           '3. El Encuentro Loft — ocean view · $326,500\n'
           '4. Costa del Sol — with pool · $320,000\n'
           '…and more.\n'
           '\n'
           'Only 29 oceanfront apartments. Ranked. The Top 10 in your inbox every Sunday 👉 pulpo.club',
  'tags': '#Apartamentos #ElZonte #BitcoinBeach #SurfCity #ElSalvador #BienesRaices',
  'primary_listing_id': 'goodlife_2-bed-condominium-at-zonset-el-zonte-445694',
  'listing_ids': ['goodlife_2-bed-condominium-at-zonset-el-zonte-445694']},
 {'day': 209,
  'slug': 'd09_demanda',
  'kind': 'inspira',
  'color_key': 'insp_teal',
  'scheduled_for': '2026-07-19T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': '2021 → hoy',
              'l1': 'El mundo',
              'l2': 'llegó.',
              'punch': 'Vos ya estabas aquí.'},
             {'t': 'stat',
              'big': 'Surf\nCity',
              'label': 'puso nuestras olas\nen el mapa del mundo',
              'src': None},
             {'t': 'usp',
              'eyebrow': 'Tu ventaja',
              'title': 'Llegá primero.',
              'body': 'Todo el mercado, rankeado, en un solo lugar. Lo bueno se vende de primero.'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L209.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'El Tunco · $755,000',
              'color_key': 'casas_playa'}],
  'capES': '**El mundo descubrió El Salvador. Vos naciste aquí.**\n'
           '\n'
           'Surf City puso nuestras playas en el mapa: gente de Estados Unidos, de Europa, y hermanos que se '
           'fueron, todos buscando su pedazo.\n'
           '\n'
           'Lo bueno se vende primero. Con Pulpo lo ves antes que la fila crezca.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**The world discovered El Salvador. You were born here.**\n'
           '\n'
           'Surf City put our beaches on the map: people from the U.S., from Europe, and family who left, all '
           'after their piece.\n'
           '\n'
           'The good ones sell first. With Pulpo you see them before the line grows.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Todas las propiedades del país, comparadas y rankeadas.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo.\n'
           '\n'
           'pulpo.club',
  'comEN': 'Every property in the country, compared and ranked.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday.\n'
           '\n'
           'pulpo.club',
  'tags': '#ElSalvador #SurfCity #SalvadorenosPorElMundo #BitcoinCountry #BienesRaices #TuPedazoDeParaiso',
  'primary_listing_id': 'oceanside_12288',
  'listing_ids': ['oceanside_12288']},
 {'day': 210,
  'slug': 'd10_terrenos_lago',
  'kind': 'top10',
  'color_key': 'terrenos_lago',
  'scheduled_for': '2026-07-20T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LP1a.jpg',
              'ribbon': 'TERRENOS DE LAGO',
              'star': True,
              'badge': 'Coatepeque · 1 manzana · $200,000'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LP1b.jpg',
              'ribbon': 'TERRENOS DE LAGO',
              'badge': 'Vista completa al lago'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/LP1c.jpg',
              'ribbon': 'TERRENOS DE LAGO',
              'badge': 'Ver el Top 10 → pulpo.club'}],
  'capES': '**Terrenos de Lago · #1 — Coatepeque, vista al lago.**\n'
           '\n'
           '1 manzana (≈6,989 m²) sobre las colinas de Coatepeque, con el lago entero de frente. Espacio para '
           'tu casa, la de tus hijos, y que sobre.\n'
           '\n'
           'Tierra con esta vista casi no aparece — solo 18 lotes en todo Coatepeque.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Lake Land · #1 — Coatepeque, lake view.**\n'
           '\n'
           '1 manzana (≈6,989 m²) on the hills of Coatepeque, the whole lake in front. Room for your house, '
           "your kids' house, and then some.\n"
           '\n'
           'Land with this view barely shows up — only 18 lots in all of Coatepeque.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Terrenos con vista al Lago 🌅**\n'
           '1. Coatepeque — 1 manzana, vista al lago · $200,000\n'
           '2. Cerro Verde — 2 manzanas · $365,000 · $26/m²\n'
           '3. 2,500 v² vista espectacular · $135,000\n'
           '…y más.\n'
           '\n'
           'Solo 18 lotes en todo Coatepeque. Rankeadas. El Top 10 en tu correo cada domingo 👉 pulpo.club',
  'comEN': '**Top 10 Land with Lake Views 🌅**\n'
           '1. Coatepeque — 1 manzana, lake view · $200,000\n'
           '2. Cerro Verde — 2 manzanas · $365,000 · $26/m²\n'
           '3. 2,500 v² spectacular view · $135,000\n'
           '…and more.\n'
           '\n'
           'Only 18 lots in all of Coatepeque. Ranked. The Top 10 in your inbox every Sunday 👉 pulpo.club',
  'tags': '#TerrenosDeLago #LagoDeCoatepeque #Coatepeque #ElSalvador #BienesRaices',
  'primary_listing_id': 'bienesraices_2229',
  'listing_ids': ['bienesraices_2229']},
 {'day': 211,
  'slug': 'd11_herencia',
  'kind': 'inspira',
  'color_key': 'insp_seagreen',
  'scheduled_for': '2026-07-21T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': 'Herencia',
              'l1': '¿Qué les vas',
              'l2': 'a dejar?',
              'punch': 'La tierra no se gasta.'},
             {'t': 'stat', 'big': '+ valor', 'label': 'un buen terreno crece\nmientras dormís', 'src': None},
             {'t': 'cta', 'big': 'Sembrá algo\nque dure', 'sub': 'pulpo.club · link en bio'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L211.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'San Diego · $787,000',
              'color_key': 'casas_playa'}],
  'capES': '**¿Qué les vas a dejar a tus hijos?**\n'
           '\n'
           'Un terreno frente al mar o al lago no es un gasto: es lo único que no se devalúa, que crece '
           'mientras dormís. La herencia que tus papás no pudieron comprar porque no había cómo encontrarla.\n'
           '\n'
           'Hoy está a un clic, rankeada.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**What are you going to leave your kids?**\n'
           '\n'
           "Land on the water or the lake isn't an expense: it's the one thing that doesn't lose value, that "
           "grows while you sleep. The inheritance your parents couldn't buy because there was no way to find "
           'it.\n'
           '\n'
           "Today it's one click away, ranked.\n"
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Todo el mercado, comparado y rankeado por valor.\n'
           '\n'
           'El Top 10 en tu correo cada domingo, gratis.\n'
           '\n'
           'pulpo.club',
  'comEN': 'The whole market, compared and ranked by value.\n'
           '\n'
           'The Top 10 in your inbox every Sunday, free.\n'
           '\n'
           'pulpo.club',
  'tags': '#Herencia #ElSalvador #Terrenos #LagoDeCoatepeque #SurfCity #TuPedazoDeParaiso',
  'primary_listing_id': 'bienesraices_2156',
  'listing_ids': ['bienesraices_2156']},
 {'day': 212,
  'slug': 'd12_casas_playa_destacada',
  'kind': 'top10',
  'color_key': 'casas_playa',
  'scheduled_for': '2026-07-22T01:00:00+00:00',
  'slides': [{'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH2a.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'El Palmarcito, El Tunco · $115,000'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH2b.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'badge': 'Nueva · estrenala vos'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/BH2c.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'badge': 'Ver el Top 10 → pulpo.club'}],
  'capES': '**Casas de Playa · destacada — El Palmarcito, El Tunco.**\n'
           '\n'
           'Casa nueva, para estrenar, a minutos de las olas de El Tunco, con vista al valle y las montañas. '
           'Prueba de que un pedazo de Surf City no cuesta una fortuna: $115,000.\n'
           '\n'
           'Está en nuestro Top 10 de la semana.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Beach Homes · featured — El Palmarcito, El Tunco.**\n'
           '\n'
           "A brand-new home, never lived in, minutes from El Tunco's waves, with valley and mountain views. "
           "Proof that a piece of Surf City doesn't cost a fortune: $115,000.\n"
           '\n'
           "It's in our Top 10 this week.\n"
           '\n'
           'pulpo.club · link in bio',
  'comES': '**Top 10 Casas de Playa 🏄** — de $115,000 para arriba.\n'
           'Cerromar, El Sunzal, El Zonte, El Palmarcito… todas comparadas y rankeadas por precio, zona y '
           'acceso.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo 👉 pulpo.club',
  'comEN': '**Top 10 Beach Homes 🏄** — from $115,000 up.\n'
           'Cerromar, El Sunzal, El Zonte, El Palmarcito… all compared and ranked by price, location, and '
           'access.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday 👉 pulpo.club',
  'tags': '#CasasDePlaya #ElPalmarcito #ElTunco #SurfCity #ElSalvador #BienesRaices',
  'primary_listing_id': 'encuentra24_31372098',
  'listing_ids': ['encuentra24_31372098']},
 {'day': 213,
  'slug': 'd13_noticias',
  'kind': 'inspira',
  'color_key': 'insp_green',
  'scheduled_for': '2026-07-23T01:00:00+00:00',
  'slides': [{'t': 'news',
              'eyebrow': 'Noticia · Pulpo Pro',
              'head': 'La carretera al mar se amplía.',
              'body': 'El MOP avanza en Los Chorros — la ruta clave de San Salvador a la costa.',
              'src': 'La Página · jun 2026'},
             {'t': 'usp',
              'eyebrow': 'Qué significa para vos',
              'title': 'Menos viaje, más valor.',
              'body': 'Mejor acceso a El Tunco y La Libertad sube el valor de la tierra en la costa.'},
             {'t': 'cta', 'big': 'En Pulpo\nPro', 'sub': 'las noticias que mueven el precio · pulpo.club'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L213.jpg',
              'ribbon': 'TERRENOS DE PLAYA',
              'star': True,
              'badge': 'La Libertad · $500,000',
              'color_key': 'terrenos_playa'}],
  'capES': '**Buena noticia para quien tiene (o quiere) tierra en la costa.**\n'
           '\n'
           'El Ministerio de Obras Públicas avanza en la ampliación de Los Chorros, la carretera que conecta '
           'San Salvador con las playas. Menos tráfico, viaje más corto a El Tunco y La Libertad — y más valor '
           'para la tierra costera.\n'
           '\n'
           'Esto lo encontramos y te lo contamos en el newsletter Pulpo Pro.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Good news if you own (or want) land on the coast.**\n'
           '\n'
           'The Ministry of Public Works is advancing the Los Chorros highway expansion, the route connecting '
           'San Salvador to the beaches. Less traffic, a shorter drive to El Tunco and La Libertad — and more '
           'value for coastal land.\n'
           '\n'
           'We find this and bring it to you in the Pulpo Pro newsletter.\n'
           '\n'
           'pulpo.club · link en bio',
  'comES': 'Cada domingo, además del Top 10, te contamos las noticias que suben el valor de tu tierra. Gratis, '
           'en tu correo.\n'
           '\n'
           'pulpo.club · Fuente: La Página, jun 2026',
  'comEN': "Every Sunday, along with the Top 10, we bring you the news that raises your land's value. Free, in "
           'your inbox.\n'
           '\n'
           'pulpo.club · Source: La Página, Jun 2026',
  'tags': '#ElSalvador #LosChorros #SurfCity #LaLibertad #ElTunco #BienesRaices #PulpoPro',
  'primary_listing_id': 'citymax_sc_se-vende-terreno-con-vista-al-mar-en-surf-city',
  'listing_ids': ['citymax_sc_se-vende-terreno-con-vista-al-mar-en-surf-city']},
 {'day': 214,
  'slug': 'd14_cierre',
  'kind': 'wrap',
  'color_key': 'cierre',
  'scheduled_for': '2026-07-24T01:00:00+00:00',
  'slides': [{'t': 'statement',
              'eyebrow': '2 semanas después',
              'l1': 'Ya sabés',
              'l2': 'dónde buscar.',
              'punch': 'Playa, lago, casas, lotes, apartamentos.'},
             {'t': 'cta', 'big': 'Rankeadas.', 'sub': 'El Top 10 en tu correo cada domingo.'},
             {'t': 'cta', 'big': 'pulpo.club', 'sub': 'link en bio · gratis'},
             {'t': 'photo',
              'img': 'web/data/ig_assets/campaign/_src/L214.jpg',
              'ribbon': 'CASAS DE PLAYA',
              'star': True,
              'badge': 'La Libertad · $565,000',
              'color_key': 'casas_playa'}],
  'capES': '**Dos semanas, todo El Salvador rankeado.**\n'
           '\n'
           'Playa y lago, casas, lotes y apartamentos — comparados y ordenados de mejor a peor, en un solo '
           'lugar. Y esto apenas empieza.\n'
           '\n'
           'Rankeadas. El Top 10 en tu correo cada domingo, gratis. Sumate.\n'
           '\n'
           'pulpo.club · link en bio',
  'capEN': '**Two weeks, all of El Salvador ranked.**\n'
           '\n'
           'Beach and lake, homes, lots, and apartments — compared and ordered best to worst, in one place. '
           'And this is just the start.\n'
           '\n'
           'Ranked. The Top 10 in your inbox every Sunday, free. Join us.\n'
           '\n'
           'pulpo.club · link in bio',
  'comES': 'Suscribite gratis: el Top 10 de El Salvador, cada domingo, sin spam.\n\npulpo.club',
  'comEN': 'Subscribe free: the Top 10 of El Salvador, every Sunday, no spam.\n\npulpo.club',
  'tags': '#ElSalvador #BienesRaices #SurfCity #LagoDeCoatepeque #TuPedazoDeParaiso #PulpoClub',
  'primary_listing_id': 'oceanside_11468',
  'listing_ids': ['oceanside_11468']}]

PLAN_BY_DAY = {p["day"]: p for p in PLAN}


# ── build ──────────────────────────────────────────────────────────────

def render_post(post: dict) -> dict:
    """Render a post's slides to PNGs under ASSETS_ROOT/<slug>/ and return
    a fully-formed ig_queue.json item (approved, not posted)."""
    color = CATEGORY_COLORS[post["color_key"]]
    out_dir = ASSETS_ROOT / post["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)

    slide_paths: list[str] = []
    for i, spec in enumerate(post["slides"], start=1):
        path = out_dir / f"slide{i}.png"
        # A slide may override the post color (e.g. the ★ listing slide
        # appended to a topic post renders in its category color — blue
        # TERRENOS DE PLAYA — not the post's inspiration hue).
        slide_color = CATEGORY_COLORS.get(spec.get("color_key"), color)
        render_slide(spec, slide_color, path)
        slide_paths.append(str(path).replace("\\", "/"))

    caption = _bilingual(post["capES"], post["capEN"])
    comment = _bilingual(post["comES"], post["comEN"], tail=post["tags"])

    return {
        "day": post["day"],
        "shelf": f"campaign_{post['kind']}",
        "selector": "campaign_v1",
        "poster_type": "campaign",
        "palette": post["color_key"],
        "scheduled_for": post["scheduled_for"],
        "assets_dir": str(ASSETS_ROOT / post["slug"]).replace("\\", "/"),
        "poster_path": slide_paths[0],
        "poster_overrides": {},
        "caption": caption,
        "comment": comment,
        "lint_violations": [],
        "caption_status": "clean",
        "carousel_photo_paths": slide_paths[1:],
        "listing_ids": post.get("listing_ids", []),
        "primary_listing_id": post.get("primary_listing_id"),
        "status": "scheduled",
        "approved": True,
        "posted": False,
        "posted_at": None,
        "posted_media_id": None,
    }


def patch_queue(item: dict, queue_path: Path = QUEUE_PATH) -> None:
    """Insert `item` into the queue and supersede the old-design pending
    items so the publisher's next due pick is this campaign post.

    Superseding = approved:false + status:"superseded_campaign_v1" on any
    still-unposted item that isn't part of campaign_v1.  Posted items are
    left untouched (history).  Idempotent: re-running replaces the same
    day id rather than duplicating it.
    """
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    items = data.get("items", [])

    superseded = 0
    for it in items:
        if it.get("posted"):
            continue
        if it.get("selector") == "campaign_v1":
            continue
        if it.get("approved"):
            it["approved"] = False
            it["status"] = "superseded_campaign_v1"
            superseded += 1

    items = [it for it in items if it.get("day") != item["day"]]
    items.append(item)
    items.sort(key=lambda it: it.get("scheduled_for") or "")
    data["items"] = items

    atomic_write_text(queue_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"queue patched: +day {item['day']}, superseded {superseded} old-design item(s)")


def _main() -> None:
    ap = argparse.ArgumentParser(description="Build a campaign post into the IG queue.")
    ap.add_argument("--day", type=int, help="campaign day id (e.g. 201) or 1-based index")
    ap.add_argument("--all", action="store_true", help="build every day in PLAN, in schedule order")
    ap.add_argument("--render", action="store_true", help="render the slide PNGs")
    ap.add_argument("--apply", action="store_true", help="patch ig_queue.json with the built item(s)")
    args = ap.parse_args()

    if args.all:
        posts = list(PLAN)
    elif args.day is not None:
        # Accept either the day id (201) or the 1-based ordinal (1).
        post = PLAN_BY_DAY.get(args.day)
        if post is None and 1 <= args.day <= len(PLAN):
            post = PLAN[args.day - 1]
        if post is None:
            raise SystemExit(f"no plan entry for day {args.day}; known: {sorted(PLAN_BY_DAY)}")
        posts = [post]
    else:
        raise SystemExit("pass --day <id> or --all")

    if not args.render:
        print(json.dumps(posts if args.all else posts[0], indent=2, ensure_ascii=False))
        return

    for post in posts:
        item = render_post(post)
        print(f"rendered {len(post['slides'])} slides → {item['assets_dir']}")
        if args.apply:
            patch_queue(item)
        else:
            print("(dry: not patching queue; pass --apply to write ig_queue.json)")


if __name__ == "__main__":
    _main()

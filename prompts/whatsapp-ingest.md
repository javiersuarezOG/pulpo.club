# WhatsApp chat ingester — pulpo.club

You are adding a new ingestion path: take a WhatsApp `.txt` chat
export, extract real-estate listings (whether they arrive as URLs,
inline structured text, or a mix), and merge them into the existing
`ranked` pipeline as `source: "whatsapp"`. This is the same shape as
the existing scrapers — a `Source` that yields raw dicts that
normalize.py can ingest — but the input is a file, not a URL.

There are three real chat exports in `inbox/` (sample data; gitignored)
that demonstrate the shape variety you must handle:

1. **Daniel personal chat** — sparse, mostly noise, but bursts of
   forwarded URLs (Facebook shares, encuentra24, bienesraicesenelsalvador).
2. **Broker DM, broker @ +503 7860 2228** — pasted full listing prose
   in one or two messages, no URLs, sometimes followed by photos.
3. **Broker DM, broker @ +503 7851 3928** — numbered options
   ("OPCION 1)", "OPCION 2)"…) with a mix of URLs, inline text, and
   maps coordinates. Highest density.

Read `pulpo/normalize.py`, `pulpo/scrapers/__init__.py`, and one
existing scraper (e.g. `century21.py`) before writing anything. The
output dict schema must match what `normalize` already expects — same
keys, same types.

## Files to create

**1. `automation/ingest_chat.py`** — CLI entrypoint:

```bash
python3 automation/ingest_chat.py inbox/_chat_5.txt
python3 automation/ingest_chat.py inbox/*.txt   # batch
```

**2. `pulpo/ingest/__init__.py`** and **`pulpo/ingest/whatsapp.py`** —
the module the CLI delegates to. Keep the parser, the LLM extractor,
and the dedup logic in three separate functions for testability.

**3. `tests/ingest/test_whatsapp.py`** — pytest covering:
- Parser correctly splits a synthetic chat into messages.
- Sender-grouping correctly merges 3 consecutive broker messages
  into one listing unit.
- "OPCION N)" markers force a split even when sender is the same.
- A URL-only unit is classified `route: "url"`.
- A text-only unit with "$200,000" + "5,000 varas²" is classified
  `route: "text"`.
- Dedup against a synthetic `ranked.json` correctly drops a
  bienesraicesenelsalvador URL we already have.

## What the ingester does, step by step

### Step 1 — Parse the export

Each line starts with `[DD/MM/YYYY, HH:MM:SS] Sender: body` (or with a
`‎` BOM-style char prefix for media omissions). Body can span
multiple lines until the next timestamp line. Skip lines containing:
"image omitted", "video omitted", "audio omitted", "sticker omitted",
"document omitted", "Voice call.", "Missed voice call.", "Video call.",
"Silenced voice call.", "Contact card omitted", "Location:" (you keep
the URL from these though — see Step 4),
"This message was deleted.", "You deleted this message.",
"created this group", "added you", "changed this group's icon",
"changed the group name", "Messages and calls are end-to-end encrypted".

### Step 2 — Group into listing units

A "unit" is N consecutive messages from the same sender, where N stops
when:
- A different sender posts.
- A 30+ minute gap between consecutive messages from the same sender.
- The next message starts with `OPCION ` (Spanish "Option") or
  `OPTION ` followed by a digit. This is a forced split — the broker
  is starting a new listing.
- The unit accumulates more than ~2,000 chars (defensive cap).

A unit can be empty after media-stripping; drop those.

### Step 3 — Classify each unit

For each unit's text body:
- If it contains URLs, extract them. A URL belongs to a unit if it
  appeared within the unit's message window.
- If the unit has a URL AND text, route = `mixed`.
- If only URL, route = `url`.
- If only text with listing markers (regex over `\$[\d,]+`,
  `varas?²?`, `mz`, `manzanas?`, `m²`, `frente al mar`, `playa`),
  route = `text`.
- Else route = `noise`, drop.

### Step 4 — Extract by route

**route = `url`**:
- For each URL, classify by host:
  - `bienesraicesenelsalvador.com` → strip `?referer=` query,
    check if URL is already in `web/data/ranked.json`. If yes, mark
    `dedup: scraped_known` and DROP. If no, fetch OG tags or queue
    for next scrape cycle (record with `source: "whatsapp"` and a
    note `pending_scrape: true` — we'll backfill on the next
    bienesraices crawl).
  - `facebook.com/share/*` → fetch the URL with a regular User-Agent.
    Facebook serves Open Graph metadata (og:title, og:description,
    og:image) in the HTML head without auth. Parse those, hand to
    the LLM normalizer with the OG dict.
  - `maps.google.com` or `maps.app.goo.gl` → extract `?q=lat,lng`
    if present. Don't emit a listing for this — instead, attach as
    `lat`/`lng` to the temporally-nearest listing in the same chat
    from the same sender within ±10 minutes.
  - `encuentra24.com`, `propilatam.com`, `realtechsv.com`,
    `elsalvadorsurfrealestate.com` → fetch and hand to LLM.
  - Anything else → fetch HTML, hand to LLM with a "extract listing
    fields if this is a real estate page" prompt.

**route = `text`**:
- Hand the unit's text directly to the LLM normalizer.

**route = `mixed`**:
- Use the text as primary, URL(s) as secondary. The LLM gets both.

### Step 5 — LLM normalizer

Single function `extract_listing(text: str, og: dict | None = None) ->
dict | None`. Calls Anthropic `claude-haiku-4-5-20251001` with a tight
Spanish/English-aware system prompt:

> You're extracting Salvadoran real-estate listing fields from a
> WhatsApp message. Output STRICT JSON with these keys (use null if
> unknown): title (string), raw_price_text (string),
> raw_size_text (string with unit — varas², m², manzanas), price_usd
> (number or null), location_text (string), is_beachfront (boolean),
> has_paved_access (boolean), has_water (boolean), has_power
> (boolean), description (string ≤500 chars), confidence (low|mid|high).
> If the text is not a real estate listing, return {"is_listing":
> false}.

Parse the JSON, validate, log low-confidence extractions but still
emit them.

### Step 6 — Build the raw dict

For each successfully extracted unit:

```python
{
  "source": "whatsapp",
  "source_id": hashlib.sha1(f"{chat_file}:{msg_idx}:{content[:200]}".encode()).hexdigest()[:16],
  "url": canonical_url or "",  # Facebook share, broker URL, or empty
  "title": extracted["title"],
  "price_usd": extracted["price_usd"],
  "raw_price_text": extracted["raw_price_text"] or "",
  "raw_size_text": extracted["raw_size_text"] or "",
  "location_text": extracted["location_text"] or "",
  "description": extracted["description"] or "",
  "property_type": "land",  # all current chat traffic is land
  "is_beachfront": extracted["is_beachfront"] or False,
  "has_paved_access": extracted["has_paved_access"] or False,
  "has_water": extracted["has_water"] or False,
  "has_power": extracted["has_power"] or False,
  "broker_name": sender if not sender.startswith("+") else "",
  "broker_phone": sender if sender.startswith("+") else "",
  "lat": attached_coords[0] if coords_match else None,
  "lng": attached_coords[1] if coords_match else None,
  "scraped_at": message_timestamp_iso,
  # Provenance:
  "_referrer": "Daniel Garcia" or whichever forwarder,
  "_chat_file": basename(chat_file),
  "_extraction_route": route,
  "_extraction_confidence": extracted.get("confidence", "low"),
}
```

### Step 7 — Dedup against ranked.json

Two passes:
1. Exact URL match on `url` field — drop.
2. Fuzzy match on `(zone, area_m2, price_usd)`: same `zone` after
   normalize.detect_zone, area within ±10%, price within ±15%. Drop
   with `dedup: similar_to=<source_id>` logged.

### Step 8 — Emit

Append the new records to `web/data/ranked.json` (insert before
ranking — `automation/run.py` re-ranks on next run). Print a summary:

```
ingested inbox/_chat_5.txt:
  68 messages parsed
  12 listing units
  6 routes:url, 4 routes:text, 2 routes:mixed
  3 dropped (dedup)
  9 emitted (5 new, 4 pending_scrape)
  2 maps coordinates attached
```

## Hard constraints

- **One env var dependency**: `ANTHROPIC_API_KEY`. Document in
  README. If unset, the script processes everything except the LLM
  step and emits unprocessed units to `inbox/.unprocessed/`.
- **Cache OG fetches**: `inbox/.cache/<sha1(url)>.json` so reruns
  don't re-fetch. Cache hits are free, fresh fetches respect a
  1.0s delay between calls.
- **Add `anthropic` to `requirements.txt`** (latest stable). Justify
  in the commit message.
- **Don't break the offline pipeline.** `python3 -m pulpo.cli
  --offline` must still work.
- **Don't break the existing tests.** Add new tests; don't modify
  old ones.
- **Don't fetch anything from Facebook beyond OG tags.** No login, no
  scraping the post HTML beyond what's in the head element. Comment
  the code to make the boundary explicit.
- **Image attachments stay omitted.** Don't try to OCR them in this
  PR — that's a follow-up if the chat-text-only signal proves
  insufficient.
- **Don't change the ranker or normalize.** The ingester emits raw
  dicts, normalize handles the rest. If a field doesn't fit the
  existing schema, that's a bug in the extractor, not a reason to
  change normalize.

## Verification

```bash
# Unit tests
PULPO_OFFLINE=1 pytest -q tests/ingest/

# Full offline pipeline still works
python3 -m pulpo.cli --offline

# Dry-run against the three sample chats — outputs to stdout, no
# writes to ranked.json
python3 automation/ingest_chat.py --dry-run inbox/*.txt

# Real run against one chat — emits to ranked.json
python3 automation/ingest_chat.py inbox/_chat_7.txt
python3 automation/run.py   # re-rank with new records
```

Expected for chat 7 (the broker with numbered OPCIONs): ~10 listing
units detected, ~6–8 emitted after dedup against existing
bienesraicesenelsalvador URLs. The emitted units should include
Punta Mango 3,200 vrs² @ $800k, Maculís ~5,000 vrs² total, El Zonte
71,448 m² @ $6.5M.

## Final summary in chat

≤200 words. Cover:
1. Per-chat counts: messages parsed, units detected, listings
   emitted, dedups dropped.
2. Anything weird the LLM extractor mis-classified — show one
   before/after example.
3. Whether the OG-tag fetch on Facebook share URLs works as expected
   (it should; if not, what blocked it).
4. One concrete next step — e.g. "the encuentra24 URLs in chat 5 hint
   that ~80% of Daniel's leads come from there. A proper
   encuentra24.py scraper would close that gap and let us drop the
   per-URL LLM extraction for that host."

If something needs my decision (e.g., the Haiku model returns
malformed JSON >5% of the time, or one of the broker URLs requires
auth, or the dedup heuristic catches obvious different listings),
stop and report. Don't paper over.

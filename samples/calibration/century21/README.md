# Century 21 El Salvador calibration samples

Drop saved detail pages here as `*.html`. The site runs on Tokko Broker —
results pages render server-side, so a normal "Save Page As → Webpage,
HTML Only" capture is sufficient (no need for headless rendering).

Suggested captures before flipping `PULPO_OFFLINE=0`:

- `index-results.html` — saved from the filtered LIST_URL the scraper
  uses (`/v/resultados/.../oficina_4942-century-21-el-salvador_local/`).
  The "index" in the filename flips calibrate.py to index-card mode.
- 3+ detail pages spanning at least two property types (e.g. one
  `lote_residencial`, one `finca`, one `terreno_de_conservacion`) — the
  Tokko skin sometimes routes different property types through slightly
  different templates and we want all of them green.

Then run:

```bash
python3 automation/calibrate.py --source century21
```

Coverage target: ≥95% across the saved pages.

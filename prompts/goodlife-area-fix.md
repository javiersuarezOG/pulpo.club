# Fix goodlife area_m2 — calibration gap on live data

You are fixing a calibration regression. The live coverage run on
2026-05-01 showed `area_m2 = 0%` on all 10 live goodlife listings, but
goodlife was previously calibrated at 100% against the saved HTML at
`samples/calibration/goodlife/detail.html`. The Mikado/Kastell theme
likely changed the `<h4>` toggle label that
`pulpo/scrapers/goodlife.py` keys off, so the area field is going
unmatched even though the value is on the page.

Read `pulpo/scrapers/goodlife.py` and look at `_TOGGLE_AREA_KEYS` —
that's the set of `<h4>` titles (lowercased) the parser tries to match
to extract the area toggle. The fix is one line: add whatever label
the live theme is actually using.

## Steps

1. **Capture a fresh detail page**. Pick any URL from the goodlife
   land index. The current index URL is
   `https://goodlifeelsalvador.com/land/?page=1`. Fetch it, parse out
   one `mkdf-ips-item-link` href, then fetch that detail page. Save the
   HTML to `samples/calibration/goodlife/detail-live-1.html`.

2. **Run the calibration harness against the new sample**:
   ```bash
   python3 automation/calibrate.py --source goodlife --html samples/calibration/goodlife/detail-live-1.html
   ```
   The output will show which selectors hit and which miss. Confirm
   `area` is missing.

3. **Print the actual `<h4>` labels** the live page uses. Quick
   helper:
   ```python
   from selectolax.parser import HTMLParser
   tree = HTMLParser(open("samples/calibration/goodlife/detail-live-1.html").read())
   for tog in tree.css("div.vc_toggle"):
       head = tog.css_first(".vc_toggle_title") or tog.css_first("h4")
       if head:
           print(repr(head.text(strip=True).lower()))
   ```
   Eyeball the output. Find the one that looks like an area/size
   label.

4. **Add the missing key(s) to `_TOGGLE_AREA_KEYS`** in
   `pulpo/scrapers/goodlife.py`. Don't remove existing keys — additive
   only. If the new label is in Spanish, add the singular and any
   common pluralization. If English, same.

5. **Re-run the calibration harness** to confirm `area` now matches:
   ```bash
   python3 automation/calibrate.py --source goodlife
   ```
   Should report 100% across all goodlife samples (including the new
   live one).

6. **Re-run the live pipeline and verify**:
   ```bash
   python3 automation/run.py
   python3 -c "
   import json
   d = json.load(open('web/data/ranked.json'))
   gl = [r for r in d if r['source'] == 'goodlife']
   with_area = sum(1 for r in gl if r.get('area_m2'))
   print(f'goodlife: area_m2 {with_area}/{len(gl)}')
   "
   ```
   Expect ≥ 9/10 (one might legitimately have no published size).

7. **Commit**:
   ```
   fix(scrapers/goodlife): restore area_m2 extraction after live theme
   change
   ```
   Body: explain which label was missing, paste the before/after
   counts.

## Hard constraints

- Don't change selector logic beyond `_TOGGLE_AREA_KEYS`. The whole
  vc_toggle parsing path is sound — only the label dictionary needs
  updating.
- Don't break `tests/test_units.py`. Run `pytest -q` before
  committing.
- If the `<h4>` labels look totally different from anything in
  `_TOGGLE_AREA_KEYS` (e.g. icon-only, or numeric, or in a different
  DOM structure entirely), STOP and report — that's a bigger
  regression than a label rename and I want to see it before you
  guess.
- Don't commit the saved HTML — it's already gitignored under
  `samples/calibration/*/*.html`.

## Final summary in chat

≤80 words. What label was missing, the before/after percent, and
goodlife's new live coverage. End with a single sentence on whether
you noticed any other selector that's drifted while you were in there
(don't fix it, just flag it).

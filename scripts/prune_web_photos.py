"""Prune web/photos to only files referenced by active listings.

Photos are a re-downloadable cache (source URLs live in ranked.json) and
git history retains every deletion, so this is safe + reversible. The
keep-set is derived from the ONLY files that drive /photos serving:
ranked{,.list}{,.PA}.json. We keep ALL variants of every referenced hero
(base + .hero.jpg + .meta.json + .hash) and delete the rest.

Run with --apply to actually delete; default is dry-run.
"""
import os
import re
import sys

APPLY = "--apply" in sys.argv
PHOTOS = "web/photos"
SOURCES = ["web/data/ranked.json", "web/data/ranked.list.json",
           "web/data/ranked.PA.json", "web/data/ranked.list.PA.json"]

# extension tokens to strip to reduce a filename to its {source}_{id} base
EXTS = (".meta.json", ".hash", ".hero.jpg", ".hero.jpeg", ".hero.png",
        ".hero.webp", ".jpg", ".jpeg", ".png", ".webp", ".hero")

def base_of(name):
    changed = True
    while changed:
        changed = False
        for e in EXTS:
            if name.endswith(e):
                name = name[: -len(e)]
                changed = True
                break
    return name

# 1) collect referenced /photos/ filenames (NOT /photos-hires/, separate dir)
refs = set()
for p in SOURCES:
    if not os.path.exists(p):
        continue
    blob = open(p, encoding="utf-8").read()
    for m in re.findall(r'/photos/([^"\\\s]+)', blob):
        refs.add(m)
keep_bases = {base_of(r) for r in refs}
print(f"referenced /photos files: {len(refs)}  →  distinct bases: {len(keep_bases)}")

# 2) walk web/photos. Photos are served ONLY from the top level
# (/photos/:file is one path segment), so keep = top-level files whose
# base is referenced, PLUS any exactly-referenced path (covers a ref with
# a slash, if any). Everything else — chiefly web/photos/_archive/ — is
# never served → delete.
exact_keep = {os.path.normpath(os.path.join(PHOTOS, r)) for r in refs}
allfiles = []
for root, _, files in os.walk(PHOTOS):
    for fn in files:
        allfiles.append(os.path.join(root, fn))
def keep_file(f):
    if os.path.normpath(f) in exact_keep:
        return True
    return os.path.dirname(f) == PHOTOS and base_of(os.path.basename(f)) in keep_bases
keep = [f for f in allfiles if keep_file(f)]
delete = [f for f in allfiles if not keep_file(f)]
archived = [f for f in delete if f"{os.sep}_archive{os.sep}" in f]
print(f"web/photos: {len(allfiles)} files | keep {len(keep)} | delete {len(delete)} (of which _archive: {len(archived)})")

# 3) SANITY GATES — abort if anything looks wrong
# a) every referenced hero that EXISTS on disk must be in keep (never delete a served file)
served_on_disk = [r for r in refs if os.path.exists(os.path.join(PHOTOS, r))]
served_kept = [r for r in served_on_disk if os.path.join(PHOTOS, r) in set(keep)]
missing_ref = [r for r in refs if not os.path.exists(os.path.join(PHOTOS, r))]
assert len(served_kept) == len(served_on_disk), \
    f"GATE FAIL: {len(served_on_disk)-len(served_kept)} served photos would be deleted!"
print(f"served-on-disk heroes: {len(served_on_disk)} — ALL kept ✓ | referenced-but-already-missing: {len(missing_ref)}")
# b) delete count in the expected huge range; keep count small
assert 150_000 <= len(delete) <= 205_000, f"GATE FAIL: delete count {len(delete)} out of range"
assert len(keep) <= 30_000, f"GATE FAIL: keeping too many ({len(keep)})"
# c) not deleting the whole dir
assert len(keep) >= len(served_on_disk) >= 1, "GATE FAIL: keep-set empty"
print("ALL SANITY GATES PASSED ✓")

if missing_ref[:5]:
    print("  (sample already-missing referenced heroes, pre-existing):", missing_ref[:5])

if APPLY:
    for f in delete:
        os.remove(f)
    print(f"DELETED {len(delete)} files from web/photos")
else:
    print("DRY RUN — pass --apply to delete")

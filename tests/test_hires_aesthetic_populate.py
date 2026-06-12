"""Sidecar -> Listing population of the deterministic aesthetic issues
(plan 005). The hires QC pass writes sidecar["aesthetic"] =
{"issues": [...], ...}; _populate_hires_fields_from_sidecar copies the
issues list onto li.hires_aesthetic_issues so the featured pools and the
IG gate can exclude logo/watermark heroes. Older sidecars predate the
"aesthetic" key and must leave the field None without crashing.
"""
from automation.run import _populate_hires_fields_from_sidecar
from pulpo.models import Listing


def _listing() -> Listing:
    return Listing(source="x", source_id="1", url="http://e/1",
                   scraped_at="2026-06-12T00:00:00Z", title="t")


def test_aesthetic_issues_copied_from_sidecar():
    li = _listing()
    sidecar = {"width": 1200, "height": 1200,
               "aesthetic": {"issues": ["logo_or_watermark", "low_quality"],
                             "visual_appeal": 3.2, "provider": "deterministic"}}
    _populate_hires_fields_from_sidecar(li, sidecar, quarantined=False)
    assert li.hires_aesthetic_issues == ["logo_or_watermark", "low_quality"]


def test_older_sidecar_without_aesthetic_key_leaves_field_none():
    li = _listing()
    sidecar = {"width": 1200, "height": 1200,
               "hires_photo_quality_score": 80}
    _populate_hires_fields_from_sidecar(li, sidecar, quarantined=False)
    assert li.hires_aesthetic_issues is None


def test_empty_issues_list_leaves_field_none():
    li = _listing()
    sidecar = {"aesthetic": {"issues": [], "visual_appeal": 9.0}}
    _populate_hires_fields_from_sidecar(li, sidecar, quarantined=False)
    assert li.hires_aesthetic_issues is None


def test_malformed_aesthetic_payload_does_not_crash():
    li = _listing()
    # aesthetic is not a dict (defensive: a stale/garbage sidecar shape)
    _populate_hires_fields_from_sidecar(li, {"aesthetic": "watermark"},
                                        quarantined=False)
    assert li.hires_aesthetic_issues is None
    # issues is not a list
    li2 = _listing()
    _populate_hires_fields_from_sidecar(li2, {"aesthetic": {"issues": "x"}},
                                        quarantined=False)
    assert li2.hires_aesthetic_issues is None

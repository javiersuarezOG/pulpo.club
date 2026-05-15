"""Per-source URL rewrite tests for the hires photo pipeline."""
from __future__ import annotations

import pytest

from automation.hires_url_transform import describe_transform, transform_hires_url


class TestNoOpSources:
    """Day-1 sources: bienesraices, remax, century21, oceanside, nexo —
    URLs already expose hi-res variants; transform must be a no-op."""

    @pytest.mark.parametrize(
        "source,url",
        [
            (
                "bienesraices",
                "https://assets.easybroker.com/property_images/abc/EB-IM4863.jpg?rasterize=true",
            ),
            (
                "remax",
                "https://remax-central.com.sv/storage/properties/listing-slug-large.png",
            ),
            (
                "century21",
                "https://cdn.21online.lat/centroam/cache/awsTest1/rc/token/uploads/41/propiedades/1/photo.jpg",
            ),
            (
                "oceanside",
                "https://i0.wp.com/oceansideelsalvador.com/wp-content/uploads/2026/04/7-1-scaled.jpg?fit=2560%2C1807&ssl=1",
            ),
            (
                "nexo",
                "https://nexo.com.sv/properties/123/fotoGeneral_6_19.jpg",
            ),
        ],
    )
    def test_no_op_for_day_one_sources(self, source: str, url: str) -> None:
        assert transform_hires_url(source, url) == url

    @pytest.mark.parametrize(
        "source",
        ["bienesraices", "remax", "century21", "oceanside", "nexo"],
    )
    def test_describe_returns_none_for_day_one_sources(self, source: str) -> None:
        assert describe_transform(source) == "none"


class TestGoodlifeWPSizeStrip:
    """WordPress media library serves -<W>x<H> sized variants. Strip
    the suffix to get the original upload."""

    def test_strips_size_suffix(self) -> None:
        assert (
            transform_hires_url(
                "goodlife",
                "https://goodlifeelsalvador.com/wp-content/uploads/2026/04/DSC02001-1024x683.jpg",
            )
            == "https://goodlifeelsalvador.com/wp-content/uploads/2026/04/DSC02001.jpg"
        )

    def test_strips_size_suffix_png(self) -> None:
        assert transform_hires_url(
            "goodlife",
            "https://goodlifeelsalvador.com/wp-content/uploads/foo-2048x1365.png",
        ) == "https://goodlifeelsalvador.com/wp-content/uploads/foo.png"

    def test_idempotent_without_suffix(self) -> None:
        # No size suffix to strip → URL unchanged.
        url = "https://goodlifeelsalvador.com/wp-content/uploads/2026/04/full-original.jpg"
        assert transform_hires_url("goodlife", url) == url

    def test_doesnt_strip_within_path_segment(self) -> None:
        # The pattern is anchored to the filename end with extension, so
        # a directory name like "2024-12x" should not match.
        url = "https://goodlifeelsalvador.com/wp-content/uploads/2026/04/SomeOrigName.jpg"
        assert transform_hires_url("goodlife", url) == url

    def test_describe(self) -> None:
        assert describe_transform("goodlife") == "goodlife-strip-wp-size-suffix"


class TestEncuentra24CloudinaryTransform:
    """Cloudinary uses /t_<transform>/ tokens to select sized variants.
    Replace t_or_fh_m (medium-fit) with t_full to get source res."""

    def test_replaces_medium_token(self) -> None:
        assert (
            transform_hires_url(
                "encuentra24",
                "https://photos.encuentra24.com/t_or_fh_m/f_auto/v1/sv/abc/xxx.jpg",
            )
            == "https://photos.encuentra24.com/t_full/f_auto/v1/sv/abc/xxx.jpg"
        )

    def test_idempotent_when_already_full(self) -> None:
        url = "https://photos.encuentra24.com/t_full/f_auto/v1/sv/abc/xxx.jpg"
        assert transform_hires_url("encuentra24", url) == url

    def test_passthrough_when_no_transform_token(self) -> None:
        url = "https://photos.encuentra24.com/v1/sv/abc/xxx.jpg"
        assert transform_hires_url("encuentra24", url) == url

    def test_describe(self) -> None:
        assert describe_transform("encuentra24") == "encuentra24-cloudinary-t-full"


class TestEdgeCases:
    def test_unknown_source_returns_unchanged(self) -> None:
        url = "https://example.com/foo.jpg"
        assert transform_hires_url("future_unknown_broker", url) == url

    def test_empty_url_returns_empty(self) -> None:
        assert transform_hires_url("goodlife", "") == ""
        assert transform_hires_url("any", "") == ""

    def test_describe_unknown_source(self) -> None:
        assert describe_transform("future_unknown_broker") == "none"

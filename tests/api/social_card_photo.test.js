// Unit tests for api/social/card.js photo selection.
//
// The OG share card is a click-through producer: the image a crawler
// renders into the link-preview tile is the image a user clicks. The
// continuity contract (PR #785) requires it to lead with the hero
// picker's winning broker URL (`selected_photo_url`) so the previewed
// image matches the first image the detail gallery shows on arrival —
// rather than the raw `photo_urls[0]`, which diverges from the winner
// for ~44% of listings.
//
// We test the pure `pickPhotoUrl` helper (exposed via `_internal`)
// rather than the full Satori render, mirroring the `_internal`
// convention in tests/api/share_landing.test.js.

import { describe, it, expect } from "vitest";

import cardHandler from "../../api/social/card.js";
const { pickPhotoUrl } = cardHandler._internal;

describe("pickPhotoUrl", () => {
  it("prefers selected_photo_url over photo_urls[0]", () => {
    const listing = {
      selected_photo_url: "https://cdn.example/winner.jpg",
      photo_urls: ["https://cdn.example/first.jpg", "https://cdn.example/winner.jpg"],
    };
    expect(pickPhotoUrl(listing)).toBe("https://cdn.example/winner.jpg");
  });

  it("falls back to photo_urls[0] when selected_photo_url is absent", () => {
    const listing = {
      photo_urls: ["https://cdn.example/first.jpg", "https://cdn.example/second.jpg"],
    };
    expect(pickPhotoUrl(listing)).toBe("https://cdn.example/first.jpg");
  });

  it("falls back to photo_urls[0] when selected_photo_url is not an http URL", () => {
    const listing = {
      selected_photo_url: "/relative/path.jpg",
      photo_urls: ["https://cdn.example/first.jpg"],
    };
    expect(pickPhotoUrl(listing)).toBe("https://cdn.example/first.jpg");
  });

  it("returns null when neither field yields a usable URL", () => {
    expect(pickPhotoUrl({})).toBeNull();
    expect(pickPhotoUrl({ photo_urls: [] })).toBeNull();
    expect(pickPhotoUrl({ selected_photo_url: null, photo_urls: null })).toBeNull();
  });
});

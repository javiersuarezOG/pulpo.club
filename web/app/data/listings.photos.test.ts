// Unit tests for buildPhotos reordering (P2) via the public adaptListing.
//
// The hero picker selects a winning broker image and the card thumbnail
// paints it via thumbnail_url. Before P2 the detail gallery showed
// photo_urls[0] — frequently a DIFFERENT image. adaptListing now reorders
// `photos` so the selected image is photos[0], matching the card.

import { describe, it, expect } from "vitest";
import { adaptListing } from "./listings";

const base = {
  source: "goodlife",
  source_id: "x1",
  url: "https://example.com/l",
  title: "Test",
};

describe("adaptListing photo reordering (P2)", () => {
  it("moves selected_photo_url to photos[0]", () => {
    const l = adaptListing({
      ...base,
      photo_urls: ["https://b/1.jpg", "https://b/2.jpg", "https://b/3.jpg"],
      selected_photo_url: "https://b/3.jpg",
    });
    expect(l.photos[0]).toBe("https://b/3.jpg");
    // No photo is dropped — only reordered.
    expect(new Set(l.photos)).toEqual(
      new Set(["https://b/1.jpg", "https://b/2.jpg", "https://b/3.jpg"]),
    );
    expect(l.photos).toHaveLength(3);
  });

  it("is a no-op when selected_photo_url is already first", () => {
    const l = adaptListing({
      ...base,
      photo_urls: ["https://b/1.jpg", "https://b/2.jpg"],
      selected_photo_url: "https://b/1.jpg",
    });
    expect(l.photos).toEqual(["https://b/1.jpg", "https://b/2.jpg"]);
  });

  it("preserves order when selected_photo_url is absent (pre-P2 record)", () => {
    const l = adaptListing({
      ...base,
      photo_urls: ["https://b/1.jpg", "https://b/2.jpg"],
    });
    expect(l.photos).toEqual(["https://b/1.jpg", "https://b/2.jpg"]);
  });

  it("preserves order when selected_photo_url is not among photo_urls", () => {
    const l = adaptListing({
      ...base,
      photo_urls: ["https://b/1.jpg", "https://b/2.jpg"],
      selected_photo_url: "https://b/not-here.jpg",
    });
    expect(l.photos).toEqual(["https://b/1.jpg", "https://b/2.jpg"]);
  });
});

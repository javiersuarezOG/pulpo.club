import { describe, expect, test } from "vitest";
import { __test__ } from "./use-document-meta";
import { CATEGORY_KEYS } from "./categories";

describe("use-document-meta route copy", () => {
  test("serves Spanish legal metadata on legal routes", () => {
    const meta = __test__.metaForSection("privacy", "es", "");

    expect(meta.title).toBe("Política de privacidad · Pulpo");
    expect(meta.description).toContain("Pulpo");
    expect(meta.canonicalPath).toBe("/privacy");
    expect(meta.robots).toBeUndefined();
  });

  test("serves localized contact metadata", () => {
    const en = __test__.metaForSection("contact", "en", "");
    const es = __test__.metaForSection("contact", "es", "");

    expect(en.title).toBe("Contact Pulpo — support, privacy & billing");
    expect(en.description).toContain("billing");
    expect(es.title).toBe("Contacto — Pulpo");
    expect(es.description).toContain("facturación");
    expect(en.canonicalPath).toBe("/contact");
  });

  test("keeps auth-only pages out of the index", () => {
    expect(__test__.metaForSection("saved", "en", "").robots).toBe("noindex,follow");
    expect(__test__.metaForSection("account", "es", "").robots).toBe("noindex,follow");
    expect(__test__.metaForSection("admin", "en", "").robots).toBe("noindex,nofollow");
  });

  test("canonicalizes browse category URLs and drops noisy filters", () => {
    const meta = __test__.metaForSection(
      "browse",
      "en",
      "?cat=beachfront&sort=price&min=1000",
    );

    expect(meta.title).toContain("Beachfront land");
    expect(meta.canonicalPath).toBe("/browse?cat=beachfront");
  });
});

// Full-coverage assertion: every category key from CATEGORY_KEYS must
// resolve to a unique, non-generic title in both locales. Adding a new
// category to lib/categories.ts without adding matching copy in
// BROWSE_CATEGORY_COPY will fail this test rather than silently shipping
// duplicate-content meta for the new URL.
describe("use-document-meta browse-category coverage", () => {
  const genericEn = __test__.metaForSection("browse", "en", "").title;
  const genericEs = __test__.metaForSection("browse", "es", "").title;

  for (const cat of CATEGORY_KEYS) {
    test(`category "${cat}" has unique EN + ES copy`, () => {
      const en = __test__.metaForSection("browse", "en", `?cat=${cat}`);
      const es = __test__.metaForSection("browse", "es", `?cat=${cat}`);

      expect(en.title).not.toBe(genericEn);
      expect(es.title).not.toBe(genericEs);
      expect(en.title).not.toBe(es.title);
      expect(en.description).not.toBe(es.description);
      expect(en.canonicalPath).toBe(`/browse?cat=${cat}`);
      expect(es.canonicalPath).toBe(`/browse?cat=${cat}`);
      // Sanity: descriptions are non-empty and reasonable length.
      expect(en.description.length).toBeGreaterThan(20);
      expect(es.description.length).toBeGreaterThan(20);
      expect(en.description.length).toBeLessThanOrEqual(220);
      expect(es.description.length).toBeLessThanOrEqual(220);
    });
  }

  test("unknown cat falls through to generic Browse meta", () => {
    const meta = __test__.metaForSection("browse", "en", "?cat=not_a_real_category");
    expect(meta.title).toBe(genericEn);
    expect(meta.canonicalPath).toBe("/browse");
  });
});

describe("use-document-meta listing meta", () => {
  test("strips newlines + HTML entities and caps at 200 chars", () => {
    const listing = {
      id: "test-1",
      title: { en: "Beachfront lot", es: "Lote frente al mar" },
      description: {
        en: "Line one.\n\nLine two has &amp; weird   spacing.\tAlso tabs.\n" +
            "Padding to push past two hundred characters so the slice + ellipsis branch actually exercises — and we can spot a stray newline in a SERP snippet quickly.",
        es: "Línea uno.",
      },
      photos: ["/photos/test.jpg"],
      zone_name: "El Tunco",
      region: null,
      price: null,
      size_m2: null,
      is_sold: false,
      source_type: "scraped",
    } as any;

    const meta = __test__.metaForListing(listing, "en");

    expect(meta.description).not.toContain("\n");
    expect(meta.description).not.toContain("\t");
    expect(meta.description).not.toContain("&amp;");
    expect(meta.description).toContain("&");
    expect(meta.description.length).toBeLessThanOrEqual(200);
    expect(meta.ogType).toBe("product");
    expect(meta.imageAlt).toBe("Beachfront lot");
  });

  test("falls back to site description when listing description is empty", () => {
    const listing = {
      id: "test-2",
      title: { en: "Lot", es: "Lote" },
      description: { en: "", es: "" },
      photos: [],
      zone_name: null,
      region: null,
    } as any;

    const meta = __test__.metaForListing(listing, "es");
    expect(meta.description).toBeTruthy();
    // Fallback uses the Spanish SITE_DESCRIPTION ("Cada casa de playa
    // y lago en El Salvador, ordenada por valor…") — must be non-empty
    // and locale-correct.
    expect(meta.description).toContain("El Salvador");
    expect(meta.description.length).toBeGreaterThan(40);
  });
});

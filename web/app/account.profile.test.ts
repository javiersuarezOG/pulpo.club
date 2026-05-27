// Behaviour test for the name-split helper that drives /account/profile's
// "Full name" → firstName / lastName mapping on save.
//
// The helper looks trivial — but a single bug here writes the wrong
// thing to Clerk on every save. People type their names in wildly
// different shapes (single-token names are common in LATAM, compound
// surnames are common everywhere), so we pin the contract.

import { describe, expect, it } from "vitest";
import { splitFullName, joinFullName } from "./lib/name-split";

describe("splitFullName", () => {
  it("returns empty parts for empty / whitespace-only input", () => {
    expect(splitFullName("")).toEqual({ firstName: "", lastName: "" });
    expect(splitFullName("   ")).toEqual({ firstName: "", lastName: "" });
    expect(splitFullName("\t\n")).toEqual({ firstName: "", lastName: "" });
  });

  it("trims outer whitespace", () => {
    expect(splitFullName("  Sebastian  ")).toEqual({ firstName: "Sebastian", lastName: "" });
    expect(splitFullName("  Sebastian Honores  ")).toEqual({ firstName: "Sebastian", lastName: "Honores" });
  });

  it("keeps a single-token name as firstName only (common in LATAM)", () => {
    expect(splitFullName("Sebastian")).toEqual({ firstName: "Sebastian", lastName: "" });
    expect(splitFullName("María")).toEqual({ firstName: "María", lastName: "" });
  });

  it("splits on the first run of whitespace", () => {
    expect(splitFullName("Sebastian Honores")).toEqual({ firstName: "Sebastian", lastName: "Honores" });
  });

  it("preserves compound last names verbatim", () => {
    expect(splitFullName("María José García Pérez")).toEqual({
      firstName: "María",
      lastName: "José García Pérez",
    });
    expect(splitFullName("Juan Pablo de la Cruz")).toEqual({
      firstName: "Juan",
      lastName: "Pablo de la Cruz",
    });
  });

  it("collapses internal whitespace at the split boundary but keeps it inside lastName", () => {
    expect(splitFullName("Sebastian   Honores")).toEqual({
      firstName: "Sebastian",
      lastName: "Honores",
    });
    // Internal double-space inside the last-name half is preserved
    // verbatim — we don't try to normalise it (that's the user's typed
    // value, and Clerk accepts it).
    expect(splitFullName("Maria   Jose Garcia")).toEqual({
      firstName: "Maria",
      lastName: "Jose Garcia",
    });
  });
});

describe("joinFullName", () => {
  it("returns empty string for null / undefined / empty", () => {
    expect(joinFullName(null)).toBe("");
    expect(joinFullName(undefined)).toBe("");
    expect(joinFullName({})).toBe("");
    expect(joinFullName({ firstName: "", lastName: "" })).toBe("");
  });

  it("joins firstName + lastName with a single space", () => {
    expect(joinFullName({ firstName: "Sebastian", lastName: "Honores" })).toBe("Sebastian Honores");
  });

  it("emits a single-token name when one side is missing", () => {
    expect(joinFullName({ firstName: "Sebastian" })).toBe("Sebastian");
    expect(joinFullName({ lastName: "Honores" })).toBe("Honores");
  });

  it("round-trips through splitFullName for the common shapes", () => {
    const cases = ["Sebastian", "Sebastian Honores", "María José García Pérez"];
    for (const c of cases) {
      expect(joinFullName(splitFullName(c))).toBe(c);
    }
  });
});

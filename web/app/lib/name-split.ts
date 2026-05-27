// Split a single "Full name" input into Clerk's firstName + lastName fields.
//
// People type their names in wildly different shapes — single-token names
// (common in LATAM where many users go by one given name), three- or
// four-token compound surnames ("María José García Pérez"), or with
// middle names. We don't try to be clever:
//
//   - Trim outer whitespace.
//   - Split on the FIRST run of whitespace. Everything before = firstName;
//     everything after = lastName (with any internal whitespace preserved
//     so "García Pérez" stays as written).
//   - Empty input → both fields empty (Clerk accepts empty strings to
//     clear).
//
// Living in lib/ so the unit test in account.profile.test.ts can import
// it without dragging the React tree.

export type NameParts = {
  firstName: string;
  lastName: string;
};

export function splitFullName(input: string): NameParts {
  const trimmed = (input || "").trim();
  if (!trimmed) return { firstName: "", lastName: "" };
  const match = trimmed.match(/^(\S+)\s+(.+)$/);
  if (!match) return { firstName: trimmed, lastName: "" };
  return { firstName: match[1], lastName: match[2].trim() };
}

export function joinFullName(parts: { firstName?: string; lastName?: string } | null | undefined): string {
  if (!parts) return "";
  const f = (parts.firstName || "").trim();
  const l = (parts.lastName || "").trim();
  if (f && l) return `${f} ${l}`;
  return f || l || "";
}

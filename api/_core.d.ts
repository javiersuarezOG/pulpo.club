// Types for api/_core.js.
//
// Re-exported from the shared SOURCE so the functions keep full type
// checking while loading the compiled bundle at runtime. Referencing
// outside api/ is safe here precisely because declarations are erased
// at compile time — they are never emitted and never loaded, so the
// api/ boundary rule (which applies to values) does not bite.
export * from "../shared/api-core";

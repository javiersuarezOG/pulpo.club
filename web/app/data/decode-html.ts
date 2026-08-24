// Moved to shared/decode-html.ts: the listing adapter runs on both the
// browser and the server now, and broker descriptions arrive
// entity-encoded from the scrape on every channel. Re-exported here so
// existing imports and tests are unchanged.
export { decodeHtmlEntities } from "../../../shared/decode-html";

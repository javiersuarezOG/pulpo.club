// Pulpo — contact-form recipient routing.
//
// Each topic on the public /contact form routes to a topical inbox.
// Topical inboxes (contact@, privacy@, legal@, abuse@, press@) live on
// pulpo.club once Resend inbound is set up (see Sebastian-only runbook
// Task 3 in the audit plan). Until then, an unset env var falls back
// to the founder fan-out (set in api/contact.js) so submissions never
// get lost.
//
// CLIENT-SIDE: this module exports ONLY topic labels + types — the
// recipient addresses are server-only and read directly inside
// `api/contact.js`. Treat the addresses as PII-adjacent: never ship
// them to the browser, never put them in event payloads.

export type ContactTopic =
  | "general"
  | "billing"
  | "privacy"
  | "legal"
  | "press"
  | "abuse"; // DMCA / takedown / fraud

export const CONTACT_TOPICS: readonly ContactTopic[] = [
  "general",
  "billing",
  "privacy",
  "legal",
  "press",
  "abuse",
] as const;

// i18n keys for the topic dropdown. Add the corresponding entries to
// UI_STRINGS in web/app/i18n.jsx.
export const CONTACT_TOPIC_I18N_KEYS: Record<ContactTopic, string> = {
  general: "contact.topic.general",
  billing: "contact.topic.billing",
  privacy: "contact.topic.privacy",
  legal: "contact.topic.legal",
  press: "contact.topic.press",
  abuse: "contact.topic.abuse",
};

// Helper for the i18n table — surfaces the canonical default copy for
// each topic so adding a row to UI_STRINGS is a copy-paste.
export const CONTACT_TOPIC_DEFAULT_COPY: Record<ContactTopic, { en: string; es: string }> = {
  general: { en: "General enquiry", es: "Consulta general" },
  billing: { en: "Billing or subscription", es: "Facturación o suscripción" },
  privacy: { en: "Privacy / data request", es: "Privacidad / solicitud de datos" },
  legal:   { en: "Legal / terms", es: "Legal / términos" },
  press:   { en: "Press / partnerships", es: "Prensa / colaboraciones" },
  abuse:   { en: "Takedown or abuse report", es: "Eliminación de contenido o reporte de abuso" },
};

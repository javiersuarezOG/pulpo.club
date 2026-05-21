// Pulpo — legal-entity configuration.
//
// Single source of truth for company entity details that flow into every
// public legal page (/terms, /privacy, /cookies, /subscription, /imprint),
// the imprint footer, and the contact-form responses.
//
// Active jurisdiction is "SV" (El Salvador). NL/ES blocks are kept for
// reference in case the platform later expands. The body copy in
// `legal-content.ts` reads from this module's `ENTITY` export, with the
// `formatAddress` / `formatRegistration` helpers gracefully omitting
// fields whose values are empty strings.
//
// Pre-incorporation soft-launch: the public legal copy uses "Pulpo" as
// the operator name and the operator-facing fields (`legal_name`,
// `chamber_of_commerce.number`, `tax_id.value`, the street address,
// `director.name`, `phone`) are empty strings. Sentences in
// `legal-content.ts` that would otherwise read awkwardly without these
// fields are written to stand on their own. When incorporation closes,
// populate those fields (and bump `last_updated` on each doc) — no
// other code changes required.

export type Jurisdiction = "NL" | "ES" | "SV";

// Vite exposes only VITE_*-prefixed env vars to the client. Server-side
// code that needs the same value reads process.env.VITE_LEGAL_JURISDICTION
// (Vercel exposes every env var to serverless functions regardless of
// prefix), so a single env var serves both surfaces.
export const JURISDICTION: Jurisdiction = (() => {
  const raw = import.meta.env.VITE_LEGAL_JURISDICTION as string | undefined;
  if (raw === "ES") return "ES";
  if (raw === "NL") return "NL";
  return "SV"; // default — the platform's first live market is El Salvador
})();

export interface EntityConfig {
  /** Marketing-facing trade name. Stable across jurisdictions. */
  trade_name: string;
  /** Full registered legal name (placeholder until incorporation). */
  legal_name: string;
  /** "Besloten Vennootschap (B.V.)" / "Sociedad Limitada (S.L.)". */
  legal_form: string;
  /** Whether incorporation has completed. Public pages show a banner when false. */
  incorporated: boolean;
  chamber_of_commerce: { authority: string; number: string };
  tax_id: { label: string; value: string };
  address: {
    street: string;
    postcode: string;
    city: string;
    country: string;
    country_code: string; // ISO-3166-1 alpha-2
  };
  director: { name: string; role: string };
  phone: string;
  governing_law: string;
  courts: string;
  supervisory_authority: { name: string; url: string; phone?: string };
  /** Renders the German Impressum mirror at /impressum. True for both NL + ES
   *  because Pulpo is reachable to German users and the German
   *  Telemediengesetz / DDG Impressum obligation applies extraterritorially. */
  requires_impressum: boolean;
  /** EU member — drives whether we surface the ODR platform link, GDPR
   *  rights table, etc. */
  edpb_member: boolean;
  /** Default "from" email used by transactional Pulpo emails (Resend). */
  outbound_from: string;
}

const ENTITIES: Record<Jurisdiction, EntityConfig> = {
  NL: {
    trade_name: "Pulpo",
    legal_name: "[FULL REGISTERED BV NAME] B.V.",
    legal_form: "Besloten Vennootschap (B.V.)",
    incorporated: false,
    chamber_of_commerce: { authority: "KvK", number: "[NUMBER]" },
    tax_id: { label: "BTW", value: "NL[NUMBER]B01" },
    address: {
      street: "[STREET AND NUMBER]",
      postcode: "[POSTCODE]",
      city: "Amsterdam",
      country: "The Netherlands",
      country_code: "NL",
    },
    director: { name: "[YOUR FULL LEGAL NAME]", role: "Director" },
    phone: "+31 [NUMBER]",
    governing_law: "Dutch law",
    courts: "Courts of Amsterdam, the Netherlands",
    supervisory_authority: {
      name: "Autoriteit Persoonsgegevens",
      url: "autoriteitpersoonsgegevens.nl",
      phone: "+31 70 888 8500",
    },
    requires_impressum: true,
    edpb_member: true,
    outbound_from: "noreply@pulpo.club",
  },
  ES: {
    trade_name: "Pulpo",
    legal_name: "[NOMBRE REGISTRADO COMPLETO] S.L.",
    legal_form: "Sociedad Limitada (S.L.)",
    incorporated: false,
    chamber_of_commerce: { authority: "Registro Mercantil", number: "[NUMBER]" },
    tax_id: { label: "NIF", value: "[NIF]" },
    address: {
      street: "[CALLE Y NÚMERO]",
      postcode: "[CP]",
      city: "Barcelona",
      country: "Spain",
      country_code: "ES",
    },
    director: { name: "[NOMBRE LEGAL COMPLETO]", role: "Administrador único" },
    phone: "+34 [NUMBER]",
    governing_law: "Spanish law",
    courts: "Courts of Barcelona, Spain",
    supervisory_authority: {
      name: "Agencia Española de Protección de Datos (AEPD)",
      url: "aepd.es",
      phone: "+34 901 100 099",
    },
    requires_impressum: true,
    edpb_member: true,
    outbound_from: "noreply@pulpo.club",
  },
  SV: {
    trade_name: "Pulpo",
    legal_name: "Pulpo",
    legal_form: "",
    incorporated: false,
    chamber_of_commerce: { authority: "", number: "" },
    tax_id: { label: "", value: "" },
    address: {
      street: "",
      postcode: "",
      city: "San Salvador",
      country: "El Salvador",
      country_code: "SV",
    },
    director: { name: "", role: "" },
    phone: "",
    governing_law: "leyes de la República de El Salvador",
    courts: "Juzgados de lo Civil y Mercantil de San Salvador, El Salvador",
    supervisory_authority: {
      name: "Defensoría del Consumidor",
      url: "defensoria.gob.sv",
      phone: "910",
    },
    requires_impressum: false,
    edpb_member: false,
    outbound_from: "hello@pulpo.club",
  },
};

export const ENTITY: EntityConfig = ENTITIES[JURISDICTION];

// Convenience: a formatted single-line address suitable for legal copy.
// Empty fields are skipped so a pre-incorporation entity (city + country
// only) renders as "San Salvador, El Salvador" rather than ", ,  …".
export function formatAddress(entity: EntityConfig = ENTITY): string {
  const a = entity.address;
  const streetLine = [a.street, a.postcode].filter(Boolean).join(" ").trim();
  return [streetLine, a.city, a.country].filter(Boolean).join(", ");
}

// Convenience: "KvK 12345678 | BTW NL123456789B01" or local equivalent.
// Returns an empty string if no registration identifiers are configured,
// so legal-content.ts can omit the line entirely when needed.
export function formatRegistration(entity: EntityConfig = ENTITY): string {
  const coc = [entity.chamber_of_commerce.authority, entity.chamber_of_commerce.number]
    .filter(Boolean)
    .join(" ");
  const tax = [entity.tax_id.label, entity.tax_id.value].filter(Boolean).join(" ");
  return [coc, tax].filter(Boolean).join(" | ");
}

// EU ODR platform URL — required for EU B2C e-commerce per Regulation (EU)
// No 524/2013.
export const EU_ODR_PLATFORM_URL = "https://ec.europa.eu/consumers/odr";

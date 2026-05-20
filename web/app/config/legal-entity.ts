// Pulpo — legal-entity configuration.
//
// Single source of truth for company entity details that flow into every
// public legal page (/terms, /privacy, /cookies, /subscription, /imprint),
// the imprint footer, and the contact-form responses.
//
// Edit THIS FILE (and re-deploy) to flip jurisdiction between NL and ES
// once incorporation is complete. The legal-doc body copy lives in
// `legal-content.ts` and reads from this module's `ENTITY` export.
//
// IMPORTANT: most fields are still placeholders. Real values land when
// Sebastian completes incorporation (either NL/Amsterdam or ES/Barcelona).
// Until then, the public legal routes render with placeholder strings
// AND a banner that reads "Pulpo is currently being incorporated — the
// entity details on this page will be finalised before the first live
// Stripe Checkout session." The banner suppresses itself once
// `ENTITY.incorporated === true`.

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
    legal_name: "[NOMBRE REGISTRADO COMPLETO] S.A. de C.V.",
    legal_form: "Sociedad Anónima de Capital Variable (S.A. de C.V.)",
    incorporated: false,
    chamber_of_commerce: {
      authority: "Centro Nacional de Registros (CNR) — Registro de Comercio",
      number: "[NÚMERO DE REGISTRO]",
    },
    tax_id: { label: "NIT", value: "[NIT]" },
    address: {
      street: "[CALLE Y NÚMERO]",
      postcode: "[CÓDIGO POSTAL]",
      city: "San Salvador",
      country: "El Salvador",
      country_code: "SV",
    },
    director: { name: "[NOMBRE LEGAL COMPLETO]", role: "Representante Legal" },
    phone: "+503 [NÚMERO]",
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
export function formatAddress(entity: EntityConfig = ENTITY): string {
  const a = entity.address;
  return `${a.street}, ${a.postcode} ${a.city}, ${a.country}`;
}

// Convenience: "KvK 12345678 | BTW NL123456789B01" or local equivalent.
export function formatRegistration(entity: EntityConfig = ENTITY): string {
  return `${entity.chamber_of_commerce.authority} ${entity.chamber_of_commerce.number} | ${entity.tax_id.label} ${entity.tax_id.value}`;
}

// EU ODR platform URL — required for EU B2C e-commerce per Regulation (EU)
// No 524/2013.
export const EU_ODR_PLATFORM_URL = "https://ec.europa.eu/consumers/odr";

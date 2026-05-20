// Pulpo — legal-page content registry.
//
// One file holds every paragraph the public legal routes render. Lawyer
// reviews the markdown drafts in `legal_documents/01-…07-*.md` (gitignored
// working copies), then the blessed prose is hand-copied here in a
// follow-up PR. Until counsel review, every page renders a banner that
// reads "Pulpo is currently being incorporated — legal copy on this page
// is a working draft pending counsel review."
//
// All entity-specific placeholders read from ENTITY in `./legal-entity.ts`
// so flipping VITE_LEGAL_JURISDICTION between NL and ES re-interpolates
// the entire content without touching this file.
//
// Adding a new section: extend the corresponding *_SECTIONS array
// below — the route components render `sections.map(...)` so a new
// section appears with no component change. Pass `{ if: (e) => …}` to
// gate a section on jurisdiction-specific or feature-specific predicates.

import { ENTITY, EU_ODR_PLATFORM_URL, JURISDICTION, formatAddress, formatRegistration } from "./legal-entity";

/**
 * One block of legal copy. `body` accepts ReactNode-as-string templates;
 * downstream renderer (`web/app/pages/legal/*.jsx`) does the interpolation.
 */
export interface LegalSection {
  id: string;
  heading: { en: string; es: string };
  body: { en: string; es: string };
  /** Optional predicate to gate this section by jurisdiction etc. */
  if?: () => boolean;
}

export interface LegalDocument {
  slug: "terms" | "privacy" | "cookies" | "subscription" | "imprint";
  /** Page <title> attribute via useDocumentMeta. */
  title: { en: string; es: string };
  /** <meta name="description"> */
  description: { en: string; es: string };
  /** Banner displayed at the top of every legal page while review is
   *  pending. Setting `review_complete` flips this off in the route. */
  review_complete: boolean;
  last_updated: string; // ISO yyyy-mm-dd; updated when prose changes.
  sections: LegalSection[];
}

// ── Common placeholder copy ──────────────────────────────────────────
// Each page ships with skeleton sections so the route renders end-to-end
// in CI today. Lawyer-blessed prose lands incrementally in follow-up PRs.

const PLACEHOLDER_BODY = {
  en:
    "This section is a working draft pending counsel review. " +
    "Lawyer-blessed prose lands in a follow-up PR before the first " +
    "live Stripe Checkout session.",
  es:
    "Esta sección es un borrador pendiente de revisión legal. " +
    "El texto definitivo se publicará en una próxima entrega antes " +
    "del primer pago real con Stripe Checkout.",
};

// ── Document 1: Terms of Service ─────────────────────────────────────

export const TERMS: LegalDocument = {
  slug: "terms",
  title: {
    en: "Terms of Service · Pulpo",
    es: "Términos del servicio · Pulpo",
  },
  description: {
    en: "The rules of using Pulpo — the land-investment marketplace by Pulpo.",
    es: "Las reglas para usar Pulpo — el marketplace de inversión en suelo.",
  },
  review_complete: false,
  last_updated: "2026-05-19",
  sections: [
    {
      id: "parties",
      heading: { en: "1. Parties", es: "1. Partes" },
      body: {
        en:
          `These Terms of Service ("Terms") govern your use of Pulpo (the "Service"), ` +
          `operated by ${ENTITY.legal_name}, a ${ENTITY.legal_form} ` +
          `registered at ${formatAddress()} (${formatRegistration()}). ` +
          `"Pulpo", "we", and "us" refer to ${ENTITY.legal_name}.`,
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "service",
      heading: { en: "2. Nature of Service", es: "2. Naturaleza del servicio" },
      body: {
        en:
          "Pulpo is an informational marketplace that aggregates land-investment listings " +
          "from publicly available third-party sources and applies AI enrichment to provide " +
          "standardised summaries. Pulpo is not a real-estate agent, broker, or seller and " +
          "does not verify the accuracy, currency, or availability of any listing. Users " +
          "must conduct their own due diligence before making any investment decision.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "account",
      heading: { en: "3. Account & Eligibility", es: "3. Cuenta y elegibilidad" },
      body: {
        en:
          "You must be at least 18 years old and legally capable of entering into binding " +
          "contracts. By creating an account you confirm these facts. You are responsible " +
          "for maintaining the confidentiality of your account credentials.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "subscription",
      heading: { en: "4. Subscriptions and Payment", es: "4. Suscripciones y pago" },
      body: {
        en:
          "Subscription plans, pricing, promotional free months, auto-renewal disclosures, " +
          "the EU 14-day withdrawal right, and refund mechanics are set out in our " +
          "Subscription Policy at /subscription, which is incorporated by reference. " +
          "Payment is processed by Stripe Payments Europe Ltd acting as a data processor. " +
          "By subscribing you agree to Stripe's services agreement.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "acceptable-use",
      heading: { en: "5. Acceptable Use", es: "5. Uso aceptable" },
      body: {
        en:
          "You may not: (a) scrape, re-publish, or commercially redistribute listing content; " +
          "(b) reverse-engineer Pulpo's ranking models or AI enrichment pipeline; " +
          "(c) attempt to gain unauthorised access to any part of the platform; " +
          "(d) use the Service for any unlawful purpose or in violation of any applicable law.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "ip",
      heading: { en: "6. Intellectual Property", es: "6. Propiedad intelectual" },
      body: {
        en:
          `All software, design, ranking algorithms, AI-generated enrichment text, and database ` +
          `compilations are owned by or licensed to ${ENTITY.legal_name} and protected by EU ` +
          `database rights (Directive 96/9/EC) and copyright law. Nothing in these Terms grants ` +
          `you any IP rights beyond the right to use the Service for personal, non-commercial ` +
          `purposes.`,
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "third-party",
      heading: { en: "7. Third-Party Content", es: "7. Contenido de terceros" },
      body: {
        en:
          "Listings are sourced from third-party portals and may contain inaccuracies. Pulpo " +
          "does not warrant that any listing is current, accurate, or available. The original " +
          "listing source is identified on each listing card. You should independently verify " +
          "all listing details before taking any action.\n\n" +
          "If you are a broker, photographer, or rights holder and would like a specific " +
          "listing or photo removed from Pulpo, please contact us at legal@pulpo.club. " +
          "We commit to acknowledging takedown requests within 48 hours and removing the " +
          "content within 7 business days of a valid request.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "disclaimer",
      heading: { en: "8. Disclaimers and Liability", es: "8. Exenciones y responsabilidad" },
      body: {
        en:
          `TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW: the Service is provided "as is" ` +
          `without warranties of any kind. ${ENTITY.legal_name} is not liable for any investment ` +
          `decisions made on the basis of listing information on the platform. ` +
          `${ENTITY.legal_name}'s aggregate liability to you for any claim arising under these ` +
          `Terms shall not exceed the fees you paid in the 12 months preceding the claim. ` +
          `Nothing in these Terms limits liability for death, personal injury caused by ` +
          `negligence, fraud, or any other liability that cannot be excluded by law.`,
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "law",
      heading: { en: "9. Governing Law and Disputes", es: "9. Ley aplicable y disputas" },
      body: {
        en:
          `These Terms are governed by ${ENTITY.governing_law}. You and Pulpo submit to the ` +
          `exclusive jurisdiction of the ${ENTITY.courts}. If you are a consumer in the EU, ` +
          `you retain the right to bring proceedings in the courts of your country of ` +
          `residence.\n\nEU Online Dispute Resolution (ODR) platform (required by EU law): ` +
          `${EU_ODR_PLATFORM_URL}`,
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "changes",
      heading: { en: "10. Changes to these Terms", es: "10. Cambios en los términos" },
      body: {
        en:
          "We will give at least 30 days' notice of material changes via email to registered " +
          "users. Continued use of the Service after the notice period constitutes acceptance " +
          "of the revised Terms. If you do not accept the changes, you may cancel your account " +
          "before they take effect.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "contact",
      heading: { en: "11. Contact", es: "11. Contacto" },
      body: {
        en:
          `${ENTITY.legal_name}\n${formatAddress()}\n${formatRegistration()}\n\n` +
          `General: https://pulpo.club/contact · contact@pulpo.club\n` +
          `Privacy / data requests: privacy@pulpo.club\n` +
          `Legal / disputes: legal@pulpo.club`,
        es: PLACEHOLDER_BODY.es,
      },
    },
  ],
};

// ── Document 2: Privacy Policy ───────────────────────────────────────

export const PRIVACY: LegalDocument = {
  slug: "privacy",
  title: {
    en: "Privacy Policy · Pulpo",
    es: "Política de privacidad · Pulpo",
  },
  description: {
    en: "What data Pulpo collects, why, and how to exercise your rights.",
    es: "Qué datos recopila Pulpo, por qué, y cómo ejercer tus derechos.",
  },
  review_complete: false,
  last_updated: "2026-05-19",
  sections: [
    {
      id: "controller",
      heading: { en: "Who we are", es: "Quiénes somos" },
      body: {
        en:
          `${ENTITY.legal_name} ("Pulpo", "we", "us", "our") operates the Pulpo platform — ` +
          `a land-investment listing aggregator. We are the data controller for all personal ` +
          `data collected through this platform. Contact us at privacy@pulpo.club.\n\n` +
          `Registered address: ${formatAddress()}.\n${formatRegistration()}.`,
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "data-collected",
      heading: { en: "Data we collect and legal bases", es: "Datos que recopilamos y bases legales" },
      body: {
        en:
          "We collect:\n" +
          "• Account data (email, name, OAuth tokens) — Art. 6(1)(b) contract performance.\n" +
          "• Payment data (name, billing address, last 4 of card; Stripe tokenises full card data) — Art. 6(1)(b).\n" +
          "• Transactional email (account confirmation, password reset, receipts) — Art. 6(1)(b).\n" +
          "• Newsletter subscription (email, preferences) — Art. 6(1)(a) explicit opt-in, withdrawable any time.\n" +
          "• Usage analytics via PostHog (page events, 10% session replay sample with masked inputs) — Art. 6(1)(a) consent.\n" +
          "• Map interaction data (approximate coordinates sent to Mapbox) — Art. 6(1)(f) legitimate interest.\n" +
          "• AI enrichment inputs (listing text only — no user PII) — Art. 6(1)(f) legitimate interest.\n" +
          "• Edge / hosting logs (IP, user-agent, geo-region) — Art. 6(1)(f) security and fraud prevention.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "sub-processors",
      heading: { en: "Sub-processors", es: "Sub-procesadores" },
      body: {
        en:
          "We use the following sub-processors, each under a written Data Processing Agreement (DPA):\n\n" +
          "• Clerk (US) — Authentication. EU-US DPF + SCCs. clerk.com/legal/dpa\n" +
          "• Stripe (IE/US) — Payments. EU-US DPF + SCCs. stripe.com/nl/legal/dpa\n" +
          "• PostHog EU Cloud (Frankfurt) — Product analytics, 10% session replay sample, EU-hosted. EU-US DPF + SCCs. posthog.com/dpa\n" +
          "• Resend (US) — Transactional + newsletter email. EU-US DPF + SCCs. resend.com/legal/dpa\n" +
          "• Mapbox (US) — Map tiles + geocoding. EU-US DPF (certified 2023). mapbox.com/legal/privacy\n" +
          "• Vercel (US/EU) — Hosting + CDN. EU-US DPF + SCCs. vercel.com/legal/dpa\n" +
          "• DeepSeek (China) — Listing-text enrichment. Receives listing text only; no user-identifiable data is transmitted. Not a personal-data processor under GDPR Art. 4(8) for our use case.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "transfers",
      heading: { en: "International transfers", es: "Transferencias internacionales" },
      body: {
        en:
          "Where personal data is transferred outside the EEA, we rely on:\n" +
          "• EU Standard Contractual Clauses (SCCs) — Commission Decision 2021/914.\n" +
          "• EU-US Data Privacy Framework (DPF) — where the processor is certified.\n" +
          "The applicable transfer mechanism for each sub-processor is listed above.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "retention",
      heading: { en: "Retention periods", es: "Períodos de retención" },
      body: {
        en:
          "• Account data: Duration of account + 90 days after deletion request.\n" +
          "• Payment / billing records: 7 years (Dutch belastingdienst / VAT obligation).\n" +
          "• Transactional email logs: 90 days.\n" +
          "• Newsletter subscription: Until opt-out + 30 days.\n" +
          "• Analytics events (PostHog): 12 months rolling.\n" +
          "• Session replays (PostHog): 3 months (10% sample).\n" +
          "• Edge / CDN logs (Vercel): 30 days (Vercel default).",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "rights",
      heading: { en: "Your rights", es: "Tus derechos" },
      body: {
        en:
          "Under GDPR (EU/UK) and LGPD (Brazil) you have the rights of access, rectification, " +
          "erasure (subject to legal retention), portability, restriction, objection, and to " +
          "withdraw consent. Exercise any right by emailing privacy@pulpo.club with subject " +
          'line "Data Rights Request — [RIGHT TYPE]". We respond within 30 days (GDPR Art. ' +
          "12(3)) or 15 business days (LGPD Art. 19).\n\n" +
          "Supervisory authorities you may lodge a complaint with:\n" +
          `• ${ENTITY.supervisory_authority.name}: ${ENTITY.supervisory_authority.url}\n` +
          "• UK ICO: ico.org.uk\n" +
          "• ANPD (Brazil): gov.br/anpd\n" +
          "• Argentina AAIP, Chile CPLT, Mexico INAI — contact privacy@pulpo.club for details.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "automated-decisions",
      heading: { en: "Automated decision-making", es: "Decisiones automatizadas" },
      body: {
        en:
          "Pulpo uses ranking algorithms and AI enrichment to score and rank listings. These " +
          "scores affect which listings are displayed first, but no automated decision produces " +
          "a legal or similarly significant effect on you as a user (GDPR Art. 22 does not " +
          "apply). The algorithms operate on listing data, not personal data, for this purpose.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "minors",
      heading: { en: "Minors", es: "Menores" },
      body: {
        en:
          "The Service is not directed at persons under 18. We do not knowingly collect " +
          "personal data from minors. Contact privacy@pulpo.club if you believe a minor has " +
          "registered.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "changes",
      heading: { en: "Changes", es: "Cambios" },
      body: {
        en:
          "Material changes will be announced by email at least 30 days before taking effect. " +
          "The current version is always available at /privacy.",
        es: PLACEHOLDER_BODY.es,
      },
    },
  ],
};

// ── Document 3: Cookie Policy ────────────────────────────────────────

export const COOKIES: LegalDocument = {
  slug: "cookies",
  title: { en: "Cookie Policy · Pulpo", es: "Política de cookies · Pulpo" },
  description: {
    en: "Which cookies Pulpo uses, why, and how to opt out.",
    es: "Qué cookies usa Pulpo, por qué, y cómo darte de baja.",
  },
  review_complete: false,
  last_updated: "2026-05-19",
  sections: [
    {
      id: "intro",
      heading: { en: "Introduction", es: "Introducción" },
      body: {
        en:
          "Pulpo uses cookies and similar storage technologies to deliver the service, " +
          "remember your preferences, and (with your consent) measure how the platform is " +
          "used. Strictly-necessary cookies cannot be switched off. All other categories " +
          "default to OFF and require your explicit consent via the cookie banner. You can " +
          "re-open your cookie preferences at any time from the link in the site footer.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "strictly-necessary",
      heading: { en: "Category 1 — Strictly necessary", es: "Categoría 1 — Estrictamente necesarias" },
      body: {
        en:
          "These cookies are essential for the Service to function. They cannot be switched " +
          "off and do not store personally identifiable information.\n\n" +
          "• __session, __client, __clerk_db_jwt (Clerk) — Authentication.\n" +
          "• stripe.sid (Stripe) — Checkout session continuity.\n" +
          "• consent_v (Pulpo) — Stores your consent choice + version.\n" +
          "• pulpo-locale, ls_view_pref, ls_saved (Pulpo localStorage) — Preferences and pre-login saved listings.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "analytics",
      heading: { en: "Category 2 — Analytics (consent required — OFF by default)", es: "Categoría 2 — Analíticas (requiere consentimiento — desactivadas por defecto)" },
      body: {
        en:
          "Used to understand how visitors interact with the platform. Session replays are " +
          "sampled at 10% of sessions and all form fields are masked.\n\n" +
          "• ph_* (PostHog) — Analytics events, funnels, feature flags.\n" +
          "• ph_session_* (PostHog) — Session replay (10% sample, EU-hosted, masked).\n\n" +
          "PostHog is deployed on EU Cloud (Frankfurt). IP-address capture is disabled at the " +
          "organisation level per PostHog's EU Cloud default configuration.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "functional",
      heading: { en: "Category 3 — Functional (consent required — OFF by default)", es: "Categoría 3 — Funcionales (requiere consentimiento — desactivadas por defecto)" },
      body: {
        en:
          "These cookies enable optional features that improve your experience but are not " +
          "required for core functionality.\n\n" +
          "• mapbox.session (Mapbox) — Map-tile caching, user-location centring.\n" +
          "• resend_p (Resend) — Newsletter open/click tracking pixel.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "manage",
      heading: { en: "How to manage cookies", es: "Cómo gestionar las cookies" },
      body: {
        en:
          '• Click "Cookie Preferences" in the site footer at any time.\n' +
          "• Analytics and functional cookies are removed immediately if you withdraw consent.\n" +
          "• Use your browser's settings to block or delete cookies. Blocking strictly-necessary " +
          "cookies will break login functionality.",
        es: PLACEHOLDER_BODY.es,
      },
    },
  ],
};

// ── Document 4: Subscription & Refund Policy ─────────────────────────

export const SUBSCRIPTION: LegalDocument = {
  slug: "subscription",
  title: { en: "Subscription & Refund Policy · Pulpo", es: "Política de suscripción y reembolsos · Pulpo" },
  description: {
    en: "Pulpo Pro pricing, promotional free months, auto-renewal, cancellation, and refunds.",
    es: "Precios, meses promocionales, renovación, cancelación y reembolsos de Pulpo Pro.",
  },
  review_complete: false,
  last_updated: "2026-05-19",
  sections: [
    {
      id: "plans",
      heading: { en: "1. Plans and pricing", es: "1. Planes y precios" },
      body: {
        en:
          "Free Plan — Unlimited browse of listing cards; limited full listing detail views per " +
          "session; newsletter opt-in available.\n\n" +
          "Paid Plan (Pulpo Pro) — Full access: unlimited detail views, saved listings, weekly " +
          "deal digest, advanced filters. Price: €10.00 per month (or USD equivalent at the " +
          "rate displayed at checkout; geo-determined).",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "promotional-free-months",
      heading: { en: "2. Promotional free months (when offered)", es: "2. Meses gratis promocionales (cuando se ofrezcan)" },
      body: {
        en:
          "Pulpo Pro is a paid subscription from the moment you subscribe. We may, from time " +
          "to time, offer promotional free months — for example, our current launch promotion " +
          "grants new subscribers 1 month free before the first paid charge. These promotions " +
          "are perks, not guarantees, and may change or end at any time without notice.\n\n" +
          "• Promotional codes may extend the free period further (commonly 2, 3, or 6 months) " +
          "or apply other discounts. The promotion applied to your subscription, and the date " +
          "of your first paid charge, are shown on the Stripe Checkout summary before you " +
          "confirm payment.\n" +
          "• A payment method is collected at checkout. During any free promotional period the " +
          "card is authorised but not charged.\n" +
          "• If a free promotional period applies, we will send you a reminder email at least " +
          "5 days before the first paid charge.\n" +
          "• You may cancel during a free promotional period at any time — see Cancellation " +
          "below — and you will not be charged.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "paid-auto-renewal",
      heading: { en: "3. Paid subscription and auto-renewal", es: "3. Suscripción de pago y renovación automática" },
      body: {
        en:
          "Your subscription begins on the date your payment is confirmed by Stripe. If a " +
          "promotional free period applies, the first paid charge is deferred by the number " +
          "of free months in that promotion; otherwise, the first charge runs at checkout.\n\n" +
          "Your subscription renews automatically each month on the anniversary of the first " +
          "paid charge. You will be charged €10.00 + applicable VAT per month. A receipt is " +
          "sent by email after each charge. After any initial fixed term, your subscription " +
          "continues on a month-to-month basis (Dutch consumer-law requirement).",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "cancellation",
      heading: { en: "4. Cancellation", es: "4. Cancelación" },
      body: {
        en:
          "You may cancel at any time:\n" +
          "(a) Online: Account → Settings → Subscription → Manage plan → Cancel (opens the " +
          "Stripe Customer Portal).\n" +
          '(b) Email: privacy@pulpo.club — subject: "Cancel Subscription".\n\n' +
          "After cancellation:\n" +
          "• Paid Plan access continues until the end of the current billing period.\n" +
          "• No further charges are made.\n" +
          "• Your account reverts to the Free Plan at period end.\n" +
          "• You are not moved to a new fixed-term contract.\n\n" +
          "To avoid being charged for the next month, cancel at least 1 day before your renewal date.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "withdrawal",
      heading: { en: "5. EU statutory 14-day withdrawal right", es: "5. Derecho de desistimiento de 14 días (UE)" },
      body: {
        en:
          "If you are a consumer in the EU or UK, you have a statutory right to withdraw from " +
          "your paid subscription within 14 days of subscribing, without giving any reason, " +
          "and receive a full refund.\n\n" +
          'To exercise: email privacy@pulpo.club within 14 days of your subscription start ' +
          'date with subject line "Withdrawal from Subscription". We will refund you within ' +
          "14 days to the original payment method.\n\n" +
          "Partial-performance note: by beginning to use Pulpo Pro before the 14-day period " +
          "expires, you acknowledge that you are requesting immediate performance of the " +
          "service. If you withdraw having already used the service, we may charge a " +
          "proportional amount for the days of service already provided (Directive 2011/83/EU, " +
          "Art. 14(3)).",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "refunds",
      heading: { en: "6. Refunds", es: "6. Reembolsos" },
      body: {
        en:
          "Outside the 14-day withdrawal window, Pulpo does not offer refunds for partial " +
          "billing periods already in progress.\n\n" +
          "Exceptions (at our discretion):\n" +
          "• Material service outage attributable to Pulpo exceeding 24 hours in a billing period.\n" +
          "• Billing errors (double charges, incorrect amounts).\n\n" +
          'Request a refund: privacy@pulpo.club — subject: "Refund Request". We respond within ' +
          "5 business days.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "price-changes",
      heading: { en: "7. Price changes", es: "7. Cambios de precio" },
      body: {
        en:
          "We will give at least 30 days' advance notice of price changes via email to all " +
          "active subscribers. If you do not cancel before the new price takes effect, " +
          "continued use constitutes acceptance.",
        es: PLACEHOLDER_BODY.es,
      },
    },
    {
      id: "vat",
      heading: { en: "8. VAT", es: "8. IVA" },
      body: {
        en:
          "Prices are exclusive of VAT. VAT is charged at the rate applicable to your country " +
          "of residence or establishment, in accordance with EU VAT Directive rules for digital " +
          "services.",
        es: PLACEHOLDER_BODY.es,
      },
    },
  ],
};

// ── Document 5: Imprint ──────────────────────────────────────────────

export const IMPRINT: LegalDocument = {
  slug: "imprint",
  title: { en: "Imprint · Pulpo", es: "Aviso legal · Pulpo" },
  description: {
    en: "Pulpo company entity disclosure and legal notice.",
    es: "Aviso legal y datos de la empresa de Pulpo.",
  },
  review_complete: false,
  last_updated: "2026-05-19",
  sections: [
    {
      id: "entity",
      heading: { en: "Legal notice", es: "Aviso legal" },
      body: {
        en:
          `Legal entity: ${ENTITY.legal_name}\n` +
          `Trade name: ${ENTITY.trade_name}\n` +
          `Legal form: ${ENTITY.legal_form}\n` +
          `${ENTITY.chamber_of_commerce.authority}: ${ENTITY.chamber_of_commerce.number}\n` +
          `${ENTITY.tax_id.label}: ${ENTITY.tax_id.value}\n` +
          `Registered address: ${formatAddress()}\n` +
          `Director: ${ENTITY.director.name} (${ENTITY.director.role})\n` +
          `Email: contact@pulpo.club (via /contact)\n` +
          `Phone: ${ENTITY.phone}\n` +
          `Website: https://pulpo.club\n\n` +
          `Platform hosted by: Vercel, Inc. / Vercel Hosting B.V.\n` +
          `Authentication: Clerk, Inc.\n` +
          `Payments: Stripe Payments Europe Ltd (Dublin, Ireland)\n\n` +
          `Supervisory authority (data protection):\n` +
          `${ENTITY.supervisory_authority.name}\n` +
          `${ENTITY.supervisory_authority.url}\n\n` +
          `Consumer disputes:\n` +
          `${ENTITY.courts}\n` +
          `EU ODR platform: ${EU_ODR_PLATFORM_URL}`,
        es: PLACEHOLDER_BODY.es,
      },
    },
  ],
};

// ── Public registry ──────────────────────────────────────────────────

export const ALL_DOCUMENTS: readonly LegalDocument[] = [
  TERMS,
  PRIVACY,
  COOKIES,
  SUBSCRIPTION,
  IMPRINT,
];

export function findDocument(slug: LegalDocument["slug"]): LegalDocument | undefined {
  return ALL_DOCUMENTS.find((d) => d.slug === slug);
}

// True while ANY of the documents is still pending counsel review. Used by
// the route components to render a uniform "working draft" banner.
export const REVIEW_PENDING_GLOBAL: boolean = ALL_DOCUMENTS.some((d) => !d.review_complete);

// Re-export for convenience to the route components.
export { ENTITY, JURISDICTION, formatAddress, formatRegistration };

// Pulpo — legal-page content registry.
//
// One file holds every paragraph the public legal routes render. The
// shared renderer is `web/app/pages/legal/LegalPage.jsx`; adding/removing
// a section means editing prose here, not JSX.
//
// All entity-specific placeholders read from ENTITY in `./legal-entity.ts`
// so flipping VITE_LEGAL_JURISDICTION between SV / NL / ES re-interpolates
// the entire content without touching this file.
//
// Current default jurisdiction: SV (El Salvador). The Salvadoran copy is
// anchored to the Ley de Comercio Electrónico (D.L. 947/2020), the Ley
// de Protección al Consumidor (D.L. 776/2005), Art. 2 de la Constitución
// (habeas data), and the Ley Especial Contra los Delitos Informáticos y
// Conexos (D.L. 260/2016).
//
// IMPORTANT: this copy is the operator's best-effort draft, written in
// plain language for end users. It is NOT a substitute for ad-hoc review
// by a licensed Salvadoran abogado, which is planned separately. Once
// counsel signs off, no further changes to copy or banner state are
// required here — the `review_complete: true` flag below already
// suppresses the "working draft" banner.
//
// Adding a new section: extend the corresponding *_SECTIONS array
// below — the route components render `sections.map(...)` so a new
// section appears with no component change. Pass `{ if: (e) => …}` to
// gate a section on jurisdiction-specific or feature-specific predicates.

import { ENTITY, JURISDICTION, formatAddress, formatRegistration } from "./legal-entity";

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
   *  pending. Setting `review_complete: true` flips this off in the route. */
  review_complete: boolean;
  last_updated: string; // ISO yyyy-mm-dd; updated when prose changes.
  sections: LegalSection[];
}

const SUPPORT_EMAIL = "hello@pulpo.club";

// ── Document 1: Terms of Service ─────────────────────────────────────

export const TERMS: LegalDocument = {
  slug: "terms",
  title: {
    en: "Terms of Service · Pulpo",
    es: "Términos del servicio · Pulpo",
  },
  description: {
    en: "The plain-language rules of using Pulpo — what we do, what you can expect from us, and what we ask from you.",
    es: "Las reglas claras para usar Pulpo — qué hacemos, qué puedes esperar de nosotros, y qué te pedimos a ti.",
  },
  review_complete: true,
  last_updated: "2026-05-20",
  sections: [
    {
      id: "intro",
      heading: { en: "In short", es: "En pocas palabras" },
      body: {
        en:
          "Pulpo helps you find land for sale in El Salvador. We collect listings from public sources, organise them, and let you save, filter, and read enriched summaries. We are not a real-estate agent — we are an information platform.\n\n" +
          "Using Pulpo means you accept these Terms. They are written to be readable, not lawyerly. If anything is unclear, write to " + SUPPORT_EMAIL + " and we will explain.",
        es:
          "Pulpo te ayuda a encontrar terrenos a la venta en El Salvador. Reunimos anuncios de fuentes públicas, los organizamos, y te dejamos guardarlos, filtrarlos y leer resúmenes enriquecidos. No somos una agencia inmobiliaria — somos una plataforma de información.\n\n" +
          "Usar Pulpo significa que aceptas estos Términos. Están escritos para que se entiendan, no para parecer un contrato pesado. Si algo no queda claro, escríbenos a " + SUPPORT_EMAIL + " y te lo explicamos.",
      },
    },
    {
      id: "parties",
      heading: { en: "Who we are", es: "Quiénes somos" },
      body: {
        en:
          `Pulpo ("we", "us", "our") is an online land-investment platform based in ${formatAddress()}. ` +
          `The platform is operated under ${ENTITY.governing_law}, and our consumer-protection obligations are governed by the Ley de Protección al Consumidor (D.L. 776/2005) and the Ley de Comercio Electrónico (D.L. 947/2020). ` +
          `For any matter — questions, complaints, claims, takedowns, or data-protection requests — you can reach us at ${SUPPORT_EMAIL}.`,
        es:
          `Pulpo ("nosotros") es una plataforma en línea de inversión en suelo, con sede en ${formatAddress()}. ` +
          `La plataforma se opera bajo las ${ENTITY.governing_law}, y nuestras obligaciones de protección al consumidor están regidas por la Ley de Protección al Consumidor (D.L. 776/2005) y la Ley de Comercio Electrónico (D.L. 947/2020). ` +
          `Para cualquier asunto — consultas, reclamos, denuncias, eliminación de contenido, o solicitudes sobre protección de datos — puedes contactarnos en ${SUPPORT_EMAIL}.`,
      },
    },
    {
      id: "service",
      heading: { en: "What Pulpo does", es: "Qué hace Pulpo" },
      body: {
        en:
          "Pulpo is an information marketplace for land investments in El Salvador. We aggregate listings published on public real-estate portals, normalise them into a consistent format, and use AI to write short summaries and infer features (e.g. \"build-ready\", \"beachfront\", distance to the nearest beach).\n\n" +
          "What Pulpo IS:\n" +
          "• A discovery tool to compare listings.\n" +
          "• A way to save listings and get filtered views.\n" +
          "• A source of plain-language summaries.\n\n" +
          "What Pulpo IS NOT:\n" +
          "• A real-estate broker, agent, or seller.\n" +
          "• A guarantee that a listing is current, accurate, or available.\n" +
          "• A substitute for visiting the property, hiring a notario, or doing a title search at the Centro Nacional de Registros (CNR).\n\n" +
          "Before you put any money on the table, do your own due diligence — visit the lot, verify the title in the CNR, talk to a notario.",
        es:
          "Pulpo es un marketplace de información sobre inversión en suelo en El Salvador. Reunimos anuncios publicados en portales inmobiliarios públicos, los normalizamos a un formato consistente, y usamos IA para escribir resúmenes cortos y deducir características (por ejemplo, \"listo para construir\", \"frente de playa\", o distancia a la playa más cercana).\n\n" +
          "Lo que Pulpo SÍ es:\n" +
          "• Una herramienta para descubrir y comparar terrenos.\n" +
          "• Una forma de guardar anuncios y filtrarlos.\n" +
          "• Una fuente de resúmenes en lenguaje claro.\n\n" +
          "Lo que Pulpo NO es:\n" +
          "• Una corredora ni agencia inmobiliaria, ni vendedor.\n" +
          "• Una garantía de que un anuncio esté vigente, sea exacto, o esté disponible.\n" +
          "• Un sustituto de visitar el terreno, contratar a un notario, o hacer una búsqueda de título en el Centro Nacional de Registros (CNR).\n\n" +
          "Antes de poner dinero, haz tu propia investigación — visita el terreno, verifica el título en el CNR, y consulta con un notario.",
      },
    },
    {
      id: "account",
      heading: { en: "Your account", es: "Tu cuenta" },
      body: {
        en:
          "To create an account you must be at least 18 years old and legally able to enter into a contract. By signing up you confirm both. You are responsible for keeping your password safe and for everything done through your account. If you suspect someone else has access, tell us at " + SUPPORT_EMAIL + " right away.",
        es:
          "Para abrir una cuenta debes tener al menos 18 años y capacidad legal para contratar. Al registrarte confirmas ambas cosas. Eres responsable de cuidar tu contraseña y de todo lo que se haga desde tu cuenta. Si crees que alguien más tiene acceso, escríbenos a " + SUPPORT_EMAIL + " de inmediato.",
      },
    },
    {
      id: "subscription",
      heading: { en: "Plans and payment", es: "Planes y pago" },
      body: {
        en:
          "Pulpo has a free plan and a paid plan (Pulpo Pro). The full details of pricing, free trial months, auto-renewal, cancellation, and your statutory right of withdrawal (5 business days, per Art. 15 de la Ley de Comercio Electrónico) are in our Subscription Policy at /subscription — that page is part of these Terms.\n\n" +
          "Payments are processed by Stripe Payments Europe Ltd. on our behalf. By subscribing, you also accept Stripe's terms of service.",
        es:
          "Pulpo tiene un plan gratuito y un plan de pago (Pulpo Pro). Los detalles completos sobre precios, meses promocionales gratuitos, renovación automática, cancelación, y tu derecho de retracto por ley (5 días hábiles, según el Art. 15 de la Ley de Comercio Electrónico) están en nuestra Política de Suscripción en /subscription — esa página forma parte de estos Términos.\n\n" +
          "Los pagos los procesa Stripe Payments Europe Ltd. en nuestro nombre. Al suscribirte, aceptas también los términos de servicio de Stripe.",
      },
    },
    {
      id: "acceptable-use",
      heading: { en: "How you can use Pulpo", es: "Cómo puedes usar Pulpo" },
      body: {
        en:
          "Use Pulpo for personal, non-commercial decisions about land investments. Please don't:\n" +
          "• Scrape, copy, or re-publish listing content elsewhere.\n" +
          "• Reverse-engineer our ranking model, AI summaries, or other internals.\n" +
          "• Try to break, overload, or get unauthorised access to any part of the platform.\n" +
          "• Use Pulpo to do anything illegal under Salvadoran law, including any conduct covered by the Ley Especial Contra los Delitos Informáticos y Conexos.\n\n" +
          "If you break these rules, we may suspend or close your account.",
        es:
          "Usa Pulpo para tus decisiones personales — no comerciales — sobre inversión en suelo. Por favor, no:\n" +
          "• Hagas scraping, copies o republiques los anuncios en otros sitios.\n" +
          "• Intentes hacer ingeniería inversa de nuestro algoritmo de ranking, los resúmenes de IA, u otras partes internas.\n" +
          "• Intentes romper, sobrecargar, o acceder sin permiso a ninguna parte de la plataforma.\n" +
          "• Uses Pulpo para algo ilegal según la ley salvadoreña, incluyendo cualquier conducta cubierta por la Ley Especial Contra los Delitos Informáticos y Conexos.\n\n" +
          "Si rompes estas reglas, podemos suspender o cerrar tu cuenta.",
      },
    },
    {
      id: "ip",
      heading: { en: "Intellectual property", es: "Propiedad intelectual" },
      body: {
        en:
          `Everything that makes Pulpo "Pulpo" — software, design, ranking algorithm, AI-generated summaries, and the database of standardised listings — is owned by or licensed to ${ENTITY.legal_name}. It is protected by Salvadoran copyright law (Ley de Propiedad Intelectual, D.L. 604/1993) and any other applicable intellectual-property protections.\n\n` +
          "You get a personal, non-transferable, revocable right to use Pulpo. You do not get any right to copy, redistribute, or build derivative products on top of our content.",
        es:
          `Todo lo que hace que Pulpo sea "Pulpo" — software, diseño, algoritmo de ranking, resúmenes generados por IA, y la base de datos de anuncios estandarizados — pertenece o está licenciado a ${ENTITY.legal_name}. Está protegido por la legislación salvadoreña de derecho de autor (Ley de Propiedad Intelectual, D.L. 604/1993) y cualquier otra protección de propiedad intelectual aplicable.\n\n` +
          "Te damos un derecho personal, no transferible y revocable de usar Pulpo. No te damos derecho a copiar, redistribuir, ni construir productos derivados sobre nuestro contenido.",
      },
    },
    {
      id: "third-party",
      heading: { en: "Third-party listings", es: "Anuncios de terceros" },
      body: {
        en:
          "Listings on Pulpo come from third-party real-estate portals. The original source is shown on each listing card. We do not guarantee that any listing is current, accurate, complete, or still available. Prices, ownership status, and property details can change without notice.\n\n" +
          "Always verify a listing directly with the seller, a real-estate broker, or a notario before taking any action.\n\n" +
          "If you are a broker, photographer, or rights-holder and want a listing or photo removed from Pulpo, write to " + SUPPORT_EMAIL + " with the subject \"Takedown\". We will acknowledge your request within 48 hours and act on a valid request within 7 working days.",
        es:
          "Los anuncios en Pulpo vienen de portales inmobiliarios de terceros. La fuente original se muestra en cada tarjeta de anuncio. No garantizamos que un anuncio esté vigente, sea exacto, esté completo, o siga disponible. Precios, situación de propiedad y detalles del terreno pueden cambiar sin aviso.\n\n" +
          "Verifica siempre un anuncio directamente con el vendedor, un corredor inmobiliario, o un notario antes de tomar cualquier acción.\n\n" +
          "Si eres corredor, fotógrafo o titular de derechos y quieres que se elimine un anuncio o foto de Pulpo, escríbenos a " + SUPPORT_EMAIL + " con el asunto \"Eliminación\". Acusaremos recibo dentro de 48 horas y atenderemos una solicitud válida en un máximo de 7 días hábiles.",
      },
    },
    {
      id: "disclaimer",
      heading: { en: "What we can and cannot promise", es: "Lo que podemos y no podemos prometer" },
      body: {
        en:
          `In plain words: Pulpo is provided "as is". We do our best, but we cannot promise the service will be uninterrupted, error-free, or that every listing is accurate. You make your own investment decisions, and we are not responsible for the outcome of those decisions.\n\n` +
          `Up to the maximum allowed by Salvadoran law: ${ENTITY.legal_name}'s total liability to you, for any claim related to these Terms or to Pulpo, is limited to what you paid us in the 12 months before the claim. Nothing in these Terms limits any liability that cannot be limited by law (for example, in cases of fraud or gross negligence).`,
        es:
          `En palabras simples: Pulpo se ofrece "tal como está". Hacemos lo mejor que podemos, pero no podemos prometer que el servicio sea ininterrumpido, sin errores, ni que todos los anuncios sean exactos. Tú tomas tus propias decisiones de inversión, y no somos responsables del resultado de esas decisiones.\n\n` +
          `Hasta el máximo permitido por la legislación salvadoreña: la responsabilidad total de ${ENTITY.legal_name} hacia ti, por cualquier reclamo relacionado con estos Términos o con Pulpo, se limita a lo que nos hayas pagado durante los 12 meses anteriores al reclamo. Nada en estos Términos limita responsabilidades que la ley no permite limitar (por ejemplo, en casos de fraude o culpa grave).`,
      },
    },
    {
      id: "consumer-rights",
      heading: { en: "Your consumer rights", es: "Tus derechos como consumidor" },
      body: {
        en:
          "If you are a consumer in El Salvador, the Ley de Protección al Consumidor (D.L. 776) protects you. Nothing in these Terms reduces those rights. In particular:\n\n" +
          "• You always have the right to clear pre-contract information about the service and its price.\n" +
          "• You have the right to claim before the Defensoría del Consumidor if you believe we have not met our obligations. You can file a claim at defensoria.gob.sv or by calling 910.\n" +
          "• Any clause in these Terms that conflicts with the Ley de Protección al Consumidor will be interpreted in the way most favourable to you.",
        es:
          "Si eres consumidor en El Salvador, la Ley de Protección al Consumidor (D.L. 776) te protege. Nada en estos Términos reduce esos derechos. En particular:\n\n" +
          "• Siempre tienes derecho a información clara, antes de contratar, sobre el servicio y su precio.\n" +
          "• Tienes derecho a presentar un reclamo ante la Defensoría del Consumidor si crees que no cumplimos con nuestras obligaciones. Puedes presentarlo en defensoria.gob.sv o llamando al 910.\n" +
          "• Cualquier cláusula de estos Términos que entre en conflicto con la Ley de Protección al Consumidor se interpretará de la forma más favorable para ti.",
      },
    },
    {
      id: "law",
      heading: { en: "Governing law and disputes", es: "Ley aplicable y disputas" },
      body: {
        en:
          `These Terms are governed by ${ENTITY.governing_law}. If we cannot resolve a dispute between us directly, you can:\n\n` +
          "1. Try the friendly route first: email " + SUPPORT_EMAIL + " explaining the issue. We commit to responding within 5 business days.\n" +
          "2. Open a claim with the Defensoría del Consumidor (defensoria.gob.sv · 910) — a free, fast administrative channel for consumer disputes.\n" +
          `3. Bring the matter to the ${ENTITY.courts}.\n\n` +
          "If you are a consumer, you keep the right to bring proceedings before the courts of your country of residence to the extent local law gives you that right.",
        es:
          `Estos Términos se rigen por las ${ENTITY.governing_law}. Si no logramos resolver una disputa entre nosotros de forma directa, puedes:\n\n` +
          "1. Primero, la vía amistosa: escríbenos a " + SUPPORT_EMAIL + " explicando el problema. Nos comprometemos a responder en 5 días hábiles.\n" +
          "2. Abrir un reclamo en la Defensoría del Consumidor (defensoria.gob.sv · 910) — un canal administrativo gratuito y rápido para disputas de consumo.\n" +
          `3. Llevar el caso ante los ${ENTITY.courts}.\n\n` +
          "Si eres consumidor, conservas el derecho a presentar acciones ante los tribunales de tu país de residencia en la medida que la ley local te lo permita.",
      },
    },
    {
      id: "changes",
      heading: { en: "Changes to these Terms", es: "Cambios en estos Términos" },
      body: {
        en:
          "We will give you at least 30 days' notice by email before any material change takes effect. If you keep using Pulpo after that period, it means you accept the new version. If you do not, you can cancel your account before the changes apply. The latest version is always at pulpo.club/terms.",
        es:
          "Te avisaremos por correo con al menos 30 días de anticipación antes de que entre en vigor cualquier cambio importante. Si sigues usando Pulpo después de ese plazo, significa que aceptas la nueva versión. Si no, puedes cancelar tu cuenta antes de que los cambios apliquen. La versión más reciente siempre está en pulpo.club/terms.",
      },
    },
    {
      id: "contact",
      heading: { en: "Contact", es: "Contacto" },
      body: {
        en:
          `Pulpo\n${formatAddress()}\n\n` +
          `For anything — questions, complaints, takedowns, data requests: ${SUPPORT_EMAIL}\n` +
          `Or use the contact form at pulpo.club/contact.`,
        es:
          `Pulpo\n${formatAddress()}\n\n` +
          `Para cualquier cosa — preguntas, reclamos, eliminación de contenido, solicitudes de datos: ${SUPPORT_EMAIL}\n` +
          `O usa el formulario en pulpo.club/contact.`,
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
    en: "What data Pulpo collects, why, who we share it with, and how to ask us to delete it.",
    es: "Qué datos recopila Pulpo, por qué, con quién los compartimos, y cómo pedirnos que los eliminemos.",
  },
  review_complete: true,
  last_updated: "2026-05-20",
  sections: [
    {
      id: "intro",
      heading: { en: "In short", es: "En pocas palabras" },
      body: {
        en:
          "We collect the data we need to run Pulpo and nothing more. We do not sell your data. We do not share it with advertisers. We use a small set of trusted service providers (Stripe for payments, Clerk for login, Resend for email, PostHog for analytics, Vercel for hosting, Mapbox for maps) and you can ask us at any time what we hold and have us delete it.\n\n" +
          "Questions or requests: " + SUPPORT_EMAIL + ".",
        es:
          "Recopilamos solo los datos que necesitamos para que Pulpo funcione, y nada más. No vendemos tus datos. No los compartimos con anunciantes. Usamos un grupo pequeño de proveedores de confianza (Stripe para pagos, Clerk para inicio de sesión, Resend para correos, PostHog para análisis, Vercel para hosting, Mapbox para mapas) y puedes pedirnos en cualquier momento qué tenemos sobre ti y que lo eliminemos.\n\n" +
          "Preguntas o solicitudes: " + SUPPORT_EMAIL + ".",
      },
    },
    {
      id: "controller",
      heading: { en: "Who is responsible for your data", es: "Quién es responsable de tus datos" },
      body: {
        en:
          `Pulpo ("we", "us", "our") is the party responsible for the personal data we collect through pulpo.club. We operate from ${formatAddress()}, under ${ENTITY.governing_law}. For privacy questions, data-access requests, corrections, or deletion: ${SUPPORT_EMAIL}.`,
        es:
          `Pulpo ("nosotros") es el responsable de los datos personales que recopilamos a través de pulpo.club. Operamos desde ${formatAddress()}, bajo las ${ENTITY.governing_law}. Para preguntas de privacidad, acceso, rectificación o eliminación de datos: ${SUPPORT_EMAIL}.`,
      },
    },
    {
      id: "legal-basis",
      heading: { en: "Why we can hold your data (legal basis)", es: "Por qué podemos tener tus datos (base legal)" },
      body: {
        en:
          "We process personal data on the following grounds:\n\n" +
          "• To deliver the service you asked for: when you create an account, save listings, or subscribe, we need certain data to make the service work. This is the basis under Salvadoran contract law and the Ley de Comercio Electrónico (Arts. 8-13).\n" +
          "• With your consent: for analytics cookies, session replay, the newsletter, and any marketing email. You can withdraw consent at any time — it does not affect anything we already did legally.\n" +
          "• To comply with the law: invoicing, tax records, and responding to lawful requests from authorities.\n" +
          "• Our legitimate interest: security, fraud prevention, and improving Pulpo. Whenever we rely on this, we balance our interest against your rights.\n\n" +
          "Article 2 of the Constitución de la República de El Salvador (habeas data) and the Ley Especial Contra los Delitos Informáticos y Conexos (Arts. 24-25) are the foundation of how we handle data.",
        es:
          "Tratamos datos personales en estos supuestos:\n\n" +
          "• Para prestarte el servicio que pediste: cuando creas una cuenta, guardas anuncios o te suscribes, necesitamos ciertos datos para que el servicio funcione. Esta es la base bajo la legislación contractual salvadoreña y la Ley de Comercio Electrónico (Arts. 8-13).\n" +
          "• Con tu consentimiento: para las cookies de análisis, la repetición de sesión, el boletín y cualquier correo de marketing. Puedes retirar el consentimiento en cualquier momento — no afecta nada que ya hayamos hecho de forma legal antes.\n" +
          "• Para cumplir con la ley: facturación, registros fiscales y responder a requerimientos legítimos de autoridades.\n" +
          "• Nuestro interés legítimo: seguridad, prevención de fraude y mejora de Pulpo. Cuando nos apoyamos en este supuesto, ponderamos nuestro interés frente a tus derechos.\n\n" +
          "El Art. 2 de la Constitución de la República de El Salvador (habeas data) y la Ley Especial Contra los Delitos Informáticos y Conexos (Arts. 24-25) son la base de cómo manejamos tus datos.",
      },
    },
    {
      id: "data-collected",
      heading: { en: "What data we collect", es: "Qué datos recopilamos" },
      body: {
        en:
          "Account data: your email, name, and the login token created by Clerk.\n\n" +
          "Payment data: name, billing address, and the last four digits of your card. Your full card number is held by Stripe — we never see it or store it.\n\n" +
          "Transactional emails: account confirmation, password reset, receipts, and important service notices.\n\n" +
          "Newsletter (only if you opt in): your email and preferences. You can unsubscribe with one click from any newsletter email.\n\n" +
          "Product analytics (only if you accept the analytics cookie): page views, button clicks, and a 10% sample of session replays with all form fields masked. We use this to understand which features work and which don't.\n\n" +
          "Maps (only if you accept the functional cookie): approximate map view sent to Mapbox so map tiles load.\n\n" +
          "Service logs: IP address, browser type, and the city-level region you connected from. We keep these for security and to investigate abuse.\n\n" +
          "Listing text for AI enrichment: we send listing descriptions to a language model to generate plain-language summaries. We do not send any user-identifiable information.",
        es:
          "Datos de cuenta: tu correo, nombre, y el token de inicio de sesión que crea Clerk.\n\n" +
          "Datos de pago: nombre, dirección de facturación y los últimos cuatro dígitos de tu tarjeta. El número completo de la tarjeta lo guarda Stripe — nosotros nunca lo vemos ni lo almacenamos.\n\n" +
          "Correos transaccionales: confirmación de cuenta, restablecimiento de contraseña, recibos y avisos importantes del servicio.\n\n" +
          "Boletín (solo si te suscribes): tu correo y preferencias. Puedes darte de baja con un clic desde cualquier correo del boletín.\n\n" +
          "Análisis de producto (solo si aceptas la cookie de análisis): vistas de página, clics en botones, y una muestra del 10% de repeticiones de sesión con los campos de formulario enmascarados. Lo usamos para entender qué funciones sirven y cuáles no.\n\n" +
          "Mapas (solo si aceptas la cookie funcional): vista aproximada de mapa enviada a Mapbox para que se carguen los mosaicos.\n\n" +
          "Registros del servicio: dirección IP, tipo de navegador y la región (nivel ciudad) desde donde te conectas. Los guardamos por seguridad y para investigar abusos.\n\n" +
          "Texto de anuncios para enriquecimiento por IA: enviamos las descripciones de anuncios a un modelo de lenguaje para generar resúmenes claros. No enviamos información que te identifique a ti como usuario.",
      },
    },
    {
      id: "sub-processors",
      heading: { en: "Who we share data with", es: "Con quién compartimos datos" },
      body: {
        en:
          "We use a small set of service providers. Each one has a contract with us that requires them to keep your data confidential, use it only on our instructions, and apply industry-standard security.\n\n" +
          "• Clerk (United States) — log-in and account management. Privacy: clerk.com/privacy.\n" +
          "• Stripe Payments Europe (Ireland) — payment processing. Privacy: stripe.com/privacy.\n" +
          "• Resend (United States) — transactional email and newsletter delivery. Privacy: resend.com/legal/privacy-policy.\n" +
          "• PostHog (EU Cloud, Frankfurt) — product analytics and session replay. Privacy: posthog.com/privacy.\n" +
          "• Mapbox (United States) — map tiles. Privacy: mapbox.com/legal/privacy.\n" +
          "• Vercel (United States and EU) — hosting and CDN. Privacy: vercel.com/legal/privacy-policy.\n" +
          "• DeepSeek (China) — language model used to write listing summaries. We only send listing text, never user-identifiable data. Privacy: deepseek.com/privacy.\n\n" +
          "We do not sell your data. We will only share it with authorities if a Salvadoran court or competent authority requires it.",
        es:
          "Usamos un grupo pequeño de proveedores. Cada uno tiene un contrato con nosotros que les obliga a mantener tus datos confidenciales, usarlos solo según nuestras instrucciones y aplicar medidas de seguridad estándar de la industria.\n\n" +
          "• Clerk (Estados Unidos) — inicio de sesión y gestión de cuentas. Privacidad: clerk.com/privacy.\n" +
          "• Stripe Payments Europe (Irlanda) — procesamiento de pagos. Privacidad: stripe.com/privacy.\n" +
          "• Resend (Estados Unidos) — envío de correos transaccionales y boletín. Privacidad: resend.com/legal/privacy-policy.\n" +
          "• PostHog (EU Cloud, Frankfurt) — análisis de producto y repetición de sesión. Privacidad: posthog.com/privacy.\n" +
          "• Mapbox (Estados Unidos) — mosaicos de mapa. Privacidad: mapbox.com/legal/privacy.\n" +
          "• Vercel (Estados Unidos y UE) — hosting y CDN. Privacidad: vercel.com/legal/privacy-policy.\n" +
          "• DeepSeek (China) — modelo de lenguaje que usamos para escribir resúmenes de anuncios. Solo enviamos el texto del anuncio, nunca datos que identifiquen a un usuario. Privacidad: deepseek.com/privacy.\n\n" +
          "No vendemos tus datos. Solo los compartiremos con autoridades si un juzgado o autoridad competente de El Salvador lo exige.",
      },
    },
    {
      id: "transfers",
      heading: { en: "Where your data lives", es: "Dónde viven tus datos" },
      body: {
        en:
          "Some of our providers are located outside El Salvador (United States, European Union, China). When we move data outside the country, we rely on contractual safeguards (standard contractual clauses) with each provider, and we choose providers that publish public commitments on data protection. If you want to know exactly where a specific piece of data is, ask us at " + SUPPORT_EMAIL + ".",
        es:
          "Algunos de nuestros proveedores están fuera de El Salvador (Estados Unidos, Unión Europea, China). Cuando movemos datos fuera del país, nos apoyamos en garantías contractuales (cláusulas-tipo) con cada proveedor, y elegimos proveedores con compromisos públicos de protección de datos. Si quieres saber exactamente dónde está un dato específico, escríbenos a " + SUPPORT_EMAIL + ".",
      },
    },
    {
      id: "retention",
      heading: { en: "How long we keep your data", es: "Cuánto tiempo guardamos tus datos" },
      body: {
        en:
          "• Account data: while your account is open, plus 30 days after you ask us to delete it.\n" +
          "• Billing records: 10 years, because the Código Tributario and the Código de Comercio require us to keep accounting records that long.\n" +
          "• Transactional email logs: 90 days.\n" +
          "• Newsletter subscription: until you unsubscribe, plus 30 days.\n" +
          "• Analytics events (PostHog): 12 months rolling.\n" +
          "• Session replays (PostHog): 3 months (10% sample).\n" +
          "• Server logs (Vercel): 30 days.",
        es:
          "• Datos de cuenta: mientras tu cuenta esté abierta, más 30 días después de que pidas eliminarla.\n" +
          "• Registros de facturación: 10 años, porque el Código Tributario y el Código de Comercio exigen conservar los registros contables ese plazo.\n" +
          "• Registros de correos transaccionales: 90 días.\n" +
          "• Suscripción al boletín: hasta que te des de baja, más 30 días.\n" +
          "• Eventos de análisis (PostHog): 12 meses móviles.\n" +
          "• Repeticiones de sesión (PostHog): 3 meses (muestra del 10%).\n" +
          "• Registros de servidor (Vercel): 30 días.",
      },
    },
    {
      id: "rights",
      heading: { en: "Your rights — and how to use them", es: "Tus derechos — y cómo ejercerlos" },
      body: {
        en:
          "Under Art. 2 of the Constitución de la República (habeas data) you have the right to:\n\n" +
          "• Access — know what data we hold about you.\n" +
          "• Rectify — correct any data that is wrong.\n" +
          "• Delete — ask us to remove your data (subject to records we must keep by law, such as tax records).\n" +
          "• Object — tell us not to use your data for a specific purpose (e.g. marketing).\n" +
          "• Withdraw consent — pull back consent for analytics, newsletter, or marketing at any time.\n\n" +
          "To exercise any of these, email " + SUPPORT_EMAIL + " with the subject \"Solicitud de derechos\" and tell us which right you want to use. We will respond within 15 business days.\n\n" +
          "If you are not happy with our response, you can file a complaint with the Defensoría del Consumidor (defensoria.gob.sv · 910), which handles consumer complaints including those involving data, or with any other competent authority.",
        es:
          "Bajo el Art. 2 de la Constitución de la República (habeas data) tienes derecho a:\n\n" +
          "• Acceso — saber qué datos tenemos sobre ti.\n" +
          "• Rectificación — corregir cualquier dato que esté mal.\n" +
          "• Eliminación — pedirnos que borremos tus datos (sujeto a los registros que la ley nos obliga a conservar, como los fiscales).\n" +
          "• Oposición — decirnos que no usemos tus datos para un fin específico (por ejemplo, marketing).\n" +
          "• Retiro del consentimiento — retirar el consentimiento para análisis, boletín o marketing en cualquier momento.\n\n" +
          "Para ejercer cualquiera de estos derechos, escríbenos a " + SUPPORT_EMAIL + " con el asunto \"Solicitud de derechos\" y dinos qué derecho quieres ejercer. Te responderemos en 15 días hábiles.\n\n" +
          "Si no quedas conforme con nuestra respuesta, puedes presentar un reclamo ante la Defensoría del Consumidor (defensoria.gob.sv · 910), que tramita reclamos de consumo incluyendo los relativos a datos, o ante cualquier otra autoridad competente.",
      },
    },
    {
      id: "security",
      heading: { en: "How we protect your data", es: "Cómo protegemos tus datos" },
      body: {
        en:
          "We use HTTPS everywhere, encrypt sensitive data at rest, give our team the minimum access needed, and rotate credentials when people leave. No system is perfect, but if a breach affects you, we will notify you without undue delay and explain what happened and what to do.",
        es:
          "Usamos HTTPS en todo el sitio, ciframos datos sensibles en reposo, damos a nuestro equipo solo los accesos mínimos necesarios, y rotamos credenciales cuando alguien deja el equipo. Ningún sistema es perfecto, pero si una brecha te afecta, te avisaremos sin demora indebida y te explicaremos qué pasó y qué hacer.",
      },
    },
    {
      id: "automated-decisions",
      heading: { en: "Automated decisions", es: "Decisiones automáticas" },
      body: {
        en:
          "Pulpo uses ranking algorithms and AI summaries to decide which listings to show first. These work on listing data, not on personal data, and no automated decision produces a legal or similarly significant effect on you as a user. If you want to understand how a specific listing was ranked or summarised, write to " + SUPPORT_EMAIL + ".",
        es:
          "Pulpo usa algoritmos de ranking y resúmenes de IA para decidir qué anuncios mostrar primero. Operan sobre los datos del anuncio, no sobre datos personales, y ninguna decisión automática produce efectos legales o similares sobre ti como usuario. Si quieres entender cómo se rankeó o resumió un anuncio específico, escríbenos a " + SUPPORT_EMAIL + ".",
      },
    },
    {
      id: "minors",
      heading: { en: "Minors", es: "Menores de edad" },
      body: {
        en:
          "Pulpo is for people 18 and older. We do not knowingly collect data from minors. If you believe a minor has signed up, write to " + SUPPORT_EMAIL + " and we will delete the account.",
        es:
          "Pulpo es para personas de 18 años en adelante. No recopilamos datos de menores a sabiendas. Si crees que un menor se registró, escríbenos a " + SUPPORT_EMAIL + " y eliminaremos la cuenta.",
      },
    },
    {
      id: "changes",
      heading: { en: "Changes to this policy", es: "Cambios en esta política" },
      body: {
        en:
          "When we make material changes, we will tell you by email at least 30 days before the new version takes effect. The current version is always at pulpo.club/privacy.",
        es:
          "Cuando hagamos cambios importantes, te avisaremos por correo con al menos 30 días de anticipación antes de que entre en vigor la nueva versión. La versión actual siempre está en pulpo.club/privacy.",
      },
    },
  ],
};

// ── Document 3: Cookie Policy ────────────────────────────────────────

export const COOKIES: LegalDocument = {
  slug: "cookies",
  title: { en: "Cookie Policy · Pulpo", es: "Política de cookies · Pulpo" },
  description: {
    en: "Which cookies Pulpo uses, why, and how to turn them on or off.",
    es: "Qué cookies usa Pulpo, por qué, y cómo activarlas o desactivarlas.",
  },
  review_complete: true,
  last_updated: "2026-05-20",
  sections: [
    {
      id: "intro",
      heading: { en: "What is a cookie?", es: "¿Qué es una cookie?" },
      body: {
        en:
          "A cookie is a small file your browser saves to remember things about your visit — like staying logged in or remembering your language. Pulpo uses cookies in three categories. Only the first one is essential; the others are off by default and only turn on if you say yes.\n\n" +
          "You can change your choice any time by clicking \"Cookie Preferences\" in the footer.",
        es:
          "Una cookie es un pequeño archivo que tu navegador guarda para recordar cosas de tu visita — como mantener tu sesión abierta o recordar tu idioma. Pulpo usa cookies en tres categorías. Solo la primera es indispensable; las otras están apagadas por defecto y solo se encienden si tú dices que sí.\n\n" +
          "Puedes cambiar tu elección en cualquier momento haciendo clic en \"Preferencias de cookies\" en el pie de página.",
      },
    },
    {
      id: "strictly-necessary",
      heading: { en: "1. Strictly necessary (always on)", es: "1. Estrictamente necesarias (siempre activas)" },
      body: {
        en:
          "Without these, the site can't keep you logged in or process payments. They never identify you to advertisers.\n\n" +
          "• __session, __client, __clerk_db_jwt (Clerk) — keep you signed in.\n" +
          "• stripe.sid (Stripe) — keep your checkout session alive long enough to finish payment.\n" +
          "• consent_v (Pulpo) — remembers your cookie choice so we don't ask you again every visit.\n" +
          "• pulpo-locale, ls_view_pref, ls_saved (browser localStorage) — language, view preferences, and listings you saved before signing in.",
        es:
          "Sin estas, el sitio no puede mantenerte conectado ni procesar pagos. Nunca te identifican ante anunciantes.\n\n" +
          "• __session, __client, __clerk_db_jwt (Clerk) — mantienen tu sesión.\n" +
          "• stripe.sid (Stripe) — mantiene tu sesión de checkout viva el tiempo suficiente para completar el pago.\n" +
          "• consent_v (Pulpo) — recuerda tu elección de cookies para no preguntarte de nuevo cada visita.\n" +
          "• pulpo-locale, ls_view_pref, ls_saved (almacenamiento local del navegador) — idioma, preferencias de vista y anuncios guardados antes de iniciar sesión.",
      },
    },
    {
      id: "analytics",
      heading: { en: "2. Analytics (off until you say yes)", es: "2. Análisis (apagadas hasta que digas que sí)" },
      body: {
        en:
          "We use these to understand which features people use and where they get stuck. They never identify you personally to us; PostHog is hosted in the EU (Frankfurt) and IP capture is disabled.\n\n" +
          "• ph_* (PostHog) — counts visits, button clicks, and which paths people take through the site.\n" +
          "• ph_session_* (PostHog) — records a small 10% sample of sessions, with every form field masked, so we can watch where people get confused.",
        es:
          "Las usamos para entender qué partes del sitio funcionan y dónde la gente se atora. Nunca te identifican personalmente ante nosotros; PostHog está alojado en la UE (Frankfurt) y la captura de IP está desactivada.\n\n" +
          "• ph_* (PostHog) — cuenta visitas, clics en botones, y qué caminos toma la gente por el sitio.\n" +
          "• ph_session_* (PostHog) — graba una pequeña muestra del 10% de las sesiones, con todos los campos de formulario enmascarados, para que podamos ver dónde la gente se confunde.",
      },
    },
    {
      id: "functional",
      heading: { en: "3. Functional (off until you say yes)", es: "3. Funcionales (apagadas hasta que digas que sí)" },
      body: {
        en:
          "These improve your experience but the site works without them.\n\n" +
          "• mapbox.session (Mapbox) — caches map tiles so the map loads faster.\n" +
          "• resend_p (Resend) — small pixel in newsletter emails that tells us if you opened the email. Only loaded if you accept this category.",
        es:
          "Mejoran tu experiencia pero el sitio funciona sin ellas.\n\n" +
          "• mapbox.session (Mapbox) — guarda en caché los mosaicos de mapa para que cargue más rápido.\n" +
          "• resend_p (Resend) — un pequeño pixel en los correos del boletín que nos dice si lo abriste. Solo se carga si aceptas esta categoría.",
      },
    },
    {
      id: "manage",
      heading: { en: "How to manage your choice", es: "Cómo gestionar tu elección" },
      body: {
        en:
          "• Click \"Cookie Preferences\" in the footer at any time to change your mind.\n" +
          "• Use your browser settings to block cookies entirely. Note that blocking the strictly-necessary ones will break login.\n" +
          "• Withdrawing consent is as easy as giving it — that's the rule we apply across the site.",
        es:
          "• Haz clic en \"Preferencias de cookies\" en el pie de página en cualquier momento para cambiar tu elección.\n" +
          "• Usa la configuración de tu navegador para bloquear cookies por completo. Ten en cuenta que bloquear las estrictamente necesarias romperá el inicio de sesión.\n" +
          "• Retirar el consentimiento es tan fácil como darlo — esa es la regla que aplicamos en todo el sitio.",
      },
    },
  ],
};

// ── Document 4: Subscription & Refund Policy ─────────────────────────

export const SUBSCRIPTION: LegalDocument = {
  slug: "subscription",
  title: { en: "Subscription & Refund Policy · Pulpo", es: "Política de suscripción y reembolsos · Pulpo" },
  description: {
    en: "Pulpo Pro pricing, promotional free months, auto-renewal, cancellation, and the statutory 5-business-day withdrawal right.",
    es: "Precios, meses promocionales, renovación automática, cancelación, y el derecho de retracto de 5 días hábiles de Pulpo Pro.",
  },
  review_complete: true,
  last_updated: "2026-05-20",
  sections: [
    {
      id: "plans",
      heading: { en: "1. Plans and pricing", es: "1. Planes y precios" },
      body: {
        en:
          "Free Plan — Unlimited browsing of listing cards, limited full detail views per session, and the option to receive the newsletter.\n\n" +
          "Pulpo Pro (paid plan) — Unlimited detail views, saved listings, weekly deal digest, and advanced filters. Price: USD 10.00 per month. The price you see at checkout is the price you pay.",
        es:
          "Plan gratuito — Navegación ilimitada de tarjetas de anuncios, vistas de detalle limitadas por sesión, y la opción de recibir el boletín.\n\n" +
          "Pulpo Pro (plan de pago) — Vistas de detalle ilimitadas, anuncios guardados, resumen semanal de oportunidades, y filtros avanzados. Precio: USD 10.00 al mes. El precio que ves en el checkout es el que pagas.",
      },
    },
    {
      id: "promotional-free-months",
      heading: { en: "2. Promotional free months (when offered)", es: "2. Meses gratis promocionales (cuando se ofrezcan)" },
      body: {
        en:
          "We sometimes offer promotional free months — for example, a launch promotion that gives new subscribers 1 month free before the first paid charge. These are perks, not guarantees, and may change or end at any time.\n\n" +
          "• Promo codes may extend the free period (usually 2, 3, or 6 months).\n" +
          "• A payment method is collected at checkout. During any free period, the card is authorised but not charged.\n" +
          "• If a free period applies, we will email you at least 5 days before the first paid charge.\n" +
          "• You can cancel during a free period at any time — see Cancellation below — and no charge will be made.",
        es:
          "A veces ofrecemos meses gratis promocionales — por ejemplo, una promoción de lanzamiento que da a nuevos suscriptores 1 mes gratis antes del primer cobro. Son beneficios, no garantías, y pueden cambiar o terminar en cualquier momento.\n\n" +
          "• Los códigos promocionales pueden extender el período gratuito (normalmente 2, 3 o 6 meses).\n" +
          "• Se recoge un método de pago en el checkout. Durante cualquier período gratuito, la tarjeta se autoriza pero no se cobra.\n" +
          "• Si aplica un período gratuito, te enviaremos un correo al menos 5 días antes del primer cobro.\n" +
          "• Puedes cancelar durante el período gratuito en cualquier momento — ver Cancelación más abajo — y no se hará ningún cobro.",
      },
    },
    {
      id: "paid-auto-renewal",
      heading: { en: "3. Paid subscription and auto-renewal", es: "3. Suscripción de pago y renovación automática" },
      body: {
        en:
          "Your subscription starts the day Stripe confirms your payment. If a free promotional period applies, the first paid charge is deferred by the number of free months in that promotion.\n\n" +
          "After that, your subscription renews automatically every month. You will be charged USD 10.00 per month (plus any taxes that apply where you live). We send a receipt by email after each charge.\n\n" +
          "Auto-renewal is required by Stripe's flow, but you can cancel any time and avoid future charges — see below.",
        es:
          "Tu suscripción comienza el día en que Stripe confirma tu pago. Si aplica un período gratuito promocional, el primer cobro se difiere por la cantidad de meses gratuitos de esa promoción.\n\n" +
          "Después, tu suscripción se renueva automáticamente cada mes. Se te cobrará USD 10.00 al mes (más los impuestos que correspondan donde vives). Enviamos un recibo por correo tras cada cobro.\n\n" +
          "La renovación automática es parte del flujo de Stripe, pero puedes cancelar en cualquier momento y evitar cobros futuros — ver abajo.",
      },
    },
    {
      id: "cancellation",
      heading: { en: "4. How to cancel", es: "4. Cómo cancelar" },
      body: {
        en:
          "Two ways:\n\n" +
          "(a) From your account: Account → Subscription → Manage plan → Cancel (opens the Stripe Customer Portal).\n" +
          "(b) By email: write to " + SUPPORT_EMAIL + " with the subject \"Cancelar suscripción\".\n\n" +
          "After you cancel:\n" +
          "• Pulpo Pro stays active until the end of the current billing month.\n" +
          "• No further charges are made.\n" +
          "• Your account goes back to the Free Plan at the end of the period.\n\n" +
          "To avoid the next month's charge, cancel at least 1 day before your renewal date.",
        es:
          "Dos formas:\n\n" +
          "(a) Desde tu cuenta: Cuenta → Suscripción → Gestionar plan → Cancelar (abre el Portal de Cliente de Stripe).\n" +
          "(b) Por correo: escríbenos a " + SUPPORT_EMAIL + " con el asunto \"Cancelar suscripción\".\n\n" +
          "Después de cancelar:\n" +
          "• Pulpo Pro sigue activo hasta el final del mes facturado.\n" +
          "• No se hacen más cobros.\n" +
          "• Tu cuenta vuelve al plan gratuito al final del período.\n\n" +
          "Para evitar el cobro del mes siguiente, cancela al menos 1 día antes de tu fecha de renovación.",
      },
    },
    {
      id: "withdrawal",
      heading: { en: "5. Your right of withdrawal — 5 business days", es: "5. Tu derecho de retracto — 5 días hábiles" },
      body: {
        en:
          "Under Art. 15 de la Ley de Comercio Electrónico of El Salvador (D.L. 947), you have the right to withdraw from your paid subscription within 5 business days from the day the contract was formed, without giving any reason, and receive a full refund.\n\n" +
          "How to use it: email " + SUPPORT_EMAIL + " within 5 business days of subscribing with the subject \"Retracto de suscripción\". We will process your refund within 14 days to the same payment method you used.\n\n" +
          "If you started using Pulpo Pro before the 5 business days are up, by exercising withdrawal you accept that we may keep a proportional amount for the days you already used (this matches Art. 15 LCE's partial-performance rule).",
        es:
          "Bajo el Art. 15 de la Ley de Comercio Electrónico de El Salvador (D.L. 947), tienes derecho a retractarte de tu suscripción de pago dentro de 5 días hábiles desde el día en que se formó el contrato, sin necesidad de dar razones, y recibir un reembolso total.\n\n" +
          "Cómo ejercerlo: escríbenos a " + SUPPORT_EMAIL + " dentro de 5 días hábiles desde tu suscripción con el asunto \"Retracto de suscripción\". Procesaremos tu reembolso dentro de 14 días al mismo método de pago que usaste.\n\n" +
          "Si comenzaste a usar Pulpo Pro antes de que terminen los 5 días hábiles, al ejercer el retracto aceptas que podamos retener una cantidad proporcional por los días que ya usaste (esto coincide con la regla de prestación parcial del Art. 15 LCE).",
      },
    },
    {
      id: "refunds",
      heading: { en: "6. Refunds outside the withdrawal window", es: "6. Reembolsos fuera del plazo de retracto" },
      body: {
        en:
          "After the 5-business-day window, we don't refund partial months. Two exceptions, at our discretion:\n\n" +
          "• A material outage attributable to Pulpo lasting more than 24 hours in a single billing month.\n" +
          "• Billing errors (double charges, wrong amount).\n\n" +
          "Request a refund: email " + SUPPORT_EMAIL + " with the subject \"Reembolso\". We respond within 5 business days.\n\n" +
          "If we can't reach an agreement, you can take it to the Defensoría del Consumidor (defensoria.gob.sv · 910), a free administrative channel for consumer disputes.",
        es:
          "Después del plazo de 5 días hábiles, no reembolsamos meses parciales. Dos excepciones, a nuestra discreción:\n\n" +
          "• Una caída importante atribuible a Pulpo que dure más de 24 horas en un mismo mes de facturación.\n" +
          "• Errores de facturación (doble cobro, monto incorrecto).\n\n" +
          "Solicita un reembolso: escríbenos a " + SUPPORT_EMAIL + " con el asunto \"Reembolso\". Respondemos en 5 días hábiles.\n\n" +
          "Si no llegamos a un acuerdo, puedes acudir a la Defensoría del Consumidor (defensoria.gob.sv · 910), un canal administrativo gratuito para disputas de consumo.",
      },
    },
    {
      id: "price-changes",
      heading: { en: "7. Price changes", es: "7. Cambios de precio" },
      body: {
        en:
          "We will give you at least 30 days' notice by email before any price change applies to you. If you don't cancel before the new price takes effect, your continued use means you accept it.",
        es:
          "Te avisaremos por correo con al menos 30 días de anticipación antes de que un cambio de precio aplique. Si no cancelas antes de que el nuevo precio entre en vigor, tu uso continuado significa que lo aceptas.",
      },
    },
    {
      id: "taxes",
      heading: { en: "8. Taxes", es: "8. Impuestos" },
      body: {
        en:
          "The displayed price is the price you pay. If the law where you live requires us to add a tax (e.g. IVA in El Salvador), we will show it before you confirm payment.",
        es:
          "El precio mostrado es el precio que pagas. Si la ley donde vives nos obliga a sumar un impuesto (por ejemplo, IVA en El Salvador), te lo mostraremos antes de que confirmes el pago.",
      },
    },
  ],
};

// ── Document 5: Imprint / Aviso Legal ────────────────────────────────

export const IMPRINT: LegalDocument = {
  slug: "imprint",
  title: { en: "Legal notice · Pulpo", es: "Aviso legal · Pulpo" },
  description: {
    en: "Pulpo company entity disclosure required by Salvadoran electronic-commerce law.",
    es: "Datos de la empresa Pulpo, según lo exige la legislación salvadoreña de comercio electrónico.",
  },
  review_complete: true,
  last_updated: "2026-05-20",
  sections: [
    {
      id: "entity",
      heading: { en: "Provider information (Art. 6 LCE)", es: "Información del proveedor (Art. 6 LCE)" },
      body: {
        en:
          `Trade name: ${ENTITY.trade_name}\n` +
          `Operating address: ${formatAddress()}\n` +
          `Governing law: ${ENTITY.governing_law}\n` +
          `Email: ${SUPPORT_EMAIL}\n` +
          `Website: https://pulpo.club\n\n` +
          `Service providers used to operate the platform:\n` +
          `• Hosting and CDN: Vercel, Inc. (United States / EU)\n` +
          `• Authentication: Clerk, Inc. (United States)\n` +
          `• Payments: Stripe Payments Europe Ltd. (Dublin, Ireland)\n` +
          `• Transactional email: Resend, Inc. (United States)\n` +
          `• Product analytics: PostHog, Inc. (United States / EU)\n` +
          `• Maps: Mapbox, Inc. (United States)\n\n` +
          `Consumer-protection authority (claims under the Ley de Protección al Consumidor, D.L. 776/2005):\n` +
          `${ENTITY.supervisory_authority.name}\n` +
          `Website: ${ENTITY.supervisory_authority.url}\n` +
          `Phone: ${ENTITY.supervisory_authority.phone}\n\n` +
          `Civil and commercial disputes:\n` +
          `${ENTITY.courts}.`,
        es:
          `Nombre comercial: ${ENTITY.trade_name}\n` +
          `Domicilio de operación: ${formatAddress()}\n` +
          `Ley aplicable: ${ENTITY.governing_law}\n` +
          `Correo: ${SUPPORT_EMAIL}\n` +
          `Sitio web: https://pulpo.club\n\n` +
          `Proveedores de servicios para operar la plataforma:\n` +
          `• Hosting y CDN: Vercel, Inc. (Estados Unidos / UE)\n` +
          `• Autenticación: Clerk, Inc. (Estados Unidos)\n` +
          `• Pagos: Stripe Payments Europe Ltd. (Dublín, Irlanda)\n` +
          `• Correo transaccional: Resend, Inc. (Estados Unidos)\n` +
          `• Analítica de producto: PostHog, Inc. (Estados Unidos / UE)\n` +
          `• Mapas: Mapbox, Inc. (Estados Unidos)\n\n` +
          `Autoridad de protección al consumidor (reclamos al amparo de la Ley de Protección al Consumidor, D.L. 776/2005):\n` +
          `${ENTITY.supervisory_authority.name}\n` +
          `Sitio web: ${ENTITY.supervisory_authority.url}\n` +
          `Teléfono: ${ENTITY.supervisory_authority.phone}\n\n` +
          `Disputas civiles y mercantiles:\n` +
          `${ENTITY.courts}.`,
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

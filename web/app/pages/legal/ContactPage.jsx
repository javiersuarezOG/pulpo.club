// ContactPage — /contact public route.
//
// Submits to POST /api/contact (api/contact.js) which routes to the
// right topical inbox (contact@ / privacy@ / legal@ / etc.) per the
// audit plan + legal_documents/05-data-subject-rights.md. While DNS
// for those addresses is still pending, the endpoint fans out to
// founders so submissions never get lost.
//
// Frontend non-negotiables:
//   - Responsive: max-width 640, padding via design tokens, no
//     horizontal scroll at 320px.
//   - i18n: every visible string via t(); EN + ES coverage in i18n.jsx.
//   - Telemetry: `legal.page_viewed` (slug=contact) on mount,
//     `contact.form_opened` on first focus, `contact.form_submitted`
//     with topic + status on every submit attempt. NO PII in payloads
//     (no email, name, body content).
//   - Design tokens only.
//   - Honeypot field (`website`) catches bots — humans don't see it.

import React, { useEffect, useState, useRef } from "react";
import { useDocumentMeta } from "../../lib/use-document-meta";
import { t } from "../../i18n.jsx";
import { track } from "../../telemetry/client";
import { CONTACT_TOPICS } from "../../config/contact-routing";

const PAGE_STYLES = `
.page-contact {
  max-width: 640px;
  margin: 0 auto;
  padding: 48px var(--section-pad, 24px) 96px;
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
}
.page-contact__back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--type-card-meta-size);
  color: var(--ink-3);
  text-decoration: none;
  margin-bottom: 32px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
}
.page-contact__back:hover { color: var(--ink); }
.page-contact__title {
  font-family: var(--font-sans);
  font-size: 36px;
  line-height: 44px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 8px;
}
.page-contact__lede {
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
  color: var(--ink-2);
  margin: 0 0 32px;
}
.page-contact__form {
  display: grid;
  gap: 16px;
  margin: 0 0 32px;
}
.page-contact__field {
  display: grid;
  gap: 4px;
}
.page-contact__label {
  font-size: var(--type-card-meta-size);
  font-weight: 600;
  color: var(--ink);
}
.page-contact__input,
.page-contact__select,
.page-contact__textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: var(--type-body-size);
  line-height: var(--type-body-line);
  box-sizing: border-box;
}
.page-contact__input:focus,
.page-contact__select:focus,
.page-contact__textarea:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
  border-color: var(--accent);
}
.page-contact__textarea {
  min-height: 160px;
  resize: vertical;
  font-family: var(--font-sans);
}
.page-contact__honeypot {
  position: absolute;
  left: -9999px;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
}
.page-contact__submit {
  justify-self: start;
  padding: 12px 20px;
  border-radius: 8px;
  border: 0;
  background: var(--accent);
  color: var(--paper);
  font-family: var(--font-sans);
  font-size: var(--type-body-size);
  font-weight: 600;
  cursor: pointer;
}
.page-contact__submit:hover:not(:disabled) {
  background: var(--accent-strong, var(--accent));
}
.page-contact__submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.page-contact__status {
  padding: 12px 16px;
  border-radius: 8px;
  font-size: var(--type-card-meta-size);
  line-height: 1.6;
}
.page-contact__status--success {
  background: color-mix(in oklch, var(--accent) 12%, var(--paper));
  border: 1px solid var(--accent);
  color: var(--ink);
}
.page-contact__status--error {
  background: var(--paper-2);
  border: 1px solid var(--line-2);
  color: var(--ink-2);
}
.page-contact__inbox-list {
  list-style: none;
  padding: 0;
  margin: 24px 0 0;
  display: grid;
  gap: 12px;
}
.page-contact__inbox-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
  padding: 16px;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.page-contact__inbox-label {
  font-size: var(--type-card-meta-size);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}
.page-contact__inbox-address {
  font-family: var(--font-mono);
  font-size: var(--type-card-meta-size);
  color: var(--ink-2);
  margin: 0;
}
@media (max-width: 599px) {
  .page-contact { padding: 24px 16px 80px; }
  .page-contact__title { font-size: 28px; line-height: 36px; }
}
`;

export function ContactPage({ app }) {
  const locale = app?.locale === "es" ? "es" : "en";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [topic, setTopic] = useState("general");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState(null); // null | "success" | "error"
  const formOpenedFired = useRef(false);

  useDocumentMeta({
    title: t("contact.page.title", locale),
    description: t("contact.page.description", locale),
  });

  useEffect(() => {
    track("legal.page_viewed", { page: "contact" });
  }, []);

  function handleFirstFocus() {
    if (formOpenedFired.current) return;
    formOpenedFired.current = true;
    track("contact.form_opened", { topic });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (submitting) return;
    setStatus(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, email, topic, subject, message, honeypot }),
      });
      if (res.ok) {
        track("contact.form_submitted", { topic, status: "success" });
        setStatus("success");
        // Clear the message but keep contact details so a follow-up
        // is one button press away.
        setMessage("");
        setSubject("");
      } else if (res.status === 429) {
        track("contact.form_submitted", { topic, status: "rate_limit" });
        setStatus("error");
      } else if (res.status >= 400 && res.status < 500) {
        track("contact.form_submitted", { topic, status: "validation_error" });
        setStatus("error");
      } else {
        track("contact.form_submitted", { topic, status: "server_error" });
        setStatus("error");
      }
    } catch {
      track("contact.form_submitted", { topic, status: "server_error" });
      setStatus("error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page page-contact" role="main">
      <style>{PAGE_STYLES}</style>
      <button
        type="button"
        className="page-contact__back"
        onClick={() => app.go("home")}
        aria-label={t("legal.back_to_home", locale)}
      >
        ← {t("legal.back_to_home", locale)}
      </button>

      <h1 className="page-contact__title">{t("contact.page.title", locale)}</h1>
      <p className="page-contact__lede">{t("contact.page.lede", locale)}</p>

      {status === "success" && (
        <div className="page-contact__status page-contact__status--success" role="status">
          {t("contact.page.success", locale)}
        </div>
      )}
      {status === "error" && (
        <div className="page-contact__status page-contact__status--error" role="alert">
          {t("contact.page.error", locale)}
        </div>
      )}

      <form className="page-contact__form" onSubmit={handleSubmit} onFocus={handleFirstFocus}>
        <div className="page-contact__field">
          <label className="page-contact__label" htmlFor="contact-name">
            {t("contact.form.name_label", locale)}
          </label>
          <input
            id="contact-name"
            className="page-contact__input"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
          />
        </div>

        <div className="page-contact__field">
          <label className="page-contact__label" htmlFor="contact-email">
            {t("contact.form.email_label", locale)}
          </label>
          <input
            id="contact-email"
            className="page-contact__input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={254}
          />
        </div>

        <div className="page-contact__field">
          <label className="page-contact__label" htmlFor="contact-topic">
            {t("contact.form.topic_label", locale)}
          </label>
          <select
            id="contact-topic"
            className="page-contact__select"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          >
            {CONTACT_TOPICS.map((key) => (
              <option key={key} value={key}>
                {t(`contact.topic.${key}`, locale)}
              </option>
            ))}
          </select>
        </div>

        <div className="page-contact__field">
          <label className="page-contact__label" htmlFor="contact-subject">
            {t("contact.form.subject_label", locale)}
          </label>
          <input
            id="contact-subject"
            className="page-contact__input"
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            maxLength={200}
          />
        </div>

        <div className="page-contact__field">
          <label className="page-contact__label" htmlFor="contact-message">
            {t("contact.form.message_label", locale)}
          </label>
          <textarea
            id="contact-message"
            className="page-contact__textarea"
            required
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={5000}
          />
        </div>

        {/* Honeypot — humans never see this. */}
        <div className="page-contact__honeypot" aria-hidden="true">
          <label htmlFor="contact-website">Website (leave blank)</label>
          <input
            id="contact-website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </div>

        <button
          type="submit"
          className="page-contact__submit"
          disabled={submitting || !email || message.length < 5}
        >
          {submitting ? t("contact.form.submitting", locale) : t("contact.form.submit", locale)}
        </button>
      </form>

      <ul className="page-contact__inbox-list" aria-label={t("contact.page.inbox_list_label", locale)}>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.general", locale)}</p>
          <p className="page-contact__inbox-address">contact@pulpo.club</p>
        </li>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.privacy", locale)}</p>
          <p className="page-contact__inbox-address">privacy@pulpo.club</p>
        </li>
        <li className="page-contact__inbox-row">
          <p className="page-contact__inbox-label">{t("contact.topic.legal", locale)}</p>
          <p className="page-contact__inbox-address">legal@pulpo.club</p>
        </li>
      </ul>
    </div>
  );
}

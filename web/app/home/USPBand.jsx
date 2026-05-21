// USP band — three editorial cards on a white background. The id
// `why-pulpo` is the smooth-scroll target for the header's "How it
// works" link.
//
// Card titles include an intentional \n line-break per the design
// spec (e.g. "10 best deals,\nevery week"). The CSS preserves the
// break with white-space: pre-line on the title element.
//
// Post-Wave-5: the section is clickable for anon + free users, opening
// the FreeMonthModal. Paid users see the same cards as a read-only
// pitch — the wrapper drops the role="button" / onClick so the section
// behaves like prose.
import React, { useEffect, useState } from "react";
import { t } from "../i18n.jsx";
import { IconLock, IconMailFast, IconListSearch, IconMapPinHeart } from "./icons.jsx";
import { tierFor } from "../lib/gating";
import { priceForCountry, fetchPriceForCurrentGeo } from "../lib/pricing";

export function USPBand({ app, locale }) {
  const tier = tierFor(app?.user);
  const clickable = tier === "anonymous" || tier === "free";

  // Geo-derived display price for the templated h2. Synchronous USD
  // fallback renders first; cached /api/geo refines.
  const [price, setPrice] = useState(() => priceForCountry(null));
  useEffect(() => {
    let cancelled = false;
    fetchPriceForCurrentGeo().then((p) => { if (!cancelled) setPrice(p); });
    return () => { cancelled = true; };
  }, []);

  const onClick = () => {
    if (!clickable) return;
    app?.openFreeMonthModal?.({ trigger: "usp_section" });
  };
  const onKeyDown = (e) => {
    if (!clickable) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <section
      id="why-pulpo"
      className={`hp-usp${clickable ? " hp-usp-clickable" : ""}`}
      aria-labelledby="hp-usp-h2"
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onClick : undefined}
      onKeyDown={clickable ? onKeyDown : undefined}
      aria-label={clickable ? t("free_month_modal.aria.dialog", locale) : undefined}
    >
      <div className="hp-usp-inner">
        <span className="hp-usp-eyebrow">
          <IconLock size={14} strokeWidth={1.8} className="hp-usp-eyebrow-icon" />
          {t("home.usp.eyebrow", locale)}
        </span>
        <h2 id="hp-usp-h2" className="hp-usp-h2">
          {t("home.usp.h2", locale, { price: price.displayString })}
        </h2>

        <div className="hp-usp-cards">
          <article className="hp-usp-card">
            <IconMailFast size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card1.title", locale)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card1.body", locale)}</p>
          </article>
          <article className="hp-usp-card">
            <IconListSearch size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card2.title", locale)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card2.body", locale)}</p>
          </article>
          <article className="hp-usp-card hp-usp-card-wide">
            <IconMapPinHeart size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card3.title", locale)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card3.body", locale)}</p>
          </article>
        </div>
      </div>
    </section>
  );
}

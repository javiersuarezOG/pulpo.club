// USP band — three editorial cards on a white background. The id
// `why-pulpo` is the smooth-scroll target for the header's "How it
// works" link.
//
// Card titles include an intentional \n line-break per the design
// spec (e.g. "10 best deals,\nevery 2 weeks"). The CSS preserves the
// break with white-space: pre-line on the title element.
import React from "react";
import { t } from "../i18n.jsx";
import { IconLock, IconMailFast, IconListSearch, IconMapPinHeart } from "./icons.jsx";

export function USPBand({ locale }) {
  return (
    <section id="why-pulpo" className="hp-usp" aria-labelledby="hp-usp-h2">
      <div className="hp-usp-inner">
        <span className="hp-usp-eyebrow">
          <IconLock size={14} strokeWidth={1.8} className="hp-usp-eyebrow-icon" />
          {t("home.usp.eyebrow", locale)}
        </span>
        <h2 id="hp-usp-h2" className="hp-usp-h2">{t("home.usp.h2", locale)}</h2>

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

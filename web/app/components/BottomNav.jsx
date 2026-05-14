// Wave-3a: extracted from pages.jsx's inline BottomNav. Same behavior;
// only the i18n keys changed (nav.tab.* → nav.home / nav.discover /
// nav.favorites) so SiteHeader and BottomNav share the same labels.

import React from "react";
import { t } from "../i18n.jsx";
import { Icon } from "../components.jsx";

export function BottomNav({ app }) {
  const lc = app.locale;
  const tabs = [
    { key: "home",    labelKey: "nav.home",      icon: "home" },
    { key: "browse",  labelKey: "nav.discover",  icon: "search" },
    { key: "saved",   labelKey: "nav.favorites", icon: "heart" },
    { key: "profile", labelKey: app.user ? "nav.tab.profile" : "nav.tab.signin", icon: "user" },
  ];
  return (
    <nav className="bottomnav">
      {tabs.map(tab => (
        <button
          key={tab.key}
          className={(app.route === tab.key || (tab.key === "profile" && app.route === "account")) ? "active" : ""}
          onClick={() => {
            if (tab.key === "profile") {
              if (!app.user) app.openSignup({ mode: "login" });
              else app.go("account");
            } else app.go(tab.key);
          }}
        >
          <Icon name={tab.icon} size={20} />
          <span>{t(tab.labelKey, lc)}</span>
          {tab.key === "saved" && app.savedIds.size > 0 && <span className="tab-count">{app.savedIds.size}</span>}
        </button>
      ))}
    </nav>
  );
}

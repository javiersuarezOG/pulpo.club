// One-shot telemetry for env vars that override documented code defaults.
//
// The values can contain operational details, so we never emit the raw
// value. A short SHA prefix is enough to tell "changed again" apart from
// "same override as last deploy" without leaking secrets or addresses.

const crypto = require("crypto");
const posthog = require("./_posthog");

const OVERRIDES = [
  {
    varName: "PULPO_ACTIVATION_FROM_EMAIL",
    codeDefault: "Pulpo Club <hello@mail.pulpo.club>",
  },
  {
    varName: "RESEND_FROM_NOREPLY",
    codeDefault: "",
  },
  {
    varName: "PULPO_ACTIVE_COUNTRY",
    codeDefault: "",
  },
];

let audited = false;

function hashValue(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex").slice(0, 16);
}

async function auditEnvOverridesOnce() {
  if (audited) return;
  audited = true;
  let emitted = false;
  for (const item of OVERRIDES) {
    const raw = process.env[item.varName];
    if (raw == null || String(raw) === item.codeDefault) continue;
    posthog.capture("server:env-audit", "env_var.override_detected", {
      var_name: item.varName,
      code_default: item.codeDefault,
      env_value_hash: hashValue(raw),
    });
    emitted = true;
  }
  if (emitted) await posthog.flush();
}

module.exports = {
  OVERRIDES,
  auditEnvOverridesOnce,
  hashValue,
};

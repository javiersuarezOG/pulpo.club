// Plain CJS function require()-ing across the api/ boundary. If this
// passes, the endpoints can simply be CommonJS and the fix is small.
const { OUTSIDE_CJS } = require("../../shared/probe-helper.cjs");
module.exports = (req, res) =>
  res.status(200).json({ probe: 7, kind: "cjs-requires-cjs-outside-api", v: OUTSIDE_CJS });

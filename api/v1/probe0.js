// CONTROL: plain CommonJS, no imports. If this fails, nothing works.
module.exports = (req, res) => res.status(200).json({ probe: 0, kind: "cjs-no-imports" });

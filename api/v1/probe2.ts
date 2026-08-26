// TypeScript written CommonJS-style. If probe1 fails and this passes,
// the problem is purely the export/import syntax, not TS itself.
module.exports = (req: any, res: any) =>
  res.status(200).json({ probe: 2, kind: "ts-no-imports-cjs-export" });

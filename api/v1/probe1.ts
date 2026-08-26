// Does TypeScript work here AT ALL? No imports, ESM-style export.
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: 1, kind: "ts-no-imports-esm-export" });
}

// TS importing plain .js from OUTSIDE api/. If this fails too, the
// boundary is what matters, not TypeScript.
import { OUTSIDE_JS } from "../../shared/probe-helper.js";
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: 6, kind: "ts-imports-js-outside-api", v: OUTSIDE_JS });
}

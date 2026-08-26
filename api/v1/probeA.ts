// The one untested link: a TypeScript function importing the CJS bridge,
// which itself requires across the api/ boundary.
//   probe4: TS -> self-contained .js inside api/      = 200
//   probe7: CJS ENTRYPOINT -> outside api/            = 200
//   probeA: TS -> .js inside api/ -> outside api/     = ?
import { API_VERSION } from "../_core.js";
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: "A", kind: "ts-via-cjs-bridge", version: API_VERSION });
}

// TypeScript importing the existing CommonJS helper. Isolates TS->CJS interop.
import { ipFromRequest } from "../_rate_limit.js";
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: 4, kind: "ts-imports-cjs-helper", ip: typeof ipFromRequest });
}

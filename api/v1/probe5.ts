// TS importing a .ts file INSIDE api/. If this passes, the .ts
// extension is fine and the problem is purely crossing out of api/.
import { logApi } from "./_http";
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: 5, kind: "ts-imports-ts-inside-api", fn: typeof logApi });
}

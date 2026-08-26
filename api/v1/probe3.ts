// TypeScript importing TypeScript from OUTSIDE api/ (the shared core).
// Isolates cross-tree TS resolution.
import { API_VERSION } from "../../shared/version";
export default function handler(req: any, res: any) {
  return res.status(200).json({ probe: 3, kind: "ts-imports-shared-ts", version: API_VERSION });
}

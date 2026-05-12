// Barrel export for the new homepage components. Phase 4C wires
// these into a NewHomePage shell behind the VITE_NEW_HOMEPAGE flag.
//
// Importing from "../home" lets the shell stay readable:
//   import { Hero, ProofRow, CategoryGrid, DiscoveryPills, USPRow }
//     from "../home";
//
// Pure re-exports — no new logic.

export { Hero } from "./Hero.jsx";
export { ProofRow } from "./ProofRow.jsx";
export { CategoryGrid } from "./CategoryGrid.jsx";
export { DiscoveryPills } from "./DiscoveryPills.jsx";
export { USPRow } from "./USPRow.jsx";

// GET /api/admin/newsletter/options
//
// Returns the filter dimensions present in the current ranked.json so the
// admin newsletter widget can populate its chip pickers from live data
// (instead of hardcoded constants that drift). No auth: the /admin page
// is open by design — see web/app/admin/AdminShell.jsx for the rationale.
//
// Response: { departments, zones, property_types, total_listings }

const { loadRanked } = require("./_filter");

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const data = loadRanked();
  if (!data || !Array.isArray(data)) {
    return res.status(503).json({
      error: "ranked_not_available",
      hint: "web/data/ranked.json is missing or malformed — re-run the nightly pipeline.",
    });
  }

  const departments = new Set();
  const zones = new Set();
  const propertyTypes = new Set();
  for (const l of data) {
    if (l.department) departments.add(l.department);
    if (l.zone) zones.add(l.zone);
    if (l.property_type) propertyTypes.add(l.property_type);
  }
  const sortStr = (a, b) => a.localeCompare(b);

  // No-cache so a fresh nightly run is reflected immediately when the
  // admin re-opens the widget. The payload is small (a few hundred
  // strings); we don't need a CDN hop.
  res.setHeader("Cache-Control", "no-store");
  return res.status(200).json({
    departments: [...departments].sort(sortStr),
    zones: [...zones].sort(sortStr),
    property_types: [...propertyTypes].sort(sortStr),
    total_listings: data.length,
  });
};

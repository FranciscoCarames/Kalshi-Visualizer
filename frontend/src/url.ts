/* URL/query-param state — pure encode/decode so filters survive reload + are shareable (old-dashboard
 * parity). Restore is sanitized against the live feed by the caller (drop a sport/tournament not present),
 * applied only after the first feed arrives, and writes are guarded against no-op replaceState loops. */
export interface UrlState {
  surface: string; zone: string; section: string; lens: string;
  sports: string[]; tours: string[]; part: string;
}

const splitList = (v: string | null): string[] => (v ? v.split(",").map((s) => s.trim()).filter(Boolean) : []);

/** Encode to a `?a=b&…` string (empty when nothing non-default is set). `surface=opp` is the default and
 * is omitted. Stable key order via URLSearchParams. */
export function encodeUrl(s: UrlState): string {
  const p = new URLSearchParams();
  if (s.surface && s.surface !== "opp") p.set("surface", s.surface);
  if (s.zone && s.zone !== "exec") p.set("zone", s.zone);
  if (s.section && s.section !== "act") p.set("section", s.section);
  if (s.lens) p.set("lens", s.lens);
  if (s.sports.length) p.set("sport", s.sports.join(","));
  if (s.tours.length) p.set("tour", s.tours.join(","));
  if (s.part) p.set("part", s.part);
  const q = p.toString();
  return q ? "?" + q : "";
}

/** Decode a `location.search` string to a partial state (only the keys actually present). */
export function decodeUrl(search: string): Partial<UrlState> {
  const p = new URLSearchParams(search);
  const out: Partial<UrlState> = {};
  const surface = p.get("surface"); if (surface) out.surface = surface;
  const zone = p.get("zone"); if (zone) out.zone = zone;
  const section = p.get("section"); if (section) out.section = section;
  const lens = p.get("lens"); if (lens) out.lens = lens;
  if (p.has("sport")) out.sports = splitList(p.get("sport"));
  if (p.has("tour")) out.tours = splitList(p.get("tour"));
  const part = p.get("part"); if (part) out.part = part;
  return out;
}

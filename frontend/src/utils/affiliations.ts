import type { AuthorAffiliation } from "../types";

export function getUniqueAffiliations(
  affiliations: (AuthorAffiliation | string)[] | null | undefined
): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const item of affiliations || []) {
    const raw =
      typeof item === "string"
        ? item
        : item.affiliation || item.institution || item.org || "";
    const affiliation = raw.trim();
    const key = affiliation.toLowerCase();
    if (!affiliation || seen.has(key)) continue;
    seen.add(key);
    result.push(affiliation);
  }

  return result;
}

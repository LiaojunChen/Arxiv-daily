import type { AppSettings, Paper } from "../types";
import { getUniqueAffiliations } from "./affiliations";

type SubscriptionSettings = Pick<AppSettings, "followed_authors" | "followed_institutions">;

function normalizeSubscriptionValue(value: string): string {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function matchesSubscription(value: string, subscription: string): boolean {
  const normalizedValue = normalizeSubscriptionValue(value);
  const normalizedSubscription = normalizeSubscriptionValue(subscription);
  if (!normalizedValue || !normalizedSubscription) return false;

  const valueWithBoundaries = ` ${normalizedValue} `;
  const subscriptionWithBoundaries = ` ${normalizedSubscription} `;
  return (
    valueWithBoundaries.includes(subscriptionWithBoundaries) ||
    subscriptionWithBoundaries.includes(valueWithBoundaries)
  );
}

function getLocalMatchReason(paper: Paper, settings: SubscriptionSettings): string | null {
  const author = settings.followed_authors.find((followedAuthor) =>
    paper.authors.some((paperAuthor) => matchesSubscription(paperAuthor, followedAuthor)),
  );
  if (author) return `本地作者订阅:${author}`;

  const institution = settings.followed_institutions.find((followedInstitution) =>
    getUniqueAffiliations(paper.affiliations).some((affiliation) =>
      matchesSubscription(affiliation, followedInstitution),
    ),
  );
  return institution ? `本地机构订阅:${institution}` : null;
}

export function mergeFollowedPapers(
  serverFollowedPapers: Paper[],
  discoveredPapers: Paper[],
  settings: SubscriptionSettings,
): Paper[] {
  const paperIds = new Set(serverFollowedPapers.map((paper) => paper.arxiv_id));
  const followedPapers = [...serverFollowedPapers];

  for (const paper of discoveredPapers) {
    if (paperIds.has(paper.arxiv_id)) continue;

    const matchedBy = getLocalMatchReason(paper, settings);
    if (!matchedBy) continue;

    paperIds.add(paper.arxiv_id);
    followedPapers.push({ ...paper, source: "followed", matched_by: matchedBy });
  }

  return followedPapers;
}

"""Deliver an already generated snapshot without fetching or ranking again."""
import json
import os
from pathlib import Path
import hydra
from omegaconf import DictConfig
from .construct_email import render_email
from .feedback import build_feedback_issue_url
from .protocol import Paper
from .utils import send_email
from openai import OpenAI


def snapshot_papers(snapshot, repo):
    result = []
    for item in snapshot["similar_papers"]:
        affiliations = [a if isinstance(a, str) else a.get("affiliation", "") for a in item.get("affiliations", [])]
        paper = Paper(source="arxiv", title=item["title"], authors=item["authors"], abstract=item["abstract"],
            url=item["abstract_url"], pdf_url=item["pdf_url"], affiliations=affiliations,
            score=item.get("similarity_score"), keywords=item.get("keywords", []),
            matched_keywords=item.get("matched_keywords", []), paper_id=item["arxiv_id"],
            recommendation_group=item.get("recommendation_group", "primary"),
            recommendation_reason=item.get("recommendation_reason"))
        if repo:
            paper.feedback_urls = {action: build_feedback_issue_url(repo, paper, action, snapshot["run_id"])
                                   for action in ("like", "interested", "not_interested")}
        result.append(paper)
    return result


@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config: DictConfig):
    snapshot = json.loads(Path(os.environ.get("PAPER_SNAPSHOT_PATH", "data/papers.json")).read_text(encoding="utf-8"))
    papers = snapshot_papers(snapshot, os.environ.get("GITHUB_REPOSITORY"))
    if os.environ.get("OPENAI_API_KEY"):
        client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)
        for paper in papers:
            paper.generate_tldr(client, config.llm)
    if papers or config.executor.send_empty:
        send_email(config, render_email(papers, top_keywords=snapshot.get("top_keywords", []),
            exploration_keywords=snapshot.get("exploration_keywords", [])))


if __name__ == "__main__":
    main()

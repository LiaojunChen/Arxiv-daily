from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig, ListConfig
from .utils import glob_match
from .retriever import get_retriever_cls
from .protocol import CorpusPaper, Paper
import random
from datetime import datetime
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email
from openai import OpenAI
from tqdm import tqdm
import os

from .feedback import GitHubFeedbackClient, build_feedback_issue_url, make_paper_id
from .interest_profile import InterestProfile, guess_exploration_keywords, utcnow_iso
from .keyword_extractor import (
    assign_keywords_to_papers,
    keyword_overlap_score,
    matched_keywords_for_paper,
)


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        self.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
        self.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)
    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    
    def _interest_mode_enabled(self) -> bool:
        interest_config = self.config.get("interest")
        return bool(interest_config and interest_config.get("enabled", False))

    def run(self):
        if self._interest_mode_enabled():
            self._run_keyword_recommendations()
            return
        self._run_zotero_recommendations()

    def _run_zotero_recommendations(self):
        corpus = self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
        if len(corpus) == 0:
            logger.error(f"No zotero papers found. Please check your zotero settings:\n{self.config.zotero}")
            return
        all_papers = self._retrieve_all_papers()
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            logger.info("Generating TLDR and affiliations...")
            for p in tqdm(reranked_papers):
                p.generate_tldr(self.openai_client, self.config.llm)
                p.generate_affiliations(self.openai_client, self.config.llm)
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. No email will be sent.")
            return
        logger.info("Sending email...")
        email_content = render_email(reranked_papers)
        send_email(self.config, email_content)
        logger.info("Email sent successfully")

    def _run_keyword_recommendations(self):
        interest_config = self.config.interest
        profile = InterestProfile.from_config(self.config)
        feedback_client = GitHubFeedbackClient.from_config(self.config)
        try:
            feedback_items = feedback_client.fetch_feedback()
        except Exception as exc:
            logger.warning(f"Failed to collect GitHub feedback; continuing with current profile: {exc}")
            feedback_items = []
        applied_feedback = profile.apply_feedback(feedback_items)
        if applied_feedback:
            applied_keys = {item["feedback_key"] for item in applied_feedback}
            feedback_client.close_feedback_issues(
                [item for item in feedback_items if profile._feedback_key(item) in applied_keys]
            )
            profile.save()

        top_keywords = profile.top_keywords()
        logger.info(f"Current top keywords: {top_keywords}")

        all_papers = self._retrieve_all_papers()
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        paper_keyword_count = int(interest_config.get("paper_keyword_count", 6))
        assign_keywords_to_papers(all_papers, max_keywords=paper_keyword_count)
        for paper in all_papers:
            paper.paper_id = make_paper_id(paper)

        run_id = utcnow_iso()
        if len(all_papers) == 0:
            if not self.config.executor.send_empty:
                logger.info("No new papers found. No email will be sent.")
                profile.save()
                return
            logger.info("No new papers found. Sending empty email.")
            email_content = render_email([], top_keywords=top_keywords, exploration_keywords=[])
            send_email(self.config, email_content)
            profile.set_last_run(run_id=run_id, papers=[], exploration_keywords=[])
            profile.save()
            logger.info("Email sent successfully")
            return

        primary_count = int(interest_config.get("primary_paper_count", 40))
        exploration_count = int(interest_config.get("exploration_paper_count", 10))
        exploration_keyword_count = int(interest_config.get("exploration_keyword_count", 10))

        primary_ranked = self._rank_by_keywords(all_papers, top_keywords)
        primary_papers = primary_ranked[:primary_count]
        for paper in primary_papers:
            paper.recommendation_group = "primary"
            paper.matched_keywords = matched_keywords_for_paper(paper, top_keywords)

        exploration_keywords = guess_exploration_keywords(
            top_keywords=top_keywords,
            candidates=primary_ranked,
            feedback_history=profile.data.get("feedback_history", []),
            openai_client=self.openai_client,
            llm_config=self.config.llm,
            max_keywords=exploration_keyword_count,
            use_llm=bool(interest_config.get("use_llm_keyword_guess", True)),
        )
        logger.info(f"Exploration keywords: {exploration_keywords}")

        selected_ids = {paper.paper_id for paper in primary_papers}
        remaining = [paper for paper in all_papers if paper.paper_id not in selected_ids]
        exploration_papers = self._rank_by_keywords(remaining, exploration_keywords)[:exploration_count]
        for paper in exploration_papers:
            paper.recommendation_group = "exploration"
            paper.matched_keywords = matched_keywords_for_paper(paper, exploration_keywords)

        selected_papers = primary_papers + exploration_papers
        self._attach_feedback_urls(selected_papers, run_id)

        logger.info("Generating TLDR and affiliations...")
        for paper in tqdm(selected_papers):
            paper.generate_tldr(self.openai_client, self.config.llm)
            paper.generate_affiliations(self.openai_client, self.config.llm)

        logger.info("Sending email...")
        email_content = render_email(
            selected_papers,
            top_keywords=top_keywords,
            exploration_keywords=exploration_keywords,
        )
        send_email(self.config, email_content)
        profile.set_last_run(
            run_id=run_id,
            papers=selected_papers,
            exploration_keywords=exploration_keywords,
        )
        profile.save()
        logger.info("Email sent successfully")

    def _retrieve_all_papers(self) -> list[Paper]:
        all_papers = []
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            papers = retriever.retrieve_papers()
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        return all_papers

    def _rank_by_keywords(self, papers: list[Paper], keywords: list[str]) -> list[Paper]:
        if not papers:
            return []
        if not keywords:
            logger.warning("No keywords available for ranking; returning candidates unchanged.")
            return papers

        corpus = InterestProfile.from_config(self.config).to_corpus(keywords)
        try:
            ranked = self.reranker.rerank(papers, corpus)
        except Exception as exc:
            logger.warning(f"Configured reranker failed; falling back to keyword overlap scoring: {exc}")
            for paper in papers:
                paper.score = keyword_overlap_score(paper, keywords)
            ranked = sorted(papers, key=lambda paper: paper.score or 0.0, reverse=True)
        return ranked

    def _attach_feedback_urls(self, papers: list[Paper], run_id: str) -> None:
        feedback_config = self.config.get("feedback", {})
        if feedback_config and feedback_config.get("enabled") is False:
            return

        repo = None
        label = "paper-feedback"
        if feedback_config:
            repo = feedback_config.get("github_repo")
            label = feedback_config.get("issue_label", label)
        repo = repo or os.environ.get("GITHUB_REPOSITORY")
        if not repo:
            logger.info("GitHub repository is not configured; feedback buttons will be omitted.")
            return

        for paper in papers:
            paper.paper_id = paper.paper_id or make_paper_id(paper)
            paper.feedback_urls = {
                "interested": build_feedback_issue_url(repo, paper, "interested", run_id, label),
                "like": build_feedback_issue_url(repo, paper, "like", run_id, label),
            }

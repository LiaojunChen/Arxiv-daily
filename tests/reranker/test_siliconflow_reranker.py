import json

from tests.canned_responses import make_sample_corpus, make_sample_paper
from zotero_arxiv_daily.reranker.siliconflow import SiliconFlowReranker


class FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body


def test_siliconflow_reranker_sends_request_and_sorts(config, monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append((request, payload, timeout))
        return FakeResponse(
            {
                "results": [
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 1, "relevance_score": 0.9},
                ]
            }
        )

    monkeypatch.setattr("zotero_arxiv_daily.reranker.siliconflow.urlopen", fake_urlopen)

    config.reranker.siliconflow.model = "Qwen/Qwen3-Reranker-0.6B"
    config.reranker.siliconflow.batch_size = 64
    reranker = SiliconFlowReranker(config)
    papers = [
        make_sample_paper(title="Less Relevant"),
        make_sample_paper(title="More Relevant"),
    ]

    ranked = reranker.rerank(papers, make_sample_corpus(2))

    assert [paper.title for paper in ranked] == ["More Relevant", "Less Relevant"]
    assert ranked[0].score == 9.0
    assert len(calls) == 1
    request, payload, timeout = calls[0]
    assert request.full_url == "http://localhost:30000/v1/rerank"
    assert request.get_header("Authorization") == "Bearer sk-fake"
    assert timeout == 60
    assert payload["model"] == "Qwen/Qwen3-Reranker-0.6B"
    assert payload["top_n"] == 2
    assert payload["return_documents"] is False
    assert len(payload["documents"]) == 2
    assert "Zotero library" in payload["query"]


def test_siliconflow_reranker_batches_candidates(config, monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(payload)
        results = []
        for index, document in enumerate(payload["documents"]):
            if "Paper 2" in document:
                score = 0.8
            elif "Paper 1" in document:
                score = 0.4
            else:
                score = 0.1
            results.append({"index": index, "relevance_score": score})
        return FakeResponse({"results": results})

    monkeypatch.setattr("zotero_arxiv_daily.reranker.siliconflow.urlopen", fake_urlopen)

    config.reranker.siliconflow.batch_size = 2
    reranker = SiliconFlowReranker(config)
    papers = [make_sample_paper(title=f"Paper {index}") for index in range(3)]

    ranked = reranker.rerank(papers, make_sample_corpus(1))

    assert [paper.title for paper in ranked] == ["Paper 2", "Paper 1", "Paper 0"]
    assert [call["top_n"] for call in calls] == [2, 1]

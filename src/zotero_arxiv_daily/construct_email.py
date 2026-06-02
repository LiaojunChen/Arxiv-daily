from __future__ import annotations

import html
import math

from .protocol import Paper


INTERESTED_LABEL = "\u611f\u5174\u8da3"
LIKE_LABEL = "\u559c\u6b22"


framework = """
<!DOCTYPE HTML>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { margin: 0; padding: 0; background: #f4f6f8; }
    .page { font-family: Arial, sans-serif; color: #222; max-width: 920px; margin: 0 auto; padding: 20px 12px; }
    .header { background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px; padding: 18px; margin-bottom: 16px; }
    .section-title { font-size: 18px; font-weight: 700; margin: 22px 0 10px; color: #111827; }
    .paper-card { width: 100%; border: 1px solid #d9e2ec; border-radius: 8px; background-color: #ffffff; margin: 0 0 14px; }
    .paper-inner { padding: 16px; }
    .paper-title { font-size: 19px; line-height: 1.35; font-weight: 700; color: #111827; }
    .paper-title a { color: #111827; text-decoration: none; }
    .meta { font-size: 13px; color: #596579; line-height: 1.45; padding-top: 8px; }
    .field { font-size: 14px; line-height: 1.5; color: #263241; padding-top: 10px; }
    .chip { display: inline-block; border: 1px solid #cbd5e1; border-radius: 999px; padding: 3px 8px; margin: 3px 4px 3px 0; background: #f8fafc; color: #334155; font-size: 12px; }
    .button { display: inline-block; text-decoration: none; font-size: 13px; font-weight: bold; color: #ffffff; padding: 8px 12px; border-radius: 5px; margin: 8px 6px 0 0; }
    .button-pdf { background: #d9534f; }
    .button-paper { background: #2563eb; }
    .button-interested { background: #047857; }
    .button-like { background: #7c3aed; }
    .muted { color: #64748b; font-size: 13px; line-height: 1.45; }
    .star-wrapper { font-size: 1.3em; line-height: 1; display: inline-flex; align-items: center; }
    .half-star { display: inline-block; width: 0.5em; overflow: hidden; white-space: nowrap; vertical-align: middle; }
    .full-star { vertical-align: middle; }
  </style>
</head>
<body>
<div class="page">
    __CONTENT__
    <br><br>
    <div class="muted">
      To unsubscribe, remove your email in your GitHub Action settings.
    </div>
</div>
</body>
</html>
"""


def _escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _chips(items: list[str] | None) -> str:
    if not items:
        return '<span class="muted">None</span>'
    return "".join(f'<span class="chip">{_escape(item)}</span>' for item in items)


def get_empty_html():
    return """
    <table border="0" cellpadding="0" cellspacing="0" width="100%" class="paper-card">
      <tr>
        <td class="paper-inner">
          <div class="paper-title">No Papers Today. Take a Rest!</div>
        </td>
      </tr>
    </table>
    """


def _button(url: str | None, label: str, css_class: str) -> str:
    if not url:
        return ""
    return f'<a href="{_escape(url)}" class="button {css_class}">{_escape(label)}</a>'


def get_block_html(
    title: str,
    authors: str,
    rate: str,
    tldr: str,
    pdf_url: str,
    affiliations: str | None = None,
    keywords: list[str] | None = None,
    feedback_urls: dict[str, str] | None = None,
    paper_url: str | None = None,
    matched_keywords: list[str] | None = None,
):
    feedback_urls = feedback_urls or {}
    title_html = _escape(title)
    if paper_url:
        title_html = f'<a href="{_escape(paper_url)}">{title_html}</a>'

    actions = (
        _button(pdf_url, "PDF", "button-pdf")
        + _button(paper_url, "Abstract", "button-paper")
        + _button(feedback_urls.get("interested"), INTERESTED_LABEL, "button-interested")
        + _button(feedback_urls.get("like"), LIKE_LABEL, "button-like")
    )

    matched_html = ""
    if matched_keywords:
        matched_html = f"""
        <div class="field">
          <strong>Matched Top Keywords:</strong> {_chips(matched_keywords)}
        </div>
        """

    return f"""
    <table border="0" cellpadding="0" cellspacing="0" width="100%" class="paper-card">
      <tr>
        <td class="paper-inner">
          <div class="paper-title">{title_html}</div>
          <div class="meta">
            {_escape(authors)}<br>
            <i>{_escape(affiliations or "Unknown Affiliation")}</i>
          </div>
          <div class="field"><strong>Similarity:</strong> {_escape(rate)}</div>
          <div class="field"><strong>TLDR:</strong> {_escape(tldr)}</div>
          <div class="field"><strong>Keywords:</strong> {_chips(keywords)}</div>
          {matched_html}
          <div>{actions}</div>
        </td>
      </tr>
    </table>
    """


def get_stars(score: float):
    full_star = '<span class="full-star">&#9733;</span>'
    half_star = '<span class="half-star">&#9733;</span>'
    low = 6
    high = 8
    if score <= low:
        return ""
    if score >= high:
        return full_star * 5

    interval = (high - low) / 10
    star_num = math.ceil((score - low) / interval)
    full_star_num = int(star_num / 2)
    half_star_num = star_num - full_star_num * 2
    return '<div class="star-wrapper">' + full_star * full_star_num + half_star * half_star_num + "</div>"


def _format_authors(authors: list[str]) -> str:
    author_list = [author for author in authors]
    num_authors = len(author_list)
    if num_authors <= 5:
        return ", ".join(author_list)
    return ", ".join(author_list[:3] + ["..."] + author_list[-2:])


def _format_affiliations(affiliations: list[str] | None) -> str:
    if affiliations is None:
        return "Unknown Affiliation"
    selected = affiliations[:5]
    text = ", ".join(selected)
    if len(affiliations) > 5:
        text += ", ..."
    return text


def _header_html(top_keywords: list[str] | None, exploration_keywords: list[str] | None) -> str:
    if not top_keywords and not exploration_keywords:
        return ""
    exploration_block = ""
    if exploration_keywords:
        exploration_block = f"""
        <div class="field"><strong>Exploration Keywords:</strong> {_chips(exploration_keywords)}</div>
        """
    return f"""
    <div class="header">
      <div class="paper-title">Daily Paper Recommendations</div>
      <div class="field"><strong>Current Top Keywords:</strong> {_chips(top_keywords)}</div>
      {exploration_block}
      <div class="muted">Feedback buttons open a pre-filled GitHub issue. Submit it, and the next scheduled run will update the keyword profile automatically.</div>
    </div>
    """


def _paper_html(paper: Paper) -> str:
    rate = round(paper.score, 2) if paper.score is not None else "Unknown"
    return get_block_html(
        paper.title,
        _format_authors(paper.authors),
        str(rate),
        paper.tldr or paper.abstract or "",
        paper.pdf_url or "",
        _format_affiliations(paper.affiliations),
        paper.keywords,
        paper.feedback_urls,
        paper.url,
        paper.matched_keywords,
    )


def render_email(
    papers: list[Paper],
    *,
    top_keywords: list[str] | None = None,
    exploration_keywords: list[str] | None = None,
) -> str:
    if len(papers) == 0:
        content = _header_html(top_keywords, exploration_keywords) + get_empty_html()
        return framework.replace("__CONTENT__", content)

    parts = [_header_html(top_keywords, exploration_keywords)]
    primary = [paper for paper in papers if paper.recommendation_group == "primary"]
    exploration = [paper for paper in papers if paper.recommendation_group == "exploration"]
    other = [paper for paper in papers if paper.recommendation_group not in {"primary", "exploration"}]

    if primary or exploration:
        if primary:
            parts.append('<div class="section-title">Top Keyword Matches</div>')
            parts.extend(_paper_html(paper) for paper in primary)
        if exploration:
            parts.append('<div class="section-title">Exploratory Picks</div>')
            parts.extend(_paper_html(paper) for paper in exploration)
        if other:
            parts.append('<div class="section-title">Additional Papers</div>')
            parts.extend(_paper_html(paper) for paper in other)
    else:
        parts.extend(_paper_html(paper) for paper in papers)

    return framework.replace("__CONTENT__", "\n".join(parts))

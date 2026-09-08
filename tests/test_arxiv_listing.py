import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from arxiv_listing import parse_listing


def section(name, key, count="1 of 1"):
    return f"""<dl id='articles'><h3>{name} (showing {count} entries)</h3>
    <dt><a href='/abs/{key}'>arXiv:{key}</a><a href='/pdf/{key}'>pdf</a></dt>
    <dd><div class='meta'><div class='list-title mathjax'>
    <span class='descriptor'>Title:</span> A &amp; B <b>model</b></div>
    <div class='list-authors'><a>Alice Smith</a>, <a>Bob Li</a></div>
    <div class='list-subjects'><span>Subjects:</span>AI (cs.AI); ML (cs.LG)</div>
    <p class='mathjax'>A new <em>world</em> model.</p></div></dd></dl>"""


def test_real_structure_keeps_cross_lists_excludes_replacements_and_preserves_date():
    html = "<h3>Showing new listings for Monday, 7 September 2026</h3>"
    html += section("New submissions", "2609.00001")
    html += section("Cross submissions", "2609.00002")
    html += section("Replacement submissions", "2609.00003")
    papers = parse_listing(html)
    assert [p["arxiv_id"] for p in papers] == ["2609.00001", "2609.00002"]
    assert papers[0]["title"] == "A & B model"
    assert papers[0]["abstract"] == "A new world model."
    assert papers[0]["authors"] == ["Alice Smith", "Bob Li"]
    assert papers[0]["categories"] == ["cs.AI", "cs.LG"]
    assert papers[0]["source_date"] == "2026-09-07"


@pytest.mark.parametrize("html", ["<html>Service unavailable</html>",
    "<h3>Showing new listings for Monday, 7 September 2026</h3>" + section("New submissions", "2609.00001", "1 of 2001")])
def test_invalid_and_truncated_lists_fail_for_rss_fallback(html):
    with pytest.raises(ValueError):
        parse_listing(html)

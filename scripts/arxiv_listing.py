"""Read announcement-time listings; RSS is published later in the day."""
import re
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def find(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()):
                    yield child
                yield from child.find(tag, cls)


class ListingHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_listing(html):
    parser = ListingHTML()
    parser.feed(html)
    root = parser.root
    heading = next((h.text() for h in root.find("h3") if "Showing new listings for " in h.text()), None)
    if not heading:
        raise ValueError("Missing arXiv listing date")
    date = datetime.strptime(heading.strip().split(" for ", 1)[1], "%A, %d %B %Y").date().isoformat()
    articles = [n for n in root.find("dl") if n.attrs.get("id") == "articles"]
    if not articles:
        raise ValueError("Missing arXiv articles")
    papers, arxiv_id, replacements = [], None, False
    for node in (child for section in articles for child in section.children):
        if not isinstance(node, Node):
            continue
        if node.tag == "h3":
            replacements = "replacement" in node.text().lower()
            match = re.search(r"showing (\d+) of (\d+)", node.text())
            if match and match[1] != match[2]:
                raise ValueError("Truncated arXiv listing")
        if node.tag == "dt":
            arxiv_id = next((a.attrs["href"].split("/abs/", 1)[1] for a in node.find("a") if a.attrs.get("href", "").startswith("/abs/")), None)
        if node.tag != "dd" or replacements:
            continue
        def field(cls):
            return next(node.find(cls=cls), Node())
        title = " ".join(field("list-title").text().removeprefix("Title:").split())
        title = re.sub(r"^Title:\s*", "", title)
        abstract = " ".join(" ".join(p.text() for p in node.find("p", "mathjax")).split())
        authors = [" ".join(a.text().split()) for a in field("list-authors").find("a")]
        if not arxiv_id or not title or not abstract or not authors:
            raise ValueError("Incomplete arXiv listing entry")
        papers.append(dict(arxiv_id=arxiv_id, title=title, abstract=abstract, authors=authors,
            categories=re.findall(r"\(([A-Za-z][A-Za-z0-9.-]*)\)", field("list-subjects").text()),
            affiliations=[], source="arxiv", source_date=date, listing_date=date,
            published=date, abstract_url=f"https://arxiv.org/abs/{arxiv_id}", pdf_url=f"https://arxiv.org/pdf/{arxiv_id}"))
        arxiv_id = None
    return papers


def get_new_listing_papers(categories):
    cats = list(dict.fromkeys(c for c in re.split(r"[+,\s]+", categories.strip()) if c))
    if not cats or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*", c) for c in cats):
        raise ValueError("Invalid arXiv category codes")
    papers = []
    for index, category in enumerate(cats):
        if index:
            time.sleep(3)
        request = urllib.request.Request(f"https://arxiv.org/list/{category}/new?show=2000", headers={"User-Agent": "arXivDaily/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            papers.extend(parse_listing(response.read().decode("utf-8")))
    return papers

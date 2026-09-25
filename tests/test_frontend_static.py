"""Browser-free consistency checks between the frontend's static files."""

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "app" / "static"


def test_every_element_id_used_by_app_js_exists_in_index_html():
    js_source = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))

    used = set(re.findall(r'getElementById\("([^"$]+)"\)', js_source))
    used |= set(re.findall(r'querySelector\("#([\w-]+)"\)', js_source))
    for view in re.search(r"const VIEWS = \[([^\]]+)\]", js_source).group(1).split(","):
        used.add(f"view-{view.strip().strip(chr(34))}")
    for dialog in re.findall(r'setupDialog\("([^"]+)"', js_source):
        used.add(dialog)

    assert used, "regexes found nothing; did app.js change shape?"
    assert used - html_ids == set()


def test_index_html_references_existing_assets():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/static/([^"]+)"', html)
    assert sorted(refs) == ["app.js", "styles.css"]
    for ref in refs:
        assert (STATIC / ref).is_file()

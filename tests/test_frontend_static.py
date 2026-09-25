"""Browser-free consistency checks between the frontend's static files."""

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "app" / "static"
JS_FILES = sorted(STATIC.rglob("*.js"))


def js_source():
    return "\n".join(f.read_text(encoding="utf-8") for f in JS_FILES)


def test_every_element_id_used_by_the_js_exists_in_index_html():
    source = js_source()
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))

    used = set(re.findall(r'getElementById\("([^"$]+)"\)', source))
    used |= set(re.findall(r'querySelector\("#([\w-]+)"\)', source))
    for view in re.search(r"const VIEWS = \[([^\]]+)\]", source).group(1).split(","):
        used.add(f"view-{view.strip().strip(chr(34))}")
    for dialog in re.findall(r'setupDialog\("([^"]+)"', source):
        used.add(dialog)

    assert used, "regexes found nothing; did the JS change shape?"
    assert used - html_ids == set()


def test_index_html_references_existing_assets():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/static/([^"]+)"', html)
    assert sorted(refs) == ["main.js", "styles.css"]
    assert '<script type="module" src="/static/main.js">' in html
    for ref in refs:
        assert (STATIC / ref).is_file()


def test_every_relative_import_resolves_to_a_file():
    """A typo in an import path only fails in the browser, at load time, so catch it here."""
    for f in JS_FILES:
        for target in re.findall(r'^import\s+(?:[^"]*?\s+from\s+)?"(\.[^"]+)";', f.read_text(encoding="utf-8"), re.M):
            assert (f.parent / target).resolve().is_file(), f"{f.relative_to(STATIC)} imports missing {target}"


def test_every_module_is_reachable_from_main():
    """Each .js file must be imported (directly or not) by main.js, or it never runs."""
    seen, todo = set(), [STATIC / "main.js"]
    while todo:
        f = todo.pop().resolve()
        if f in seen:
            continue
        seen.add(f)
        for target in re.findall(r'^import\s+(?:[^"]*?\s+from\s+)?"(\.[^"]+)";', f.read_text(encoding="utf-8"), re.M):
            todo.append(f.parent / target)
    assert {f.resolve() for f in JS_FILES} - seen == set()

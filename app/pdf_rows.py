"""Layout helpers shared by the PDF importers (import_meet_results.py, import_time_standards.py)."""


def cluster_rows(words, tol=2.5):
    """Group pdfplumber words into rows by y-position ('top'), tolerating small jitter."""
    # Words are visited top-down and each row's anchor is more than `tol` below
    # the previous one, so only the most recent row can ever match - O(n).
    rows = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and w["top"] - rows[-1]["top"] <= tol:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    return rows

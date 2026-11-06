#!/usr/bin/env python3
"""
Extract underlined sentences from the new PDF using PyMuPDF,
then patch questions3.json and questions4.json with underlinedSentence fields.
"""
import pymupdf
import re
import json
import os

PDF_PATH  = os.path.expanduser("~/Downloads/questionbank-export-2026-11-5.pdf")
EOI_JSON  = os.path.join(os.path.dirname(__file__), "questions3.json")
CS_JSON   = os.path.join(os.path.dirname(__file__), "questions4.json")

def norm(s):
    """Normalize for fuzzy matching: lowercase, remove whitespace, standardize apostrophes."""
    s = s.replace("'", "'").replace("'", "'").replace("’", "'").replace("‘", "'")
    return re.sub(r"[\s]", "", s.lower())

def get_page_underlines(page):
    """Return list of (y0, x0, x1) for thin black horizontal rects on the page."""
    underlines = []
    for p in page.get_drawings():
        fill = p.get("fill")
        if not fill or not all(c < 0.15 for c in fill):
            continue
        for item in p["items"]:
            if item[0] == "re":
                r = item[1]
                h = r.y1 - r.y0
                w = r.x1 - r.x0
                if 0 < h < 2.5 and w > 30:
                    underlines.append((r.y0, r.x0, r.x1))
    return sorted(underlines)

def extract_underlined_raw(page):
    """Extract raw underlined text using word-level extraction + underline rects."""
    underlines = get_page_underlines(page)
    if not underlines:
        return None

    words = page.get_text("words")  # (x0, y0, x1, y1, word, ...)

    # For each underline, collect words whose bottom is just above it
    per_ul = {}
    for ul_y0, ul_x0, ul_x1 in underlines:
        key = round(ul_y0, 1)
        per_ul[key] = []
        for w in words:
            wx0, wy0, wx1, wy1, word = w[:5]
            y_diff = ul_y0 - wy1
            if -2 < y_diff < 5:
                x_overlap = min(wx1, ul_x1) - max(wx0, ul_x0)
                if x_overlap > 3:
                    per_ul[key].append((wx0, word))

    # Sort each line by x, then join lines by y order
    parts = []
    for key in sorted(per_ul.keys()):
        line_words = sorted(per_ul[key])
        if line_words:
            parts.append(" ".join(w for _, w in line_words))

    return " ".join(parts).strip() if parts else None

def find_in_passage(raw_underlined, passage):
    """
    Find raw_underlined (possibly with space/ligature differences) as a substring
    of passage and return the exact matching passage substring, extended to word boundaries.
    """
    n_ul = norm(raw_underlined)
    n_pass = norm(passage)

    if not n_ul or len(n_ul) < 5:
        return None

    idx = n_pass.find(n_ul)
    if idx == -1:
        n_ul2 = n_ul.rstrip('.')
        idx = n_pass.find(n_ul2)
        if idx == -1:
            return None
        n_ul = n_ul2

    # Map normalized idx back to original passage character positions
    count = 0
    start_orig = end_orig = None
    for i, c in enumerate(passage):
        nc = norm(c)
        if nc:
            if count == idx:
                start_orig = i
            count += len(nc)
            if count >= idx + len(n_ul):
                end_orig = i + 1
                break

    if start_orig is None or end_orig is None:
        return None

    # Extend start backwards to word boundary if we're mid-word
    while start_orig > 0 and passage[start_orig - 1].isalpha():
        start_orig -= 1

    return passage[start_orig:end_orig].strip()

def build_qid_page_map(doc):
    """Build a map from question ID to page index (0-based)."""
    qid_page = {}
    for i, page in enumerate(doc):
        # Fast text check
        text = page.get_text()
        for m in re.finditer(r'Question ID:\s*([a-f0-9]+)', text):
            qid = m.group(1)
            if qid not in qid_page:
                qid_page[qid] = i
    return qid_page

def patch_questions(questions, qid_page, doc):
    patched = 0
    for q in questions:
        qid = q["id"]
        page_idx = qid_page.get(qid)
        if page_idx is None:
            continue

        page = doc[page_idx]
        raw_ul = extract_underlined_raw(page)
        if not raw_ul:
            continue

        passage = q["question"]
        matched = find_in_passage(raw_ul, passage)
        if matched and len(matched) > 10:
            q["underlinedSentence"] = matched
            patched += 1

    return patched

def main():
    print(f"Opening {PDF_PATH}…")
    doc = pymupdf.open(PDF_PATH)
    print(f"Building page map ({len(doc)} pages)…")
    qid_page = build_qid_page_map(doc)
    print(f"Found {len(qid_page)} question IDs")

    for path, label in [(EOI_JSON, "Expression of Ideas"), (CS_JSON, "Craft and Structure")]:
        with open(path) as f:
            questions = json.load(f)
        n = patch_questions(questions, qid_page, doc)
        with open(path, "w") as f:
            json.dump(questions, f, indent=2, ensure_ascii=False)
        print(f"{label}: patched {n}/{len(questions)} questions with underlinedSentence")

    print("Done.")

if __name__ == "__main__":
    main()

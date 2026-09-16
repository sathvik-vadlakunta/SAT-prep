#!/usr/bin/env python3
"""
Renders each visual question's PDF page, crops to show only the chart/table
(below metadata table header, above passage text), saves to graphs/.
Also patches questions.json for text-table questions and updates graphImage paths.
"""
import re
import json
import subprocess
import os
import tempfile
from PIL import Image

PDF_PATH = os.path.expanduser("~/Downloads/questionbank-export-2026-9-13.pdf")
GRAPHS_DIR = os.path.join(os.path.dirname(__file__), "graphs")
QUESTIONS_JSON = os.path.join(os.path.dirname(__file__), "questions.json")
DPI = 130
MAX_W = 920

os.makedirs(GRAPHS_DIR, exist_ok=True)

PROSE_WORDS = {
    'the','a','an','of','in','to','that','and','or','but','with','for',
    'was','were','have','has','had','is','are','be','been','may','can',
    'this','which','who','from','by','as','on','at','its','their','it',
    'these','those','however','recently','although','while','since','when',
    'not','no','some','many','most','all','such','other','also','researchers',
    'study','students','scientists','data'
}

def is_prose_line(line):
    words = line.lower().split()
    if len(words) < 7:
        return False
    common = sum(1 for w in words if re.sub(r'[^a-z]', '', w) in PROSE_WORDS)
    return common >= 3

def find_chart_bounds(img):
    """
    Returns (crop_top, crop_bottom).
    crop_top: just below the CB metadata table (~13.5% of page height).
    crop_bottom: just before the passage text (detected via white-gap then text).
    """
    w, h = img.size
    px = img.load()

    # --- Fixed crop top: always skip the metadata table & "Question" label ---
    # The metadata table ends at ~9.5% of page height, "Question" label is
    # another ~1.5% below, so starting at 13% is reliably past both.
    crop_top = int(h * 0.130)

    # --- Find passage start via gap detection ---
    # After the chart/table there's a blank region (gap) before the prose.
    # We look for a run of ≥18 mostly-white rows, then text resuming.
    ROW_STEP = 5
    MIN_GAP = 18
    gap_count = 0
    in_gap = False
    passage_start = int(h * 0.56)   # conservative default (~56% of page)

    search_start = crop_top + 80    # give chart at least 80px

    for y in range(search_start, h - 80):
        # Count dark pixels across the full row
        dark = sum(1 for x in range(20, w - 20, ROW_STEP) if sum(px[x, y]) < 215)
        total_samples = (w - 40) // ROW_STEP
        white_row = dark / total_samples < 0.012   # <1.2% dark = mostly white

        if white_row:
            gap_count += 1
            in_gap = True
        else:
            if in_gap and gap_count >= MIN_GAP:
                # We just left a significant gap — this row starts the passage
                passage_start = y - 4
                break
            # Not enough gap, reset
            gap_count = 0
            in_gap = False

    crop_bottom = min(passage_start, int(h * 0.70))

    # Safety: crop must be at least 120px tall
    if crop_bottom - crop_top < 120:
        crop_bottom = crop_top + 300

    return crop_top, crop_bottom


def render_page_crop(page_num):
    """Render one PDF page and return a cropped PIL Image of the chart area."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "p")
        subprocess.run(
            ["pdftoppm", "-r", str(DPI), "-f", str(page_num), "-l", str(page_num),
             "-png", PDF_PATH, prefix],
            capture_output=True
        )
        files = sorted(f for f in os.listdir(tmpdir) if f.endswith(".png"))
        if not files:
            return None
        img = Image.open(os.path.join(tmpdir, files[0])).convert("RGB")
        ct, cb = find_chart_bounds(img)
        w = img.size[0]
        cropped = img.crop((12, ct, w - 12, cb))
        if cropped.width > MAX_W:
            ratio = MAX_W / cropped.width
            cropped = cropped.resize((MAX_W, int(cropped.height * ratio)), Image.LANCZOS)
        return cropped


def detect_text_table(question_text):
    """
    Returns (is_table, passage_text) for questions where the 'graph' is a
    plain-text table (pdftotext rendered it as text, not a vector graphic).
    """
    lines = question_text.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i > 0 and stripped and is_prose_line(stripped):
            table_part = lines[:i]
            # Only a table if table part has numeric data
            table_text = '\n'.join(table_part)
            if re.search(r'[\d.]+\s*%?|\bkm/s\b|\bdays?\b|\bhours?\b', table_text):
                return True, '\n'.join(lines[i:]).strip()
    return False, question_text


def main():
    # Build page map
    result = subprocess.run(["pdftotext", "-raw", PDF_PATH, "-"], capture_output=True, text=True)
    pages = result.stdout.split("\x0c")
    qid_to_page = {}
    for pn, pt in enumerate(pages, 1):
        for qid in re.findall(r"Question ID:\s*([a-f0-9]+)", pt):
            if qid not in qid_to_page:
                qid_to_page[qid] = pn

    with open(QUESTIONS_JSON) as f:
        questions = json.load(f)

    # --- Pass 1: detect and patch text-table questions ---
    patched = 0
    for q in questions:
        if q.get('hasGraph'):
            continue
        is_tbl, passage = detect_text_table(q['question'])
        if is_tbl:
            q['hasGraph'] = True
            q['graphTitle'] = 'Table'
            q['question'] = passage   # only the prose stays in q.question
            patched += 1
            print(f"  Patched text-table: {q['id']} ({q['skill']})")
    print(f"Patched {patched} text-table questions")

    # --- Pass 2: extract images ---
    graph_qs = [q for q in questions if q.get('hasGraph')]
    print(f"\nExtracting images for {len(graph_qs)} visual questions...")

    for i, q in enumerate(graph_qs):
        qid = q['id']
        page = qid_to_page.get(qid)
        if not page:
            print(f"  [{i+1}] {qid}: no page, skip")
            continue

        out = os.path.join(GRAPHS_DIR, f"{qid}.png")

        # Force re-extract if already exists (to apply new crop logic)
        cropped = render_page_crop(page)
        if cropped:
            cropped.save(out, "PNG", optimize=True)
            q['graphImage'] = f"graphs/{qid}.png"
            sz = os.path.getsize(out) // 1024
            print(f"  [{i+1}/{len(graph_qs)}] {qid}: p{page} → {cropped.size} ({sz}KB)")
        else:
            print(f"  [{i+1}/{len(graph_qs)}] {qid}: render failed")

    with open(QUESTIONS_JSON, "w") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    print("\nDone — questions.json updated.")


if __name__ == "__main__":
    main()

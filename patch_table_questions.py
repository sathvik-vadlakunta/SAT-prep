#!/usr/bin/env python3
"""
Find all table questions where the table data is embedded as raw text
(hasGraph=False but question references 'the table'), render their PDF pages
as images, strip table text from q.question, and set hasGraph=True.
"""
import re, json, subprocess, os, tempfile
from PIL import Image

PDF_PATH = os.path.expanduser("~/Downloads/questionbank-export-2026-9-13.pdf")
GRAPHS_DIR = os.path.join(os.path.dirname(__file__), "graphs")
QUESTIONS_JSON = os.path.join(os.path.dirname(__file__), "questions.json")
DPI = 130
MAX_W = 920

PROSE_WORDS = {
    'the','a','an','of','in','to','that','and','or','but','with','for',
    'was','were','have','has','had','is','are','be','been','may','can',
    'this','which','who','from','by','as','on','at','its','their','it',
    'these','those','however','recently','although','while','since','when',
    'not','no','some','many','most','all','such','other','also'
}


def find_prose_start(lines):
    """
    Return the index where the prose passage begins, after the table data.
    Strategy: find the last clearly-numeric data row, then scan forward for
    the first long prose line (skipping table footnotes).
    """
    def num_count(line):
        return len(re.findall(r'\b\d+\.?\d*\b', line))

    def is_data_row(line):
        n = num_count(line)
        w = len(line.split())
        return (n >= 2 and w > 0 and n / w >= 0.3) or n >= 4

    def is_footnote(line):
        return bool(re.match(r'Rows?\s+(in\s+table|may)', line, re.IGNORECASE))

    def is_prose(line):
        words = line.split()
        low = re.sub(r'[^a-z ]', ' ', line.lower()).split()
        common = sum(1 for w in low if w in PROSE_WORDS)
        return len(words) >= 8 and common >= 4

    # Find last data row
    last_data = 0
    for i, line in enumerate(lines):
        if is_data_row(line.strip()):
            last_data = i

    # Scan forward from after last data row for first prose line
    for i in range(last_data + 1, len(lines)):
        line = lines[i].strip()
        if not line or is_footnote(line):
            continue
        if is_prose(line):
            return i

    # Fallback: scan from line 1 for first prose line
    for i in range(1, len(lines)):
        line = lines[i].strip()
        if not line or is_footnote(line):
            continue
        if is_prose(line):
            return i

    return 1


def find_chart_bounds(img):
    w, h = img.size
    px = img.load()
    crop_top = int(h * 0.130)
    LEFT_MARGIN, LEFT_END = 55, 130
    passage_start = int(h * 0.67)
    for y in range(crop_top + 100, h - 60):
        left_dark = sum(1 for x in range(LEFT_MARGIN, LEFT_END, 4) if sum(px[x, y]) < 195)
        if left_dark < 2:
            continue
        center_dark = sum(1 for x in range(w // 5, 4 * w // 5, 8) if sum(px[x, y]) < 200)
        if center_dark >= 5:
            passage_start = y - 4
            break
    crop_bottom = min(passage_start, int(h * 0.69))
    if crop_bottom - crop_top < 200:
        crop_bottom = crop_top + 340
    return crop_top, crop_bottom


def render_page_crop(page_num):
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
        cropped = img.crop((12, ct, img.size[0] - 12, cb))
        if cropped.width > MAX_W:
            ratio = MAX_W / cropped.width
            cropped = cropped.resize((MAX_W, int(cropped.height * ratio)), Image.LANCZOS)
        return cropped


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

    # Find all table questions with embedded raw text
    targets = [
        q for q in questions
        if not q.get('hasGraph')
        and re.search(r'\bthe table\b', q['question'], re.IGNORECASE)
    ]
    print(f"Found {len(targets)} unpatched table questions")

    for i, q in enumerate(targets):
        qid = q['id']
        lines = q['question'].split('\n')
        split_idx = find_prose_start(lines)
        prose = '\n'.join(lines[split_idx:]).strip()

        page = qid_to_page.get(qid)
        if not page:
            print(f"  [{i+1}] {qid}: no page found, skipping")
            continue

        out = os.path.join(GRAPHS_DIR, f"{qid}.png")
        cropped = render_page_crop(page)
        if not cropped:
            print(f"  [{i+1}] {qid}: render failed")
            continue

        cropped.save(out, "PNG", optimize=True)
        q['hasGraph'] = True
        q['graphTitle'] = 'Table'
        q['graphImage'] = f"graphs/{qid}.png"
        q['question'] = prose
        sz = os.path.getsize(out) // 1024
        print(f"  [{i+1}/{len(targets)}] {qid}: p{page}, split@{split_idx}, {cropped.size} ({sz}KB)")

    with open(QUESTIONS_JSON, "w") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    print(f"\nDone. Patched {len(targets)} questions, questions.json updated.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Parse SAT Math Hard questions from PDF.
Renders each question as a cropped PNG (above Correct Answer:) so that
formulas and graphs are displayed correctly in the browser.
"""
import re, json, os
import pymupdf

PDF_PATH = os.path.expanduser(
    '~/Downloads/questionbank-export-2026-11-23 (1).pdf'
)
OUT_JSON    = os.path.join(os.path.dirname(__file__), 'questions5.json')
OUT_IMG_DIR = os.path.join(os.path.dirname(__file__), 'images', 'math')

os.makedirs(OUT_IMG_DIR, exist_ok=True)

MATH_DOMAINS = [
    'Algebra',
    'Advanced Math',
    'Problem-Solving and Data Analysis',
    'Geometry and Trigonometry',
]

def parse_metadata(text):
    m = re.search(
        r'\nSAT\n(Math|Reading and Writing)\n(.*?)\n(Easy|Medium|Hard)\n',
        text, re.DOTALL
    )
    if not m:
        return None, None, None, None
    test       = m.group(1)
    rest       = re.sub(r'\s+', ' ', m.group(2).strip())
    difficulty = m.group(3)
    domain = skill = ''
    for d in MATH_DOMAINS:
        if rest.startswith(d):
            domain = d
            skill  = rest[len(d):].strip()
            break
    return test, domain, skill, difficulty

def render_question_image(page, qid):
    """Render page area above 'Correct Answer:' as a PNG and return rel path."""
    rects = page.search_for('Correct Answer:')
    y_crop = rects[0].y0 - 4 if rects else page.rect.height
    clip = pymupdf.Rect(page.rect.x0, page.rect.y0, page.rect.x1, y_crop)
    mat  = pymupdf.Matrix(1.5, 1.5)
    pix  = page.get_pixmap(matrix=mat, clip=clip, colorspace=pymupdf.csRGB)
    img_path = os.path.join(OUT_IMG_DIR, f'{qid}.png')
    pix.save(img_path)
    return f'images/math/{qid}.png'

def extract_choices_text(text):
    choices = {}
    answer_match = re.search(
        r'\nAnswer\n(.*?)(?:Correct Answer:|$)', text, re.DOTALL
    )
    if not answer_match:
        return choices
    block = answer_match.group(1)
    for m in re.finditer(r'\n([A-D])\.\s*(.*?)(?=\n[A-D]\.\s|$)', block, re.DOTALL):
        letter = m.group(1)
        txt    = re.sub(r'\s+', ' ', m.group(2)).strip()
        choices[letter] = txt
    return choices

def clean_rationale(text):
    m = re.search(r'\nRationale\n(.*?)$', text, re.DOTALL)
    if not m:
        return ''
    rat = re.sub(r'\s*\x0c.*', '', m.group(1), flags=re.DOTALL)  # stop at page break
    return re.sub(r'  +', ' ', re.sub(r'\n+', ' ', rat.strip()))

def main():
    doc = pymupdf.open(PDF_PATH)
    print(f'PDF: {len(doc)} pages')

    questions = []
    img_errors = 0

    for pg_num in range(len(doc)):
        page = doc[pg_num]
        text = page.get_text()

        if not text.strip().startswith('Question ID:'):
            continue

        qid_m = re.search(r'Question ID:\s*([a-f0-9]+)', text)
        if not qid_m:
            continue
        qid = qid_m.group(1)

        test, domain, skill, difficulty = parse_metadata(text)
        if test != 'Math' or domain not in MATH_DOMAINS:
            continue
        if difficulty != 'Hard':
            continue

        correct_m = re.search(r'Correct Answer:\s*([^\n]+)', text)
        correct   = correct_m.group(1).strip() if correct_m else ''
        is_mcq    = correct in ('A', 'B', 'C', 'D')

        choices  = extract_choices_text(text) if is_mcq else {}
        rationale = clean_rationale(text)

        try:
            img_path = render_question_image(page, qid)
        except Exception as e:
            print(f'  image error {qid}: {e}')
            img_path = None
            img_errors += 1

        questions.append({
            'id':            qid,
            'assessment':    'SAT',
            'test':          'Math',
            'domain':        domain,
            'skill':         skill,
            'difficulty':    'Hard',
            'correct':       correct,
            'is_mcq':        is_mcq,
            'choices':       choices,
            'rationale':     rationale,
            'questionImage': img_path,
        })

    doc.close()

    domains = {}
    for q in questions:
        domains[q['domain']] = domains.get(q['domain'], 0) + 1
    mcq_n = sum(1 for q in questions if q['is_mcq'])

    print(f'Hard math questions: {len(questions)}')
    print(f'  MCQ: {mcq_n}  Free-response: {len(questions)-mcq_n}')
    print(f'  Domains: {domains}')
    print(f'  Image errors: {img_errors}')

    with open(OUT_JSON, 'w') as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    print(f'Saved to {OUT_JSON}')
    print(f'Images in {OUT_IMG_DIR}')

if __name__ == '__main__':
    main()

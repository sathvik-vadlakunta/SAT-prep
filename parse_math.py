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
    """Render question content only — below metadata, above answer choices/correct answer."""
    # Top crop: just below the difficulty label in the metadata table.
    y_start = page.rect.y0
    for diff in ('Hard', 'Medium', 'Easy'):
        rects = page.search_for(diff)
        if rects:
            y_start = rects[0].y1 + 6
            break

    # Also skip the "Question" section header itself
    for x0, by0, x1, by1, btext, bno, btype in page.get_text('blocks'):
        if btext.strip() == 'Question' and by0 > y_start:
            y_start = by1 + 4
            break

    # Bottom crop: "Correct Answer:" first, then "Rationale" as fallback
    y_end = page.rect.height
    for label in ('Correct Answer:', 'Rationale'):
        rects = page.search_for(label)
        if rects:
            y_end = rects[0].y0 - 4
            break

    # For MCQ pages there's a standalone "Answer" section header above the choices.
    # Crop at that so the choices don't appear in the image (they're rendered as buttons).
    answer_block_found = False
    for x0, by0, x1, by1, btext, bno, btype in page.get_text('blocks'):
        if btext.strip() == 'Answer' and y_start < by0 < y_end:
            y_end = by0 - 4
            answer_block_found = True
            break

    # Safety: only apply minimum height for free-response (no Answer block).
    # For MCQ, the Answer block may be very close to y_start for short questions.
    if not answer_block_found:
        y_end = max(y_end, y_start + 80)

    clip = pymupdf.Rect(page.rect.x0, y_start, page.rect.x1, y_end)
    mat  = pymupdf.Matrix(1.5, 1.5)
    pix  = page.get_pixmap(matrix=mat, clip=clip, colorspace=pymupdf.csRGB)
    img_path = os.path.join(OUT_IMG_DIR, f'{qid}.png')
    pix.save(img_path)
    return f'images/math/{qid}.png'

def render_choice_images(page, qid, out_dir):
    """Crop each A/B/C/D choice as a separate PNG for the right-panel buttons."""
    blocks = page.get_text('blocks')

    # Find where the "Answer" section header ends (choices start below it)
    answer_y1 = None
    for x0, by0, x1, by1, btext, bno, btype in blocks:
        if btext.strip() == 'Answer':
            answer_y1 = by1
            break
    if answer_y1 is None:
        return {}

    # Find each choice block (starts with A., B., C., or D.)
    choice_tops = {}
    for x0, by0, x1, by1, btext, bno, btype in blocks:
        t = btext.strip()
        if re.match(r'^[A-D]\.', t) and by0 > answer_y1:
            letter = t[0]
            if letter not in choice_tops:  # take first occurrence per letter
                choice_tops[letter] = by0
    if len(choice_tops) != 4:
        return {}

    # Find where choices end
    end_y = page.rect.height
    for label in ('Correct Answer:', 'Rationale'):
        rects = page.search_for(label)
        if rects:
            end_y = rects[0].y0 - 2
            break

    letters = sorted(choice_tops, key=lambda l: choice_tops[l])
    mat = pymupdf.Matrix(2.0, 2.0)
    result = {}
    for i, letter in enumerate(letters):
        y_top = choice_tops[letter] - 3
        y_bot = (choice_tops[letters[i+1]] - 3) if i + 1 < len(letters) else end_y
        clip = pymupdf.Rect(page.rect.x0, y_top, page.rect.x1, y_bot)
        pix = page.get_pixmap(matrix=mat, clip=clip, colorspace=pymupdf.csRGB)
        fname = f'{qid}_{letter}.png'
        pix.save(os.path.join(out_dir, fname))
        result[letter] = f'images/math/{fname}'
    return result


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
        # Fallback: extract from "The correct answer is X." in rationale
        if not correct:
            fb = re.search(r'The correct answer is ([A-Za-z0-9./\- ]+?)\.', text)
            if fb:
                correct = fb.group(1).strip()
        is_mcq    = correct in ('A', 'B', 'C', 'D')
        rationale = clean_rationale(text)

        try:
            img_path = render_question_image(page, qid)
        except Exception as e:
            print(f'  image error {qid}: {e}')
            img_path = None
            img_errors += 1

        # For MCQ, render each choice as a mini image (all math choices are formulas)
        choice_images = {}
        if is_mcq:
            try:
                choice_images = render_choice_images(page, qid, OUT_IMG_DIR)
            except Exception as e:
                print(f'  choice image error {qid}: {e}')

        questions.append({
            'id':            qid,
            'assessment':    'SAT',
            'test':          'Math',
            'domain':        domain,
            'skill':         skill,
            'difficulty':    'Hard',
            'correct':       correct,
            'is_mcq':        is_mcq,
            'choices':       {},
            'choiceImages':  choice_images,
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

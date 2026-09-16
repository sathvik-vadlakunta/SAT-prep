#!/usr/bin/env python3
import re
import json
import subprocess
import os

PDF_PATH = os.path.expanduser("~/Downloads/questionbank-export-2026-9-13.pdf")
OUT_PATH = os.path.join(os.path.dirname(__file__), "questions.json")

PROSE_WORDS = {
    'the','a','an','of','in','to','that','and','or','but','with','for',
    'was','were','have','has','had','is','are','be','been','may','can',
    'this','which','who','from','by','as','on','at','its','their','it',
    'these','those','however','recently','although','while','since','when',
    'not','no','some','many','most','all','such','other','also'
}

def extract_text(pdf_path):
    result = subprocess.run(
        ["pdftotext", "-raw", pdf_path, "-"],
        capture_output=True, text=True
    )
    return result.stdout

def clean_text(text):
    text = text.replace("\x0c", "\n")
    # Normalize curly quotes/apostrophes to straight ones
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "—").replace("–", "–")
    # Fix apostrophe glued to following digit (e.g. "'2010" -> "' 2010")
    text = re.sub(r"'(\d)", r"' \1", text)
    return text.strip()

def parse_metadata_line(line):
    line = line.strip()
    diff_match = re.search(r'\b(Easy|Medium|Hard)\s*$', line)
    difficulty = diff_match.group(1) if diff_match else ""
    line = re.sub(r'\s*(Easy|Medium|Hard)\s*$', '', line)
    line = re.sub(r'^SAT\s+', '', line)

    for t in ["Reading and Writing", "Math"]:
        if line.startswith(t):
            test = t
            line = line[len(t):].strip()
            break
    else:
        test = ""

    for d in [
        "Information and Ideas", "Craft and Structure", "Expression of Ideas",
        "Standard English Conventions", "Algebra", "Advanced Math",
        "Problem-Solving and Data Analysis", "Geometry and Trigonometry",
    ]:
        if line.startswith(d):
            domain = d
            line = line[len(d):].strip()
            break
    else:
        domain = ""

    return "SAT", test, domain, line.strip(), difficulty

def is_prose_line(line):
    words = line.lower().split()
    if len(words) < 8:
        return False
    common = sum(1 for w in words if re.sub(r'[^a-z]', '', w) in PROSE_WORDS)
    return common >= 3

def detect_graph(question_text):
    lines = question_text.split('\n')
    graph_end = -1
    for i, line in enumerate(lines):
        if is_prose_line(line.strip()):
            graph_end = i
            break

    if graph_end >= 2:
        graph_data_lines = [l.strip() for l in lines[:graph_end] if l.strip()]
        label_lines = [l for l in graph_data_lines
                       if not re.match(r'^[\d\s.,\-%()/]+$', l)
                       and 3 < len(l) <= 60 and len(l.split()) <= 8]
        graph_title = " | ".join(label_lines[:6]) if label_lines else "Chart/Graph"
        actual_question = '\n'.join(lines[graph_end:]).strip()
        return True, graph_title, actual_question
    return False, "", question_text

def extract_choices(block):
    choices = {}
    pattern = re.compile(r'\n([A-D])\.\s+(.*?)(?=\n[A-D]\.\s+|Correct Answer:|\Z)', re.DOTALL)
    for m in pattern.finditer(block):
        letter = m.group(1)
        text = re.sub(r'\n+', ' ', m.group(2).strip()).strip()
        choices[letter] = text
    return choices

def parse_questions(raw_text):
    raw_text = clean_text(raw_text)
    parts = re.split(r'Question ID:\s*([a-f0-9]+)', raw_text)
    questions = []
    i = 1
    while i < len(parts) - 1:
        qid = parts[i].strip()
        block = parts[i + 1]
        i += 2

        meta_match = re.search(r'Assessment Test Domain Skill Difficulty\n(.*?)\n', block)
        if meta_match:
            assessment, test, domain, skill, difficulty = parse_metadata_line(meta_match.group(1))
        else:
            assessment, test, domain, skill, difficulty = "SAT", "Reading and Writing", "", "", ""

        q_match = re.search(r'\nQuestion\n(.*?)\nAnswer\n', block, re.DOTALL)
        question_text = ""
        has_graph = False
        graph_title = ""
        if q_match:
            question_text = re.sub(r'\n{3,}', '\n\n', q_match.group(1).strip())
            has_graph, graph_title, question_text = detect_graph(question_text)

        answer_block_match = re.search(r'\nAnswer\n(.*?)Correct Answer:', block, re.DOTALL)
        choices = {}
        if answer_block_match:
            choices = extract_choices("\n" + answer_block_match.group(1))

        correct_match = re.search(r'Correct Answer:\s*([A-D])', block)
        correct = correct_match.group(1) if correct_match else ""

        rationale_match = re.search(r'Rationale\n(.*?)$', block, re.DOTALL)
        rationale = ""
        if rationale_match:
            rationale = re.sub(r'\n+', ' ', rationale_match.group(1).strip()).strip()

        if not qid or not question_text or len(choices) < 2 or not correct:
            continue

        questions.append({
            "id": qid,
            "assessment": assessment,
            "test": test,
            "domain": domain,
            "skill": skill,
            "difficulty": difficulty,
            "question": question_text,
            "choices": choices,
            "correct": correct,
            "rationale": rationale,
            "hasGraph": has_graph,
            "graphTitle": graph_title,
        })

    return questions

if __name__ == "__main__":
    print(f"Extracting from {PDF_PATH}...")
    raw = extract_text(PDF_PATH)
    questions = parse_questions(raw)
    print(f"Parsed {len(questions)} questions")
    with open(OUT_PATH, "w") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUT_PATH}")
    difficulties = {}
    skills = {}
    graph_count = 0
    for q in questions:
        difficulties[q['difficulty']] = difficulties.get(q['difficulty'], 0) + 1
        skills[q['skill']] = skills.get(q['skill'], 0) + 1
        if q.get('hasGraph'):
            graph_count += 1
    print("Difficulty:", difficulties)
    print("Skills:", skills)
    print("Graph questions:", graph_count)

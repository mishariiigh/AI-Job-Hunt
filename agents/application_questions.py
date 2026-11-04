import re


CATEGORIES = [
    "personal",
    "contact",
    "education",
    "employment",
    "experience",
    "skills",
    "certifications",
    "work_authorization",
    "location",
    "remote",
    "shift",
    "salary",
    "yes_no",
    "free_text",
]

_NON_QUESTION_HEADINGS = re.compile(
    r"^(?:how\s+to\s+apply|application\s+instructions?|privacy(?:\s+notice|\s+statement)?|"
    r"equal\s+opportunity(?:\s+employer|\s+statement)?|eeo(?:\s+statement)?|"
    r"about\s+(?:the\s+)?(?:company|employer)|about\s+us|our\s+company)\s*:?$",
    re.I,
)
_NON_QUESTION_CONTENT = re.compile(
    r"\b(?:privacy notice|equal opportunity employer|equal employment opportunity|"
    r"we are an equal opportunity|accommodation statement|reasonable accommodation)\b",
    re.I,
)
_INSTRUCTION_START = re.compile(
    r"^(?:to apply|please apply|apply by|submit (?:your|a)|please submit|"
    r"email your|send your|visit our|click (?:here|the)|how to apply)\b",
    re.I,
)
_PROMPT_START = re.compile(
    r"^(?:describe|explain|provide|list|tell us|share)\b",
    re.I,
)
_QUESTION_END = re.compile(r"\?\s*(?:\([^)]*\)\s*)?\*?$")


def classify_question(text):
    t = (text or "").lower()
    if "salary" in t or "compensation" in t:
        return "salary"
    if any(
        term in t
        for term in (
            "authorization",
            "authorized",
            "eligible to work",
            "work permit",
            "citizen",
            "sponsorship",
        )
    ):
        return "work_authorization"
    if any(
        term in t
        for term in ("availability", "start date", "when can you start", "hours per week", "relocate")
    ):
        return "availability"
    if any(
        term in t
        for term in (
            "legal declaration",
            "criminal",
            "disability",
            "veteran",
            "race",
            "background check",
        )
    ):
        return "legal_declaration"
    if "remote" in t:
        return "remote"
    if "shift" in t or "evening" in t or "hours" in t:
        return "shift"
    if "location" in t or "city" in t or "province" in t:
        return "location"
    if "certification" in t or "certificate" in t:
        return "certifications"
    if "skill" in t:
        return "skills"
    if "experience" in t and "year" in t:
        return "experience"
    if "employment" in t or "work history" in t or "employer" in t:
        return "employment"
    if "education" in t or "degree" in t or "university" in t:
        return "education"
    if "email" in t or "phone" in t or "contact" in t:
        return "contact"
    if "name" in t:
        return "personal"
    if re.match(r"^(are|do|did|have|has|can|will|would)\s+you\b", t.strip()):
        return "yes_no"
    return "free_text"


def extract_questions(text, source="job_description"):
    questions = []
    inside_non_question_section = False
    for index, raw_line in enumerate((text or "").splitlines()):
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw_line).strip()
        if not line:
            continue
        if line.endswith(":"):
            inside_non_question_section = bool(
                _NON_QUESTION_HEADINGS.fullmatch(line)
            )
            continue
        if inside_non_question_section:
            continue
        if _NON_QUESTION_HEADINGS.fullmatch(line):
            inside_non_question_section = True
            continue
        if _NON_QUESTION_CONTENT.search(line) or _INSTRUCTION_START.search(line):
            continue
        if not _QUESTION_END.search(line) and not _PROMPT_START.search(line):
            continue
        questions.append(
            {
                "id": f"q{index}",
                "text": line,
                "category": classify_question(line),
                "required": not bool(re.search(r"\boptional\b", line, re.I)),
                "source": source,
            }
        )
    return questions


def mark_optional(questions, optional_markers=None):
    optional_markers = optional_markers or ["optional"]
    for question in questions:
        if any(marker in question["text"].lower() for marker in optional_markers):
            question["required"] = False
    return questions

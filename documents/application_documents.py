import re


_IT01 = re.compile(r"\bIT\s*[-–]?\s*01\b", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
_NAME_LINE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,79}$")
_SECTION_NAMES = {
    "contact",
    "top skills",
    "skills",
    "technical skills",
    "program related skills",
    "soft skills",
    "languages",
    "certifications",
    "certifications & professional development",
    "professional summary",
    "summary",
    "profile",
    "experience",
    "professional experience",
    "work experience",
    "employment history",
    "freelance experience",
    "project experience",
    "projects",
    "education",
    "references",
}
_RESUME_SECTIONS = (
    ("PROFESSIONAL SUMMARY", re.compile(r"^(?:professional\s+)?summary$", re.I)),
    ("TECHNICAL SKILLS", re.compile(r"^(?:technical|program-related|program related)?\s*skills$", re.I)),
    ("PROFESSIONAL EXPERIENCE", re.compile(r"^(?:(?:professional|work)\s+)?experience|employment\s+history$", re.I)),
    ("FREELANCE EXPERIENCE", re.compile(r"^freelance\s+experience$", re.I)),
    ("PROJECT EXPERIENCE", re.compile(r"^(?:project\s+experience|projects)$", re.I)),
    ("EDUCATION", re.compile(r"^education$", re.I)),
    ("CERTIFICATIONS & PROFESSIONAL DEVELOPMENT", re.compile(r"^(?:certifications?(?:\s*&\s*professional\s+development)?|professional\s+development)$", re.I)),
)
_IT01_IN_PARENS = re.compile(r"\(\s*\)")
_DATE_RANGE = re.compile(
    r"(?:\d{4}\s*[–—-]\s*(?:\d{4}|present)|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4}\s*[–—-]\s*(?:(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+)?(?:\d{4}|present))",
    re.I,
)


def _clean_source_line(line):
    cleaned = _IT01_IN_PARENS.sub("", _IT01.sub("", line)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned if cleaned and cleaned not in {"-", "|", "•"} else ""


def resume_header_details(profile, resume_text):
    profile = profile or {}
    source_lines = [line.strip() for line in (resume_text or "").splitlines() if line.strip()]
    email_match = _EMAIL.search(resume_text or "")
    phone_match = _PHONE.search(resume_text or "")
    candidates = []
    for index, line in enumerate(source_lines[:60]):
        candidate = _clean_source_line(line)
        if (
            "|" in candidate
            or "•" in candidate
            or len(candidate.split()) > 4
            or re.search(r"\d", candidate)
            or candidate.endswith(".")
        ):
            continue
        candidate = _EMAIL.sub("", candidate)
        candidate = _PHONE.sub("", candidate)
        candidate = re.sub(r"https?://\S+|www\.\S+", "", candidate, flags=re.I)
        candidate = re.sub(r"[•·,]+", " ", candidate).strip(" -")
        normalized = re.sub(r"\s+", " ", candidate).casefold()
        if (
            _NAME_LINE.fullmatch(candidate)
            and len(candidate.split()) >= 2
            and normalized not in _SECTION_NAMES
            and normalized not in {
                "professional summary",
                "career objective",
                "contact information",
                "curriculum vitae",
                "resume",
            }
        ):
            score = 0
            if line == source_lines[0]:
                score += 4
            if line.isupper():
                score += 3
            if index + 1 < len(source_lines) and "|" in source_lines[index + 1]:
                score += 5
            if normalized in {"it professional development", "user interface design"}:
                score -= 4
            candidates.append((score, -index, candidate))
    resume_name = max(candidates, default=(0, 0, ""))[2]
    details = {
        "name": str(profile.get("name") or "").strip() or resume_name,
        "email": str(profile.get("email") or "").strip()
        or (email_match.group(0) if email_match else ""),
        "phone": str(profile.get("phone") or "").strip()
        or (phone_match.group(0) if phone_match else ""),
        "location": str(profile.get("location") or "").strip(),
        "sources": {},
    }
    for key in ("name", "email", "phone", "location"):
        details["sources"][key] = (
            "candidate_profile"
            if str(profile.get(key) or "").strip()
            else "original_resume"
            if details[key]
            else ""
        )
    missing = []
    if not details["name"]:
        missing.append("candidate name")
    if not (details["email"] or details["phone"]):
        missing.append("email or phone number")
    return details, missing


def _resume_section(line):
    cleaned = _clean_source_line(line).strip(" :")
    for heading, pattern in _RESUME_SECTIONS:
        if pattern.fullmatch(cleaned):
            return heading
    return None


def _extract_resume_sections(resume_text):
    sections = {}
    section_order = []
    current_section = None
    for line in (resume_text or "").splitlines():
        section = _resume_section(line)
        if section:
            current_section = section
            if section not in sections:
                sections[section] = []
                section_order.append(section)
        elif current_section:
            sections[current_section].append(line)
    return sections, section_order


def _clean_section_content(section, lines):
    cleaned = []
    for line in lines:
        value = _clean_source_line(line)
        if not value:
            continue
        if value.startswith(("•", "·", "-")):
            value = value.lstrip("•·- ").strip()
            if not value:
                continue
            cleaned.append("• " + value)
        elif section == "PROFESSIONAL SUMMARY":
            if cleaned:
                cleaned[-1] += " " + value
            else:
                cleaned.append(value)
        elif section == "TECHNICAL SKILLS":
            if cleaned and not value.endswith(":"):
                cleaned[-1] += " " + value
            else:
                cleaned.append("• " + value)
        elif (
            cleaned
            and cleaned[-1].startswith("• ")
            and not _DATE_RANGE.search(value)
        ):
            if cleaned[-1].endswith("-"):
                cleaned[-1] += value
            else:
                cleaned[-1] += " " + value
        else:
            cleaned.append(value)
    return cleaned


def generate_tailored_resume(profile, resume_text, job):
    """Prepare source-backed resume content for the shared document renderer."""
    header, _ = resume_header_details(profile, resume_text)
    sections, section_order = _extract_resume_sections(resume_text)
    content = {
        section: _clean_section_content(section, values)
        for section, values in sections.items()
    }
    if not content.get("PROFESSIONAL SUMMARY"):
        summary = str(profile.get("career_direction") or "").strip()
        if summary:
            content["PROFESSIONAL SUMMARY"] = [summary]
            section_order.insert(0, "PROFESSIONAL SUMMARY")

    if not content.get("TECHNICAL SKILLS"):
        skills = [
            str(skill).strip()
            for skill in profile.get("technical_interests", [])
            if str(skill).strip()
        ]
        if skills:
            content["TECHNICAL SKILLS"] = ["• " + skill for skill in skills]
            section_order.append("TECHNICAL SKILLS")

    if not content.get("EDUCATION"):
        education = str(profile.get("education") or "").strip()
        if education:
            content["EDUCATION"] = [education]
            section_order.append("EDUCATION")

    description = str(job.get("description") or "").lower()
    description_terms = {
        word
        for word in re.findall(r"[a-z0-9+#.]+", description)
        if len(word) > 3
        and word
        not in {
            "with", "from", "that", "this", "will", "your", "experience",
            "required", "preferred", "provide", "support", "supporting",
            "evening", "position", "including", "ability", "candidate",
        }
    }
    skills = content.get("TECHNICAL SKILLS", [])
    skills.sort(
        key=lambda item: (
            -sum(
                1
                for term in description_terms
                if re.search(r"\b" + re.escape(term) + r"\b", item, re.I)
            )
        )
    )
    if "TECHNICAL SKILLS" in content:
        content["TECHNICAL SKILLS"] = skills

    name = header["name"]
    contact = [header[key] for key in ("email", "phone", "location") if header[key]]
    lines = [name, " | ".join(contact)]
    target = " | ".join(
        _clean_source_line(str(value).strip())
        for value in (job.get("job_title"), job.get("employer"))
        if str(value or "").strip()
    )
    if target:
        lines.append(f"Target role: {target}")
    for section in section_order:
        section_content = content.get(section) or []
        if section_content:
            lines.extend(["", section, *section_content])
    return "\n".join(lines).strip() + "\n"


def generate_cover_letter(profile, resume_text, job):
    employer = str(job.get("employer") or "").strip() or "the hiring team"
    title = str(job.get("job_title") or "").strip() or "the position"
    description = (job.get("description") or "").lower()
    description_terms = {
        word
        for word in re.findall(r"[a-z0-9+#.]+", description)
        if len(word) > 3
        and word
        not in {
            "with", "from", "that", "this", "will", "your", "experience",
            "required", "preferred", "provide", "support", "supporting",
            "evening", "position", "including", "ability", "candidate",
        }
    }
    header, _ = resume_header_details(profile, resume_text)
    contact = [header[key] for key in ("email", "phone", "location") if header[key]]

    verified_text = (resume_text or "").lower()
    sections, _ = _extract_resume_sections(resume_text)
    specific_evidence = []
    for section in (
        "PROFESSIONAL EXPERIENCE",
        "FREELANCE EXPERIENCE",
        "PROJECT EXPERIENCE",
    ):
        for line in _clean_section_content(section, sections.get(section, [])):
            if not line.startswith("•"):
                continue
            evidence = line[1:].strip()
            overlap = sum(
                1
                for word in description_terms
                if re.search(r"\b" + re.escape(word) + r"\b", evidence, re.I)
            )
            if overlap:
                specific_evidence.append((overlap, evidence))
    specific_evidence.sort(key=lambda item: item[0], reverse=True)
    relevant_skills = [
        str(skill).strip()
        for skill in profile.get("technical_interests", [])
        if str(skill).strip()
        and re.search(
            r"\b" + re.escape(str(skill).strip().lower()) + r"\b",
            verified_text,
        )
        and re.search(
            r"\b" + re.escape(str(skill).strip().lower()) + r"\b",
            description,
        )
    ][:4]
    education = str(profile.get("education") or "").strip()
    education_terms = re.findall(r"[A-Za-z]{4,}", education)
    if not education_terms or not all(
        re.search(r"\b" + re.escape(term) + r"\b", verified_text, re.I)
        for term in education_terms
    ):
        education = ""
    paragraphs = [
        header["name"],
        " | ".join(contact),
        "",
        f"Dear {employer} Hiring Team,",
        "",
        f"I am applying for the {title} position with {employer}.",
        "",
    ]
    if specific_evidence:
        paragraphs.append("Relevant examples documented in my resume include:")
        paragraphs.append("")
        paragraphs.extend(
            "• " + evidence
            for _, evidence in specific_evidence[:2]
        )
        paragraphs.append("")
    elif relevant_skills:
        paragraphs.append(
            "My resume documents experience with " + ", ".join(relevant_skills)
            + ", which are relevant to this position."
        )
        paragraphs.append("")
    if education:
        paragraphs.append(f"My education includes {education}.")
        paragraphs.append("")
    paragraphs.extend([
        f"I would welcome the opportunity to discuss how this experience can contribute to the {title} team.",
        "",
        "Thank you for your consideration.",
        "",
        "Sincerely,",
        "",
        header["name"],
    ])
    return "\n".join(paragraphs) + "\n"

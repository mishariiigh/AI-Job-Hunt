import os
import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


EXPORT_DIR = os.path.join("storage", "exports")
_NAVY = colors.HexColor("#243F69")
_INK = colors.HexColor("#273344")
_MUTED = colors.HexColor("#526173")
_RULE = colors.HexColor("#91A2B8")
_SECTIONS = {
    "PROFESSIONAL SUMMARY",
    "TECHNICAL SKILLS",
    "PROFESSIONAL EXPERIENCE",
    "FREELANCE EXPERIENCE",
    "PROJECT EXPERIENCE",
    "EDUCATION",
    "CERTIFICATIONS & PROFESSIONAL DEVELOPMENT",
}
_DATE_RANGE = re.compile(
    r"(?P<date>(?:(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+)?\d{4}\s*[–—-]\s*"
    r"(?:(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+)?(?:\d{4}|Present))$",
    re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")


def _export_path(filename):
    safe_name = Path(str(filename)).name
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("A valid export filename is required.")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    return os.path.join(EXPORT_DIR, safe_name)


def _lines(text):
    return [line.strip() for line in (text or "").replace("\r\n", "\n").split("\n")]


def _has_resume_sections(lines):
    return any(line.upper().strip(" :") in _SECTIONS for line in lines)


def _is_document(text):
    lines = _lines(text)
    return (
        _has_resume_sections(lines)
        or any(line.startswith("Dear ") for line in lines)
        or any(line.startswith("Target role:") for line in lines)
    )


def _header(lines):
    content = [line for line in lines if line]
    if not content:
        return None, 0
    name = content[0]
    if name.upper().strip(" :") in _SECTIONS or _EMAIL.search(name) or _PHONE.search(name):
        raise ValueError("The document is missing a verified candidate name in its header.")
    if len(content) < 2 or not (_EMAIL.search(content[1]) or _PHONE.search(content[1])):
        raise ValueError(
            "The document is missing verified email or phone contact information; update the Candidate Profile or source resume."
        )
    index = lines.index(content[0]) + 1
    contact_index = next(
        position
        for position in range(index, len(lines))
        if lines[position] == content[1]
    ) + 1
    target = ""
    while contact_index < len(lines) and not lines[contact_index]:
        contact_index += 1
    if contact_index < len(lines) and lines[contact_index].startswith("Target role:"):
        target = lines[contact_index].removeprefix("Target role:").strip()
        contact_index += 1
    return (name, content[1], target), contact_index


def _resume_blocks(lines, start):
    blocks = []
    current_title = None
    current_content = []
    for line in lines[start:]:
        if not line:
            continue
        heading = line.upper().strip(" :")
        if heading in _SECTIONS:
            if current_title:
                blocks.append((current_title, current_content))
            current_title, current_content = heading, []
        elif current_title:
            if line.startswith(("•", "·", "-")):
                current_content.append(line)
            elif current_content and current_content[-1].startswith(("•", "·", "-")):
                if _DATE_RANGE.search(line):
                    current_content.append(line)
                else:
                    current_content[-1] += " " + line
            elif current_title == "PROFESSIONAL SUMMARY" and current_content:
                current_content[-1] += " " + line
            elif current_title == "TECHNICAL SKILLS" and current_content:
                current_content[-1] += " " + line
            else:
                current_content.append(line)
        else:
            blocks.append(("", [line]))
    if current_title:
        blocks.append((current_title, current_content))
    return blocks


def _styles(compact=False):
    base = getSampleStyleSheet()
    body_size = 10
    leading = 12.2 if compact else 12.8
    return {
        "name": ParagraphStyle(
            "CandidateName",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=20,
            leading=23,
            alignment=TA_CENTER,
            textColor=_NAVY,
            spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "CandidateContact",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            textColor=_MUTED,
            spaceAfter=2,
        ),
        "target": ParagraphStyle(
            "TargetRole",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=11,
            alignment=TA_CENTER,
            textColor=_MUTED,
            spaceAfter=4,
        ),
        "section": ParagraphStyle(
            "ResumeSection",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=11,
            leading=13,
            textColor=_NAVY,
            spaceBefore=8 if compact else 10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ResumeBody",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=body_size,
            leading=leading,
            textColor=_INK,
            spaceAfter=3,
            alignment=TA_LEFT,
            allowWidows=0,
            allowOrphans=0,
        ),
        "bullet": ParagraphStyle(
            "ResumeBullet",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=body_size,
            leading=leading,
            textColor=_INK,
            leftIndent=13,
            firstLineIndent=-9,
            bulletIndent=0,
            spaceAfter=2,
            allowWidows=0,
            allowOrphans=0,
        ),
        "role": ParagraphStyle(
            "ResumeRole",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=body_size,
            leading=leading,
            textColor=_INK,
            spaceBefore=3,
            spaceAfter=1,
            keepWithNext=True,
        ),
        "employer": ParagraphStyle(
            "ResumeEmployer",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=body_size - 0.2,
            leading=leading,
            textColor=_MUTED,
            spaceAfter=2,
            keepWithNext=True,
        ),
        "letter": ParagraphStyle(
            "CoverLetterBody",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=11,
            leading=15,
            textColor=_INK,
            spaceAfter=9,
            allowWidows=0,
            allowOrphans=0,
        ),
        "salutation": ParagraphStyle(
            "CoverLetterSalutation",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=11,
            leading=14,
            textColor=_INK,
            spaceBefore=8,
            spaceAfter=8,
        ),
    }


def _section_heading(title, style):
    heading = Paragraph(escape(title), style)
    rule = Table([[""]], colWidths=[7.15 * inch], rowHeights=[0.6])
    rule.keepWithNext = True
    rule.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, _RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    spacer = Spacer(1, 3)
    spacer.keepWithNext = True
    return [heading, rule, spacer]


def _header_story(header, styles, letter=False):
    name, contact, target = header
    story = [
        Paragraph(escape(name), styles["name"]),
        Paragraph(escape(contact), styles["contact"]),
    ]
    if target and not letter:
        story.append(Paragraph(escape(target), styles["target"]))
    story.append(Spacer(1, 5))
    rule = Table([[""]], colWidths=[7.15 * inch], rowHeights=[0.6])
    rule.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.8, _NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.extend([rule, Spacer(1, 7)])
    return story


def _split_role_date(line):
    match = _DATE_RANGE.search(line)
    if not match:
        return line, ""
    return line[: match.start()].strip(" —–-"), match.group("date").strip()


def _resume_story(blocks, styles):
    story = []
    for title, lines in blocks:
        section_story = []
        if title:
            section_story.extend(_section_heading(title, styles["section"]))
        previous_was_role = False
        for line in lines:
            if line.startswith(("•", "·", "-")):
                text = line.lstrip("•·- ").strip()
                category, separator, remainder = text.partition(":")
                if separator and title == "TECHNICAL SKILLS":
                    text = f"<b>{escape(category)}:</b>{escape(remainder)}"
                else:
                    text = escape(text)
                section_story.append(
                    Paragraph(text, styles["bullet"], bulletText="•")
                )
                previous_was_role = False
                continue
            role, date = _split_role_date(line)
            if date:
                table = Table(
                    [[Paragraph(escape(role), styles["role"]), Paragraph(escape(date), styles["role"])]],
                    colWidths=[5.35 * inch, 1.8 * inch],
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ]
                    )
                )
                section_story.append(KeepTogether([table]))
                previous_was_role = True
            elif previous_was_role:
                section_story.append(Paragraph(escape(line), styles["employer"]))
                previous_was_role = False
            elif title == "EDUCATION" and not line.startswith(("•", "·", "-")):
                style = (
                    styles["role"]
                    if not section_story or section_story[-1].__class__ is not Paragraph
                    else styles["employer"]
                )
                section_story.append(Paragraph(escape(line), style))
                previous_was_role = False
            else:
                section_story.append(Paragraph(escape(line), styles["body"]))
                previous_was_role = False
        if title:
            section_story.append(Spacer(1, 2))
        story.extend(section_story)
    return story


def _cover_letter_story(lines, start, styles):
    story = []
    paragraphs = []

    def flush():
        if not paragraphs:
            return
        paragraph = " ".join(paragraphs)
        style = styles["salutation"] if paragraph.startswith("Dear ") else styles["letter"]
        story.append(Paragraph(escape(paragraph), style))
        paragraphs.clear()

    for line in lines[start:]:
        if line.startswith(("•", "·", "-")):
            flush()
            story.append(
                Paragraph(
                    escape(line.lstrip("•·- ").strip()),
                    styles["bullet"],
                    bulletText="•",
                )
            )
        elif line:
            paragraphs.append(line)
        else:
            flush()
    flush()
    return story


def _draw_footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7DEE7"))
    canvas.setLineWidth(0.5)
    canvas.line(document.leftMargin, 0.48 * inch, letter[0] - document.rightMargin, 0.48 * inch)
    canvas.setFont("Times-Roman", 8.5)
    canvas.setFillColor(_MUTED)
    canvas.drawRightString(letter[0] - document.rightMargin, 0.28 * inch, str(document.page))
    canvas.restoreState()


def export_pdf(text, filename, *, compact=False):
    path = _export_path(filename)
    lines = _lines(text)
    structured = _is_document(text)
    header, start = _header(lines) if structured else (None, 0)
    is_letter = any(line.startswith("Dear ") for line in lines)
    styles = _styles(compact)
    story = []
    if header:
        story.extend(_header_story(header, styles, letter=is_letter))
    if is_letter:
        story.extend(_cover_letter_story(lines, start, styles))
    elif structured:
        story.extend(_resume_story(_resume_blocks(lines, start), styles))
    else:
        story.extend(
            Paragraph(escape(line), styles["body"])
            for line in lines
            if line
        )
    doc = SimpleDocTemplate(
        path,
        pagesize=letter,
        rightMargin=0.68 * inch,
        leftMargin=0.68 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.65 * inch,
        title=filename,
        author=header[0] if header else "",
    )
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return path


def _set_cell_border(paragraph, color="91A2B8"):
    p = paragraph._p
    p_pr = p.get_or_add_pPr()
    borders = p_pr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr")
    if borders is None:
        from docx.oxml import OxmlElement

        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)


def _add_page_number(section):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = 2
    run = paragraph.add_run()
    run.font.name = "Times New Roman"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(82, 97, 115)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run._r.addnext(field)


def _docx_header(document, header, letter=False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    name, contact, target = header
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(1)
    run = paragraph.add_run(name)
    run.bold = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(36, 63, 105)

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run(contact)
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(82, 97, 115)
    if target and not letter:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(5)
        run = paragraph.add_run(target)
        run.font.name = "Times New Roman"
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(82, 97, 115)
    rule = document.add_paragraph()
    rule.paragraph_format.space_after = Pt(7)
    _set_cell_border(rule)


def _docx_section_heading(document, title, *, page_break_before=False):
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.page_break_before = page_break_before
    paragraph.paragraph_format.space_before = Pt(9)
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(title)
    run.bold = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor(36, 63, 105)
    _set_cell_border(paragraph)


def _docx_resume_blocks(document, blocks):
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Inches, Pt, RGBColor

    prior_content_length = 0
    for title, lines in blocks:
        if title:
            _docx_section_heading(
                document,
                title,
                page_break_before=(
                    title == "PROJECT EXPERIENCE" and prior_content_length >= 1800
                ),
            )
        previous_was_role = False
        education_line_count = 0
        for line in lines:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(2.5)
            paragraph.paragraph_format.line_spacing = 1.08
            bullet = line.startswith(("•", "·", "-"))
            if bullet:
                paragraph.paragraph_format.left_indent = Inches(0.18)
                paragraph.paragraph_format.first_line_indent = Inches(-0.14)
                text = line.lstrip("•·- ").strip()
                category, separator, remainder = text.partition(":")
                run = paragraph.add_run("• ")
                run.font.name = "Times New Roman"
                if separator and title == "TECHNICAL SKILLS":
                    run = paragraph.add_run(category + ":")
                    run.bold = True
                    run.font.name = "Times New Roman"
                    paragraph.add_run(remainder)
                else:
                    paragraph.add_run(text)
                previous_was_role = False
                continue
            role, date = _split_role_date(line)
            if date:
                paragraph.paragraph_format.keep_with_next = True
                paragraph.paragraph_format.space_before = Pt(3)
                paragraph.paragraph_format.tab_stops.add_tab_stop(
                    Inches(7.13), WD_TAB_ALIGNMENT.RIGHT
                )
                run = paragraph.add_run(role)
                run.bold = True
                paragraph.add_run("\t")
                date_run = paragraph.add_run(date)
                date_run.bold = True
                previous_was_role = True
            elif previous_was_role:
                run = paragraph.add_run(line)
                run.italic = True
                run.font.color.rgb = RGBColor(82, 97, 115)
                paragraph.paragraph_format.keep_with_next = True
                previous_was_role = False
            elif title == "EDUCATION":
                if education_line_count == 0:
                    run = paragraph.add_run(line)
                    run.bold = True
                else:
                    run = paragraph.add_run(line)
                    run.italic = True
                    run.font.color.rgb = RGBColor(82, 97, 115)
                education_line_count += 1
            else:
                paragraph.add_run(line)
                previous_was_role = False
            for run in paragraph.runs:
                run.font.name = "Times New Roman"
                if run.font.size is None:
                    run.font.size = Pt(9.4)
                if run.font.color.rgb is None:
                    run.font.color.rgb = RGBColor(39, 51, 68)
        prior_content_length += sum(len(line) for line in lines)


def _docx_cover_letter(document, lines, start):
    from docx.shared import Inches, Pt, RGBColor

    paragraph_lines = []

    def flush():
        if not paragraph_lines:
            return
        text = " ".join(paragraph_lines)
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(9)
        paragraph.paragraph_format.line_spacing = 1.12
        run = paragraph.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(10.2)
        run.font.color.rgb = RGBColor(39, 51, 68)
        if text.startswith("Dear "):
            paragraph.paragraph_format.space_before = Pt(9)
        paragraph_lines.clear()

    for line in lines[start:]:
        if line.startswith(("•", "·", "-")):
            flush()
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Inches(0.18)
            paragraph.paragraph_format.first_line_indent = Inches(-0.14)
            paragraph.paragraph_format.space_after = Pt(3)
            run = paragraph.add_run("• ")
            run.font.name = "Times New Roman"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(39, 51, 68)
            run = paragraph.add_run(line.lstrip("•·- ").strip())
            run.font.name = "Times New Roman"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(39, 51, 68)
        elif line:
            paragraph_lines.append(line)
        else:
            flush()
    flush()


def export_docx(text, filename):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    path = _export_path(filename)
    lines = _lines(text)
    structured = _is_document(text)
    header, start = _header(lines) if structured else (None, 0)
    is_letter = any(line.startswith("Dear ") for line in lines)
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.48)
    section.bottom_margin = Inches(0.62)
    section.left_margin = Inches(0.68)
    section.right_margin = Inches(0.68)
    section.footer_distance = Inches(0.3)
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(9.5)
    normal.font.color.rgb = RGBColor(39, 51, 68)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.08
    _add_page_number(section)

    if header:
        _docx_header(document, header, letter=is_letter)
    if is_letter:
        _docx_cover_letter(document, lines, start)
    elif structured:
        _docx_resume_blocks(document, _resume_blocks(lines, start))
    else:
        for line in lines:
            if line:
                document.add_paragraph(line)
    document.core_properties.title = Path(filename).stem
    document.core_properties.author = header[0] if header else ""
    document.save(path)
    return path

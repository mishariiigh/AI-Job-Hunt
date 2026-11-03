import re
import json


def parse_resume(text):
    text = text or ""
    sections = {
        'contact': {},
        'summary': None,
        'skills': [],
        'experience': [],
        'education': [],
        'certifications': [],
        'projects': [],
        'languages': []
    }
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Extract contact info
    email_match = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match:
        sections['contact']['email'] = email_match[0]
    phone_match = re.findall(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
    if phone_match:
        sections['contact']['phone'] = ''.join(phone_match[0]) if isinstance(phone_match[0], tuple) else phone_match[0]
    linkedin_match = re.findall(r'linkedin\.com/in/[\w\-]+', text, re.I)
    if linkedin_match:
        sections['contact']['linkedin'] = 'https://' + linkedin_match[0] if not linkedin_match[0].startswith('http') else linkedin_match[0]

    current = None
    for i, line in enumerate(lines):
        low = line.lower()
        if re.match(r'^(summary|profile|objective|about)$', low) or ('summary' in low and len(line) < 30):
            current = 'summary'
            continue
        if re.match(r'^(experience|work experience|employment|professional experience)$', low) or ('experience' in low and len(line) < 40 and 'work' in low or (low.strip() == 'experience')):
            current = 'experience'
            continue
        if re.match(r'^(education|academic|qualification)$', low) or (low.strip() == 'education'):
            current = 'education'
            continue
        if re.match(r'^(skills|technical skills|core competencies|key skills)$', low) or (low.strip() == 'skills' or 'technical skill' in low):
            current = 'skills'
            continue
        if re.match(r'^(certifications|certification|licenses|certificates)$', low) or 'certif' in low and len(line) < 40:
            current = 'certifications'
            continue
        if re.match(r'^(projects|project)$', low) or (low.strip() == 'projects'):
            current = 'projects'
            continue
        if re.match(r'^(languages|language)$', low):
            current = 'languages'
            continue

        if current == 'summary':
            if sections['summary']:
                sections['summary'] += ' ' + line
            else:
                sections['summary'] = line
        elif current == 'skills':
            # split by comma, semicolon, bullet
            items = re.split(r'[;,•\|]', line)
            for item in items:
                item = item.strip().strip('-').strip('•')
                if item and len(item) > 1:
                    sections['skills'].append(item)
        elif current == 'experience':
            # Heuristic: if it looks like a job title/company line
            if re.search(r'\b(20\d{2}|19\d{2})\b', line) or '|' in line or ' at ' in low:
                sections['experience'].append({
                    'title': line,
                    'employer': None,
                    'start': None,
                    'end': None,
                    'bullets': [],
                    'description': line
                })
            elif line.startswith(('-', '•', '*')) or (sections['experience'] and not re.match(r'^[A-Z][a-z]+ [A-Z]', line) and len(line) > 30):
                if sections['experience']:
                    bullet = line.strip('-').strip('•').strip('*').strip()
                    sections['experience'][-1].setdefault('bullets', []).append(bullet)
            else:
                sections['experience'].append({
                    'title': line,
                    'employer': None,
                    'start': None,
                    'end': None,
                    'bullets': [],
                    'description': line
                })
        elif current == 'education':
            sections['education'].append({
                'institution': line,
                'credential': None,
                'program': None,
                'graduation': None,
                'description': line
            })
        elif current == 'certifications':
            sections['certifications'].append({
                'name': line,
                'issuer': None,
                'expiry': None,
                'description': line
            })
        elif current == 'projects':
            if line.startswith(('-', '•', '*')):
                if sections['projects']:
                    sections['projects'][-1].setdefault('bullets', []).append(line.strip('-').strip('•').strip('*').strip())
                else:
                    sections['projects'].append({'name': line.strip('-').strip('•').strip('*').strip(), 'description': None, 'technologies': [], 'dates': None, 'bullets': []})
            else:
                sections['projects'].append({
                    'name': line,
                    'description': None,
                    'technologies': [],
                    'dates': None,
                    'bullets': []
                })
        elif current == 'languages':
            items = re.split(r'[;,•\|,]', line)
            for item in items:
                item = item.strip().strip('-')
                if item and len(item) > 1:
                    sections['languages'].append(item)

    # Deduplicate skills
    seen = set()
    deduped = []
    for s in sections['skills']:
        key = s.lower()
        if key not in seen and len(s) < 50:
            seen.add(key)
            deduped.append(s)
    sections['skills'] = deduped

    return sections


def parse_to_json(text):
    return json.dumps(parse_resume(text), indent=2)

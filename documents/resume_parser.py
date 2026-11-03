import os, zipfile, re


def extract_text(path):
    if path.lower().endswith('.txt'):
        with open(path, 'r', errors='ignore') as f:
            return f.read()
    if path.lower().endswith('.docx'):
        try:
            z = zipfile.ZipFile(path)
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
            text = re.sub(r'<w:br[^>]*/>', '\n', xml)
            text = re.sub(r'</w:p>', '\n', text)
            text = re.sub(r'<[^>]+>', '', text)
            return text
        except Exception:
            return ''
    if path.lower().endswith('.pdf'):
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            return '\n'.join(page.extract_text() or '' for page in reader.pages)
        except Exception:
            return ''
    return ''

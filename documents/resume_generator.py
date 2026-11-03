from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os


class ResumeGenerator:
    def __init__(self, output_dir="storage/resumes"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate(self, content, filename):
        path = os.path.join(self.output_dir, filename)
        c = canvas.Canvas(path, pagesize=letter)
        text = c.beginText(40, 750)
        for line in content.split('\n'):
            text.textLine(line)
        c.drawText(text)
        c.save()
        return path

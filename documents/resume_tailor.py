def generate_tailored_resume(profile, resume_text, job):
    from documents.application_documents import generate_tailored_resume as generate
    return generate(profile, resume_text, job)

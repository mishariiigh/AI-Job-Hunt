from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    id: Optional[int] = None
    employer: str = ""
    job_title: str = ""
    job_url: str = ""
    source: str = ""
    description: str = ""
    location: str = ""
    remote: bool = False
    salary: str = ""
    shift: str = ""
    employment_type: str = ""
    experience_required: str = ""
    education_required: str = ""
    deadline: str = ""
    discovered_at: str = ""
    match_score: float = 0.0
    match_explanation: str = ""
    status: str = "discovered"
    approved: bool = False


@dataclass
class Application:
    id: Optional[int] = None
    job_id: int = 0
    resume_filename: str = ""
    cover_letter_filename: str = ""
    answers: str = ""
    applied_at: Optional[str] = None
    status: str = "prepared"
    interview_status: str = ""
    notes: str = ""

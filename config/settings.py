import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    DATABASE_PATH = os.getenv("DATABASE_PATH", "database/app.db")
    STORAGE_DIR = os.getenv("STORAGE_DIR", "storage")
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8501"))
    DISCOVERY_SCHEDULE = int(os.getenv("DISCOVERY_SCHEDULE", "60"))
    
    TARGET_CATEGORIES = [
        "IT Support Technician", "Technical Support Specialist", "Application Support Analyst",
        "Help Desk Analyst", "Service Desk Analyst", "Junior Systems Administrator",
        "NOC Analyst", "Junior Cybersecurity Analyst", "Security Operations Support",
        "Software Support Specialist", "QA / Software Testing", "Python Developer – Junior",
        "AI Automation Specialist", "Technical Customer Support", "IT Operations Analyst"
    ]
    
    REQUIRED_KEYWORDS = ["remote", "canada"]
    EVENING_KEYWORDS = ["evening", "after hours", "flexible", "part-time", "20", "25"]


settings = Settings()

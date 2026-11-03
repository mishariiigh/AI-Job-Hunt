# AI Job Hunter - Python

Production-quality, semi-automated AI Job Application Agent for finding fully remote, evening-shift IT jobs in Canada.

## Features
- Job discovery from legitimate sources
- AI-powered matching (0-100) with explanations
- Tailored resume and cover letter generation (PDF)
- Browser-assisted application workflow (Playwright, manual approval required)
- Human approval system before submission
- SQLite tracking
- Streamlit dashboard

## Setup
1. Create venv: `python3 -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Install Playwright browsers: `playwright install`
4. Copy `.env.example` to `.env` and configure
5. Initialize DB: `python database/db.py`
6. Run dashboard: `streamlit run app.py`

## Important Notes
- Never auto-submits applications - requires explicit approval per job
- Only uses permitted automation methods
- Respects terms of service, no stealth/captcha bypass
- Keeps data local

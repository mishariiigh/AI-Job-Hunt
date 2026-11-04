# AI Job Hunter - Python

Production-quality, semi-automated AI Job Application Agent for finding Canada-eligible remote roles and in-person work in Oakville or Mississauga, with explicitly verified evening schedules.

## Features
- Job discovery from legitimate sources
- Eligibility triage requires explicit Canadian eligibility and a stated shift start at or after 5:00 PM Toronto time; unknown details remain in Needs Verification
- Conflicting shift hours and structured schedule labels require review; manual resolution stores its source, evidence, and timestamp
- Personal dashboard for confirmed matches, verification gaps, application progress, next actions, and recent discoveries
- AI-powered matching (0-100) with explanations
- Per-job application drafts with duplicate prevention, versioning, and an audit trail
- Editable, source-grounded resumes and cover letters with PDF and DOCX exports
- PDF and DOCX documents share a single-column design with navy section rules, readable serif typography, grouped skills, right-aligned experience dates, and consistent page numbering
- Employer-question extraction from job details or user-supplied text, with answer provenance and review gates
- Requirement-by-requirement mandatory/preferred/unclear assessment with candidate evidence; unsupported qualifications are flagged for verification rather than assumed missing
- Resume header fields are sourced from the verified profile or original resume; missing name/contact details block readiness and prompt profile correction
- Resume exports preserve source section hierarchy and employment dates, prioritize relevant source-backed skills, and keep section headings with their content across page breaks
- Human approval and manual employer-site submission tracking; no automatic submission
- SQLite application tracking with schema migrations
- LinkedIn PDF text extraction, structured comparison, and content-based duplicate detection
- Public Greenhouse and Lever employer board feeds, plus the attributed Remotive remote-jobs API
- D2L's public Greenhouse feed for Canadian product-support and application-support opportunities
- Source-snapshot freshness, normalized ISO/Unix-millisecond posting dates, last-verified timestamps, active-feed status, and possible-repost grouping without merging separate requisitions
- Streamlit dashboard

## Setup
1. Create venv: `python3 -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Install Playwright browsers: `playwright install`
4. Copy `.env.example` to `.env` and configure
5. Initialize DB: `python database/db.py`
6. Run dashboard: `streamlit run app.py`

## Important Notes
- Applications are never submitted by the app. A candidate must approve and submit on the employer's website, then can record the self-reported outcome and reference number.
- Automated employer submission is not configured or supported here. Greenhouse Harvest access requires employer-controlled credentials and permissions; Lever application access requires employer-authorized account credentials or OAuth. LinkedIn Apply Connect is an ATS integration, not a general job-seeker submission API.
- LinkedIn PDF parsing is heuristic. Imported experience, education, skills, and certifications must be compared and reviewed; profile changes are never applied without explicit approval.
- Match scores do not override location, schedule, expiry, or language eligibility checks
- Does not automate LinkedIn Easy Apply, bypass authentication, or bypass CAPTCHA
- Keeps data local
- Remotive data can be delayed by 24 hours. Its API is cached for at least six hours to respect the documented limit of four requests per day. Remotive listings are linked and attributed; they remain blocked from a confirmed-open match until the employer posting is verified.
- Greenhouse and Lever public board feeds are authoritative snapshots for their configured employer boards. Jobs absent from a successful snapshot are marked `not_listed_on_source`, not automatically described as definitively closed.
- Job Bank access is currently unsupported: the repository contains no official API/feed integration, and the Job Bank robots file requests a five-second crawl delay. No scraping is enabled. Employer-site discovery remains manual.
- A possible repost or parallel requisition is flagged by employer, title, and location, but separate URLs are retained as separate records.
- Evening eligibility requires explicit shift hours starting at or after 5:00 PM in America/Toronto time. Remote postings must establish an Eastern/Toronto time basis; other or unstated time zones require verification. Oakville/Mississauga in-person hours are interpreted in local time. Overnight shifts are separately labeled; rotating, flexible, 24/7, day-shift labels without hours, mixed day/evening options, and missing schedules do not confirm evening availability.
- Schedule evidence records its posting URL, each extracted shift range, time-zone basis, rotating/evening/after-hours/on-call/24-hour/global-coverage signals, and conflicts. The Application Review page can prepare an editable employer inquiry for unknown or conflicting schedules; it is never sent automatically.
- D2L is included because its public employer feed contains Canadian product-support openings. A live Product Support Analyst posting states that its rotation includes weekdays, evenings, and weekends but does not state shift start hours; it remains a potential opportunity pending schedule verification.
- No general Indeed job-seeker API or authorized public endpoint was identified for automated discovery. User-provided Indeed postings can be reviewed or entered manually; the application does not scrape Indeed.

## Platform authorization references
- [LinkedIn API access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
- [LinkedIn Apply Connect overview](https://learn.microsoft.com/en-us/linkedin/talent/apply-connect/apply-connect-overview)
- [Greenhouse Harvest API](https://docs.greenhouse.io/harvest.html)
- [Lever API documentation](https://hire.lever.co/developer/documentation)

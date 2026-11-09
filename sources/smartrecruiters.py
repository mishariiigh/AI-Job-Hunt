"""SmartRecruiters public job-posting source.

Uses SmartRecruiters' public, unauthenticated company postings endpoint:

    https://api.smartrecruiters.com/v1/companies/{companyId}/postings

This is the same feed an employer's SmartRecruiters career page renders.
No authentication, no scraping of protected pages, and no field invention:
values absent from the API stay empty.

Architecture mirrors sources/lever.py so discovery, deduplication,
persistence, classification and ranking work without modification.
"""
import requests
from typing import Dict, List
from datetime import datetime
from sources.date_utils import normalize_source_timestamp

API_BASE = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 50
MAX_PAGES = 10
REQUEST_TIMEOUT = 30


class SmartRecruitersSource:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'AI-Job-Hunter/1.0'})

    def fetch_company_postings(self, company_id: str) -> Dict:
        """Fetch all postings for one company with pagination.

        Returns {'jobs': [...], 'status': 'ok'|'error', 'error': str|None}.
        A failure on any page keeps successfully fetched pages.
        """
        result = {'jobs': [], 'status': 'ok', 'error': None, 'retrieved': 0}
        if not company_id or not company_id.strip():
            result['status'] = 'error'
            result['error'] = 'Empty company identifier'
            return result
        company_id = company_id.strip()
        offset = 0
        try:
            for _page in range(MAX_PAGES):
                response = self.session.get(
                    f"{API_BASE}/{company_id}/postings",
                    params={'offset': offset, 'limit': PAGE_SIZE},
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 429:
                    result['status'] = 'error'
                    result['error'] = 'Rate limited (429); partial results kept'
                    break
                if response.status_code in (404, 410):
                    result['status'] = 'error'
                    result['error'] = f'Company {company_id} not found (404)'
                    break
                if response.status_code >= 500:
                    result['status'] = 'error'
                    result['error'] = f'Server error {response.status_code}; partial results kept'
                    break
                if response.status_code != 200:
                    result['status'] = 'error'
                    result['error'] = f'Unexpected status {response.status_code}'
                    break
                try:
                    data = response.json()
                except ValueError:
                    result['status'] = 'error'
                    result['error'] = 'Malformed JSON response'
                    break
                postings = data.get('content')
                if not isinstance(postings, list):
                    result['status'] = 'error'
                    result['error'] = 'Unexpected response shape'
                    break
                for posting in postings:
                    if not isinstance(posting, dict):
                        continue
                    job_record = self._map_posting(company_id, posting)
                    if job_record:
                        result['jobs'].append(job_record)
                total = data.get('totalFound')
                offset += len(postings)
                if not postings or (isinstance(total, int) and offset >= total):
                    break
        except requests.exceptions.RequestException as exc:
            result['status'] = 'error'
            result['error'] = f'Network failure: {exc}'
        result['retrieved'] = len(result['jobs'])
        return result

    def search(self, company_ids: List[str] = None) -> Dict:
        """Fetch postings for a list of configured company IDs."""
        result = {'jobs': [], 'statuses': [], 'retrieved': 0}
        for company_id in company_ids or []:
            company_result = self.fetch_company_postings(company_id)
            result['statuses'].append({
                'company': company_id,
                'status': company_result['status'],
                'error': company_result['error'],
                'count': company_result['retrieved'],
            })
            result['jobs'].extend(company_result['jobs'])
        result['retrieved'] = len(result['jobs'])
        return result

    def _map_posting(self, company_id: str, posting: dict) -> Dict:
        """Map one SmartRecruiters posting to the standard job record.

        Missing fields stay empty — never inferred. Employer attribution is
        preserved in source_feed so the source remains identifiable.
        """
        title = posting.get('name') or ''
        if not title:
            return None
        location = posting.get('location') or {}
        city = str(location.get('city') or '').strip()
        country = str(location.get('country') or '').strip()
        # SmartRecruiters returns ISO 3166 alpha-2 codes ("CA", "US").
        # Expand to full country names so the downstream eligibility logic
        # never mistakes "CA" (Canada) for "CA" (California) and vice versa.
        country_names = {
            'CA': 'Canada', 'US': 'United States', 'GB': 'United Kingdom',
            'DE': 'Germany', 'FR': 'France', 'AU': 'Australia',
            'IN': 'India', 'NL': 'Netherlands', 'IE': 'Ireland',
        }
        country_full = country_names.get(str(country).upper(), country)
        region = str(location.get('region') or '').strip()
        # "CA" as a bare region code is ambiguous (California vs Canada);
        # with the full country name already present, drop an ambiguous
        # region code that equals a country code.
        if region.upper() == country.upper() and len(region) == 2:
            region = ''
        location_parts = [part for part in (city, region, country_full) if part]
        location_text = ', '.join(location_parts)
        # Remote flag: SmartRecruiters provides remote boolean on some feeds.
        remote = bool(posting.get('remote'))
        if not remote and location_text:
            remote = 'remote' in location_text.lower()
        released = normalize_source_timestamp(
            posting.get('releasedDate') or posting.get('createdOn')
        )
        employer = str(posting.get('company', {}).get('name') or company_id)
        return {
            'employer': employer,
            'job_title': title,
            'job_url': self._posting_url(company_id, posting),
            'source': 'smartrecruiters',
            'source_feed': company_id,
            'description': posting.get('jobAd', {}).get('sections', {}).get('jobDescription', {}).get('text', '') if isinstance(posting.get('jobAd'), dict) else '',
            'location': location_text,
            'remote': remote,
            'salary': '',
            'shift': 'unknown',
            'employment_type': '',
            'experience_required': '',
            'education_required': '',
            'posting_date': released,
            'source_updated_at': posting.get('releasedDate') or posting.get('createdOn'),
            'deadline': '',
            'retrieved_at': datetime.now().isoformat(),
            'last_checked': datetime.now().isoformat(),
            'listing_status': 'active_on_source',
            'job_category': '',
            'external_job_id': str(posting.get('id') or ''),
        }

    @staticmethod
    def _posting_url(company_id: str, posting: dict) -> str:
        """Canonical public career-page URL for the posting."""
        posting_id = posting.get('id') or ''
        if not posting_id:
            return ''
        return f"https://jobs.smartrecruiters.com/{company_id}/{posting_id}"

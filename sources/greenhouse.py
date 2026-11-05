import requests
import json
from typing import List, Dict
from datetime import datetime
from sources.date_utils import normalize_source_timestamp


DETAIL_REQUEST_TIMEOUT = 15


def _extract_employment_type(metadata):
    """Pull an employment type from Greenhouse board metadata, if provided.

    Greenhouse metadata is a list of {name, value} pairs whose contents vary
    by employer. Only a genuine employment-type field is returned; never
    inferred from anything else.
    """
    if not isinstance(metadata, list):
        return ''
    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip().lower()
        if name in {'employment type', 'type', 'position type'}:
            value = item.get('value')
            if isinstance(value, dict):
                value = value.get('value')
            return str(value or '').strip()
    return ''


def _extract_offices(offices):
    """Normalize the Greenhouse offices list into a display string."""
    if not isinstance(offices, list):
        return ''
    names = []
    for office in offices:
        if isinstance(office, dict) and office.get('name'):
            names.append(str(office['name']).strip())
        elif isinstance(office, str) and office.strip():
            names.append(office.strip())
    return '; '.join(dict.fromkeys(names))


def _extract_metadata_fields(metadata):
    """Extract useful structured fields from Greenhouse metadata."""
    fields = {}
    if not isinstance(metadata, list):
        return fields
    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip().lower()
        value = item.get('value')
        if isinstance(value, dict):
            value = value.get('value')
        value = str(value or '').strip()
        if not value:
            continue
        if name in {'employment type', 'type', 'position type'}:
            fields['employment_type'] = value
        elif 'education' in name:
            fields['education_required'] = value
        elif 'experience' in name or 'years' in name:
            fields['experience_required'] = value
    return fields


def fetch_job_detail(board_token, job_id):
    """Fetch a single job's detail from the public Greenhouse board API.

    Returns the parsed JSON dict, or None on any failure (404, 429, 5xx,
    network errors, malformed JSON). Never raises; callers must tolerate
    None and keep the original feed record.
    """
    url = (
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        "?content=true"
    )
    try:
        response = requests.get(
            url,
            timeout=DETAIL_REQUEST_TIMEOUT,
            headers={'User-Agent': 'AI-Job-Hunter/1.0'},
        )
        if response.status_code != 200:
            return None
        return response.json()
    except (
        requests.exceptions.RequestException,
        ValueError,
    ):
        return None


class GreenhouseSource:
    def search_board(self, board_token: str) -> Dict:
        result = {
            'jobs': [],
            'status': 'ok',
            'error': None,
            'retrieved': 0
        }
        if not board_token or not isinstance(board_token, str) or board_token.strip() == '':
            result['status'] = 'error'
            result['error'] = 'Invalid board token'
            return result
        
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board_token.strip()}/jobs?content=true"
            resp = requests.get(url, timeout=30, headers={'User-Agent': 'AI-Job-Hunter/1.0'})
            if resp.status_code != 200:
                result['status'] = 'error'
                result['error'] = f'HTTP {resp.status_code}'
                return result
            try:
                data = resp.json()
            except Exception as e:
                result['status'] = 'error'
                result['error'] = f'Invalid JSON: {e}'
                return result
            
            if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
                result['status'] = 'error'
                result['error'] = 'Unexpected response format: jobs must be a list'
                return result

            jobs_list = data['jobs']
            malformed_records = 0
            for j in jobs_list:
                if not isinstance(j, dict):
                    malformed_records += 1
                    continue
                location = j.get('location') or {}
                loc_name = location.get('name', '') if isinstance(location, dict) else str(location)
                desc = j.get('content') or j.get('description') or ''
                job_url = j.get('absolute_url') or j.get('url') or ''
                if not job_url:
                    malformed_records += 1
                    continue
                employer = j.get('company_name') or j.get('company') or board_token.strip()
                # Structured enrichment from fields the feed already provides.
                metadata_fields = _extract_metadata_fields(j.get('metadata'))
                offices_text = _extract_offices(j.get('offices'))
                gh_job_id = j.get('id')
                job_record = {
                    'employer': employer,
                    'job_title': j.get('title') or '',
                    'job_url': job_url,
                    'source': 'greenhouse',
                    'source_feed': board_token.strip(),
                    'description': str(desc),
                    'location': loc_name,
                    'department': j.get('departments', [{}])[0].get('name', '') if j.get('departments') else '',
                    'remote': True if 'remote' in loc_name.lower() else False,
                    'salary': '',
                    'shift': 'unknown',
                    'employment_type': metadata_fields.get('employment_type', ''),
                    'experience_required': metadata_fields.get('experience_required', ''),
                    'education_required': metadata_fields.get('education_required', ''),
                    'posting_date': normalize_source_timestamp(
                        j.get('first_published') or j.get('created_at')
                    ),
                    'source_updated_at': j.get('updated_at'),
                    'deadline': j.get('close_date') or '',
                    'retrieved_at': datetime.now().isoformat(),
                    'last_checked': datetime.now().isoformat(),
                    'listing_status': 'active_on_source',
                    # New enrichment fields (empty when the API provides nothing)
                    'gh_job_id': gh_job_id,
                    'office_locations': offices_text,
                    'gh_metadata': json.dumps(j.get('metadata')) if j.get('metadata') else '',
                }
                result['jobs'].append(job_record)
            if malformed_records:
                result['status'] = 'error'
                result['error'] = (
                    f'Source snapshot incomplete: skipped {malformed_records} malformed posting records'
                )
            result['retrieved'] = len(result['jobs'])
            return result
        except requests.exceptions.Timeout:
            result['status'] = 'error'
            result['error'] = 'Timeout'
            return result
        except requests.exceptions.RequestException as e:
            result['status'] = 'error'
            result['error'] = str(e)
            return result
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            return result
    
    def search(self, board_tokens: List[str] = None) -> Dict:
        all_jobs = []
        statuses = []
        for token in (board_tokens or []):
            res = self.search_board(token)
            all_jobs.extend(res['jobs'])
            statuses.append({'board': token, **res})
        return {'jobs': all_jobs, 'statuses': statuses}

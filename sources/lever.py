import requests
from typing import List, Dict
from datetime import datetime
from sources.date_utils import normalize_source_timestamp


class LeverSource:
    def search_board(self, board: str) -> Dict:
        result = {
            'jobs': [],
            'status': 'ok',
            'error': None,
            'retrieved': 0
        }
        if not board or not isinstance(board, str) or board.strip() == '':
            result['status'] = 'error'
            result['error'] = 'Invalid board identifier'
            return result
        
        try:
            url = f"https://api.lever.co/v0/postings/{board.strip()}?mode=json"
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
            
            if not isinstance(data, list):
                result['status'] = 'error'
                result['error'] = 'Unexpected response format'
                return result
            
            malformed_records = 0
            for j in data:
                if not isinstance(j, dict):
                    malformed_records += 1
                    continue
                categories = j.get('categories') or {}
                loc = categories.get('location') or j.get('workplaceType') or ''
                desc = j.get('descriptionPlain') or j.get('description') or ''
                job_url = j.get('hostedUrl') or j.get('applyUrl') or j.get('url') or ''
                if not job_url:
                    malformed_records += 1
                    continue
                workplace = j.get('workplaceType') or ''
                country = j.get('country') or ''
                employer = j.get('company') or j.get('companyName') or board.strip()
                result['jobs'].append({
                    'employer': employer,
                    'job_title': j.get('text') or j.get('title') or '',
                    'job_url': job_url,
                    'source': 'lever',
                    'source_feed': board.strip(),
                    'description': str(desc),
                    'location': loc if isinstance(loc, str) else str(loc),
                    'department': categories.get('team', '') if isinstance(categories, dict) else '',
                    'remote': True if str(workplace).lower() == 'remote' else False,
                    'salary': '',
                    'shift': 'unknown',
                    'employment_type': categories.get('commitment', '') if isinstance(categories, dict) else '',
                    'experience_required': '',
                    'education_required': '',
                    'posting_date': normalize_source_timestamp(j.get('createdAt')),
                    'source_updated_at': normalize_source_timestamp(j.get('updatedAt')),
                    'deadline': normalize_source_timestamp(j.get('closingAt')),
                    'workplace_type': workplace,
                    'country': country,
                    'retrieved_at': datetime.now().isoformat(),
                    'last_checked': datetime.now().isoformat(),
                    'listing_status': 'active_on_source',
                })
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
    
    def search(self, boards: List[str] = None) -> Dict:
        all_jobs = []
        statuses = []
        for board in (boards or []):
            res = self.search_board(board)
            all_jobs.extend(res['jobs'])
            statuses.append({'board': board, **res})
        return {'jobs': all_jobs, 'statuses': statuses}

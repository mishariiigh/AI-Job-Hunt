import requests
from typing import List, Dict
from datetime import datetime


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
            
            jobs_list = data.get('jobs', []) if isinstance(data, dict) else []
            for j in jobs_list:
                if not isinstance(j, dict):
                    continue
                location = j.get('location') or {}
                loc_name = location.get('name', '') if isinstance(location, dict) else str(location)
                desc = j.get('content') or j.get('description') or ''
                job_url = j.get('absolute_url') or j.get('url') or ''
                if not job_url:
                    continue
                employer = j.get('company_name') or j.get('company') or board_token.strip()
                result['jobs'].append({
                    'employer': employer,
                    'job_title': j.get('title') or '',
                    'job_url': job_url,
                    'source': 'greenhouse',
                    'description': str(desc),
                    'location': loc_name,
                    'department': j.get('departments', [{}])[0].get('name', '') if j.get('departments') else '',
                    'remote': True if 'remote' in loc_name.lower() else False,
                    'salary': '',
                    'shift': 'unknown',
                    'employment_type': '',
                    'experience_required': '',
                    'education_required': '',
                    'posting_date': j.get('updated_at') or j.get('created_at') or j.get('first_published'),
                    'deadline': j.get('close_date') or '',
                    'retrieved_at': datetime.now().isoformat(),
                    'last_checked': datetime.now().isoformat()
                })
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

import requests
from datetime import datetime
from typing import Dict, List


class SourceValidator:
    def __init__(self):
        self.timeout = 30
    
    def validate_greenhouse(self, board_token: str) -> Dict:
        if not board_token or not board_token.strip():
            return {'board': board_token, 'status': 'invalid', 'error': 'Empty identifier', 'valid': False}
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board_token.strip()}/jobs?content=false"
            resp = requests.get(url, timeout=self.timeout, headers={'User-Agent': 'AI-Job-Hunter/1.0'})
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    jobs = data.get('jobs', []) if isinstance(data, dict) else []
                    return {
                        'board': board_token.strip(),
                        'status': 'valid',
                        'valid': True,
                        'job_count': len(jobs),
                        'error': None,
                        'last_checked': datetime.now().isoformat()
                    }
                except Exception as e:
                    return {'board': board_token.strip(), 'status': 'error', 'valid': False, 'error': f'Invalid JSON: {e}', 'last_checked': datetime.now().isoformat()}
            elif resp.status_code == 429:
                return {'board': board_token.strip(), 'status': 'rate_limited', 'valid': False, 'error': 'Rate limited', 'last_checked': datetime.now().isoformat()}
            elif resp.status_code == 404:
                return {'board': board_token.strip(), 'status': 'invalid', 'valid': False, 'error': 'Board not found', 'last_checked': datetime.now().isoformat()}
            else:
                return {'board': board_token.strip(), 'status': 'error', 'valid': False, 'error': f'HTTP {resp.status_code}', 'last_checked': datetime.now().isoformat()}
        except requests.exceptions.Timeout:
            return {'board': board_token.strip(), 'status': 'error', 'valid': False, 'error': 'Timeout', 'last_checked': datetime.now().isoformat()}
        except requests.exceptions.RequestException as e:
            return {'board': board_token.strip(), 'status': 'error', 'valid': False, 'error': str(e), 'last_checked': datetime.now().isoformat()}
    
    def validate_lever(self, board: str) -> Dict:
        if not board or not board.strip():
            return {'board': board, 'status': 'invalid', 'error': 'Empty identifier', 'valid': False}
        try:
            url = f"https://api.lever.co/v0/postings/{board.strip()}?mode=json"
            resp = requests.get(url, timeout=self.timeout, headers={'User-Agent': 'AI-Job-Hunter/1.0'})
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        return {
                            'board': board.strip(),
                            'status': 'valid',
                            'valid': True,
                            'job_count': len(data),
                            'error': None,
                            'last_checked': datetime.now().isoformat()
                        }
                    else:
                        return {'board': board.strip(), 'status': 'error', 'valid': False, 'error': 'Unexpected format', 'last_checked': datetime.now().isoformat()}
                except Exception as e:
                    return {'board': board.strip(), 'status': 'error', 'valid': False, 'error': f'Invalid JSON: {e}', 'last_checked': datetime.now().isoformat()}
            elif resp.status_code == 429:
                return {'board': board.strip(), 'status': 'rate_limited', 'valid': False, 'error': 'Rate limited', 'last_checked': datetime.now().isoformat()}
            elif resp.status_code == 404:
                return {'board': board.strip(), 'status': 'invalid', 'valid': False, 'error': 'Board not found', 'last_checked': datetime.now().isoformat()}
            else:
                return {'board': board.strip(), 'status': 'error', 'valid': False, 'error': f'HTTP {resp.status_code}', 'last_checked': datetime.now().isoformat()}
        except requests.exceptions.Timeout:
            return {'board': board.strip(), 'status': 'error', 'valid': False, 'error': 'Timeout', 'last_checked': datetime.now().isoformat()}
        except requests.exceptions.RequestException as e:
            return {'board': board.strip(), 'status': 'error', 'valid': False, 'error': str(e), 'last_checked': datetime.now().isoformat()}
    
    def validate_all(self, greenhouse_boards: List[str], lever_boards: List[str]) -> Dict:
        results = {
            'greenhouse': [],
            'lever': [],
            'last_checked': datetime.now().isoformat()
        }
        for board in greenhouse_boards or []:
            results['greenhouse'].append(self.validate_greenhouse(board))
        for board in lever_boards or []:
            results['lever'].append(self.validate_lever(board))
        return results

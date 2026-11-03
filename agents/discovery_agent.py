from sources.greenhouse import GreenhouseSource
from sources.lever import LeverSource
from sources.job_bank import JobBankSource
from sources.employer_sites import EmployerSitesSource
from tracking.application_tracker import ApplicationTracker
from datetime import datetime


class DiscoveryAgent:
    def __init__(self):
        self.greenhouse = GreenhouseSource()
        self.lever = LeverSource()
        self.job_bank = JobBankSource()
        self.employer = EmployerSitesSource()
        self.tracker = ApplicationTracker()
    
    def is_canadian_remote(self, job):
        loc = (job.get('location') or '').lower()
        desc = (job.get('description') or '').lower()
        country = (job.get('country') or '').upper()
        workplace = (job.get('workplace_type') or '').lower()
        other_countries = ['remote - usa', 'united states', ' usa', ', usa', 'uk only', 'australia only']
        if any(c in loc for c in other_countries) and 'canada' not in loc:
            # explicit US-only restriction
            if 'canada' not in desc:
                return False
        if country == 'CA':
            return True
        if country == 'US':
            if 'canada' in desc or 'canadian' in desc:
                return True
            if 'us only' in desc or 'united states only' in desc or 'us-only' in desc:
                return False
            # unknown/ambiguous
            return False
        if 'canada' in loc or 'canadian' in desc:
            return True
        canadian_cities = ['toronto', 'vancouver', 'montreal', 'calgary', 'ottawa', 'edmonton', 'winnipeg', 'halifax']
        if any(city in loc for city in canadian_cities):
            return True
        # remote ambiguous
        if 'canada-wide' in desc or 'canada wide' in desc:
            return True
        if workplace == 'remote' and ('canada' in desc or 'canadian' in desc):
            return True
        return False

    def classify_schedule(self, job):
        text = f"{job.get('shift','')} {job.get('description','')} {job.get('job_title','')} {job.get('employment_type','')}".lower()
        evening_keywords = ['evening', 'after 6', 'after six', '18:00', '6 pm', '6pm', 'late shift']
        weekend_keywords = ['weekend']
        flexible_keywords = ['flexible']
        part_time_keywords = ['part-time', 'part time', '20-25', '20 hours', '25 hours']
        
        confirmed_evening = any(k in text for k in evening_keywords)
        confirmed_weekend = any(k in text for k in weekend_keywords)
        flexible = any(k in text for k in flexible_keywords)
        part_time = any(k in text for k in part_time_keywords)
        
        if confirmed_evening:
            schedule_type = 'confirmed_evening'
        elif confirmed_weekend and not confirmed_evening:
            schedule_type = 'confirmed_weekend'
        elif flexible:
            schedule_type = 'flexible'
        elif job.get('shift') == 'unknown' or ('shift' not in job or job.get('shift') == ''):
            schedule_type = 'unknown'
        else:
            schedule_type = 'other'
        
        return {
            'schedule_type': schedule_type,
            'confirmed_evening': confirmed_evening,
            'confirmed_weekend': confirmed_weekend,
            'flexible': flexible,
            'part_time': part_time
        }
    
    def has_evening_shift(self, job):
        sched = self.classify_schedule(job)
        if sched['schedule_type'] == 'unknown':
            return True
        if sched['confirmed_evening'] or sched['flexible'] or sched['part_time']:
            return True
        return False
    
    def is_expired(self, job):
        deadline = job.get('deadline')
        if not deadline:
            return False
        try:
            from datetime import datetime
            # try ISO date
            dt = datetime.fromisoformat(str(deadline).replace('Z','+00:00'))
            return dt < datetime.now(dt.tzinfo) if dt.tzinfo else dt < datetime.now()
        except Exception:
            return False
    
    def is_french_required(self, job):
        text = f"{job.get('description','')} {job.get('job_title','')}".lower()
        if 'bilingual french' in text or 'french required' in text or 'français requis' in text:
            return True
        return False
    
    def filter_job(self, job):
        if self.is_french_required(job):
            return False, "French required"
        if not self.is_canadian_remote(job):
            return False, "Not Canadian remote / restricted to other region"
        if self.is_expired(job):
            return False, "Expired"
        if self.tracker.job_exists(job.get('job_url', '')):
            return False, "Duplicate"
        sched = self.classify_schedule(job)
        job['schedule_classification'] = sched
        if sched['schedule_type'] == 'unknown':
            return True, "Passed"
        if sched['confirmed_evening'] or sched['flexible'] or sched['part_time']:
            return True, "Passed"
        return False, "Schedule conflict"
    
    def discover(self, greenhouse_boards=None, lever_boards=None):
        all_jobs = []
        stats = {
            'retrieved': 0,
            'new_saved': 0,
            'duplicates_skipped': 0,
            'expired_skipped': 0,
            'rejected_reasons': {},
            'errors': [],
            'sources': {},
            'per_source': {}
        }
        gh_res = self.greenhouse.search(greenhouse_boards or [])
        all_jobs.extend(gh_res['jobs'])
        stats['sources']['greenhouse'] = gh_res['statuses']
        stats['retrieved'] += len(gh_res['jobs'])
        stats['per_source']['greenhouse'] = {'retrieved': len(gh_res['jobs']), 'statuses': gh_res['statuses']}
        lev_res = self.lever.search(lever_boards or [])
        all_jobs.extend(lev_res['jobs'])
        stats['sources']['lever'] = lev_res['statuses']
        stats['retrieved'] += len(lev_res['jobs'])
        stats['per_source']['lever'] = {'retrieved': len(lev_res['jobs']), 'statuses': lev_res['statuses']}
        all_jobs.extend(self.job_bank.search())
        all_jobs.extend(self.employer.search())
        discovered = []
        for job in all_jobs:
            passed, reason = self.filter_job(job)
            if not passed:
                if reason == "Duplicate":
                    stats['duplicates_skipped'] += 1
                elif reason == "Expired":
                    stats['expired_skipped'] += 1
                stats['rejected_reasons'][reason] = stats['rejected_reasons'].get(reason, 0) + 1
                continue
            job['discovered_at'] = datetime.now().isoformat()
            job['status'] = 'discovered'
            job['approved'] = 0
            inserted = self.tracker.add_job(job)
            if not inserted:
                stats['duplicates_skipped'] += 1
                continue
            stats['new_saved'] += 1
            try:
                from agents.matching_agent import MatchingAgent
                matcher = MatchingAgent()
                match_res = matcher.score_job(job)
                matcher.save_match(inserted, match_res)
            except Exception:
                pass
            discovered.append(job)
        stats['last_updated'] = datetime.now().isoformat()
        return discovered, stats

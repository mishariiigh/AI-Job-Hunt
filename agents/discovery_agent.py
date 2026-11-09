import re
from sources.greenhouse import GreenhouseSource
from sources.lever import LeverSource
from sources.job_bank import JobBankSource
from sources.employer_sites import EmployerSitesSource
from sources.remotive import RemotiveSource
from sources.smartrecruiters import SmartRecruitersSource
from tracking.application_tracker import ApplicationTracker
from datetime import datetime
from agents.job_classifier import (
    canadian_eligibility,
    classify_evening_eligibility,
    french_is_mandatory,
)


_TARGET_ROLE_PATTERN = re.compile(
    r"\b(?:it|support|help desk|helpdesk|service desk|software|developer|"
    r"programmer|python|java|javascript|cloud|azure|cybersecurity|security|"
    r"network|devops|sre|site reliability|noc|soc|automation|technical|application|"
    r"systems|ai|artificial intelligence|"
    r"technical operations?|it operations?)\b",
    re.IGNORECASE,
)


def job_category(job_title):
    title = str(job_title or "").lower()
    if any(term in title for term in ("support", "help desk", "helpdesk", "service desk")):
        return "IT and application support"
    if any(term in title for term in ("cybersecurity", "security", "soc")):
        return "Cybersecurity and security support"
    if any(term in title for term in ("cloud", "azure", "network", "devops", "sre", "noc", "systems")):
        return "Cloud, infrastructure and technical operations"
    if re.search(r"\b(?:automation|artificial intelligence|ai)\b", title):
        return "AI automation and technical operations"
    return "Software development"


class DiscoveryAgent:
    def __init__(self):
        self.greenhouse = GreenhouseSource()
        self.lever = LeverSource()
        self.job_bank = JobBankSource()
        self.employer = EmployerSitesSource()
        self.remotive = RemotiveSource()
        self.smartrecruiters = SmartRecruitersSource()
        self.smartrecruiters_companies = self._load_smartrecruiters_companies()
        self.tracker = ApplicationTracker()
    
    def is_canadian_remote(self, job):
        eligibility = canadian_eligibility(job)
        if eligibility["status"] == "incompatible":
            return False
        location = str(job.get("location") or "").lower()
        remote = (
            job.get("remote") in (1, True, "1", "true", "yes", "remote")
            or str(job.get("workplace_type") or "").lower() in {"remote", "hybrid"}
            or "remote" in location
        )
        local = bool(
            re.search(r"\b(?:oakville|mississauga|toronto)\b", location, re.I)
        )
        return remote or local

    @staticmethod
    def _load_smartrecruiters_companies():
        """Load SmartRecruiters company IDs from config; empty list when unset."""
        import json as _json
        import os
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "sources.json")
        try:
            with open(config_path) as fh:
                config = _json.load(fh)
            companies = config.get("smartrecruiters_companies") or []
            return [str(c).strip() for c in companies if str(c).strip()]
        except (OSError, ValueError):
            return []

    def classify_schedule(self, job):
        classified = classify_evening_eligibility(job)
        text = f"{job.get('description', '')} {job.get('employment_type', '')}".lower()
        return {
            **classified,
            "confirmed_evening": classified["status"] == "confirmed_evening",
            "confirmed_weekend": bool(
                re.search(r"\b(?:weekends?|saturdays?|sundays?)\b", text)
            ),
            "flexible": classified["schedule_type"] == "flexible",
            "part_time": bool(
                re.search(r"\bpart[- ]time\b|\b20\s*[-–]\s*25\s+hours?\b", text)
            ),
        }
    
    def has_evening_shift(self, job):
        return classify_evening_eligibility(job)["status"] == "confirmed_evening"
    
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
        if french_is_mandatory(job):
            return False, "French required"
        if not self.is_canadian_remote(job):
            return False, "Not Canadian remote / restricted to other region"
        if self.is_expired(job):
            return False, "Expired"
        if not _TARGET_ROLE_PATTERN.search(str(job.get("job_title") or "")):
            return False, "Outside target technical job families"
        job["job_category"] = job_category(job.get("job_title"))
        job["schedule_classification"] = classify_evening_eligibility(job)
        return True, "Passed"
    
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
        }
        gh_res = self.greenhouse.search(greenhouse_boards or [])
        all_jobs.extend(gh_res['jobs'])
        stats['sources']['greenhouse'] = [
            {
                "board": status["board"],
                "status": status["status"],
                "retrieved": status["retrieved"],
                "error": status["error"],
            }
            for status in gh_res['statuses']
        ]
        stats['retrieved'] += len(gh_res['jobs'])
        lev_res = self.lever.search(lever_boards or [])
        all_jobs.extend(lev_res['jobs'])
        stats['sources']['lever'] = [
            {
                "board": status["board"],
                "status": status["status"],
                "retrieved": status["retrieved"],
                "error": status["error"],
            }
            for status in lev_res['statuses']
        ]
        stats['retrieved'] += len(lev_res['jobs'])
        remotive_res = self.remotive.search()
        all_jobs.extend(remotive_res["jobs"])
        stats["sources"]["remotive"] = {
            "status": remotive_res["status"],
            "retrieved": remotive_res["retrieved"],
            "last_checked": remotive_res["last_checked"],
            "error": remotive_res["error"],
            "warnings": remotive_res.get("warnings", []),
        }
        stats["retrieved"] += len(remotive_res["jobs"])
        sr_res = self.smartrecruiters.search(self.smartrecruiters_companies or [])
        all_jobs.extend(sr_res["jobs"])
        stats["sources"]["smartrecruiters"] = [
            {
                "board": status["company"],
                "status": status["status"],
                "retrieved": status["count"],
                "error": status["error"],
            }
            for status in sr_res["statuses"]
        ]
        stats["retrieved"] += len(sr_res["jobs"])
        if remotive_res["status"] == "error":
            stats["errors"].append(
                {"source": "remotive", "error": remotive_res["error"]}
            )
        stats["errors"].extend(
            {"source": "remotive", "warning": warning}
            for warning in remotive_res.get("warnings", [])
        )

        for status in gh_res["statuses"]:
            if status["status"] == "ok":
                feed_jobs = [
                    job for job in gh_res["jobs"]
                    if job.get("source_feed") == status["board"]
                ]
                self.tracker.update_source_snapshot(
                    "greenhouse",
                    status["board"],
                    [job["job_url"] for job in feed_jobs],
                    datetime.now().astimezone().isoformat(),
                )
            elif status["error"]:
                stats["errors"].append(
                    {"source": "greenhouse", "feed": status["board"], "error": status["error"]}
                )
        for status in lev_res["statuses"]:
            if status["status"] == "ok":
                feed_jobs = [
                    job for job in lev_res["jobs"]
                    if job.get("source_feed") == status["board"]
                ]
                self.tracker.update_source_snapshot(
                    "lever",
                    status["board"],
                    [job["job_url"] for job in feed_jobs],
                    datetime.now().astimezone().isoformat(),
                )
            elif status["error"]:
                stats["errors"].append(
                    {"source": "lever", "feed": status["board"], "error": status["error"]}
                )
        if remotive_res["status"] in {"ok", "cached"}:
            self.tracker.update_source_snapshot(
                "remotive",
                "remotive",
                [job["job_url"] for job in remotive_res["jobs"]],
                remotive_res["last_checked"],
                active_status="active_on_source_delayed",
            )

        discovered = []
        for job in all_jobs:
            job["job_category"] = job.get("job_category") or job_category(job.get("job_title"))
            job["schedule_classification"] = classify_evening_eligibility(job)
            if self.tracker.job_exists(job.get("job_url", "")):
                self.tracker.refresh_job_listing(job)
                stats["duplicates_skipped"] += 1
                stats["rejected_reasons"]["Previously known; source status refreshed"] = (
                    stats["rejected_reasons"].get(
                        "Previously known; source status refreshed", 0
                    ) + 1
                )
                continue
            passed, reason = self.filter_job(job)
            if not passed:
                if reason == "Expired":
                    stats['expired_skipped'] += 1
                stats['rejected_reasons'][reason] = stats['rejected_reasons'].get(reason, 0) + 1
                continue
            job['discovered_at'] = datetime.now().isoformat()
            job["last_verified_at"] = job.get("last_verified_at") or job.get("retrieved_at") or datetime.now().astimezone().isoformat()
            job["listing_status"] = job.get("listing_status") or "active_on_source"
            job['status'] = 'discovered'
            job['approved'] = 0
            inserted = self.tracker.add_job(job)
            if not inserted:
                stats['duplicates_skipped'] += 1
                continue
            job["id"] = inserted
            stats['new_saved'] += 1
            try:
                from agents.matching_agent import MatchingAgent
                matcher = MatchingAgent()
                match_res = matcher.score_job(job)
                matcher.save_match(inserted, match_res)
            except Exception:
                pass
            discovered.append(job)
        stats["previously_known"] = stats["duplicates_skipped"]
        stats["possible_repost_groups"] = len(
            {
                job["repost_group_key"]
                for job in self.tracker.get_jobs()
                if job.get("possible_repost_count", 1) > 1
            }
        )
        stats['last_updated'] = datetime.now().isoformat()
        return discovered, stats

import json
import os
from datetime import datetime, timedelta, timezone

import requests

from sources.date_utils import normalize_source_timestamp


class RemotiveSource:
    ENDPOINT = "https://remotive.com/api/remote-jobs"
    CACHE_PATH = os.path.join("storage", "remotive_jobs_cache.json")
    CACHE_TTL = timedelta(hours=6)

    def __init__(self, cache_path=None):
        self.cache_path = cache_path or self.CACHE_PATH

    @staticmethod
    def _normalize_jobs(payload, retrieved_at):
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            raise ValueError("Remotive response does not contain a jobs list")

        jobs = []
        for item in raw_jobs:
            if not isinstance(item, dict):
                raise ValueError("Remotive response contains a malformed job record")
            job_url = str(item.get("url") or "").strip()
            if not job_url:
                raise ValueError("Remotive job record is missing its original listing URL")
            job_type_key = str(item.get("job_type") or "").strip().lower()
            job_type = {
                "full_time": "Full-time",
                "part_time": "Part-time",
                "freelance": "Freelance",
                "contract": "Contract",
                "internship": "Internship",
            }.get(job_type_key, job_type_key.replace("_", " ").title())
            jobs.append(
                {
                    "employer": str(item.get("company_name") or "").strip(),
                    "job_title": str(item.get("title") or "").strip(),
                    "job_url": job_url,
                    "source": "remotive",
                    "source_feed": "remotive",
                    "description": str(item.get("description") or ""),
                    "location": str(item.get("candidate_required_location") or "").strip(),
                    "remote": True,
                    "salary": str(item.get("salary") or ""),
                    "shift": "unknown",
                    "employment_type": job_type,
                    "posting_date": normalize_source_timestamp(item.get("publication_date")),
                    "deadline": "",
                    "job_category": str(item.get("category") or "").strip(),
                    "listing_status": "active_on_source_delayed",
                    "last_verified_at": retrieved_at,
                    "retrieved_at": retrieved_at,
                }
            )
        return jobs

    def _read_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as cache_file:
                cached = json.load(cache_file)
        except FileNotFoundError:
            return None, None
        except (OSError, json.JSONDecodeError) as error:
            return None, f"Could not read Remotive cache: {error}"

        try:
            fetched_at = datetime.fromisoformat(
                str(cached["fetched_at"]).replace("Z", "+00:00")
            )
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            jobs = self._normalize_jobs(cached, fetched_at.isoformat())
        except (KeyError, TypeError, ValueError) as error:
            return None, f"Remotive cache has an invalid format: {error}"
        return (fetched_at, jobs), None

    def search(self):
        now = datetime.now(timezone.utc)
        cached, cache_error = self._read_cache()
        if cached and now - cached[0] < self.CACHE_TTL:
            return {
                "jobs": cached[1],
                "status": "cached",
                "error": None,
                "warnings": [],
                "retrieved": len(cached[1]),
                "last_checked": cached[0].isoformat(),
            }

        try:
            response = requests.get(
                self.ENDPOINT,
                timeout=30,
                headers={"User-Agent": "AI-Job-Hunter/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Remotive response is not a JSON object")
            retrieved_at = now.isoformat()
            jobs = self._normalize_jobs(payload, retrieved_at)
        except (requests.RequestException, ValueError) as error:
            detail = str(error)
            if cache_error:
                detail = f"{detail}; {cache_error}"
            return {
                "jobs": [],
                "status": "error",
                "error": detail,
                "warnings": [],
                "retrieved": 0,
                "last_checked": now.isoformat(),
            }

        warnings = [cache_error] if cache_error else []
        try:
            cache_dir = os.path.dirname(self.cache_path)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
            temporary_path = f"{self.cache_path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {
                        "fetched_at": retrieved_at,
                        "jobs": payload["jobs"],
                    },
                    cache_file,
                )
            os.replace(temporary_path, self.cache_path)
        except (OSError, TypeError, ValueError) as error:
            warnings.append(f"Could not persist Remotive rate-limit cache: {error}")

        return {
            "jobs": jobs,
            "status": "ok",
            "error": None,
            "warnings": warnings,
            "retrieved": len(jobs),
            "last_checked": retrieved_at,
            "total_job_count": payload.get("total-job-count"),
        }

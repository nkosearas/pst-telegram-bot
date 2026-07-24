import time

import requests


class PstApiError(Exception):
    pass


class PstClient:
    def __init__(self, api_username, api_password, dbs_code, base_url="https://pstapi.dbsinfo.com"):
        self.api_username = api_username
        self.api_password = api_password
        self.dbs_code = dbs_code
        self.base_url = base_url.rstrip("/")
        self._token = None
        self._token_expires_at = 0

    def _get_token(self):
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        response = requests.post(
            f"{self.base_url}/token",
            data={
                "grant_type": "password",
                "apiusername": self.api_username,
                "apipassword": self.api_password,
                "dbscode": self.dbs_code,
            },
        )
        if not response.ok:
            raise PstApiError(f"Token request failed ({response.status_code}): {response.text}")

        payload = response.json()
        token = payload.get("token") or payload.get("access_token")
        if not token:
            raise PstApiError(f"Token request succeeded but no token found in response: {payload}")

        self._token = token
        self._token_expires_at = time.time() + float(payload.get("expires_in", 1200))
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def search_jobs(self, **params):
        response = requests.get(f"{self.base_url}/jobs", headers=self._headers(), params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("IsSuccess", True):
            raise PstApiError(data.get("TransactionErrors"))
        return data.get("Jobs", [])

    def search_entities(self, **params):
        response = requests.get(f"{self.base_url}/entities", headers=self._headers(), params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("IsSuccess", True):
            raise PstApiError(data.get("TransactionErrors"))
        return data.get("Entities", [])

    def add_comment(self, job_number, comment_text, comment_datetime, is_attempt=True, is_status_report=True):
        body = {
            "Job": {
                "JobNumber": job_number,
                "CreateComments": [
                    {
                        "CommentDateTime": comment_datetime,
                        "CommentText": comment_text,
                        "IsAttempt": is_attempt,
                        "IsStatusReport": is_status_report,
                        "IsReviewed": True,
                    }
                ],
            }
        }
        response = requests.put(f"{self.base_url}/jobs", headers=self._headers(), json=body)
        response.raise_for_status()
        data = response.json()
        if not data.get("IsSuccess", True):
            raise PstApiError(data.get("TransactionErrors"))
        return data

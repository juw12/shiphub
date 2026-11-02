"""
Minimal GitHub client (stdlib only): OAuth login + public-data checks used to
verify ships and award XP for real pushes. User access tokens are only used
during login and are never stored.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

REPO_URL = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?(?:/.*)?$")


class GitHubError(Exception):
    pass


def parse_repo_url(url):
    match = REPO_URL.match((url or "").strip())
    return (match.group(1), match.group(2)) if match else None


class GitHub:
    def __init__(self, client_id, client_secret, api_base="https://api.github.com",
                 oauth_base="https://github.com", app_token=None, opener=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_base = api_base.rstrip("/")
        self.oauth_base = oauth_base.rstrip("/")
        self.app_token = app_token
        self.opener = opener or urllib.request.build_opener()

    def _open(self, request):
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise GitHubError(f"GitHub returned HTTP {error.code}") from None
        except (urllib.error.URLError, OSError) as error:
            raise GitHubError(f"cannot reach GitHub: {error}") from None

    def api(self, path, token=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "vibeHQ"}
        auth = token or self.app_token
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        return self._open(urllib.request.Request(self.api_base + path, headers=headers))

    # ------------------------------------------------------------ OAuth

    def authorize_url(self, state, redirect_uri):
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "read:user",
            "allow_signup": "true",
        })
        return f"{self.oauth_base}/login/oauth/authorize?{query}"

    def exchange_code(self, code, redirect_uri):
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }).encode()
        request = urllib.request.Request(
            f"{self.oauth_base}/login/oauth/access_token",
            data=data,
            headers={"Accept": "application/json", "User-Agent": "vibeHQ"},
        )
        result = self._open(request) or {}
        if "access_token" not in result:
            raise GitHubError(result.get("error_description", "GitHub login failed"))
        return result["access_token"]

    def current_user(self, token):
        user = self.api("/user", token=token)
        if not user:
            raise GitHubError("could not read GitHub profile")
        return user

    # ------------------------------------------------------------ verification data

    def repo(self, owner, name):
        return self.api(f"/repos/{owner}/{name}")

    def is_contributor(self, owner, name, login):
        contributors = self.api(f"/repos/{owner}/{name}/contributors?per_page=100") or []
        return any(entry.get("login", "").lower() == login.lower() for entry in contributors)

    def recent_push_events(self, login):
        events = self.api(f"/users/{urllib.parse.quote(login)}/events/public?per_page=100") or []
        return [event for event in events if event.get("type") == "PushEvent"]

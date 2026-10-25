#!/usr/bin/env python3
"""
ONE-TIME SETUP HELPER — run this on your own computer, not in GitHub Actions.

It walks you through LinkedIn's login, then prints the two (or three) values
you need to paste into your GitHub repository secrets.

Before running:
  1. pip install requests
  2. Create a LinkedIn app at https://www.linkedin.com/developers/apps
     - Associate it with any LinkedIn Page you manage (required by LinkedIn,
       even though posts go to your personal profile).
     - Under "Products", request/add:
         * "Share on LinkedIn"
         * "Sign In with LinkedIn using OpenID Connect"
       (Both are self-serve — no partner approval needed.)
     - Under the "Auth" tab, add this EXACT redirect URL:
         http://localhost:8000/callback
  3. Copy your Client ID and Client Secret from the "Auth" tab into the
     two variables below.

Then run:  python get_token.py
"""

import http.server
import socketserver
import urllib.parse
import webbrowser
import requests

# ====== FILL THESE IN (from your LinkedIn app's "Auth" tab) ======
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
# =================================================================

REDIRECT_URI = "http://localhost:8000/callback"
SCOPE = "openid profile w_member_social"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

_received = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            _received["code"] = params.get("code", [None])[0]
            _received["error"] = params.get("error_description", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h2>All set. Close this tab and go back to your terminal.</h2>"
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # keep the terminal quiet


def main():
    if CLIENT_ID == "YOUR_CLIENT_ID" or CLIENT_SECRET == "YOUR_CLIENT_SECRET":
        print("Edit this file first: set CLIENT_ID and CLIENT_SECRET at the top.")
        return

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
        }
    )
    url = f"{AUTH_URL}?{query}"
    print("Opening your browser to authorize the app...")
    print("If nothing opens, paste this into your browser manually:\n")
    print(url, "\n")
    webbrowser.open(url)

    with socketserver.TCPServer(("localhost", 8000), _Handler) as httpd:
        print("Waiting for LinkedIn to redirect back to localhost...")
        while "code" not in _received:
            httpd.handle_request()

    if _received.get("error"):
        print("LinkedIn returned an error:", _received["error"])
        return
    code = _received.get("code")
    if not code:
        print("No authorization code received. Check your redirect URL setting.")
        return

    # Exchange the code for an access token
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    access_token = token["access_token"]

    # Look up your person URN
    userinfo = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    userinfo.raise_for_status()
    sub = userinfo.json()["sub"]
    person_urn = f"urn:li:person:{sub}"

    print("\n" + "=" * 64)
    print("SUCCESS — add these as GitHub repository secrets")
    print("(Settings > Secrets and variables > Actions > New repository secret)")
    print("-" * 64)
    print("LINKEDIN_ACCESS_TOKEN =", access_token)
    print("LINKEDIN_PERSON_URN   =", person_urn)
    if token.get("refresh_token"):
        print("LINKEDIN_REFRESH_TOKEN =", token["refresh_token"])
    expires_days = round(int(token.get("expires_in", 0)) / 86400, 1)
    print("-" * 64)
    print(f"This access token expires in about {expires_days} days.")
    print("When it expires, just run this script again to get a fresh one.")
    print("=" * 64)


if __name__ == "__main__":
    main()

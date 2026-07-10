"""
🔑 generate_token.py
GAMEOVER EDITS — Local User OAuth2 Token Generator

Description:
  This script is a one-time helper to run on your local PC (with a web browser)
  to generate a Google User OAuth2 credential file ('token.json').

Requirements:
  1. pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
  2. Download 'client_secrets.json' from GCP Console (OAuth Client Desktop Application).
  3. Put 'client_secrets.json' and this script in the same directory.

Usage:
  python generate_token.py
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print(
        "❌ google-auth-oauthlib is not installed.\n"
        "Please run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client",
        file=sys.stderr
    )
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token.json"

def main():
    print("=" * 65)
    print("🔑 GAMEOVER EDITS — Google Drive User Token Generator")
    print("=" * 65)

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"❌ ERROR: '{CLIENT_SECRETS_FILE}' was not found in the current directory.")
        print("\nHow to fix this:")
        print("1. Go to Google Cloud Console -> APIs & Services -> Credentials.")
        print("2. Create an 'OAuth client ID' with Application Type set to 'Desktop app'.")
        print("3. Click the download icon (JSON) for that credential.")
        print(f"4. Rename the downloaded file to '{CLIENT_SECRETS_FILE}' and place it here.")
        sys.exit(1)

    try:
        print("⚡ Loading client secrets and starting local web server...")
        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES
        )
        
        # Runs a local server on port 8080. If blocked, it picks an arbitrary port.
        print("🌐 Opening your default web browser for Google login...")
        creds = flow.run_local_server(
            port=8080,
            prompt="select_account",
            success_message="✅ Authorization complete! You can close this window now."
        )

        # Save credentials as token.json
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

        print("\n" + "=" * 65)
        print("🎉 SUCCESS: 'token.json' has been generated successfully!")
        print("=" * 65)
        print("What to do next:")
        print("1. Upload this newly generated 'token.json' to your VPS server.")
        print("2. Place it inside the bot's root directory (~/Gameover_edits/).")
        print("3. Restart your bot on the VPS.")
        print("=" * 65 + "\n")

    except Exception as e:
        print(f"\n❌ Error generating token: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

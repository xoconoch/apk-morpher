"""APK-Morpher: Self-hosted Morphe/ReVanced auto-build pipeline.

Provides a curl_cffi session (Safari impersonation to bypass Cloudflare)
and authenticated GitHub API client for the entire builder package.
"""
import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    root_dir = Path(__file__).resolve().parent.parent
    env_path = root_dir / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass

from curl_cffi import requests
from github import Github

# Safari fingerprint bypasses Cloudflare more reliably than Chrome.
session = requests.Session(impersonate="safari17_0")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

github_token = os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')
base_url = "https://www.apkmirror.com"

if github_token:
    logging.info("GitHub token detected; using authenticated GitHub API client")
    gh = Github(github_token)
else:
    if os.getenv("CI"):
        logging.warning("No GITHUB_TOKEN detected in CI; GitHub release lookups may fail")
    else:
        logging.warning("No GitHub token detected; using anonymous GitHub API client")
    gh = Github()

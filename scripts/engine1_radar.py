import os
import time
import json
import logging
import subprocess
from pathlib import Path
import urllib.request
import urllib.error
import shutil
import stat
import errno

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Engine1(Radar): %(message)s',
    handlers=[logging.StreamHandler()]
)

WORKSPACE_DIR = Path(os.environ.get("REPO_ANALYZER_WORKSPACE", r"C:\Users\owner\.repo-analyzer-pipeline\workspace"))
ENV_PATH = WORKSPACE_DIR / ".env"
STATE_PATH = WORKSPACE_DIR / "state" / "radar_state.json"
STAGING_DIR = WORKSPACE_DIR / "staging"

def load_env():
    env_vars = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars

def load_state():
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                # Migration: if state is a list, convert to dict
                if isinstance(state.get("processed_repos"), list):
                    logging.info("Migrating radar_state from list to dict...")
                    repo_dict = {repo_id: {"sha": "unknown", "name": "migrated"} for repo_id in state["processed_repos"]}
                    state["processed_repos"] = repo_dict
                return state
        except Exception as e:
            logging.error(f"Failed to load state: {e}")
    return {"processed_repos": {}}

def save_state(state):
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save state: {e}")

def fetch_starred_repos(pat):
    """Fetches starred repositories for the authenticated user."""
    url = "https://api.github.com/user/starred?per_page=100" # Fetch up to 100 starred repos
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Repo-Analyzer-Pipeline"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
            else:
                logging.error(f"Failed to fetch stars: HTTP {response.status}")
                return []
    except urllib.error.URLError as e:
        logging.error(f"Failed to fetch stars: {e}")
        return []

def get_latest_commit_sha(pat, repo_full_name):
    """Fetches the latest commit SHA for the default branch."""
    url = f"https://api.github.com/repos/{repo_full_name}/commits?per_page=1"
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Repo-Analyzer-Pipeline"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data[0].get("sha") if data else None
    except Exception as e:
        logging.error(f"Failed to fetch SHA for {repo_full_name}: {e}")
    return None

def clone_repo(repo_url, repo_name):
    target_dir = STAGING_DIR / repo_name
    if target_dir.exists():
        logging.info(f"Directory {target_dir} exists. Cleaning up for fresh acquisition...")
        try:
            # Use powershell for much more aggressive/reliable cleanup on Windows
            subprocess.run(
                ["powershell", "-Command", f"Remove-Item -Path '{target_dir}' -Force -Recurse"],
                check=True, capture_output=True
            )
        except Exception as e:
             logging.warning(f"Initial cleanup failed, trying git GC and retry... {e}")
             # Sometimes git objects are extra stubborn
             time.sleep(1)
             subprocess.run(["powershell", "-Command", f"Remove-Item -Path '{target_dir}' -Force -Recurse -ErrorAction SilentlyContinue"], check=False)

        if target_dir.exists():
            logging.error(f"Failed to remove existing directory {target_dir}. Cannot proceed with clone.")
            return False
    
    logging.info(f"Cloning {repo_url} into {target_dir}...")
    try:
        # Clone with depth 1
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target_dir)],
            capture_output=True, text=True, check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Git clone failed for {repo_name}: {e.stderr}")
        return False

def run_radar():
    logging.info("Engine 1: GitHub Star Radar starting (V2 Smart Tracking)...")
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            env = load_env()
            pat = env.get("GITHUB_PAT")
            
            if not pat or pat == "YOUR_GITHUB_PAT_HERE":
                logging.warning("GITHUB_PAT is not set or valid in .env. Waiting 60 seconds...")
                time.sleep(60)
                continue
                
            state = load_state()
            processed_repos = state.get("processed_repos", {})
            
            stars = fetch_starred_repos(pat)
            new_clones = 0
            
            for repo in stars:
                repo_id = str(repo.get("id"))
                repo_name = repo.get("name")
                repo_full_name = repo.get("full_name")
                clone_url = repo.get("clone_url")
                
                # Fetch current SHA to see if it changed
                current_sha = get_latest_commit_sha(pat, repo_full_name)
                last_state = processed_repos.get(repo_id)
                if last_state is None or not isinstance(last_state, dict):
                    last_state = {}
                
                last_sha = last_state.get("sha")
                
                is_new = repo_id not in processed_repos
                is_updated = current_sha is not None and last_sha is not None and current_sha != last_sha
                
                if is_new or is_updated:
                    trigger_reason = "New target" if is_new else f"Update detected ({last_sha[:7]} -> {current_sha[:7]})"
                    logging.info(f"🎯 {trigger_reason}: {repo_full_name}")
                    
                    if clone_repo(clone_url, repo_name):
                        processed_repos[repo_id] = {
                            "sha": current_sha or "unknown",
                            "name": repo_name,
                            "full_name": repo_full_name,
                            "updated_at": int(time.time())
                        }
                        state["processed_repos"] = processed_repos
                        save_state(state)
                        new_clones += 1
                        logging.info(f"Triggering Engine 0 for {repo_name}...")
            
            if new_clones == 0:
                logging.info("Radar scan complete. No new or updated targets. Sleeping for 5 minutes...")
            else:
                logging.info(f"Radar scan complete. Processed {new_clones} targets. Sleeping for 5 minutes...")
            
            time.sleep(300) 
            
        except Exception as e:
            logging.error(f"Unexpected error in radar loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_radar()

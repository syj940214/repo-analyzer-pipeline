import os
import time
import json
import logging
from pathlib import Path
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [⚙️ ORCHESTRATOR] %(message)s',
    handlers=[logging.StreamHandler()]
)

WORKSPACE_DIR = Path(os.environ.get("REPO_ANALYZER_WORKSPACE", r"C:\Users\owner\.repo-analyzer-pipeline\workspace"))
STAGING_DIR = WORKSPACE_DIR / "staging"
OUTPUT_DIR = WORKSPACE_DIR / "output"
STATE_PATH = WORKSPACE_DIR / "state" / "orchestrator_state.json"

ENGINE2_SCRIPT = WORKSPACE_DIR / "scripts" / "engine2_analyzer.py"
ENGINE3_SCRIPT = WORKSPACE_DIR / "scripts" / "engine3_sandbox.py"

def load_state():
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                # Migration: if processed_repos is a list, convert to dict
                if isinstance(state.get("processed_repos"), list):
                    logging.info("Migrating orchestrator_state from list to dict...")
                    state["processed_repos"] = {repo_name: "unknown" for repo_name in state["processed_repos"]}
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

def get_local_repo_sha(repo_name):
    """Gets the current local commit SHA of a staged repository."""
    repo_path = STAGING_DIR / repo_name
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except:
        return None

def run_engine2(repo_name):
    logging.info(f"Triggering Engine 2 (Deep Analyzer) for: {repo_name}")
    try:
        subprocess.run(["python", str(ENGINE2_SCRIPT), repo_name], check=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Engine 2 failed for {repo_name}. Exception: {e}")
        return False

def run_engine3(repo_name):
    logging.info(f"Triggering Engine 3 (Docker Sandbox) for: {repo_name}")
    try:
        subprocess.run(["python", str(ENGINE3_SCRIPT), repo_name], check=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Engine 3 failed for {repo_name}. Exception: {e}")
        return False

def run_orchestrator():
    logging.info("🌟 Repo Analyzer Pipeline Orchestrator Started (V2 Smart Re-Analysis).")
    logging.info("Monitoring staging directory for new acquisitions or updates...")
    
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            state = load_state()
            processed_repos = state.get("processed_repos", {})
            
            # Scan staging directory for all folders
            targets = [d for d in os.listdir(STAGING_DIR) if os.path.isdir(STAGING_DIR / d) and not d.startswith(".") and d != "__pycache__"]
            
            for repo_name in targets:
                local_sha = get_local_repo_sha(repo_name)
                last_analyzed_sha = processed_repos.get(repo_name)
                
                is_new = repo_name not in processed_repos
                is_updated = local_sha and last_analyzed_sha and local_sha != last_analyzed_sha
                
                if is_new or is_updated:
                    trigger_reason = "New target" if is_new else f"Update detected ({last_analyzed_sha[:7]} -> {local_sha[:7]})"
                    logging.info(f"🚀 Master Pipeline Triggered ({trigger_reason}): {repo_name}")
                    
                    # Step 1: Execute AI Autopsy (Static Analysis)
                    e2_success = run_engine2(repo_name)
                    
                    # Step 2: Security Halt Check & Execute Sandbox
                    if e2_success:
                        autopsy_file = OUTPUT_DIR / f"{repo_name}_autopsy_result.json"
                        should_sandbox = True
                        
                        if autopsy_file.exists():
                            try:
                                with open(autopsy_file, "r", encoding="utf-8") as f:
                                    result = json.load(f)
                                    if result.get("security_grade") == "Critical":
                                        logging.warning(f"🚨 SECURITY HALT: {repo_name} graded as CRITICAL. Skipping Sandbox.")
                                        should_sandbox = False
                            except Exception as e:
                                logging.error(f"Failed to parse autopsy: {e}")

                        if should_sandbox:
                            run_engine3(repo_name)
                    
                    # Mark as processed with the current SHA
                    processed_repos[repo_name] = local_sha or "unknown"
                    state["processed_repos"] = processed_repos
                    save_state(state)
                    logging.info(f"✅ Pipeline complete for {repo_name}.")
                
            time.sleep(60) # Orchestrator checks for new staging folders every 60 seconds
            
        except KeyboardInterrupt:
            logging.info("Orchestrator shutting down manually.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in orchestrator loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_orchestrator()

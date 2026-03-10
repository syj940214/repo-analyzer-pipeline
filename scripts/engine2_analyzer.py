import os
import json
import logging
import requests
import time
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Engine2(Analyzer): %(message)s',
    handlers=[logging.StreamHandler()]
)

def send_telegram_alert(message):
    """Sends a formatted alert message to Telegram to trigger Human-in-the-Loop intervention."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logging.warning("Telegram credentials missing in .env. Cannot notify operator.")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=15)
        return True
    except:
        return False

WORKSPACE_DIR = Path(os.environ.get("REPO_ANALYZER_WORKSPACE", r"C:\Users\owner\.repo-analyzer-pipeline\workspace"))
STAGING_DIR = WORKSPACE_DIR / "staging"
OUTPUT_DIR = WORKSPACE_DIR / "output"
TOKEN_PATH = Path(os.path.expanduser("~")) / ".repo-analyzer-pipeline" / "credentials" / "github-copilot.token.json"
COPILOT_API_URL = "https://api.individual.githubcopilot.com/chat/completions"

# AI Autopsy Prompt Template
AUTOPSY_PROMPT_TEMPLATE = """
### Role: Senior Cyber Security Architect & Code Auditor
### Task: Perform a Deep Repo Autopsy on the following code context.

### Repo Target: {repo_name}
### Code Context Snippet (Top Files):
{code_content}

---
### Audit Requirements:
1. **Malware & Security Analysis**: 
   - Detect obfuscated strings (Base64/Hex).
   - Check for unauthorized socket/request calls to unknown IPs.
   - Detect file encryption or registry modification logic.
   - Look for sensitive credential leakage (hardcoded keys).
2. **Intent & Metadata Extraction**:
   - What is the primary purpose of this repo?
   - Is it a 'Skill' (single function/tool), a 'Framework', or a 'Reference'?
3. **Execution Feasibility**:
   - Is this code Windows-compatible?
   - What environment/dependencies are needed (Python, Node, Docker)?

### Output Format (Strict JSON):
{{
  "repo_name": "{repo_name}",
  "summary": "1-sentence summary",
  "security_grade": "Safe | Warning | Critical",
  "threat_report": ["List of suspicious findings"],
  "category": "Skill | Framework | Documentation",
  "windows_compatibility": "High | Medium | Low",
  "required_actions": ["Specific Fixes needed before local run"]
}}
"""

def get_copilot_token():
    """Retrieve the GitHub Copilot token from the local credentials file."""
    try:
        if not TOKEN_PATH.exists():
            logging.error(f"Copilot token file not found at: {TOKEN_PATH}")
            return None
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("token")
    except Exception as e:
        logging.error(f"Error reading Copilot token: {e}")
        return None

def refresh_copilot_token_hitl():
    """Human-in-the-Loop Token Refresh via Telegram & Device Flow."""
    CLIENT_ID = "Iv1.b507a08c87ecfe98"
    DEVICE_CODE_URL = "https://github.com/login/device/code"
    ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
    COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
    
    logging.info("Initiating HITL Token Recovery...")
    
    # 1. Get Device Code
    resp = requests.post(DEVICE_CODE_URL, data={"client_id": CLIENT_ID, "scope": "read:user"}, headers={"Accept": "application/json"})
    if not resp.ok:
        logging.error("Failed to fetch GitHub device code.")
        return False
        
    device_data = resp.json()
    verify_uri = device_data['verification_uri']
    user_code = device_data['user_code']
    device_code = device_data['device_code']
    interval = device_data['interval']
    
    # Send Telegram Alert
    alert_msg = f"""
🚨 *[Repo Analyzer Pipeline HITL Alert: Copilot Token Expired]*
Engine 2 has paused execution. Please authorize the new token.

1️⃣ Open this URL: {verify_uri}
2️⃣ Enter the code: `{user_code}`

The pipeline will automatically resume once authorized.
"""
    send_telegram_alert(alert_msg)
    logging.info(f"Waiting for HITL authorization... (Code: {user_code})")
    
    # 2. Poll for Access Token
    github_token = None
    max_attempts = 120 # 120 * 5s = 10 minutes max wait
    attempts = 0
    
    while attempts < max_attempts:
        time.sleep(interval)
        token_resp = requests.post(ACCESS_TOKEN_URL, data={
            "client_id": CLIENT_ID, "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
        }, headers={"Accept": "application/json"})
        
        token_data = token_resp.json()
        if "access_token" in token_data:
            github_token = token_data["access_token"]
            break
        elif token_data.get("error") == "authorization_pending":
            attempts += 1
            print(f"Waiting for user authorization... ({attempts}/{max_attempts})", end="\r")
            continue
        elif token_data.get("error") == "slow_down":
            interval += 2
            continue
        else:
            logging.error(f"Error polling token: {token_data}")
            return False
            
    if not github_token:
        logging.error("HITL authorization timeout.")
        return False
        
    # 3. Exchange for Copilot Token
    logging.info("GitHub token acquired. Exchanging for Copilot token...")
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/json",
        "Editor-Version": "vscode/1.85.1",
        "Editor-Plugin-Version": "copilot/1.143.0",
        "User-Agent": "GithubCopilot/1.143.0"
    }
    copilot_resp = requests.get(COPILOT_TOKEN_URL, headers=headers)
    if not copilot_resp.ok:
        logging.error("Failed to get Copilot token.")
        return False
        
    copilot_data = copilot_resp.json()
    expires_at = copilot_data.get("expires_at", 0)
    if isinstance(expires_at, int) and expires_at < 10000000000:
        expires_at *= 1000
        
    final_payload = {
        "token": copilot_data["token"],
        "expiresAt": expires_at,
        "updatedAt": int(time.time() * 1000)
    }
    
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)
        
    logging.info("Copilot token successfully stored. Resuming Pipeline.")
    send_telegram_alert("✅ *[Repo Analyzer Pipeline Protocol]* HITL Authorization successful. Pipeline resumed.")
    return True

def call_llm_autopsy(repo_name, context, retry=False):
    """Calls the GitHub Copilot API to perform the AI Autopsy. Handles HITL recovery."""
    token = get_copilot_token()
    if not token:
        if not retry and refresh_copilot_token_hitl():
            return call_llm_autopsy(repo_name, context, retry=True)
        return None

    prompt = AUTOPSY_PROMPT_TEMPLATE.format(
        repo_name=repo_name,
        code_content=context
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Editor-Version": "vscode/1.85.1",
        "Editor-Plugin-Version": "copilot/1.143.0",
        "User-Agent": "GithubCopilot/1.143.0"
    }

    payload = {
        "model": "gpt-4.1",
        "messages": [
            {"role": "system", "content": "You are a professional security auditor. Reply ONLY in valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "stream": False
    }

    try:
        logging.info(f"Calling LLM (gpt-4.1) for {repo_name} autopsy...")
        response = requests.post(COPILOT_API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 401:
            logging.warning("Copilot token expired (401). Triggering HITL Auto-Recovery...")
            if not retry and refresh_copilot_token_hitl():
                return call_llm_autopsy(repo_name, context, retry=True)
            return None
        
        if response.status_code != 200:
            logging.error(f"API Error ({response.status_code}): {response.text}")
            return None

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Clean up possible markdown code block formatting
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        return json.loads(content)
    except Exception as e:
        logging.error(f"Error during LLM call for {repo_name}: {e}")
        return None

def get_repo_context(repo_path, max_chars=12000):
    """Scan the repo and read top files for context."""
    context = ""
    target_exts = {'.py', '.js', '.ts', '.md', '.txt', '.env.example', 'Dockerfile', '.yaml', '.yml'}
    
    # Priority files
    priority_files = ['README.md', 'requirements.txt', 'package.json', 'Dockerfile', 'main.py', 'index.js', 'app.py']
    
    processed_count = 0
    for file_name in priority_files:
        p = repo_path / file_name
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding='utf-8', errors='ignore')
                context += f"\n--- FILE: {file_name} ---\n{content[:2500]}\n"
                processed_count += 1
            except:
                pass

    # Generic scan
    for p in repo_path.rglob('*'):
        if p.is_file() and p.suffix in target_exts and p.name not in priority_files:
            if processed_count > 20: break
            try:
                # Skip massive files
                if p.stat().st_size > 100000: continue
                content = p.read_text(encoding='utf-8', errors='ignore')
                context += f"\n--- FILE: {p.relative_to(repo_path)} ---\n{content[:1500]}\n"
                processed_count += 1
            except:
                pass
            if len(context) > max_chars: break
            
    return context[:max_chars]

def analyze_repo(repo_name):
    repo_path = STAGING_DIR / repo_name
    if not repo_path.exists():
        logging.error(f"Repo path {repo_path} not found.")
        return False
    
    logging.info(f"Starting Deep Autopsy (Brain Surgical Procedure) for {repo_name}...")
    context = get_repo_context(repo_path)
    
    # Call the actual LLM
    result = call_llm_autopsy(repo_name, context)
    
    if result:
        output_file = OUTPUT_DIR / f"{repo_name}_autopsy_result.json"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logging.info(f"Autopsy successful. Results saved to {output_file}")
        return True
    else:
        logging.error(f"Autopsy failed for {repo_name} (LLM call failed).")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        success = analyze_repo(sys.argv[1])
        sys.exit(0 if success else 1)
    else:
        logging.error("No repo name provided for analysis.")
        sys.exit(1)

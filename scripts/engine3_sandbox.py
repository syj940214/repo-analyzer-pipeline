import os
import json
import time
import logging
import subprocess
import requests
from pathlib import Path
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Engine3(Sandbox): %(message)s',
    handlers=[logging.StreamHandler()]
)

WORKSPACE_DIR = Path(os.environ.get("REPO_ANALYZER_WORKSPACE", r"C:\Users\owner\.repo-analyzer-pipeline\workspace"))
STAGING_DIR = WORKSPACE_DIR / "staging"
OUTPUT_DIR = WORKSPACE_DIR / "output"
HONEYPOT_DIR = WORKSPACE_DIR / "honeypot"

# Ensure honeypot directory exists with fake files
def setup_honeypot():
    HONEYPOT_DIR.mkdir(parents=True, exist_ok=True)
    fake_env = HONEYPOT_DIR / ".env"
    if not fake_env.exists():
        fake_env.write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\nDATABASE_URL=postgres://user:pass@localhost:5432/db", encoding='utf-8')

# Dynamic Dockerfile Template
DOCKERFILE_TEMPLATE = """
FROM python:3.10-slim

WORKDIR /app

# Copy the target repo
COPY ./ /app/

# Install dummy requirements if text exists
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt || true; fi

# Default execution
CMD ["python", "-c", "print('Sandbox Execution Complete. No default entrypoint found.')"]
"""

def send_telegram_message(message):
    """Sends a formatted message to Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        logging.warning("Telegram credentials (TELEGRAM_BOT_TOKEN/ID) missing in .env.")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logging.info("Telegram notification dispatched successfully.")
        return True
    except Exception as e:
        logging.error(f"Telegram dispatch failed: {e}")
        return False

def prepare_sandbox(repo_name):
    """Prepares the staging directory with a Dockerfile."""
    repo_path = STAGING_DIR / repo_name
    if not repo_path.exists():
        logging.error(f"Repo {repo_name} not found in staging.")
        return False
    
    dockerfile_path = repo_path / "Dockerfile"
    dockerfile_path.write_text(DOCKERFILE_TEMPLATE, encoding='utf-8')
    logging.info(f"Dockerfile injected into {repo_name}.")
    setup_honeypot()
    return repo_path

def build_and_run(repo_path, repo_name):
    """Builds and runs the docker image in a highly restricted sandbox."""
    image_name = f"repo_analyzer_sandbox_{repo_name.lower().replace('-', '_')}"
    container_name = f"sandbox_exec_{repo_name.lower().replace('-', '_')}"
    
    logging.info(f"Building Docker image: {image_name}...")
    try:
        # Build the image - Fix encoding for Windows/Docker logs
        build_cmd = ["docker", "build", "-t", image_name, str(repo_path)]
        subprocess.run(build_cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
        
        logging.info(f"Executing {image_name} in isolated container...")
        
        run_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--network", "none",
            "--memory=512m",
            "--cpus=1.0",
            "-v", f"{HONEYPOT_DIR}:/secrets:ro",
            image_name
        ]
        
        result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='ignore')
        
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
        
        logging.info(f"Sandbox execution finished with code {returncode}.")
        
    except subprocess.TimeoutExpired:
        logging.warning(f"Execution timed out after 30 seconds. Force killing container...")
        subprocess.run(["docker", "kill", container_name], capture_output=True)
        stdout = "TIMEOUT EXPIRED"
        stderr = "Execution forcefully terminated by hypervisor."
        returncode = 124
    except subprocess.CalledProcessError as e:
        logging.error(f"Docker command failed: {e}")
        stdout = e.stdout
        stderr = e.stderr
        returncode = e.returncode
    finally:
        # Cleanup the image to save space
        logging.info(f"Cleaning up Docker image {image_name}...")
        subprocess.run(["docker", "rmi", "-f", image_name], capture_output=True)
        
    return stdout, stderr, returncode

def escape_markdown(text):
    """Escapes special characters for Telegram Markdown (not V2, but basic backtick protection)."""
    if not text: return ""
    # Just basic protection for common injection/breakage in standard Markdown
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "'")

def generate_final_report(repo_name, engine2_autopsy, sandbox_stdout, sandbox_stderr, error_code):
    """Combines static analysis (Engine 2) and dynamic execution (Engine 3) into a final report."""
    
    # Process Autopsy Result (JSON)
    autopsy = {}
    try:
        autopsy = json.loads(engine2_autopsy)
    except:
        autopsy = {}

    # Define defaults and ensure required_actions is a list
    summary = escape_markdown(autopsy.get('summary', 'No summary available'))
    security_grade = autopsy.get('security_grade', 'Unknown')
    category = autopsy.get('category', 'Unknown')
    win_comp = autopsy.get('windows_compatibility', 'Unknown')
    
    threats = [escape_markdown(str(t)) for t in autopsy.get('threat_report', ['None detected'])]
    actions = [escape_markdown(str(a)) for a in autopsy.get('required_actions', ['None'])]
    
    if not isinstance(actions, list) or len(actions) == 0:
        actions = ['None']

    # Handle empty threat cases gracefully
    if not threats or all(not t.strip() for t in threats):
        threats = ["None detected"]
        
    sec_icon = "❓"
    if security_grade == "Safe": sec_icon = "✅"
    elif security_grade == "Warning": sec_icon = "⚠️"
    elif security_grade == "Critical": sec_icon = "🚨"

    exec_icon = "✅" if error_code == 0 else "⚠️"

    telegram_msg = f"""
🚀 *Repo Analyzer Pipeline Report*
---
📦 *Target:* `{repo_name}`
📝 *Summary:* {summary}
🛡️ *Security:* {security_grade} {sec_icon}
📂 *Category:* {category}
💻 *Win Compatibility:* {win_comp}

🔍 *Threat Report:*
- {chr(10).join(threats)}

⚙️ *Execution Result:* {exec_icon}
- Code: `{error_code}`
- Output: `{escape_markdown(sandbox_stdout[:100])}...`

💡 *Next Action:* {actions[0]}
"""
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 📝 Persistent Master Logging
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Master Markdown Report
    master_md_path = OUTPUT_DIR / "analyzer_reports.md"
    try:
        md_entry = f"## 📅 {timestamp} | Target: `{repo_name}`\n{telegram_msg}\n---\n\n"
        with open(master_md_path, "a", encoding="utf-8") as f:
            f.write(md_entry)
    except Exception as e:
        logging.error(f"Failed to append to master markdown log: {e}")

    # 2. Master JSONL Data (For AI consumption later)
    master_jsonl_path = OUTPUT_DIR / "analyzer_reports.jsonl"
    try:
        log_data = {
            "timestamp": time.time(),
            "date": timestamp,
            "repo_name": repo_name,
            "summary": summary,
            "security_grade": security_grade,
            "category": category,
            "windows_compatibility": win_comp,
            "threat_report": threats,
            "error_code": error_code,
            "next_action": actions[0]
        }
        with open(master_jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error(f"Failed to append to master JSONL log: {e}")
    
    # Dispatch to Telegram
    send_telegram_message(telegram_msg)
    
    return master_md_path

def execute_sandbox(repo_name):
    repo_path = prepare_sandbox(repo_name)
    if not repo_path: return
    
    # Check if we have an autopsy result file from Engine 2
    autopsy_file = OUTPUT_DIR / f"{repo_name}_autopsy_result.json"
    autopsy_content = autopsy_file.read_text(encoding='utf-8') if autopsy_file.exists() else "{}"
    
    stdout, stderr, rcode = build_and_run(repo_path, repo_name)
    report_file = generate_final_report(repo_name, autopsy_content, stdout, stderr, rcode)
    
    logging.info(f"Final report generated and dispatched for {repo_name}.")

if __name__ == "__main__":
    import sys
    # Load .env manually for standalone testing
    try:
        from dotenv import load_dotenv
        load_dotenv(WORKSPACE_DIR / ".env")
    except:
        pass
        
    if len(sys.argv) > 1:
        execute_sandbox(sys.argv[1])
    else:
        logging.error("No repo name provided for sandbox execution.")

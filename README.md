# 🦅 Repo Analyzer Pipeline

[![CI](https://github.com/syj940214/repo-analyzer-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/syj940214/repo-analyzer-pipeline/actions/workflows/ci.yml)

> **The Self-Driving AI Auditor for the Open Source Ecosystem.**

Repo Analyzer Pipeline is an autonomous agentic system designed to monitor, audit, and validate thousands of Open Source Software (OSS) repositories 24/7. It bridges the gap between static code analysis and dynamic sandbox verification using a 3-engine "Hunter" architecture.

---

## 🏛️ Architecture: The 3-Engine Hunter

Repo Analyzer Pipeline operates as a decentralized autonomous facility composed of three specialized engines coordinated by a central Heart (**Engine 0**).

### 🛰️ Engine 1: GitHub Star Radar
- **Role**: Ingestion & Surveillance.
- **Action**: Polls the GitHub Stars API to detect new projects of interest.
- **Output**: Clones targets into the `staging/` environment for immediate triage.

### 🧠 Engine 2: Deep Repo Analyzer (AI Autopsy)
- **Role**: Semantic Intelligence & Security Auditing.
- **Action**: Uses LLM (Codex/GPT-4) to perform an "AI Autopsy." It identifies intent, extracts metadata, and generates a threat report (obfuscation, credential leaks, malicious socket calls).

### 🛡️ Engine 3: Docker Sandbox Executor
- **Role**: Dynamic Verification.
- **Action**: Spins up a highly restricted Python sandbox with `--network none`.
- **Honeypot**: Mounts a fake `/secrets` directory to detect unauthorized file access attempts during runtime.

---

## 🚀 Mission: Securing the OSS Supply Chain
As AI-native development scales, the speed of repository creation outpaces human auditing capacity. Repo Analyzer Pipeline aims to democratize security by providing an autonomous, scale-free auditing layer that ensures every piece of code is vetted before it enters a developer's workflow.

### 🛡️ Core Reliability: Human-in-the-Loop (HITL) Auto-Recovery
Repo Analyzer Pipeline is built as a resilient, event-driven state machine. If an external API (like OpenAI Codex or GitHub Copilot) expires or fails with a `401 Unauthorized`, the pipeline does not crash.
Instead, it triggers a **HITL Auto-Recovery Protocol**:
1. Generates a new OAuth Device Code on the fly.
2. Dispatches a Telegram push notification to the operator with the code.
3. Pauses the specific worker thread and polls asynchronously.
4. Instantaneously resumes the isolated security autopsy the moment the human operator taps "Approve" on their phone.

## 🛠️ Tech Stack
- **Core**: Python 3.10+, Asyncio
- **AI**: GitHub Copilot / OpenAI Codex API integration
- **Infra**: Docker, Git, Telegram Dispatcher
- **State**: Idempotent state management via JSON state-tracking

---

## 🔗 How it Works
1. **Radar** detects a new starred repository.
2. **Analyzer** conducts a surgical AI surgery to find malware or architectural patterns.
3. **Sandbox** attempts to execute the code in an isolated environment to verify behavior.
4. **Dispatcher** sends a formatted security report (JSON/Markdown) to the maintainer's Telegram channel.

---

## ⚖️ License
Repo Analyzer Pipeline is open-source software licensed under the **Apache 2.0 License**.

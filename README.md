<a name="top"></a>
<div align="center">
<img src="./assets/AIHawk.png">

# Auto_Jobs_Applier_AIHawk: Agentic Extension Suite

  ![CI](https://github.com/feder-cr/Auto_Jobs_Applier_AIHawk/actions/workflows/ci.yml/badge.svg)

**🤖🔍 The Intelligent Engine for Autonomous Job Searching.**
*Now extended with multi-agent orchestration support for **OpenClaw** and **ZeroClaw**.*

</div>

## 🌟 Enhanced Agentic Edition

This version of AIHawk has been significantly upgraded to serve as a high-performance **automation engine** for autonomous AI agents. While the base tool handles the "brawn" of browser automation, these extensions provide the "brain" for a fully hands-off career search.

### 🚀 Key Agentic Enhancements

1.  **ZeroClaw & OpenClaw Integration**:
    *   **Stateless Idle Brain**: Supports running as a satellite tool for **ZeroClaw** (Rust-based agent).
    *   **5MB Deep Sleep**: Designed to wake up on trigger, process jobs, and return to an idle state with near-zero resource consumption.
    *   **Webhook Control**: Includes a dedicated `webhook_server.py` to allow remote execution via agentic skills.

2.  **Advanced LLM Orchestration**:
    *   **Model-First Rotation**: Intelligently cycles through multiple Gemini/OpenAI models (Flash -> Pro) before rotating API keys.
    *   **Failover API Keys**: Support for `llm_api_key_2`, `llm_api_key_3`, etc., ensuring 100% uptime during high-volume runs.
    *   **Immediate 429 Handling**: Zero-latency switching when hitting provider rate limits.

3.  **Autonomous Intelligence**:
    *   **Adaptive Language Detection**: Automatically detects job description language (e.g., Russian, German) and responds in kind.
    *   **Recursive Navigation Engine**: A new truly recursive iframe and Shadow DOM traversal system to defeat complex "Easy Apply" layouts.
    *   **Strict Anti-Hallucination**: Mandatory grounding rules to prevent the AI from claiming skills not present in your profile.

---

## Table of Contents

1. [Agentic Architecture](#agentic-architecture)
2. [Features](#features)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Documentation](#documentation)
7. [Contributors](#contributors)
8. [License](#license)

---

## 🧠 Agentic Architecture

This suite is designed to be the execution layer for a multi-agent system:

*   **The Orchestrator (OpenClaw/ZeroClaw)**: Handles high-level strategy, goal setting, and long-term memory via binary vector storage.
*   **The Engine (AIHawk Extension)**: Handles the tactical execution (Selenium, Telethon, PDF generation).
*   **The Bridge (Webhook)**: Connects the two via a secure local API.

For detailed information on the low-level memory layers used by the companion agent, see [zeroclaw_architecture.md](zeroclaw_architecture.md).

---

## Features

1.  **Parallel Execution Mode**: Run LinkedIn, Telegram, and Career Website bots simultaneously using Python threading.
2.  **Interactive Telegram Command Menu**: Manual control over scanning vs. applying to manage your digital footprint.
3.  **Dynamic Resume Tailoring**: On-the-fly PDF generation specifically matched to the recruiter's language and requirements.
4.  **Intelligent Filtering**: Automatic duplicate detection and anti-spam protection across different channels.

---

## Installation

1. **Clone the extension suite:**
   ```bash
   git clone https://github.com/mcnugets/Auto_Jobs_Applier_AIHawk_local.git
   cd Auto_Jobs_Applier_AIHawk
   ```

2. **Setup Environment:**
   ```bash
   chmod +x aihawk
   ./aihawk  # Automatically handles venv and dependencies
   ```

---

## Configuration

### 1. secrets.yaml (Rotational Keys)
```yaml
llm_api_key: "PRIMARY_KEY"
llm_api_key_2: "BACKUP_KEY"
telegram_api_id: "..."
```

### 2. config.yaml (Model List)
```yaml
llm_model: "gemini-2.0-flash, gemini-1.5-flash, gemini-1.5-pro"
```

---

## Usage

### Run as a Standalone Suite
```bash
python main.py
```
Select **Option 4 (All)** to trigger the high-concurrency parallel application mode.

### Run as an Agent Satellite (Webhook Mode)
```bash
python webhook_server.py
```
Your agent (ZeroClaw/OpenClaw) can now trigger applications via POST requests to `:5050/apply`.

---

## Contributors

- [feder-cr](https://github.com/feder-cr) - Creator of the original AIHawk engine.
- [mcnugets](https://github.com/mcnugets) - Lead developer of the Agentic Extension Suite.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This tool is for educational purposes. Use automated application tools responsibly and at your own risk.

[Back to top 🚀](#top)

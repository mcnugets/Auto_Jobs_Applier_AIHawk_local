<a name="top"></a>
<div align="center">

# JobAnal: The Job Applying Engine

**🤖🚀 An Autonomous, Multi-Agent Ecosystem for High-Performance Career Automation.**



</div>

## 🌐 Overview

**JobAnal** is a next-generation job application engine designed for the era of autonomous AI agents. Unlike standard automation tools, JobAnal is built to be the "execution layer" for intelligent brains like **OpenClaw** and **ZeroClaw**.

It leverages a high-concurrency Python core for browser automation and a Rust-based orchestration layer for long-term memory and system-level efficiency.

---

## 🌟 Key Features (The JobAnal Advantage)

### 1. **Agentic Orchestration (The "Idle Brain")**
JobAnal is specifically optimized to run as a satellite for **ZeroClaw**. 
*   **Deep Sleep State**: Consumes only ~5MB of RAM while waiting for triggers.
*   **Persistent Binary Memory**: Uses low-level binary vector storage to maintain your career context and application history without bloat.
*   **Webhook Interface**: Full remote-control capability via a secure local API.

### 2. **Multi-Channel Parallelism**
Why apply one by one? JobAnal's engine runs multiple channels simultaneously:
*   **Concurrent Execution**: LinkedIn, Telegram, and Career Portals run in parallel threads.
*   **Interactive Control**: A CLI-based command menu allows you to manage "Scouts" (scanning) and "Snipers" (applying) independently.

### 3. **Smart Failover & LLM Resilience**
Built for high-volume users who can't afford to stop:
*   **Model-First Rotation**: Automatically cycles through all available model tiers (e.g., Gemini Flash -> Pro) to maximize free quotas.
*   **Rotational API Keys**: Seamlessly swaps between multiple backup API keys the millisecond a rate limit (429) is detected.

### 4. **Adaptive Context Engineering**
*   **Language Mirroring**: Automatically detects the language of the job description (Russian, German, English, etc.) and generates tailored responses in the recruiter's native tongue.
*   **Recursive Navigation**: A custom navigation engine that uses recursive iframe and Shadow DOM traversal to defeat the most complex "Easy Apply" forms.
*   **Anti-Hallucination Grounding**: Strict technical rules ensure the AI never claims a skill that isn't in your core profile.

---

## 🛠️ Architecture

JobAnal follows a "Brain & Brawn" architecture:
*   **Brain**: ZeroClaw/OpenClaw (Strategic planning & long-term memory).
*   **Brawn**: JobAnal Core (Tactical Selenium automation & PDF generation).
*   **Bridge**: JobAnal Webhook (High-speed local communication).

---

## 🚀 Getting Started

### 1. Installation
```bash
git clone https://github.com/mcnugets/JobAnal.git
cd JobAnal
chmod +x aihawk
./aihawk  # Initializes the unified environment
```

### 2. Configure Your Profile
Update `data_folder/plain_text_resume.yaml` with your details. This serves as the "Source of Truth" for the engine.

### 3. Execution
```bash
# Start the full engine
python main.py

# Start the Webhook for Agent control
python webhook_server.py
```

---

## 👨‍💻 Engineering & Contributions

JobAnal is an advanced distribution of the AIHawk automation core, re-engineered for agentic autonomy and multi-threaded performance.

*   **Lead Architect**: [mcnugets](https://github.com/mcnugets)
*   **Core Logic**: Based on the AIHawk Engine.

---

## 📄 License & Disclaimer

JobAnal is licensed under the MIT License. 

**Disclaimer**: This is a powerful automation engine. Use it responsibly and in accordance with the terms of service of the platforms you interact with.

[Back to top 🚀](#top)

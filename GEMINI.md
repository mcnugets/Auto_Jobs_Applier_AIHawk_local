# Auto_Jobs_Applier_AIHawk — Project Intelligence

## Project Overview

AI-powered job application automation tool. Orchestrates web automation (Selenium),
multi-provider LLM interaction (OpenAI, Claude, Ollama, Gemini via Langchain), dynamic
resume/cover letter generation, and multi-platform job application submission.

**Python 3.10+ | Selenium | Langchain | PyYAML | Loguru | Click | ReportLab**

---

## Architecture Map

```
main.py                          ← CLI entry point (Click), config validation, orchestration
src/
  aihawk_authenticator.py        ← Platform login/session management
  aihawk_bot_facade.py           ← Simplified interface to bot subsystems
  aihawk_easy_applier.py         ← Core apply loop: navigate → fill form → upload → submit
  aihawk_job_manager.py          ← Job search, filtering, deduplication, tracking
  job.py                         ← Job data model
  job_application_profile.py    ← User profile data model
  strings.py                     ← Prompt templates (edit here first before llm_manager)
  llm/
    llm_manager.py               ← ALL LLM calls go through here. Handles: provider
                                    abstraction, prompt templating, retry/rate-limit,
                                    batching, caching, response parsing
  adapters/
    linkedin_adapter.py          ← LinkedIn Easy Apply specific logic
    career_website_adapter.py    ← Generic career site logic
    telegram_adapter.py          ← Telegram channel integration
data_folder/
  secrets.yaml                   ← API keys — NEVER read or log contents, NEVER commit
  config.yaml                    ← Job search params + LLM config
  plain_text_resume.yaml         ← User resume data (structured)
  output/                        ← Runtime outputs: open_ai_calls.json, data.json,
                                    failed.json — check these when debugging LLM issues
generated_cv/                    ← Dynamically built resumes and cover letters
tests/                           ← pytest test suite
```

---

## Critical Conventions — Read Before Touching Anything

### LLM Calls
- **ALL LLM interactions must go through `src/llm/llm_manager.py`.** Never instantiate
  a model client directly in feature code.
- Prompt templates live in `src/strings.py` or inside `llm_manager.py`. Check both
  before writing a new prompt — it likely already exists.
- `llm_manager.py` provides: retry logic, rate-limit handling, response caching,
  call logging to `output/open_ai_calls.json`. Do not bypass this.
- When adding a new LLM use case: add the prompt to `strings.py`, add the method to
  `llm_manager.py`, call it from feature code. Never inline prompts in adapters or applier.

### Selenium / Web Automation
- DOM structures on LinkedIn and career sites change frequently. Never hardcode XPaths
  or CSS selectors as bare strings — use named constants or a locator registry.
- Always wrap Selenium interactions in explicit waits (`WebDriverWait`) with a timeout.
  Never use `time.sleep()` for synchronization.
- Assume any element interaction can throw `StaleElementReferenceException` or
  `NoSuchElementException`. Handle these explicitly with retry or fallback logic.
- Before modifying any adapter, run it against a live session to confirm current DOM
  behavior. What worked last month may be broken today.
- Log every form field interaction at DEBUG level using `loguru`. This is essential for
  diagnosing silent failures in the apply loop.

### Configuration and Secrets
- `secrets.yaml` contains API keys. **Never log, print, or expose its contents.**
- All config access must go through the validated config loader in `main.py`.
  Do not open YAML files ad-hoc in feature modules.
- When adding a new config field: add it to the example in `data_folder_example/`,
  add validation in `main.py`, and document it in README.

### Logging
- Use `loguru` everywhere. No `print()` statements in non-CLI code.
- Log levels: DEBUG for step-by-step automation trace, INFO for milestones,
  WARNING for recoverable issues, ERROR for failures that skip a job,
  CRITICAL for failures that halt the bot.
- Failed applications must be written to `output/failed.json` with reason.

### Testing
- Test framework: `pytest`. Tests in `tests/` directory.
- Run tests with: `pytest tests/ -v`
- Before any PR or significant change: run full test suite and show output.
- LLM calls in tests must be mocked. Never make real API calls in test code.
- Selenium tests require a real or mocked WebDriver — document which.

---

## Build and Run Commands

```bash
# Setup
python3 -m venv virtual && source virtual/bin/activate
pip install -r requirements.txt

# Run (main modes)
python main.py                                  # full run, dynamic resume
python main.py --resume /path/to/resume.pdf     # with static PDF
python main.py --collect                        # collect jobs only, no apply
python main.py --channel linkedin               # specific channel

# Test
pytest tests/ -v
pytest tests/ -v -k "test_name"                # single test
pytest tests/ --tb=short                       # compact traceback

# Lint / style check
flake8 src/ --max-line-length=120
```

---

## Common Failure Modes — Check These First

| Symptom | Where to Look |
|---|---|
| LLM not responding / rate limit | `output/open_ai_calls.json`, `llm_manager.py` retry config |
| Form field not filled | `aihawk_easy_applier.py` DEBUG logs, check for DOM change in adapter |
| Auth failing | `aihawk_authenticator.py`, check session/cookie expiry |
| Wrong resume generated | `plain_text_resume.yaml` data, `lib_resume_builder_AIHawk` |
| Job appearing in failed.json | Read the `reason` field, cross-check with loguru output |
| Config validation error | `main.py` validator, compare against `data_folder_example/` |

---

## Agentic Task Rules for This Project

### Before touching any file:
1. Read the relevant module AND its callers (use grep/search to find all call sites).
2. Check `strings.py` and `llm_manager.py` if the task touches LLM behavior.
3. Check `output/` files if the task involves debugging a runtime failure.

### For Selenium changes:
1. Identify the current locators being used.
2. Confirm whether the target DOM element still matches (describe what you'd verify).
3. Make changes with explicit fallback handling.
4. Note that live verification requires a real browser session — flag this if you cannot run it.

### For LLM prompt changes:
1. Read the existing prompt in `strings.py` first.
2. Show the before/after diff of the prompt.
3. Explain what behavior the change is intended to produce.
4. Identify which `llm_manager.py` method calls it and confirm the response parser
   still handles the new output format.

### For new adapters:
1. Follow the structure of `linkedin_adapter.py` exactly.
2. Implement the same interface methods — do not invent a new contract.
3. Register the adapter in `aihawk_bot_facade.py`.
4. Add a test file in `tests/` before marking complete.

---

## What "Done" Means in This Project

A task is complete when:
- [ ] The code change is made
- [ ] `pytest tests/ -v` passes (show output)
- [ ] `flake8` reports no new errors
- [ ] Loguru output shows expected INFO/DEBUG trace for the affected flow
- [ ] If LLM-related: `output/open_ai_calls.json` shows the call was made and cached
- [ ] If Selenium-related: the form interaction completes without exception in a real or
      mocked session
- [ ] `output/failed.json` does not contain new entries caused by the change

---

## Files That Are Off-Limits Without Explicit Instruction

- `data_folder/secrets.yaml` — never read, modify, or reference contents
- `data_folder/config.yaml` — read-only for understanding; propose changes, don't apply
- `generated_cv/` — output directory, never modify programmatically outside the CV builder
- `requirements.txt` — only modify when adding a dependency, always pin versions

---

## Project-Specific Memory

- The LLM abstraction layer (`llm_manager.py`) is the most complex module. Changes here
  have wide blast radius — test thoroughly and check all provider paths.
- LinkedIn DOM changes are the #1 source of production failures. Treat all LinkedIn
  locators as fragile until proven stable.
- The `plain_text_resume.yaml` schema is load-bearing — the resume builder and LLM
  prompts both depend on its exact structure. Do not rename or restructure fields.
- Contributions must target the `release` branch per `CONTRIBUTING.md`.

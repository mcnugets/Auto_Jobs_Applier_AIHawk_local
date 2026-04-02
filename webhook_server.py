# webhook_server.py
import subprocess
import threading
import json
import os
from pathlib import Path
from flask import Flask, request, jsonify
import requests
from loguru import logger

app = Flask(__name__)

# Configurable via environment variables
SECRET = os.getenv("AIHAWK_SECRET", "changeme")
OC_URL = os.getenv("OPENCLAW_WEBHOOK_URL", "")
OC_TOKEN = os.getenv("OPENCLAW_TOKEN", "")

@app.route("/apply", methods=["POST"])
def trigger():
    """Endpoint for OpenClaw to trigger job applications."""
    if request.headers.get("x-aihawk-secret") != SECRET:
        logger.warning("Unauthorized access attempt to /apply")
        return jsonify({"error": "unauthorized"}), 401
    
    data = request.json or {}
    logger.info(f"Received application trigger: {data}")
    
    # Patch config.yaml on the fly from request params
    try:
        _patch_config(
            positions=data.get("positions", ["AI Backend Engineer"]),
            locations=data.get("locations", ["United Kingdom"]),
            max_jobs=data.get("max_jobs", 30)
        )
    except Exception as e:
        logger.error(f"Failed to patch config: {e}")
        return jsonify({"error": f"Failed to update configuration: {str(e)}"}), 500

    # Run AIHawk in a separate thread
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "message": "AIHawk application process initiated."}), 200

def _patch_config(positions, locations, max_jobs):
    """Updates the config.yaml file with parameters from the webhook."""
    import yaml
    cfg_path = Path("data_folder/config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found at {cfg_path}")
        
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    
    # Update fields
    cfg["positions"] = positions
    cfg["locations"] = locations
    if "job_applicants_threshold" not in cfg:
        cfg["job_applicants_threshold"] = {}
    cfg["job_applicants_threshold"]["max_applicants"] = max_jobs
    
    with open(cfg_path, "w", encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False)
    logger.debug("Configuration patched successfully.")

def _run():
    """Executes the AIHawk main loop."""
    logger.info("Starting AIHawk subprocess...")
    try:
        # Run main.py as a subprocess
        result = subprocess.run(
            ["python3", "main.py"],
            capture_output=True, 
            text=True, 
            timeout=7200 # 2 hour timeout
        )
        
        # Parse results and notify
        stats = _get_stats()
        summary = f"✅ AIHawk Finished - Applied: {stats['success']}, Failed: {stats['failed']}, Skipped: {stats['skipped']}"
        logger.info(summary)
        _notify(summary)
        
    except subprocess.TimeoutExpired:
        logger.warning("AIHawk process timed out.")
        _notify("⚠️ AIHawk timed out after 2 hours.")
    except Exception as e:
        logger.error(f"AIHawk subprocess error: {e}")
        _notify(f"❌ AIHawk Error: {str(e)}")

def _get_stats() -> dict:
    """Reads the latest output JSON files to gather statistics."""
    base = Path("data_folder/output")
    counts = {}
    for key in ["success", "failed", "skipped"]:
        f = base / f"{key}.json"
        try:
            if f.exists():
                with open(f, 'r', encoding='utf-8') as file:
                    counts[key] = len(json.load(file))
            else:
                counts[key] = 0
        except Exception:
            counts[key] = "?"
    return counts

def _notify(msg: str):
    """Sends a notification back to OpenClaw."""
    if not OC_URL:
        logger.debug("No OpenClaw webhook URL configured, skipping notification.")
        return
        
    try:
        response = requests.post(
            OC_URL,
            headers={"x-openclaw-token": OC_TOKEN},
            json={"message": msg, "deliver": True},
            timeout=10
        )
        logger.debug(f"Notification sent to OpenClaw. Status: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send notification to OpenClaw: {e}")

if __name__ == "__main__":
    logger.info("Starting AIHawk Webhook Server on port 5050...")
    app.run(host="0.0.0.0", port=5050)

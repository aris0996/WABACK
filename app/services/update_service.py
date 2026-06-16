import subprocess
import os
import threading
import time
from pathlib import Path

from flask import current_app

from .log_service import log_event


def _repo_root():
    return str(Path(current_app.root_path).resolve().parent)


def _run(command, timeout=None):
    completed = subprocess.run(
        command,
        cwd=_repo_root(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout or current_app.config["AUTO_UPDATE_TIMEOUT"],
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "output": completed.stdout.strip()[-8000:],
    }


def _ensure_success(result):
    if result["returncode"] != 0:
        raise RuntimeError(f"{result['command']} failed: {result['output']}")


def get_git_status():
    repo_path = Path(_repo_root())
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return {
            "clean": False,
            "branch": "",
            "repo_root": str(repo_path),
            "git_available": False,
            "status": {
                "command": "git status --porcelain",
                "returncode": 128,
                "output": ".git directory not found. Mount or run the app from a git clone.",
            },
        }
    status = _run(["git", "status", "--porcelain"])
    branch = _run(["git", "branch", "--show-current"])
    return {
        "clean": status["returncode"] == 0 and not status["output"],
        "branch": branch["output"] if branch["returncode"] == 0 else "",
        "repo_root": str(repo_path),
        "git_available": True,
        "status": status,
    }


def schedule_worker_restart(delay_seconds=2):
    def _restart():
        time.sleep(delay_seconds)
        os._exit(0)

    thread = threading.Thread(target=_restart, daemon=True)
    thread.start()


def auto_update():
    safe_directory = _run(["git", "config", "--global", "--add", "safe.directory", _repo_root()])
    _ensure_success(safe_directory)

    before = _run(["git", "rev-parse", "--short", "HEAD"])
    _ensure_success(before)

    status = get_git_status()
    if not status["clean"]:
        raise RuntimeError(
            "Working tree is not clean. Auto update stopped to prevent file conflicts. "
            "Commit, stash, or untrack local runtime files first."
        )

    configured_branch = current_app.config["AUTO_UPDATE_BRANCH"].strip()
    current_branch = status["branch"]
    if configured_branch and configured_branch != current_branch:
        raise RuntimeError(f"Current branch is {current_branch}, expected {configured_branch}.")

    fetch = _run(["git", "fetch", "--prune", "origin"])
    _ensure_success(fetch)

    branch = configured_branch or current_branch
    pull = _run(["git", "pull", "--ff-only", "origin", branch])
    _ensure_success(pull)

    after = _run(["git", "rev-parse", "--short", "HEAD"])
    _ensure_success(after)

    deploy_result = None
    deploy_command = current_app.config["AUTO_UPDATE_COMMAND"].strip()
    if deploy_command:
        deploy_result = _run(["sh", "-lc", deploy_command])
        _ensure_success(deploy_result)

    result = {
        "before": before["output"],
        "after": after["output"],
        "branch": branch,
        "updated": before["output"] != after["output"],
        "pull_output": pull["output"],
        "deploy_output": deploy_result["output"] if deploy_result else "",
        "worker_restart_scheduled": False,
    }
    if result["updated"] and current_app.config["AUTO_UPDATE_RESTART_WORKER"] and not deploy_command:
        schedule_worker_restart()
        result["worker_restart_scheduled"] = True
    log_event("INFO", "GitHub auto update completed", result)
    return result

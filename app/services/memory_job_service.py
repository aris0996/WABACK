import json
import threading

from flask import current_app

from ..db import execute, get_db, get_setting, query_all, query_one
from . import memory_service, waha_service
from .log_service import log_event


def _batch_size():
    try:
        return max(1, int(get_setting("memory_batch_size", "50")))
    except ValueError:
        return 50


def _set_job(job_id, **fields):
    assignments = [f"{key} = ?" for key in fields]
    values = list(fields.values())
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    execute(f"UPDATE memory_jobs SET {', '.join(assignments)} WHERE id = ?", tuple(values))


def create_memory_job(contact_id, job_type):
    cur = execute(
        """
        INSERT INTO memory_jobs (contact_id, job_type, status, stage)
        VALUES (?, ?, 'queued', 'Queued')
        """,
        (contact_id, job_type),
    )
    job_id = cur.lastrowid
    app = current_app._get_current_object()
    thread = threading.Thread(target=_run_job_thread, args=(app, job_id), daemon=True)
    thread.start()
    return job_id


def get_memory_job(job_id):
    row = query_one("SELECT * FROM memory_jobs WHERE id = ?", (job_id,))
    if not row:
        return None
    item = dict(row)
    if item.get("result_json"):
        try:
            item["result"] = json.loads(item["result_json"])
        except json.JSONDecodeError:
            item["result"] = item["result_json"]
    return item


def _run_job_thread(app, job_id):
    with app.app_context():
        try:
            _run_job(job_id)
        except Exception as exc:
            _set_job(
                job_id,
                status="failed",
                stage="Failed",
                error=str(exc),
                finished_at="CURRENT_TIMESTAMP",
            )
            # Fix timestamp assignment because CURRENT_TIMESTAMP as param is literal.
            get_db().execute("UPDATE memory_jobs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            get_db().commit()
            log_event("ERROR", "Memory job failed", {"job_id": job_id, "error": str(exc)})


def _run_job(job_id):
    job = query_one("SELECT * FROM memory_jobs WHERE id = ?", (job_id,))
    if not job:
        return
    contact_id = job["contact_id"]
    job_type = job["job_type"]
    _set_job(job_id, status="running", stage="Starting", progress=0)

    sync_result = None
    if job_type == "generate_all":
        _set_job(job_id, stage="Syncing WAHA")
        limit = int(get_setting("waha_history_sync_limit", "300") or 300)
        sync_result = waha_service.sync_contact_messages_from_waha(contact_id, limit=limit)
        log_event("INFO", "WAHA history synced before memory job", {"job_id": job_id, "contact_id": contact_id, **sync_result})
        messages = memory_service.get_all_messages_for_memory(contact_id)
        source_mode = "manual_all"
    elif job_type == "generate_new":
        messages = memory_service.get_new_messages_for_memory(contact_id)
        source_mode = "manual_new"
    else:
        raise ValueError(f"Unknown memory job type: {job_type}")

    if not messages:
        raise ValueError("Tidak ada pesan untuk generate memory.")

    batch_size = _batch_size()
    batches = [messages[i : i + batch_size] for i in range(0, len(messages), batch_size)]
    _set_job(job_id, total=len(batches), stage="Extracting", progress=0)

    old = query_one("SELECT memory_json FROM memories WHERE contact_id = ?", (contact_id,))
    current_memory = json.loads(old["memory_json"]) if old else None
    db = get_db()
    processed_to_id = messages[-1]["id"]

    for index, batch in enumerate(batches, start=1):
        _set_job(job_id, stage=f"Extracting batch {index}/{len(batches)}", progress=index - 1)
        candidate = memory_service.extract_memory_candidate(batch)
        from_id = batch[0]["id"]
        to_id = batch[-1]["id"]
        db.execute(
            """
            INSERT INTO memory_candidates
            (contact_id, source_mode, from_message_id, to_message_id, memory_json, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (contact_id, source_mode, from_id, to_id, json.dumps(candidate, ensure_ascii=False), 0.8),
        )
        db.commit()
        if current_memory:
            _set_job(job_id, stage=f"Merging batch {index}/{len(batches)}")
            current_memory = memory_service.merge_memory(current_memory, candidate)
        else:
            current_memory = candidate
        _set_job(job_id, progress=index)

    _set_job(job_id, stage="Saving")
    final_memory = memory_service.save_memory(contact_id, current_memory, source_mode)
    memory_service.update_memory_checkpoint(contact_id, processed_to_id)
    result = {"memory": final_memory, "processed_messages": len(messages), "sync": sync_result}
    _set_job(
        job_id,
        status="success",
        stage="Success",
        result_json=json.dumps(result, ensure_ascii=False),
        progress=len(batches),
        total=len(batches),
    )
    get_db().execute("UPDATE memory_jobs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
    get_db().commit()
    log_event("INFO", "Memory job completed", {"job_id": job_id, "contact_id": contact_id, "type": job_type})

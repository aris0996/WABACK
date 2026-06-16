import json


DEFAULT_MEMORY = {
    "nama": "none",
    "panggilan": "none",
    "pekerjaan": "none",
    "sekolah": "none",
    "lokasi": "none",
    "minat": [],
    "kebutuhan": [],
    "gaya_bahasa": "none",
    "catatan_penting": [],
    "larangan": [],
    "hubungan_dengan_saya": "none",
    "last_summary": "none",
}


def normalize_memory(value):
    if not value:
        return DEFAULT_MEMORY.copy()
    if isinstance(value, str):
        value = json.loads(value)
    merged = DEFAULT_MEMORY.copy()
    for key in merged:
        if key in value and value[key] not in (None, ""):
            merged[key] = value[key]
    return merged

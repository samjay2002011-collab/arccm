"""إصدار CMSync — الوصف والتحميل، عشان النسخة تتحدّث من غير ما حد يحملها من الأول.

السيرفر هو مصدر النسخة: الملف `CMSync.exe` اللي في جذر المشروع (أو FAHMY_AGENT_EXE)
هو اللي بيتقدّم للأجن وللصفحة. الأجن بيقارن البصمة بتاعته ببصمة الملف على السيرفر،
ولو اختلفوا ينزّله ويبدّل نفسه — فـ"ابديت" عند أي حد معناها زرار واحد مش تحميل من جديد.

البصمة sha256 مش رقم إصدار: مفيش حاجة تتكتب أو تتنسى عند كل بيلد، وأي ملف مختلف
فعلاً بيتكشف. تاريخ البناء (mtime) هو العرضي للبني آدم.
"""
import hashlib
import os
import time

from . import config

EXE_NAME = "CMSync.exe"
CHUNK = 1 << 20
_cache = {}  # (path, size, mtime) -> sha256


def exe_path():
    env_path = os.environ.get("FAHMY_AGENT_EXE")
    if env_path and os.path.isfile(env_path):
        return env_path
    frontend_dl = os.path.join(config.FRONTEND_DIR, "download", EXE_NAME)
    if os.path.isfile(frontend_dl):
        return frontend_dl
    root_exe = os.path.join(config.ROOT, EXE_NAME)
    if os.path.isfile(root_exe):
        return root_exe
    return frontend_dl


def sha256(path):
    st = os.stat(path)
    key = (path, st.st_size, int(st.st_mtime))
    got = _cache.get(key)
    if got:
        return got
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    _cache.clear()
    _cache[key] = value = digest.hexdigest()
    return value


def brief(path=None):
    """وصف النسخة المتاحة على السيرفر — size/built_at للعرض و sha256 للمقارنة."""
    path = path or exe_path()
    try:
        st = os.stat(path)
    except OSError:
        return {"present": False, "filename": os.path.basename(path), "path": path}
    return {"present": True, "filename": os.path.basename(path), "path": path,
            "size": st.st_size, "built_at": int(st.st_mtime),
            "built_at_text": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "sha256": sha256(path)}

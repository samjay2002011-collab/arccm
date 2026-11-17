"""بوابة الأجن المحلي — قبول التوكن من برنامج CMSync بدون لصق يدوي.

الأجن بيبعت التوكن من نفس الجهاز. القبول مش مفتوح:
  1) الطلب لازم يجي من 127.0.0.1 صافي — من غير أي هيدر بروكسي، لأن النفق العام
     (cloudflared) بيوصل عند السيرفر بعنوان 127.0.0.1 كمان، ولو اكتفينا بده كان
     أي زبون على الإنترنت يقدر يسجّل حسابات في اللوحة.
  2) لازم ييجي معاه مفتاح ملف `data/agent_secret.txt` في هيدر X-Fahmy-Agent —
     وده بيقفل أي صفحة ويب تحاول تعمل POST للوحة من المتصفح.
"""
import hmac
import os
import secrets

from . import auth, config

SECRET_FILE = os.path.join(config.DATA_DIR, "agent_secret.txt")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def secret():
    """مفتاح مشترك بيتولّد مرة واحدة على الجهاز — الأجن بيقرأ نفس الملف."""
    try:
        with open(SECRET_FILE, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(24)
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as fh:
            fh.write(value)
    except OSError:
        pass
    return value


def is_local(request):
    """loopback صافي — القيد ده بقى ملك `auth` عشان النفق بييجي من 127.0.0.1 كمان."""
    return auth.is_local(request)


def authorized(request, presented):
    return is_local(request) and hmac.compare_digest(str(presented or ""), secret())

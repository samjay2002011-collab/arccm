"""الموقع مفتوح: مفيش كلمة مرور ولا جلسات ولا صفحة دخول.

الوحيد اللي فضل هنا هو فحص الـ loopback الصافي، لأن بوابة الأجن المحلي
(backend/agent_link.py) بتعتمد عليه عشان تفرّق بين CMSync اللي على نفس الجهاز
وأي طلب جاي من نفق عام بيوصل السيرفر بـ 127.0.0.1 برضه.
"""

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _clean(host):
    return (host or "").replace("::ffff:", "").strip()


def is_local(request):
    """loopback حقيقي: من 127.0.0.1 ومن غير أي هيدر بروكسي — أي نفق بيبوظ القيد ده."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        return False
    return _clean(getattr(getattr(request, "client", None), "host", "")) in LOCAL_HOSTS

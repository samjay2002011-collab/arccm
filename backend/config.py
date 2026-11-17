"""إعدادات المشروع المحلي — كل المسارات مطلقة عشان يشتغل من أي مجلد تشغيل."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ASSETS_DIR = os.path.join(ROOT, "assets")
ITEM_ASSETS_DIR = os.path.join(ASSETS_DIR, "items")
FRONTEND_DIR = os.path.join(ROOT, "frontend")

DB_FILE = os.path.join(DATA_DIR, "rampart_local.db")
STATUS_FILE = os.path.join(DATA_DIR, "sync_status.json")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")

LEGACY_TOKEN_FILE = r"C:\Users\Administrator\Desktop\ll\rampart_token.txt"
TOKEN_FILE = os.environ.get("RAMPART_LOCAL_TOKEN", os.path.join(ROOT, "rampart_token.txt"))

# مصدر بيانات المخزن: pioneer = بوابة Embark الرسمية مباشرة، rampart = الوسيط القديم.
DATA_SOURCE = os.environ.get("FAHMY_DATA_SOURCE", "pioneer").strip().lower()

# مسار النقل الرسمي على بوابة Embark — مثبت ومتحقق منه مباشرة على الحساب.
# يقدر يتغير من البيئة، وفاضي = المسار الافتراضي في pioneer_write.
PIONEER_MOVE_ENDPOINT = os.environ.get(
    "PIONEER_MOVE_ENDPOINT", "/v1/pioneer/v1/batch-operation").strip()

# مفيش قفل بكلمة مرور: الموقع بيفتح مباشرة على / من أي جهاز بيوصل البورت.

# الارتباط بـ rampart.su متوقف بقرار من المستخدم: كل داتا المخزن بتقرأ وتكتب على
# بوابة Embark الرسمية مباشرة. المسارات تحت مستخدمة لعرض شكل الطلب في الوضع القديم بس.
RAMPART_ENABLED = os.environ.get("FAHMY_RAMPART", "off").strip().lower() in ("1", "on", "true", "yes")

UPSTREAM_API = os.environ.get("RAMPART_LOCAL_UPSTREAM", "https://api.rampart.su").rstrip("/")
UPARSE_URL_PATH = "/inventory/parsed"
EMBARK_LIST_PATH = "/auth/embark"
ACTIVATE_PATH = "/auth/embark/{account_id}/activate"
TRADERS_PATH = "/traders/offers"
ASSET_URL = UPSTREAM_API + "/assets/{filename}"

# احتياطي لو /auth/me مش reachable — الحد الحقيقي بيقرأ من البروفايل (15 في حسابنا).
ACCOUNT_LIMIT = int(os.environ.get("RAMPART_LOCAL_ACCOUNT_LIMIT", "15"))

# 0.0.0.0 = اللوحة بتقبل اتصال من برّه الجهاز (ده اللي بيحتاجه النفق العام أو صديق
# في نفس الشبكة). الموقع مفتوح من غير كلمة مرور، فأي حد بيوصل البورت بيدخل.
# للرجوع لجهازك لوحدك: RAMPART_LOCAL_HOST=127.0.0.1
HOST = os.environ.get("RAMPART_LOCAL_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("RAMPART_LOCAL_PORT") or "8001")
REFRESH_SECONDS = int(os.environ.get("RAMPART_LOCAL_REFRESH", "15"))
HTTP_TIMEOUT = 30
MAX_SNAPSHOT_KEEP = 20

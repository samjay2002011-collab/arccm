import requests
import time
import json
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

# إعدادات السيرفر المستهدف
API_BASE_URL = "https://api-gateway.europe.es-pio.net"
TARGET_ENDPOINT = "/v1/pioneer/inventory/v1/mutate" # أو المسار الذي اكتشفته

# إعدادات محاكاة العميل الرسمي (Client Emulation)
# هذه القيم يجب استخراجها من Fiddler عند نقل عنصر في اللعبة
HEADERS = {
    "User-Agent": "ArcRaiders/1.0.0 (Windows 10.0.19045; x64)", # يجب أن تطابق اللعبة تماماً
    "Content-Type": "application/json", # أو application/grpc-web+proto إذا كان gRPC
    "Accept": "application/json",
    "X-API-Key": "YOUR_GAME_API_KEY_FROM_GAME_FILE", # مفتاح اللعبة المخفي
    "Authorization": "Bearer YOUR_ACCESS_TOKEN", # التوكن الخاص بحسابك
    "X-Client-Id": "arc-raiders-client-id", # معرف العميل
    "X-Request-ID": "gen-random-uuid-here", # UUID فريد لكل طلب
    "Connection": "keep-alive",
    # إضافة هيدرات إضافية إذا كانت موجودة في اللعبة
    "X-Envoy-Expected-Routes": "pioneer-inventory" 
}

# إعداد Session مع إعادة المحاولة التلقائية (للتعامل مع الـ 500 و 404)
session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[408, 429, 500, 502, 503, 504],
    allowed_methods=["POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

def send_inventory_request(item_id, source_slot, target_slot):
    """
    يرسل طلب نقل العنصر بنفس طريقة اللعبة.
    """
    # بناء جسم الطلب (Body) - يجب أن يطابق بروتوكول اللعبة تماماً
    # إذا كانت اللعبة تستخدم Protobuf، يجب تحويل البيانات لـ Base64 أو Bytes
    payload = {
        "item_id": item_id,
        "source": {
            "type": "inventory",
            "slot_index": source_slot
        },
        "target": {
            "type": "stash",
            "slot_index": target_slot
        },
        "timestamp": int(time.time() * 1000)
    }
    
    # إذا كان الطلب يحتاج لـ gRPC (Protobuf)، استبدل الـ JSON بـ Bytes المحولة
    # data = payload.to_bytes() # مثال
    
    try:
        response = session.post(
            f"{API_BASE_URL}{TARGET_ENDPOINT}",
            headers=HEADERS,
            json=payload, # أو data=payload إذا كان Bytes
            timeout=10
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            return {"success": True, "message": "تم النقل بنجاح", "data": response.json()}
        elif response.status_code == 404:
            return {"success": False, "message": "المسار لا يزال مغلقاً أو خاطئاً"}
        elif response.status_code == 401:
            return {"success": False, "message": "خطأ في التوكن أو المفتاح"}
        else:
            return {"success": False, "message": f"خطأ غير متوقع: {response.status_code}"}
            
    except Exception as e:
        return {"success": False, "message": str(e)}

# دالة للمراقبة المستمرة (Watchdog)
def monitor_and_retry():
    print("بدء مراقبة المسار ومحاولة النقل...")
    while True:
        # محاولة التنفيذ
        result = send_inventory_request("ITEM_123", 5, 10)
        if result["success"]:
            print("تم استعادة الاتصال!")
            break
        else:
            print(f"المحاولة فشلت: {result['message']}. إعادة المحاولة بعد 30 ثانية...")
            time.sleep(30)

if __name__ == "__main__":
    monitor_and_retry()

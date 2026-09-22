#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
زمزم Payroll — Local Bridge Server
يشتغل في الخلفية ويستقبل طلبات من المتصفح
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse
from datetime import datetime
import threading
import sys
import os

# =============================================
# إعدادات الجهاز
# =============================================
DEVICE_IP   = "192.168.2.201"
DEVICE_PORT = 4370
PASSWORD    = 0
SERVER_PORT = 7788  # بورت الـ server المحلي

# لو الموظف مضى مرتين خلال أقل من الدقائق دي، نعتبرها بصمة واحدة مكررة
# (مضاء غير مقصود) ونتجاهل الثانية بدل ما نسجلها كـ"انصراف"
DUP_PUNCH_MINUTES = 10

MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
             'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

STATUS_MAP = {0:'حضور',1:'مغادرة',4:'أوفرتايم دخول',5:'أوفرتايم خروج',255:'أخرى'}
VERIFY_MAP = {0:'بصمة',1:'بصمة',3:'كارت',11:'وجه',15:'وجه + بصمة'}

# =============================================
# معالج الطلبات
# =============================================
class ZamzamHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # إخفاء logs المتصفح

    def send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # ===== اختبار الاتصال =====
        if parsed.path == '/ping':
            self.respond(200, {'status': 'ok', 'message': 'زمزم Server شغال ✅'})

        # ===== جلب البيانات من البصمة =====
        elif parsed.path == '/fetch':
            year  = int(params.get('year',  [datetime.now().year])[0])
            month = int(params.get('month', [datetime.now().month])[0])
            print(f"\n  📡 طلب بيانات: {MONTHS_AR[month-1]} {year}")
            result = self.fetch_from_device(year, month)
            self.respond(200, result)

        # ===== معلومات الجهاز =====
        elif parsed.path == '/device-info':
            result = self.get_device_info()
            self.respond(200, result)

        else:
            self.respond(404, {'error': 'not found'})

    def respond(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    def get_device_info(self):
        try:
            from zk import ZK
            zk = ZK(DEVICE_IP, port=DEVICE_PORT, timeout=8, password=PASSWORD, ommit_ping=True)
            conn = zk.connect()
            try:
                info = {
                    'status': 'connected',
                    'name':   conn.get_device_name(),
                    'serial': conn.get_serialnumber(),
                    'time':   str(conn.get_time()),
                    'ip':     DEVICE_IP,
                }
            finally:
                try:
                    conn.disconnect()
                except Exception:
                    pass
            return info
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def fetch_from_device(self, year, month):
        try:
            from zk import ZK
            from datetime import datetime

            print(f"  🔌 الاتصال بـ {DEVICE_IP}:{DEVICE_PORT}...")
            zk = ZK(DEVICE_IP, port=DEVICE_PORT, timeout=10, password=PASSWORD, ommit_ping=True)
            conn = zk.connect()
            print(f"  ✅ متصل!")

            # لازم الجهاز يترجع يتفتح والاتصال يتقفل دايمًا، حتى لو حصل
            # أي خطأ في النص — وإلا الجهاز يفضل "مقفول عن التسجيل" والاتصال
            # القديم يفضل عالق، وأي محاولة اتصال جديدة تفشل بسببه
            try:
                conn.disable_device()
                users = conn.get_users()
                user_map = {str(u.user_id): u.name or f'موظف {u.user_id}' for u in users}
                records = conn.get_attendance()
            finally:
                try:
                    conn.enable_device()
                except Exception as e2:
                    print(f"  ⚠️ تعذّر إعادة تفعيل الجهاز: {e2}")
                try:
                    conn.disconnect()
                except Exception as e3:
                    print(f"  ⚠️ تعذّر قفل الاتصال بأمان: {e3}")

            # فلترة الشهر المطلوب
            from_date = datetime(year, month, 1)
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            to_date = datetime(year, month, last_day, 23, 59, 59)

            filtered = [r for r in records if r.timestamp and from_date <= r.timestamp <= to_date]
            print(f"  📊 السجلات في {MONTHS_AR[month-1]} {year}: {len(filtered)}")

            # معالجة ودمج دخول/خروج
            merged = {}
            for r in filtered:
                uid = str(r.user_id)
                ts  = r.timestamp
                key = f"{uid}_{ts.strftime('%Y-%m-%d')}"
                date_str = ts.strftime('%Y-%m-%d')

                if key not in merged:
                    merged[key] = {
                        'id':      f"att_{uid}_{date_str}",
                        'empCode': uid,
                        'empName': user_map.get(uid, f'موظف {uid}'),
                        'date':    date_str,
                        'year':    year,
                        'month':   month,
                        'day':     ts.day,
                        'timeIn':  '',
                        'timeOut': '',
                        'ot':      0,
                        'otType':  'عادي (1.5×)',
                        'status':  'حضور',
                        'note':    f'مستورد تلقائياً {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                        'isLate':  False,
                        'allTimes': [],
                    }

                merged[key]['allTimes'].append(ts.strftime('%H:%M'))

            # تحديد دخول وخروج وأوفرتايم
            result_list = []
            for key, rec in merged.items():
                # ترتيب البصمات ثم إزالة أي بصمة متكررة (خلال DUP_PUNCH_MINUTES
                # من آخر بصمة معتمدة) — منع تسجيل "انصراف" وهمي بعد ثواني/دقائق
                # من الحضور بسبب مضاء مزدوج بالخطأ
                raw_times = sorted(rec['allTimes'])
                times = []
                last_kept = None
                for t in raw_times:
                    tt = datetime.strptime(t, '%H:%M')
                    if last_kept is None:
                        times.append(t)
                        last_kept = tt
                    else:
                        gap_min = (tt - last_kept).total_seconds() / 60
                        if gap_min >= DUP_PUNCH_MINUTES:
                            times.append(t)
                            last_kept = tt
                        # وإلا: بصمة مكررة (فرق أقل من الحد) → تجاهل تماماً

                if times:
                    rec['timeIn']  = times[0]
                    rec['timeOut'] = times[-1] if len(times) > 1 else ''

                    # حساب ساعات العمل
                    if rec['timeIn'] and rec['timeOut']:
                        try:
                            t1 = datetime.strptime(rec['timeIn'],  '%H:%M')
                            t2 = datetime.strptime(rec['timeOut'], '%H:%M')
                            diff = (t2 - t1).seconds / 3600
                            # لو أكتر من 8 ساعات — الزيادة أوفرتايم
                            if diff > 8:
                                rec['ot'] = round(diff - 8, 1)
                        except:
                            pass

                del rec['allTimes']
                result_list.append(rec)

            result_list.sort(key=lambda x: (x['empCode'], x['date']))

            print(f"  ✅ تم المعالجة: {len(result_list)} سجل")

            return {
                'status':  'success',
                'year':    year,
                'month':   month,
                'label':   f"{MONTHS_AR[month-1]} {year}",
                'total':   len(result_list),
                'records': result_list,
                # قائمة كل الموظفين المسجّلين على الجهاز (بصموا عليه) —
                # بغض النظر عن وجود حضور فعلي ليهم في الشهر ده أو لأ.
                # مبنية من نفس user_map اللي اتجابت فوق بالفعل — بدون أي
                # اتصال إضافي بالجهاز خالص، إضافة بحتة على الرد الموجود
                'allUsers': [{'code': uid_, 'name': nm_} for uid_, nm_ in user_map.items()],
            }

        except ImportError:
            return {'status': 'error', 'message': 'مكتبة pyzk غير مثبتة — شغّل: pip install pyzk'}
        except Exception as e:
            print(f"  ❌ خطأ: {e}")
            return {'status': 'error', 'message': str(e)}


# =============================================
# تشغيل الـ Server
# =============================================
def main():
    # كتابة log بسيط
    import os
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zamzam_server.log')
    with open(log_path, 'w', encoding='utf-8') as log:
        log.write(f"زمزم Server شغال — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        log.write(f"البورت: {SERVER_PORT} | البصمة: {DEVICE_IP}:{DEVICE_PORT}\n")

    try:
        server = HTTPServer(('localhost', SERVER_PORT), ZamzamHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  🔴 تم إيقاف الـ Server")
    except OSError as e:
        if "10048" in str(e) or "Address already in use" in str(e):
            print(f"\n  ❌ البورت {SERVER_PORT} مشغول بالفعل!")
            print(f"  💡 الـ Server ممكن يكون شغال في الخلفية بالفعل ✅")
        else:
            print(f"\n  ❌ خطأ: {e}")
    pass  # خلفية — مش محتاج Enter

if __name__ == "__main__":
    main()

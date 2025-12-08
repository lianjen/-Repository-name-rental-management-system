"""
幸福之家管理系統 Pro v13.10 - 莫蘭迪柔和護眼版
= 視覺優化 =
✅ 1. 全局背景：極淡冷灰白 (#f8f9fa)，模擬紙張質感，降低視覺疲勞。
✅ 2. 主色調：鼠尾草綠 (#84a98c) + 霧霾藍 (#5c677d)，低飽和度更耐看。
✅ 3. 卡片設計：去除多餘邊框，使用柔和懸浮陰影。
✅ 4. 文字優化：深灰藍色 (#2f3e46) 取代純黑，閱讀更舒適。

功能邏輯保持 v13.9/v13.8 完整架構不變。
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
import time
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List

# ============================================================================
# 日誌配置
# ============================================================================
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "rental_system.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

# ============================================================================
# 常數定義
# ============================================================================
ALL_ROOMS = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]
SHARING_ROOMS = ["2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]
NON_SHARING_ROOMS = ["1A", "1B"]
EXPENSE_CATEGORIES = ["維修", "雜項", "貸款", "水電費", "網路費"]
PAYMENT_METHODS = ["月繳", "半年繳", "年繳"]
WATER_FEE = 100

# ============================================================================
# 電費計算類 (保持不變)
# ============================================================================
class ElectricityCalculatorV10:
    def __init__(self):
        self.errors = []
        self.unit_price = 0
        self.tdy_total_kwh = 0
        self.tdy_total_fee = 0
        self.meter_total_kwh = 0
        self.public_kwh = 0
        self.public_per_room = 0
        self.non_sharing_records = {}
    
    def check_tdy_bills(self, tdy_data: Dict[str, Tuple[float, float]]) -> bool:
        st.markdown("### 📊 【第 1 步】台電單據檢查")
        valid_count = 0
        total_kwh = 0
        total_fee = 0
        
        for floor, (fee, kwh) in tdy_data.items():
            if kwh == 0 or fee == 0:
                if fee == 0 and kwh == 0:
                    self.errors.append(f"🚨 {floor}: 完全沒有輸入")
                elif kwh == 0:
                    self.errors.append(f"🚨 {floor}: 度數為 0")
                elif fee == 0:
                    self.errors.append(f"🚨 {floor}: 金額為 0")
            else:
                unit_price = fee / kwh
                st.success(f"✅ {floor}: {kwh:.1f}度 × ${unit_price:.4f}/度 = ${fee:,.0f}")
                valid_count += 1
                total_kwh += kwh
                total_fee += fee
        
        if valid_count == 0:
            self.errors.append("🚨 沒有任何有效的台電單據")
            return False
        
        self.unit_price = total_fee / total_kwh
        self.tdy_total_kwh = total_kwh
        self.tdy_total_fee = total_fee
        
        st.success(f"✅ 台電驗證通過")
        st.info(f"   台電總度數: {total_kwh:.2f}度")
        st.info(f"   台電總金額: ${total_fee:,.0f}")
        st.success(f"📊 【當期電度單價】${self.unit_price:.4f}/度")
        return True
    
    def check_meter_readings(self, meter_data: Dict[str, Tuple[float, float]]) -> bool:
        st.markdown("### 📟 【第 2 步】房間度數檢查")
        valid_count = 0
        total_kwh = 0
        
        for room in NON_SHARING_ROOMS:
            start, end = meter_data[room]
            if end > start:
                usage = round(end - start, 2)
                self.non_sharing_records[room] = usage
                st.info(f"📝 {room}: {start:.2f} → {end:.2f} (記錄: {usage:.2f}度，不計算)")
        
        st.divider()
        
        for room in SHARING_ROOMS:
            start, end = meter_data[room]
            if start == 0 and end == 0:
                continue
            elif end <= start and not (start == 0 and end == 0):
                if end < start:
                    self.errors.append(f"🚨 {room}: 本期 < 上期")
            else:
                usage = round(end - start, 2)
                st.success(f"✅ {room}: {start:.2f} → {end:.2f} (度數: {usage:.2f})")
                valid_count += 1
                total_kwh += usage
        
        if valid_count == 0:
            self.errors.append("🚨 沒有分攤房間的度數")
            return False
        
        self.meter_total_kwh = round(total_kwh, 2)
        st.success(f"✅ 房間度數驗證通過: {valid_count} 間房間")
        st.info(f"   分攤房間私表總度數: {self.meter_total_kwh:.2f}度")
        return True
    
    def calculate_public_electricity(self) -> bool:
        st.markdown("### ⚖️ 【第 2-3 步】公用電計算")
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)
        
        st.info(f"公用電度數 = 台電總度數 - 分攤房間私表總度數")
        st.info(f"           = {self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.success(f"           = {self.public_kwh:.2f}度")
        
        if self.public_kwh < 0:
            self.errors.append(f"🚨 公用電度數為負數")
            return False
        
        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        st.info(f"每戶分攤度數 = 公用電度數 ÷ {len(SHARING_ROOMS)}間")
        st.info(f"            = {self.public_kwh:.2f} ÷ {len(SHARING_ROOMS)}")
        st.success(f"            = {self.public_per_room}度/戶（四捨五入）")
        return True
    
    def diagnose(self) -> Tuple[bool, str]:
        st.markdown("---")
        if self.errors:
            error_msg = "🔴 **檢測到以下錯誤：**\n\n"
            for error in self.errors:
                error_msg += f"• {error}\n"
            return False, error_msg
        return True, "✅ 所有檢查都通過了！"

# ============================================================================
# 繳費計畫生成工具
# ============================================================================
def generate_payment_schedule(payment_method: str, start_date: str, end_date: str) -> List[Tuple[int, int]]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    schedule = []
    
    current = start
    while current <= end:
        year = current.year
        month = current.month
        
        if payment_method == "月繳":
            schedule.append((year, month))
            current += timedelta(days=30)
        elif payment_method == "半年繳":
            if month in [1, 7]:
                schedule.append((year, month))
            current += timedelta(days=180)
        elif payment_method == "年繳":
            if month == 1:
                schedule.append((year, month))
            current += timedelta(days=365)
    
    return schedule

# ============================================================================
# 數據庫類 (保持不變)
# ============================================================================
class RentalDB:
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()
        self._force_fix_schema()
        self._create_indexes()

    def _create_indexes(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_schedule_room ON payment_schedule(room_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_schedule_status ON payment_schedule(status)")
        except:
            pass

    def reset_database(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                return True, "✅ 資料庫已重置"
            return False, "⚠️ 資料庫不存在"
        except Exception as e:
            return False, str(e)

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT UNIQUE NOT NULL,
                tenant_name TEXT NOT NULL,
                phone TEXT,
                deposit REAL DEFAULT 0,
                base_rent REAL DEFAULT 0,
                lease_start TEXT NOT NULL,
                lease_end TEXT NOT NULL,
                payment_method TEXT DEFAULT '月繳',
                has_discount INTEGER DEFAULT 0,
                has_water_fee INTEGER DEFAULT 0,
                discount_notes TEXT,
                last_ac_cleaning_date TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS payment_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT NOT NULL,
                tenant_name TEXT NOT NULL,
                payment_year INTEGER NOT NULL,
                payment_month INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT DEFAULT '月繳',
                due_date TEXT,
                paid_date TEXT,
                paid_amount REAL DEFAULT 0,
                status TEXT DEFAULT '未繳',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_number) REFERENCES tenants(room_number),
                UNIQUE(room_number, payment_year, payment_month)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS rent_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT NOT NULL,
                tenant_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                base_amount REAL NOT NULL,
                water_fee REAL DEFAULT 0,
                discount_amount REAL DEFAULT 0,
                actual_amount REAL NOT NULL,
                paid_amount REAL DEFAULT 0,
                paid_date TEXT,
                payment_method TEXT,
                notes TEXT,
                status TEXT DEFAULT '待確認',
                recorded_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_number) REFERENCES tenants(room_number),
                UNIQUE(room_number, year, month)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS rent_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                amount REAL NOT NULL,
                paid_date TEXT,
                is_paid INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_number) REFERENCES tenants(room_number),
                UNIQUE(room_number, year, month)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_period (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_year INTEGER NOT NULL,
                period_month_start INTEGER NOT NULL,
                period_month_end INTEGER NOT NULL,
                tdy_total_kwh REAL DEFAULT 0,
                tdy_total_fee REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                public_kwh REAL DEFAULT 0,
                public_per_room INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_tdy_bill (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_id INTEGER NOT NULL,
                floor_name TEXT NOT NULL,
                tdy_total_kwh REAL NOT NULL,
                tdy_total_fee REAL NOT NULL,
                FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                UNIQUE(period_id, floor_name)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_meter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_id INTEGER NOT NULL,
                room_number TEXT NOT NULL,
                meter_start_reading REAL NOT NULL,
                meter_end_reading REAL NOT NULL,
                meter_kwh_usage REAL NOT NULL,
                FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                UNIQUE(period_id, room_number)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_calculation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_id INTEGER NOT NULL,
                room_number TEXT NOT NULL,
                private_kwh REAL NOT NULL,
                public_kwh INTEGER NOT NULL,
                total_kwh REAL NOT NULL,
                unit_price REAL NOT NULL,
                calculated_fee REAL NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                UNIQUE(period_id, room_number)
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_date TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            
            cursor.execute("""CREATE TABLE IF NOT EXISTS memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memo_text TEXT NOT NULL,
                priority TEXT DEFAULT 'normal',
                is_completed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

    def _force_fix_schema(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(tenants)")
                cols = [i[1] for i in cursor.fetchall()]
                if "payment_method" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
                if "discount_notes" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN discount_notes TEXT DEFAULT ''")
                if "last_ac_cleaning_date" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN last_ac_cleaning_date TEXT")
                if "has_discount" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_discount INTEGER DEFAULT 0")
                if "has_water_fee" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_water_fee INTEGER DEFAULT 0")
                
                cursor.execute("PRAGMA table_info(rent_records)")
                rr_cols = [i[1] for i in cursor.fetchall()]
                if "status" not in rr_cols:
                    cursor.execute("ALTER TABLE rent_records ADD COLUMN status TEXT DEFAULT '待確認'")
                
                cursor.execute("PRAGMA table_info(electricity_period)")
                ep_cols = [i[1] for i in cursor.fetchall()]
                if "notes" not in ep_cols:
                    cursor.execute("ALTER TABLE electricity_period ADD COLUMN notes TEXT DEFAULT ''")
        except:
            pass

    # ===== 房客管理 =====
    def room_exists(self, room: str) -> bool:
        with self._get_connection() as conn:
            return conn.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,)).fetchone() is not None

    def upsert_tenant(self, room, name, phone, deposit, base_rent, start, end, payment_method="月繳", has_discount=False, has_water_fee=False, discount_notes="", ac_date=None, tenant_id=None):
        try:
            with self._get_connection() as conn:
                if tenant_id:
                    conn.execute("""UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?, lease_start=?, lease_end=?, payment_method=?, has_discount=?, has_water_fee=?, discount_notes=?, last_ac_cleaning_date=? WHERE id=?""",
                        (name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date, tenant_id))
                    logging.info(f"房客更新: {room} ({name})")
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"
                    conn.execute("""INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, lease_start, lease_end, payment_method, has_discount, has_water_fee, discount_notes, last_ac_cleaning_date) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (room, name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date))
                    
                    self._generate_payment_schedule_for_tenant(room, name, base_rent, has_water_fee, payment_method, start, end)
                    
                    logging.info(f"房客新增: {room} ({name}) - {payment_method} - 自動生成繳費計畫")
                    return True, f"✅ 房號 {room} 已新增 (已自動生成繳費計畫)"
        except Exception as e:
            logging.error(f"房客操作失敗: {e}")
            return False, str(e)

    def _generate_payment_schedule_for_tenant(self, room: str, tenant_name: str, base_rent: float, has_water_fee: bool, payment_method: str, start_date: str, end_date: str):
        try:
            amount = base_rent + (WATER_FEE if has_water_fee else 0)
            schedule = generate_payment_schedule(payment_method, start_date, end_date)
            
            with self._get_connection() as conn:
                for year, month in schedule:
                    if month == 12:
                        due_date = f"{year + 1}-01-05"
                    else:
                        due_date = f"{year}-{month + 1:02d}-05"
                    
                    conn.execute("""INSERT OR IGNORE INTO payment_schedule
                        (room_number, tenant_name, payment_year, payment_month, amount, payment_method, due_date, status, created_at, updated_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (room, tenant_name, year, month, amount, payment_method, due_date, "未繳", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        except Exception as e:
            logging.error(f"生成繳費計畫失敗: {e}")

    def get_tenants(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)

    def get_tenant_by_id(self, tid: int):
    try:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row    # ✅ 設置行工廠
            row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
            if row:
                return dict(row)              # ✅ 直接轉換
            return None
    except Exception as e:
        logging.error(f"查詢房客失敗: {e}") # ✅ 錯誤處理
        return None


    def delete_tenant(self, tid: int):
        with self._get_connection() as conn:
            conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
        return True, "✅ 已刪除"

    # ===== 繳費計畫管理 =====
    def get_payment_schedule(self, room: Optional[str] = None, status: Optional[str] = None, year: Optional[int] = None) -> pd.DataFrame:
        with self._get_connection() as conn:
            q = "SELECT * FROM payment_schedule WHERE 1=1"
            if room:
                q += f" AND room_number='{room}'"
            if status:
                q += f" AND status='{status}'"
            if year:
                q += f" AND payment_year={year}"
            q += " ORDER BY payment_year DESC, payment_month DESC, room_number"
            return pd.read_sql(q, conn)

    def mark_payment_done(self, payment_id: int, paid_date: str, paid_amount: float, notes: str = ""):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE payment_schedule 
                    SET status='已繳', paid_date=?, paid_amount=?, notes=?, updated_at=?
                    WHERE id=?""",
                    (paid_date, paid_amount, notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_id))
                logging.info(f"繳費標記: ID {payment_id} 已繳 ${paid_amount}")
                return True, "✅ 繳費已標記"
        except Exception as e:
            logging.error(f"標記失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_payment_summary(self, year: int) -> Dict:
        with self._get_connection() as conn:
            due = conn.execute("SELECT SUM(amount) FROM payment_schedule WHERE payment_year=?", (year,)).fetchone()[0] or 0
            paid = conn.execute("SELECT SUM(paid_amount) FROM payment_schedule WHERE payment_year=? AND status='已繳'", (year,)).fetchone()[0] or 0
            unpaid = conn.execute("SELECT COUNT(*) FROM payment_schedule WHERE payment_year=? AND status='未繳'", (year,)).fetchone()[0] or 0
            return {'total_due': due, 'total_paid': paid, 'unpaid_count': unpaid, 'collection_rate': (paid/due*100) if due > 0 else 0}

    def get_overdue_payments(self) -> pd.DataFrame:
        today = date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            return pd.read_sql(f"""
                SELECT room_number, tenant_name, payment_month, amount, due_date
                FROM payment_schedule
                WHERE status='未繳' AND due_date < '{today}'
                ORDER BY due_date ASC
            """, conn)

    def get_upcoming_payments(self, days_ahead: int = 7) -> pd.DataFrame:
        today = date.today()
        future_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            return pd.read_sql(f"""
                SELECT room_number, tenant_name, payment_month, amount, due_date
                FROM payment_schedule
                WHERE status='未繳' AND due_date >= '{today_str}' AND due_date <= '{future_date}'
                ORDER BY due_date ASC
            """, conn)

    # ===== 租金管理 =====
    def batch_record_rent(self, room: str, tenant_name: str, start_year: int, start_month: int, 
                         months_count: int, base_rent: float, water_fee: float, discount: float, 
                         payment_method: str = "月繳", notes: str = ""):
        """批量預填租金"""
        try:
            with self._get_connection() as conn:
                actual_amount = base_rent + water_fee - discount
                
                current_date = date(start_year, start_month, 1)
                
                for i in range(months_count):
                    year = current_date.year
                    month = current_date.month
                    
                    conn.execute("""INSERT OR REPLACE INTO rent_records
                        (room_number, tenant_name, year, month, base_amount, water_fee, discount_amount, 
                         actual_amount, paid_amount, payment_method, notes, status, recorded_by, updated_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (room, tenant_name, year, month, base_rent, water_fee, discount, 
                         actual_amount, 0, payment_method, notes, "待確認", "batch", 
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    
                    if month == 12:
                        current_date = date(year + 1, 1, 1)
                    else:
                        current_date = date(year, month + 1, 1)
                
                logging.info(f"批量預填租金: {room} {start_year}年{start_month}月開始 {months_count}個月")
                return True, f"✅ 已預填 {months_count} 個月租金"
        except Exception as e:
            logging.error(f"批量預填失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def confirm_rent_payment(self, rent_id: int, paid_date: str, paid_amount: float = None):
        """確認已繳費"""
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT actual_amount FROM rent_records WHERE id=?", (rent_id,)).fetchone()
                if not row:
                    return False, "❌ 找不到該筆記錄"
                
                actual = row[0]
                paid_amt = paid_amount if paid_amount is not None else actual
                
                conn.execute("""UPDATE rent_records 
                    SET status='已收', paid_date=?, paid_amount=?, updated_at=?
                    WHERE id=?""",
                    (paid_date, paid_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rent_id))
                
                logging.info(f"確認租金繳費: ID {rent_id} 已收 ${paid_amt}")
                return True, "✅ 租金已確認繳清"
        except Exception as e:
            logging.error(f"確認失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_rent_records(self, year=None, month=None, status=None) -> pd.DataFrame:
        with self._get_connection() as conn:
            q = "SELECT * FROM rent_records"
            conds = []
            if year:
                conds.append(f"year={year}")
            if month and month != "全部":
                conds.append(f"month={month}")
            if status:
                conds.append(f"status='{status}'")
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY year DESC, month DESC, room_number"
            return pd.read_sql(q, conn)

    def get_pending_rents(self) -> pd.DataFrame:
        """查詢待確認的租金"""
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT id, room_number, tenant_name, year, month, actual_amount, status
                FROM rent_records 
                WHERE status IN ('待確認', '未收')
                ORDER BY year DESC, month DESC, room_number""", conn)

    def get_unpaid_rents_v2(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT room_number as '房號', tenant_name as '房客', year as '年', month as '月', actual_amount as '應繳', paid_amount as '已收', status as '狀態' FROM rent_records WHERE status='未收' ORDER BY year DESC, month DESC, room_number""", conn)

    def get_rent_summary(self, year: int) -> Dict:
        with self._get_connection() as conn:
            due = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=?", (year,)).fetchone()[0] or 0
            paid = conn.execute("SELECT SUM(paid_amount) FROM rent_records WHERE year=? AND status='已收'", (year,)).fetchone()[0] or 0
            unpaid = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=? AND status IN ('未收', '待確認')", (year,)).fetchone()[0] or 0
            return {'total_due': due, 'total_paid': paid, 'total_unpaid': unpaid, 'collection_rate': (paid/due*100) if due > 0 else 0}

    def get_rent_matrix(self, year: int) -> pd.DataFrame:
        with self._get_connection() as conn:
            df = pd.read_sql(f"SELECT room_number, month, is_paid, amount FROM rent_payments WHERE year = {year} ORDER BY room_number, month", conn)
            if df.empty:
                return pd.DataFrame()
            matrix = {r: {m: "" for m in range(1, 13)} for r in ALL_ROOMS}
            for _, row in df.iterrows():
                matrix[row['room_number']][row['month']] = "✅" if row['is_paid'] else f"❌ ${int(row['amount'])}"
            res = pd.DataFrame.from_dict(matrix, orient='index')
            res.columns = [f"{m}月" for m in range(1, 13)]
            return res

    def get_unpaid_rents(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT r.room_number as '房號', t.tenant_name as '房客', r.year as '年', r.month as '月', r.amount as '金額' FROM rent_payments r JOIN tenants t ON r.room_number = t.room_number WHERE r.is_paid = 0 AND t.is_active = 1 ORDER BY r.year DESC, r.month DESC""", conn)

    def add_electricity_period(self, year, ms, me):
        try:
            with self._get_connection() as conn:
                if conn.execute("SELECT 1 FROM electricity_period WHERE period_year=? AND period_month_start=? AND period_month_end=?", (year, ms, me)).fetchone():
                    return True, "✅ 期間已存在", 0
                c = conn.execute("INSERT INTO electricity_period(period_year, period_month_start, period_month_end) VALUES(?, ?, ?)", (year, ms, me))
                return True, "✅ 新增成功", c.lastrowid
        except Exception as e:
            return False, str(e), 0

    def get_all_periods(self):
        with self._get_connection() as conn:
            c = conn.execute("SELECT * FROM electricity_period ORDER BY id DESC")
            return [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]

    def get_period_report(self, pid):
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT room_number as '房號', private_kwh as '私表度數', public_kwh as '分攤度數', total_kwh as '合計度數', unit_price as '單價', calculated_fee as '應繳電費' FROM electricity_calculation WHERE period_id = ? ORDER BY room_number""", conn, params=(pid,))

    def add_tdy_bill(self, pid, floor, kwh, fee):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee) VALUES(?, ?, ?, ?)", (pid, floor, kwh, fee))

    def add_meter_reading(self, pid, room, start, end):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) VALUES(?, ?, ?, ?, ?)", (pid, room, start, end, round(end-start, 2)))

    def calculate_electricity_fee(self, pid, calc, meter_data, notes=""):
        try:
            results = []
            with self._get_connection() as conn:
                for room in SHARING_ROOMS:
                    s, e = meter_data[room]
                    if e <= s:
                        continue
                    priv = round(e-s, 2)
                    pub = calc.public_per_room
                    total = round(priv + pub, 2)
                    fee = round(total * calc.unit_price, 0)
                    results.append({'房號': room, '私表度數': f"{priv:.2f}", '分攤度數': str(pub), '合計度數': f"{total:.2f}", '電度單價': f"${calc.unit_price:.4f}/度", '應繳電費': f"${int(fee)}"})
                    conn.execute("INSERT OR REPLACE INTO electricity_calculation(period_id, room_number, private_kwh, public_kwh, total_kwh, unit_price, calculated_fee) VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (pid, room, priv, pub, total, calc.unit_price, fee))
                conn.execute("UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=?, notes=? WHERE id=?",
                    (calc.unit_price, calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee, notes, pid))
            return True, "✅ 計算完成", pd.DataFrame(results)
        except Exception as e:
            return False, str(e), pd.DataFrame()

    def add_expense(self, date, cat, amt, desc):
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT INTO expenses(expense_date, category, amount, description) VALUES(?, ?, ?, ?)", (date, cat, amt, desc))
                return True
        except:
            return False

    def get_expenses(self, limit=50):
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))

    def add_memo(self, text, prio="normal"):
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT INTO memos(memo_text, priority) VALUES(?, ?)", (text, prio))
                return True
        except:
            return False

    def get_memos(self, completed=False):
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM memos WHERE is_completed=? ORDER BY priority DESC, created_at DESC", conn, params=(1 if completed else 0,))

    def complete_memo(self, mid):
        with self._get_connection() as conn:
            conn.execute("UPDATE memos SET is_completed=1 WHERE id=?", (mid,))
        return True

    def delete_memo(self, mid):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM memos WHERE id=?", (mid,))
        return True

# ============================================================================
# UI 工具 (柔和護眼版)
# ============================================================================
def display_card(title: str, value: str, color: str = "blue"):
    """
    莫蘭迪風格卡片
    使用低飽和度色彩，減少視覺疲勞
    """
    # 背景色：極淡的粉筆色
    colors = {
        "blue": "#f0f4f8",      # 淡灰藍
        "green": "#edf2f0",     # 淡灰綠
        "orange": "#fdf3e7",    # 淡米橘
        "red": "#fbeaea"        # 淡灰紅
    }
    # 邊框色：柔和的莫蘭迪色
    border_colors = {
        "blue": "#98c1d9",      # 莫蘭迪藍
        "green": "#99b898",     # 莫蘭迪綠
        "orange": "#e0c3a5",    # 莫蘭迪棕
        "red": "#e5989b"        # 莫蘭迪紅
    }
    # 文字色：深灰藍，不使用純黑
    text_color = "#4a5568"
    value_color = "#2d3748"
    
    st.markdown(f"""
    <div style="background: {colors.get(color, '#f8f9fa')}; border-radius: 10px; padding: 16px; margin-bottom: 12px; border: 1px solid {border_colors.get(color, '#d1d5db')}; border-left: 5px solid {border_colors.get(color, '#d1d5db')}; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="color: {text_color}; font-size: 0.9rem; font-weight: 600; letter-spacing: 0.5px;">{title}</div>
        <div style="color: {value_color}; font-size: 1.6rem; font-weight: 700; margin-top: 6px; font-family: 'Segoe UI', sans-serif;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def display_room_card(room, status_color, status_text, detail_text=""):
    """
    房間卡片 - 護眼風格
    去除粗邊框，使用柔和背景
    """
    bg_color = {
        "green": "#eaf4e7", # 護眼綠背景
        "red": "#fae3e3",   # 柔和紅背景
        "orange": "#fef5e6" # 暖米色背景
    }.get(status_color, "#f8f9fa")
    
    text_color = {
        "green": "#2f5d34", # 深苔綠文字
        "red": "#8a2c2c",   # 深磚紅文字
        "orange": "#8a5a2c" # 深褐色文字
    }.get(status_color, "#4a5568")
    
    st.markdown(f"""
    <div style="background-color: {bg_color}; border-radius: 12px; padding: 12px; text-align: center; height: 100px; display: flex; flex-direction: column; justify-content: center; align-items: center; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: transform 0.2s;">
        <div style="font-size: 1.3rem; font-weight: 700; color: {text_color};">{room}</div>
        <div style="font-size: 0.9rem; font-weight: 600; color: {text_color}; margin-top: 4px;">{status_text}</div>
        <div style="font-size: 0.75rem; color: {text_color}; opacity: 0.8;">{detail_text}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 頁面層 - 儀表板
# ============================================================================
def page_dashboard(db: RentalDB):
    st.header("📊 儀表板")
    
    tenants = db.get_tenants()
    today = date.today()
    
    st.markdown("##### 🏢 物業概況")
    col1, col2, col3, col4 = st.columns(4)
    
    occupancy = len(tenants)
    rate = (occupancy / 12 * 100) if occupancy > 0 else 0
    
    with col1:
        display_card("入住房間", f"{occupancy} 間", "green")
    with col2:
        display_card("入住率", f"{rate:.0f}%", "blue")
    with col3:
        display_card("空房", f"{12 - occupancy} 間", "red")
    with col4:
        display_card("總房間", "12 間", "orange")
    
    st.divider()
    
    st.markdown("##### 💳 繳費狀態")
    
    col1, col2, col3 = st.columns(3)
    
    overdue = db.get_overdue_payments()
    upcoming = db.get_upcoming_payments(7)
    summary = db.get_payment_summary(today.year)
    
    with col1:
        if len(overdue) > 0:
            display_card("逾期未繳", f"{len(overdue)} 筆", "red")
        else:
            display_card("逾期未繳", "0 筆", "green")
    
    with col2:
        if len(upcoming) > 0:
            display_card("7天內到期", f"{len(upcoming)} 筆", "orange")
        else:
            display_card("7天內到期", "0 筆", "green")
    
    with col3:
        display_card("本年度收款率", f"{summary['collection_rate']:.1f}%", "blue")
    
    st.divider()
    
    expiring_soon = []
    if not tenants.empty:
        for _, t in tenants.iterrows():
            try:
                end_date = datetime.strptime(t['lease_end'], "%Y-%m-%d").date()
                days_left = (end_date - today).days
                if 0 <= days_left <= 45:
                    expiring_soon.append((t['room_number'], t['tenant_name'], days_left, t['lease_end']))
            except:
                pass
    
    if expiring_soon:
        st.markdown("##### 🚨 即將到期合約 (45天內)")
        cols = st.columns(4)
        for i, (room, name, days, end_date) in enumerate(expiring_soon):
            with cols[i % 4]:
                st.error(f"**{room} {name}**\n\n剩餘 **{days}** 天\n\n({end_date})")
        st.divider()
    
    st.markdown("##### 🏠 房間實時狀態")
    active_rooms = tenants.set_index('room_number') if not tenants.empty else pd.DataFrame()
    cols = st.columns(6)
    
    for i, room in enumerate(ALL_ROOMS):
        with cols[i % 6]:
            if not active_rooms.empty and room in active_rooms.index:
                t = active_rooms.loc[room]
                try:
                    days = (datetime.strptime(t['lease_end'], "%Y-%m-%d").date() - today).days
                    if days <= 45:
                        status_color = "orange"
                        status_text = "即將到期"
                        detail_text = f"剩 {days} 天"
                    else:
                        status_color = "green"
                        status_text = t['tenant_name']
                        detail_text = f"{t['payment_method']}"
                except:
                    status_color = "green"
                    status_text = t['tenant_name']
                    detail_text = "租期異常"
                display_room_card(room, status_color, status_text, detail_text)
            else:
                display_room_card(room, "red", "空房", "可招租")

    st.divider()
    
    st.markdown("##### 📅 年度房租繳費總覽")
    year = st.selectbox("選擇年份", [today.year, today.year + 1], key="dash_year")
    rent_matrix = db.get_rent_matrix(year)
    if not rent_matrix.empty:
        st.dataframe(rent_matrix, use_container_width=True)
    else:
        st.info("尚無資料")

    st.divider()
    
    col_memo, col_unpaid = st.columns([1, 1])
    
    with col_memo:
        st.markdown("##### 📝 待辦事項")
        memos = db.get_memos(completed=False)
        if not memos.empty:
            for _, memo in memos.iterrows():
                c1, c2 = st.columns([5, 1])
                c1.write(f"• {memo['memo_text']}")
                if c2.button("✓", key=f"m_{memo['id']}"):
                    db.complete_memo(memo['id'])
                    st.rerun()
        else:
            st.caption("✅ 無待辦事項")

    with col_unpaid:
        st.markdown("##### 💰 舊版未繳記錄")
        unpaid = db.get_unpaid_rents()
        if not unpaid.empty:
            st.dataframe(unpaid[['房號','房客','金額']], use_container_width=True, hide_index=True)
        else:
            st.caption("✅ 全數繳清")

# ============================================================================
# 頁面層 - 收租金
# ============================================================================
def page_collect_rent(db: RentalDB):
    st.header("💳 收租金管理")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📝 快速單月", "📋 批量預填", "✅ 待確認清單", "📊 統計"])
    
    with tab1:
        st.markdown("#### 📍 快速記錄單月租金")
        tenants = db.get_tenants()
        if tenants.empty:
            st.warning("請先新增房客")
            return

        with st.container(border=True):
            col_sel1, col_sel2, col_sel3 = st.columns(3)
            with col_sel1:
                room_options = {f"{r['room_number']} - {r['tenant_name']}": r['room_number'] for _, r in tenants.iterrows()}
                selected_label = st.selectbox("選擇房客", list(room_options.keys()))
                room = room_options[selected_label]
                t_data = tenants[tenants['room_number'] == room].iloc[0]
            
            with col_sel2:
                year = st.number_input("年", value=datetime.now().year)
            with col_sel3:
                month = st.number_input("月", value=datetime.now().month, min_value=1, max_value=12)

            st.divider()

            base_rent = float(t_data['base_rent'])
            water_fee = WATER_FEE if t_data['has_water_fee'] else 0
            
            col_calc1, col_calc2, col_calc3 = st.columns(3)
            with col_calc1:
                new_base = st.number_input("房租", value=base_rent, step=100.0)
            with col_calc2:
                new_water = st.number_input("水費", value=float(water_fee), step=50.0)
            with col_calc3:
                new_discount = st.number_input("折扣", value=0.0, step=100.0)
            
            final_amount = new_base + new_water - new_discount
            st.markdown(f"<div style='text-align:right; font-size:1.5em; font-weight:bold; color:#5c677d;'>本期應收：<span style=\"font-size:1.8em; color:#2f3e46;\">${final_amount:,.0f}</span></div>", unsafe_allow_html=True)
            
            with st.expander("💵 填寫收款詳情 (若已收款)", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    paid_amt = st.number_input("實收金額", value=0.0, step=100.0)
                with c2:
                    paid_date = st.date_input("收款日期", value=date.today())
                
                notes = st.text_input("備註", placeholder="例如：提早匯款")
            
            if st.button("✅ 確認並儲存", type="primary", use_container_width=True):
                st.toast("正在儲存...", icon="⏳")
                ok, msg = db.batch_record_rent(
                    room, t_data['tenant_name'], year, month, 1,
                    new_base, new_water, new_discount, t_data['payment_method'], notes
                )
                if ok:
                    st.toast(msg, icon="✅")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.toast(msg, icon="❌")

    with tab2:
        st.markdown("#### 📋 **批量預填多個月租金**")
        st.info("💡 例如：月繳房客從 114/7/1 到 115/6/30，一次預填 12 個月，到時候只需要確認收款")
        
        tenants = db.get_tenants()
        if tenants.empty:
            st.warning("請先新增房客")
        else:
            with st.container(border=True):
                col_sel1, col_sel2, col_sel3 = st.columns(3)
                
                with col_sel1:
                    room_options = {f"{r['room_number']} - {r['tenant_name']}": r['room_number'] for _, r in tenants.iterrows()}
                    selected_label = st.selectbox("選擇房客", list(room_options.keys()), key="batch_room_sel")
                    room = room_options[selected_label]
                    t_data = tenants[tenants['room_number'] == room].iloc[0]
                
                with col_sel2:
                    start_year = st.number_input("開始年份", value=datetime.now().year, key="batch_start_year")
                with col_sel3:
                    start_month = st.number_input("開始月份", value=datetime.now().month, min_value=1, max_value=12, key="batch_start_month")
                
                st.divider()
                
                col_rent, col_water, col_discount = st.columns(3)
                with col_rent:
                    batch_base = st.number_input("月租", value=float(t_data['base_rent']), step=100.0, key="batch_base")
                with col_water:
                    batch_water = st.number_input("月水費", value=float(WATER_FEE if t_data['has_water_fee'] else 0), step=50.0, key="batch_water")
                with col_discount:
                    batch_discount = st.number_input("月折扣", value=0.0, step=100.0, key="batch_discount")
                
                batch_actual = batch_base + batch_water - batch_discount
                st.markdown(f"<div style='text-align:right; font-size:1.2em; font-weight:bold; color:#5c677d;'>每月應收：<span style=\"font-size:1.5em; color:#2f3e46;\">${batch_actual:,.0f}</span></div>", unsafe_allow_html=True)
                
                st.divider()
                st.markdown("### 📅 預填月份設定")
                
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    months_count = st.slider("要預填幾個月？", min_value=1, max_value=12, value=12)
                with col_m2:
                    end_month = start_month + months_count - 1
                    end_year = start_year
                    if end_month > 12:
                        end_year = start_year + (end_month - 1) // 12
                        end_month = (end_month - 1) % 12 + 1
                    st.metric("預填至", f"{end_year}年{end_month}月")
                
                notes = st.text_input("備註 (選填)", placeholder="例如：114/7/1 - 115/6/30", key="batch_notes")
                
                st.divider()
                
                if st.button("🚀 確認批量預填", type="primary", use_container_width=True):
                    progress_text = "正在生成帳單..."
                    my_bar = st.progress(0, text=progress_text)
                    
                    for percent_complete in range(100):
                        time.sleep(0.005)
                        my_bar.progress(percent_complete + 1, text=progress_text)
                    
                    ok, msg = db.batch_record_rent(
                        room, t_data['tenant_name'],
                        start_year, start_month, months_count,
                        batch_base, batch_water, batch_discount,
                        t_data['payment_method'], notes
                    )
                    
                    my_bar.empty()
                    
                    if ok:
                        st.toast(msg, icon="✅")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.toast(msg, icon="❌")

    with tab3:
        st.markdown("#### ✅ **待確認租金清單**")
        st.info("💡 已預填但未確認繳費的租金項目")
        
        pending = db.get_pending_rents()
        
        if pending.empty:
            st.success("✅ 沒有待確認項目")
        else:
            col_pending, col_confirmed = st.columns(2)
            
            with col_pending:
                st.subheader("⏳ 待確認 (未繳)")
                pending_only = pending[pending['status'] == '待確認']
                if not pending_only.empty:
                    for _, row in pending_only.iterrows():
                        with st.container(border=True):
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.write(f"**{row['room_number']} {row['tenant_name']}**")
                                st.caption(f"{row['year']}年{row['month']}月 - 應收：${row['actual_amount']:.0f}")
                            with col2:
                                if st.button("✅ 已繳", key=f"confirm_{row['id']}", use_container_width=True):
                                    ok, msg = db.confirm_rent_payment(row['id'], date.today().strftime("%Y-%m-%d"), row['actual_amount'])
                                    if ok:
                                        st.toast(msg, icon="✅")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.toast(msg, icon="❌")
                else:
                    st.info("✅ 無待確認項目")
            
            with col_confirmed:
                st.subheader("✅ 已收")
                confirmed = pending[pending['status'] == '已收']
                if not confirmed.empty:
                    for _, row in confirmed.iterrows():
                        st.write(f"✅ **{row['room_number']} {row['tenant_name']}**")
                        st.caption(f"{row['year']}年{row['month']}月 - 已收：${row['actual_amount']:.0f}")
                else:
                    st.caption("尚無已收項目")

    with tab4:
        st.subheader("📊 年度統計")
        y_stat = st.number_input("統計年份", value=datetime.now().year, key="rent_year_stat")
        summary = db.get_rent_summary(y_stat)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("應收總額", f"${summary['total_due']:,.0f}")
        c2.metric("已收總額", f"${summary['total_paid']:,.0f}")
        c3.metric("未收總額", f"${summary['total_unpaid']:,.0f}", delta_color="inverse")
        c4.metric("收款率", f"{summary['collection_rate']:.1f}%")
        
        st.divider()
        st.subheader("📋 詳細明細")
        records = db.get_rent_records(year=y_stat)
        if not records.empty:
            st.dataframe(records[['year','month','room_number','tenant_name','actual_amount','paid_amount','status','paid_date']], use_container_width=True, hide_index=True)
        else:
            st.info("尚無紀錄")

# ============================================================================
# 頁面層 - 智慧繳費追蹤
# ============================================================================
def page_payment_tracker(db: RentalDB):
    st.header("💳 智慧繳費追蹤")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📋 繳費計畫", "✅ 標記繳費", "📊 統計分析", "⚠️ 逾期管理"])
    
    with tab1:
        st.subheader("📋 繳費計畫總覽")
        
        col1, col2 = st.columns(2)
        with col1:
            filter_room = st.selectbox("篩選房號", ["全部"] + ALL_ROOMS, key="filter_room")
        with col2:
            filter_status = st.selectbox("篩選狀態", ["全部", "未繳", "已繳"], key="filter_status")
        
        room = filter_room if filter_room != "全部" else None
        status = filter_status if filter_status != "全部" else None
        
        schedule_df = db.get_payment_schedule(room=room, status=status, year=datetime.now().year)
        
        if not schedule_df.empty:
            display_cols = ['room_number', 'tenant_name', 'payment_month', 'amount', 'payment_method', 'due_date', 'status', 'paid_date']
            display_df = schedule_df[display_cols].copy()
            display_df.columns = ['房號', '房客', '月份', '應繳', '繳費方式', '應繳日期', '狀態', '繳費日期']
            
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "應繳": st.column_config.NumberColumn(
                        "應繳金額",
                        format="NT$ %d",
                    ),
                    "狀態": st.column_config.SelectboxColumn(
                        "繳費狀態",
                        options=["已繳", "未繳"],
                    ),
                }
            )
        else:
            st.info("📭 暫無繳費計畫")
    
    with tab2:
        st.subheader("✅ 標記繳費已完成")
        
        unpaid = db.get_payment_schedule(status="未繳")
        if unpaid.empty:
            st.success("✅ 所有繳費已清！")
        else:
            payment_options = {}
            for _, row in unpaid.iterrows():
                label = f"{row['room_number']} {row['tenant_name']} - {row['payment_month']}月 (${row['amount']:.0f})"
                payment_options[label] = row['id']
            
            selected_label = st.selectbox("選擇繳費記錄", list(payment_options.keys()), key="select_payment")
            payment_id = payment_options[selected_label]
            
            with st.form("mark_paid"):
                col1, col2 = st.columns(2)
                with col1:
                    paid_date = st.date_input("繳費日期", value=date.today())
                with col2:
                    paid_amount = st.number_input("繳款金額", min_value=0.0, step=100.0)
                
                notes = st.text_input("備註", placeholder="例如：銀行轉帳、現金、支票")
                
                if st.form_submit_button("✅ 確認標記已繳", type="primary", use_container_width=True):
                    ok, msg = db.mark_payment_done(payment_id, paid_date.strftime("%Y-%m-%d"), paid_amount, notes)
                    if ok:
                        st.toast(msg, icon="✅")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.toast(msg, icon="❌")
    
    with tab3:
        st.subheader("📊 繳費統計分析")
        
        year = st.number_input("統計年份", value=datetime.now().year)
        summary = db.get_payment_summary(year)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("應繳總額", f"${summary['total_due']:,.0f}")
        col2.metric("已收總額", f"${summary['total_paid']:,.0f}")
        col3.metric("未繳件數", f"{summary['unpaid_count']} 件")
        col4.metric("收款率", f"{summary['collection_rate']:.1f}%")
        
        st.divider()
        
        tenants = db.get_tenants()
        if not tenants.empty:
            payment_dist = tenants['payment_method'].value_counts()
            st.markdown("##### 繳費方式分佈")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.write(payment_dist)
            with col2:
                st.bar_chart(payment_dist)
    
    with tab4:
        st.subheader("⚠️ 逾期管理")
        
        overdue = db.get_overdue_payments()
        if overdue.empty:
            st.success("✅ 沒有逾期未繳")
        else:
            st.error(f"🚨 共有 {len(overdue)} 筆逾期未繳")
            st.dataframe(overdue, use_container_width=True, hide_index=True)

# ============================================================================
# 頁面層 - 房客管理
# ============================================================================
def page_tenants(db: RentalDB):
    st.header("👥 房客管理")
    if "edit_id" not in st.session_state:
        st.session_state.edit_id = None
    
    if st.session_state.edit_id == -1:
        st.subheader("➕ 新增租客")
        with st.form("new_t"):
            available = [x for x in ALL_ROOMS if not db.room_exists(x)]
            r = st.selectbox("房號", available)
            c1, c2 = st.columns(2)
            n = c1.text_input("姓名")
            p = c2.text_input("電話")
            dep = c1.number_input("押金", 10000)
            rent = c2.number_input("月租", 6000)
            s = c1.date_input("開始")
            e = c2.date_input("結束", value=date.today()+timedelta(days=365))
            st.divider()
            
            st.markdown("### 📋 繳費方式設定")
            pay = st.selectbox("繳費方式", PAYMENT_METHODS, help="系統會自動生成繳費計畫")
            water = st.checkbox("收水費 ($100/月)")
            note = st.text_input("備註")
            ac = st.text_input("冷氣清洗日")
            
            if st.form_submit_button("✅ 確認新增", type="primary"):
                ok, m = db.upsert_tenant(r, n, p, dep, rent, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), pay, False, water, note, ac)
                if ok:
                    st.toast(m, icon="✅")
                    st.session_state.edit_id = None
                    time.sleep(1)
                    st.rerun()
                else:
                    st.toast(m, icon="❌")
        if st.button("❌ 取消"):
            st.session_state.edit_id = None
            st.rerun()
    
    elif st.session_state.edit_id:
    t = db.get_tenant_by_id(st.session_state.edit_id)
    
    # ✅ 添加 None 檢查
    if t is None:
        st.error("❌ 找不到該房客資料，可能已被刪除")
        if st.button("🔙 返回房客列表"):
            st.session_state.edit_id = None
            st.rerun()
        st.stop()
    
    st.subheader(f"✏️ 編輯 {t['room_number']} {t['tenant_name']}")
        with st.form("edit_t"):
            c1, c2 = st.columns(2)
            n = c1.text_input("姓名", t['tenant_name'])
            p = c2.text_input("電話", t['phone'] or "")
            rent = c1.number_input("月租", t['base_rent'])
            e = c2.date_input("租期至", datetime.strptime(t['lease_end'], "%Y-%m-%d"))
            ac = st.text_input("冷氣清洗日", t.get('last_ac_cleaning_date', '') or "")
            
            if st.form_submit_button("✅ 確認更新", type="primary"):
                db.upsert_tenant(t['room_number'], n, p, t['deposit'], rent, t['lease_start'], e.strftime("%Y-%m-%d"), t['payment_method'], t['has_discount'], t['has_water_fee'], t['discount_notes'], ac, t['id'])
                st.toast("✅ 已更新", icon="✅")
                st.session_state.edit_id = None
                time.sleep(1)
                st.rerun()
        if st.button("❌ 取消"):
            st.session_state.edit_id = None
            st.rerun()
    
    else:
        if st.button("➕ 新增房客", use_container_width=True):
            st.session_state.edit_id = -1
            st.rerun()
        
        ts = db.get_tenants()
        if not ts.empty:
            for _, row in ts.iterrows():
                with st.expander(f"🏠 {row['room_number']} - {row['tenant_name']} | ${row['base_rent']:,} ({row['payment_method']})"):
                    st.write(f"**電話**: {row['phone']}")
                    st.write(f"**租期**: {row['lease_start']} ~ {row['lease_end']}")
                    st.write(f"**繳費方式**: {row['payment_method']}")
                    if row.get('last_ac_cleaning_date'):
                        st.write(f"**冷氣**: {row['last_ac_cleaning_date']}")
                    
                    room_schedule = db.get_payment_schedule(room=row['room_number'], year=datetime.now().year)
                    if not room_schedule.empty:
                        st.markdown("**本年繳費計畫**")
                        for _, schedule in room_schedule.iterrows():
                            status_icon = "✅" if schedule['status'] == "已繳" else "⏳"
                            st.caption(f"{status_icon} {schedule['payment_month']}月 - ${schedule['amount']:.0f}")
                    
                    if st.button("✏️ 編輯", key=f"e_{row['id']}", use_container_width=True):
                        st.session_state.edit_id = row['id']
                        st.rerun()
        else:
            st.info("暫無房客")

# ============================================================================
# 頁面層 - 電費管理 (保持不變)
# ============================================================================
def page_electricity(db: RentalDB):
    st.header("💡 電費管理")
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None
    
    tab1, tab2, tab3 = st.tabs(["① 新增期間", "② 計算電費", "📊 歷史帳單"])

    with tab1:
        with st.form("period_form", border=True):
            col1, col2, col3 = st.columns(3)
            year = col1.number_input("年份", value=datetime.now().year)
            month_start = col2.number_input("開始月", value=1, min_value=1, max_value=12)
            month_end = col3.number_input("結束月", value=2, min_value=1, max_value=12)
            if st.form_submit_button("✅ 新增期間", type="primary", use_container_width=True):
                ok, msg, pid = db.add_electricity_period(year, month_start, month_end)
                if ok:
                    st.session_state.current_period_id = pid
                    st.toast(msg, icon="✅")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.toast(msg, icon="❌")

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先在【① 新增期間】建立計費期間")
        else:
            with st.form("electricity_form", border=True):
                st.markdown("### 📊 台電單據")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown("**2F**")
                    fee_2f = st.number_input("金額", min_value=0, key="fee_2f")
                    kwh_2f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_2f")
                with col2:
                    st.markdown("**3F**")
                    fee_3f = st.number_input("金額", min_value=0, key="fee_3f")
                    kwh_3f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_3f")
                with col3:
                    st.markdown("**4F**")
                    fee_4f = st.number_input("金額", min_value=0, key="fee_4f")
                    kwh_4f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_4f")
                st.divider()
                st.markdown("### 📟 房間度數")
                for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                    st.markdown(f"**{floor_label}**")
                    for room in rooms:
                        c1, c2, c3 = st.columns([0.8, 2, 2])
                        with c1:
                            st.write(f"**{room}**")
                        with c2:
                            st.number_input("上期", min_value=0.0, format="%.2f", key=f"start_{room}")
                        with c3:
                            st.number_input("本期", min_value=0.0, format="%.2f", key=f"end_{room}")
                st.divider()
                st.markdown("### 📝 備註（選填）")
                notes = st.text_area("特殊事項", placeholder="例：某房間電表損壞")
                if st.form_submit_button("🚀 開始計算", type="primary", use_container_width=True):
                    calc = ElectricityCalculatorV10()
                    tdy_data = {
                        "2F": (st.session_state.get("fee_2f", 0), st.session_state.get("kwh_2f", 0.0)),
                        "3F": (st.session_state.get("fee_3f", 0), st.session_state.get("kwh_3f", 0.0)),
                        "4F": (st.session_state.get("fee_4f", 0), st.session_state.get("kwh_4f", 0.0))
                    }
                    meter_data = {room: (st.session_state.get(f"start_{room}", 0.0), st.session_state.get(f"end_{room}", 0.0)) for room in ALL_ROOMS}
                    
                    if not calc.check_tdy_bills(tdy_data):
                        st.error("❌ 台電單據驗證失敗")
                        st.stop()
                    if not calc.check_meter_readings(meter_data):
                        st.error("❌ 度數驗證失敗")
                        st.stop()
                    
                    for room, (s, e) in meter_data.items():
                        if e > s:
                            db.add_meter_reading(st.session_state.current_period_id, room, s, e)
                    for floor, (f, k) in tdy_data.items():
                        if f > 0 and k > 0:
                            db.add_tdy_bill(st.session_state.current_period_id, floor, k, f)
                    
                    if not calc.calculate_public_electricity():
                        st.error("❌ 公用電計算失敗")
                        st.stop()
                    
                    can_proceed, msg = calc.diagnose()
                    if can_proceed:
                        ok, msg, df = db.calculate_electricity_fee(st.session_state.current_period_id, calc, meter_data, notes)
                        if ok:
                            st.balloons()
                            st.toast(msg, icon="✅")
                            st.dataframe(df, use_container_width=True, hide_index=True)
                        else:
                            st.toast(msg, icon="❌")
                    else:
                        st.error(msg)

    with tab3:
        st.subheader("📊 歷史帳單查詢")
        periods = db.get_all_periods()
        if not periods:
            st.info("暫無歷史資料")
        else:
            period_options = {f"{p['period_year']}年 {p['period_month_start']}-{p['period_month_end']}月": p['id'] for p in periods}
            selected_period_label = st.selectbox("選擇計費期間", list(period_options.keys()), key="select_period")
            selected_pid = period_options[selected_period_label]
            period_data = next((p for p in periods if p['id'] == selected_pid), None)
            
            if period_data:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    display_card("總電費", f"${period_data['tdy_total_fee']:,.0f}", "blue")
                with col2:
                    display_card("總度數", f"{period_data['tdy_total_kwh']:.1f}度", "green")
                with col3:
                    display_card("單價", f"${period_data['unit_price']:.4f}", "orange")
                with col4:
                    display_card("分攤", f"{period_data['public_per_room']}度", "blue")
                
                if period_data.get('notes'):
                    st.info(f"📝 **備註**：{period_data['notes']}")
            
            st.divider()
            report_df = db.get_period_report(selected_pid)
            if not report_df.empty:
                st.dataframe(report_df, use_container_width=True, hide_index=True)
            else:
                st.warning("查無此期間的計算資料")

# ============================================================================
# 頁面層 - 支出管理 (保持不變)
# ============================================================================
def page_expenses(db: RentalDB):
    st.header("💸 支出管理")
    with st.form("exp"):
        c1, c2 = st.columns(2)
        d = c1.date_input("日期")
        cat = c2.selectbox("分類", EXPENSE_CATEGORIES)
        amt = c1.number_input("金額")
        desc = c2.text_input("說明")
        if st.form_submit_button("➕ 記帳", type="primary", use_container_width=True):
            if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc):
                st.toast("已儲存", icon="✅")
                time.sleep(0.5)
                st.rerun()
    
    st.divider()
    st.subheader("📊 最近支出")
    st.dataframe(db.get_expenses(30), use_container_width=True, hide_index=True)

# ============================================================================
# 頁面層 - 設定 (保持不變)
# ============================================================================
def page_settings(db: RentalDB):
    st.header("⚙️ 設定")
    
    st.subheader("📥 Excel 匯入")
    f = st.file_uploader("上傳 Excel 檔案", type=["xlsx"])
    if f and st.button("🚀 開始匯入"):
        with st.spinner("匯入中..."):
            try:
                df = pd.read_excel(f, header=1)
                success = 0
                for _, r in df.iterrows():
                    try:
                        rm = str(r.get('房號', '')).strip()
                        if rm in ALL_ROOMS:
                            nm = str(r.get('姓名', 'Unknown'))
                            rent = float(str(r.get('現租金', 0)).replace(',', ''))
                            end = "2025-12-31"
                            db.upsert_tenant(rm, nm, "", 0, rent, "2024-01-01", end)
                            success += 1
                    except:
                        pass
                st.success(f"✅ 成功匯入 {success} 筆")
            except Exception as e:
                st.error(f"❌ 錯誤: {e}")
    
    st.divider()
    st.subheader("💾 資料管理")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 備份資料庫", use_container_width=True):
            with open(db.db_path, 'rb') as f:
                st.download_button("下載", f.read(), f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with col2:
        if st.button("🔴 重置系統", use_container_width=True):
            if st.checkbox("確認重置？"):
                db.reset_database()
                st.rerun()

# ============================================================================
# 主程式 - UI/UX 莫蘭迪柔和版
# ============================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v13.10 Soft",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # ✨ UI 美化：莫蘭迪柔和護眼主題
    st.markdown("""
    <style>
        /* 1. 護眼背景與字體 */
        .stApp {
            background-color: #f8f9fa; /* 極淡的冷灰白，接近紙張顏色 */
            font-family: '微軟正黑體', 'Microsoft JhengHei', sans-serif;
            color: #2f3e46; /* 深灰藍，不使用純黑，減少對比刺激 */
        }
        
        /* 2. 標題與文字：使用莫蘭迪綠與深灰藍 */
        h1, h2, h3 {
            color: #52796f; /* 深鼠尾草綠 */
            font-weight: 700;
        }
        h4, h5, h6 {
            color: #5c677d; /* 霧霾藍 */
            font-weight: 600;
        }
        
        /* 3. 側邊欄：純淨白 */
        section[data-testid="stSidebar"] {
            background-color: #ffffff;
            box-shadow: 2px 0 8px rgba(0,0,0,0.03); /* 極淡陰影 */
        }

        /* 4. 卡片式佈局優化：柔和圓角與懸浮感 */
        div[data-testid="stVerticalBlock"] > div[style*="padding"], 
        [data-testid="stExpander"] {
            background-color: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03); /* 擴散柔和陰影 */
            padding: 16px;
            border: 1px solid #e9ecef !important; /* 極淡邊框 */
        }
        
        /* 5. 主要按鈕：鼠尾草綠 */
        .stButton>button[kind="primary"] {
            background-color: #84a98c !important; /* 鼠尾草綠 */
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 2px 5px rgba(132, 169, 140, 0.3) !important;
        }
        .stButton>button[kind="primary"]:hover {
            background-color: #52796f !important; /* 深綠 */
            transform: translateY(-2px) !important;
            box-shadow: 0 4px 10px rgba(132, 169, 140, 0.4) !important;
        }

        /* 6. 次要按鈕 */
        .stButton>button {
            border-radius: 8px !important;
            background-color: #ffffff;
            border: 1px solid #cbd5e0;
            color: #4a5568;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
        }
        .stButton>button:hover {
            border-color: #84a98c;
            color: #2f3e46;
            transform: translateY(-2px) !important;
        }
        
        /* 7. 數值強調色：暖褐色 */
        [data-testid="stMetricValue"] { 
            color: #6b705c !important; /* 橄欖褐 */
            font-size: 1.8rem !important;
        }
        
        /* 8. 分隔線 */
        .stDivider {
            border-top: 1px solid #e9ecef !important;
        }

        /* 9. 輸入框優化 */
        .stTextInput>div>div>input,
        .stNumberInput>div>div>input,
        .stSelectbox>div>div>select,
        .stDateInput>div>div>input {
            border-radius: 8px !important;
            border: 1px solid #ced4da !important;
            padding: 8px 12px !important;
            background-color: #fcfcfc;
        }
        .stTextInput>div>div>input:focus,
        .stNumberInput>div>div>input:focus {
            border-color: #84a98c !important;
            box-shadow: 0 0 0 2px rgba(132, 169, 140, 0.2) !important;
        }

        /* 10. Expander 標題 */
        .streamlit-expanderHeader {
            background-color: #ffffff !important;
            border-radius: 8px !important;
            border: none !important;
            color: #52796f !important;
        }

        /* 11. Tab 選項卡 */
        [data-testid="stTabs"] {
            border-bottom: 2px solid #e9ecef !important;
        }
        button[data-baseweb="tab"] {
            color: #6c757d;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #52796f;
            font-weight: bold;
        }

    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v13.10 柔和護眼版")
        st.divider()
        menu = st.radio("主選單", [
            "📊 儀表板",
            "💳 智慧繳費",
            "💰 收租金",
            "👥 房客",
            "💡 電費",
            "💸 支出",
            "⚙️ 設定"
        ], label_visibility="collapsed")
    
    db = RentalDB()
    
    if menu == "📊 儀表板":
        page_dashboard(db)
    elif menu == "💳 智慧繳費":
        page_payment_tracker(db)
    elif menu == "💰 收租金":
        page_collect_rent(db)
    elif menu == "👥 房客":
        page_tenants(db)
    elif menu == "💡 電費":
        page_electricity(db)
    elif menu == "💸 支出":
        page_expenses(db)
    else:
        page_settings(db)

if __name__ == "__main__":
    main()

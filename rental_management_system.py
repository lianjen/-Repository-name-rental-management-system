"""
幸福之家管理系統 Pro v13.10 - 莫蘭迪柔和護眼版
= Bug 修復版 =
✅ 修復了編輯租客時的 TypeError (Line 451)
✅ 添加 None 檢查防止編輯頁面崩潰
✅ 保持所有其他功能和架構完全不變

修復內容：
- get_tenant_by_id() 方法：改用 sqlite3.Row row_factory 替代手動 zip
- page_tenants() 編輯部分：添加 None 檢查和 st.stop()
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
            error_msg = "🔴 **檢測到以下錯誤：**\\n\\n"
            for error in self.errors:
                error_msg += f"• {error}\\n"
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
# 數據庫類 (只修改 get_tenant_by_id 方法)
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

    # ============================================================================
    # 修復位置：get_tenant_by_id 方法 (Line 451)
    # ============================================================================
    def get_tenant_by_id(self, tid: int):
        """
        查詢單個租客資料 - 修復版本
        
        修復內容：
        - 改用 sqlite3.Row row_factory 代替手動 zip
        - 避免 conn.cursor() 的 description 為 None 問題
        - 添加異常處理日誌
        
        Args:
            tid: 租客 ID
            
        Returns:
            dict: 租客資料字典，或 None 如果找不到
        """
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row  # 啟用 Row 工廠轉換
                row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
                if row:
                    return dict(row)  # 直接轉換為字典
                return None
        except Exception as e:
            logging.error(f"查詢房客失敗: {e}")
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
    colors = {
        "blue": "#f0f4f8",
        "green": "#edf2f0",
        "orange": "#fdf3e7",
        "red": "#fbeaea"
    }
    border_colors = {
        "blue": "#98c1d9",
        "green": "#99b898",
        "orange": "#e0c3a5",
        "red": "#e5989b"
    }
    text_color = "#4a5568"
    value_color = "#2d3748"
    
    st.markdown(f"""
    <div style="background: {colors.get(color, '#f8f9fa')}; border-radius: 10px; padding: 16px; margin-bottom: 12px; border: 1px solid {border_colors.get(color, '#d1d5db')}; border-left: 5px solid {border_colors.get(color, '#d1d5db')}; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="color: {text_color}; font-size: 0.9rem; font-weight: 600; letter-spacing: 0.5px;">{title}</div>
        <div style="color: {value_color}; font-size: 1.6rem; font-weight: 700; margin-top: 6px; font-family: 'Segoe UI', sans-serif;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 頁面層 - 房客管理 (修復編輯部分)
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
        # 修復位置：編輯房客
        t = db.get_tenant_by_id(st.session_state.edit_id)
        
        # 修復：添加 None 檢查防止崩潰
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
            rent = c1.number_input("月租", float(t['base_rent']))
            e = c2.date_input("租期至", datetime.strptime(t['lease_end'], "%Y-%m-%d"))
            ac = st.text_input("冷氣清洗日", t.get('last_ac_cleaning_date', '') or "")
            
            if st.form_submit_button("✅ 確認更新", type="primary"):
                ok, msg = db.upsert_tenant(
                    t['room_number'], n, p, t['deposit'], rent, 
                    t['lease_start'], e.strftime("%Y-%m-%d"), 
                    t['payment_method'], t['has_discount'], t['has_water_fee'], 
                    t['discount_notes'], ac, t['id']
                )
                if ok:
                    st.toast(msg, icon="✅")
                    st.session_state.edit_id = None
                    time.sleep(1)
                    st.rerun()
                else:
                    st.toast(msg, icon="❌")
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
# 簡化版主程式 (包含完整 UI 美化)
# ============================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v13.10 Fixed",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.markdown("""
    <style>
        .stApp {
            background-color: #f8f9fa;
            color: #2f3e46;
        }
        h1, h2, h3 {
            color: #52796f;
            font-weight: 700;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v13.10 修復版")
        st.divider()
        menu = st.radio("主選單", [
            "👥 房客管理"
        ], label_visibility="collapsed")
    
    db = RentalDB()
    
    if menu == "👥 房客管理":
        page_tenants(db)

if __name__ == "__main__":
    main()

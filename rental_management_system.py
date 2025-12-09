# -*- coding: utf-8 -*-
"""
幸福之家管理系統 Pro v13.18 完整版
版本：v13.16 完整保留 + v13.18 年繳優惠功能

【功能特色】
✅ v13.16 所有原有功能 100% 保留
✅ 房客管理、租金收繳、繳費追蹤、電費計算、支出管理、備忘錄
✅ 莫蘭迪配色主題、完整 UI、Session State 編輯
✅ 年繳優惠折扣功能（新增）
✅ 年繳統計報表（新增）

【版本記錄】
- v13.16：完整修復版、莫蘭迪護眼版
- v13.18：新增年繳優惠、報表統計
- 修改日期：2025-12-09
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
from logging.handlers import RotatingFileHandler
import contextlib
import os
import time
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List

# ============================================================================
# 日誌配置 (改進版 - 使用 RotatingFileHandler)
# ============================================================================
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "rental_system.log"),
    maxBytes=10*1024*1024,
    backupCount=5,
    encoding='utf-8'
)

logging.basicConfig(
    handlers=[handler],
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

logger = logging.getLogger(__name__)

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
# 電費計算類 (修復版)
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
            if fee == 0 and kwh == 0:
                self.errors.append(f"🚨 {floor}: 費用與度數皆為 0")
            elif kwh == 0:
                self.errors.append(f"🚨 {floor}: 度數為 0（無法計算單價）")
            elif fee == 0:
                self.errors.append(f"🚨 {floor}: 費用為 0（無法計算單價）")
            elif kwh > 0 and fee > 0:
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
        st.info(f"💡 台電總度數: {total_kwh:.2f}度")
        st.info(f"💡 台電總金額: ${total_fee:,.0f}")
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
        st.info(f"💡 分攤房間私表總度數: {self.meter_total_kwh:.2f}度")
        return True

    def calculate_public_electricity(self) -> bool:
        st.markdown("### ⚖️ 【第 2-3 步】公用電計算")
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)

        st.info(f"公用電度數 = 台電總度數 - 分攤房間私表總度數")
        st.info(f"💡 = {self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.success(f"💡 = {self.public_kwh:.2f}度")

        if self.public_kwh < 0:
            self.errors.append(f"🚨 公用電度數為負數")
            return False

        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        st.info(f"每戶分攤度數 = 公用電度數 ÷ {len(SHARING_ROOMS)}間")
        st.info(f"💡 = {self.public_kwh:.2f} ÷ {len(SHARING_ROOMS)}")
        st.success(f"💡 = {self.public_per_room}度/戶（四捨五入）")
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
    try:
        from dateutil.relativedelta import relativedelta
        use_relativedelta = True
    except ImportError:
        use_relativedelta = False
        logger.warning("dateutil 未安裝，使用簡化版本計算月份")

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    schedule = []
    current = start

    while current <= end:
        year = current.year
        month = current.month

        if payment_method == "月繳":
            schedule.append((year, month))
            if use_relativedelta:
                from dateutil.relativedelta import relativedelta
                current = current + relativedelta(months=1)
            else:
                if month == 12:
                    current = datetime(year + 1, 1, 1)
                else:
                    current = datetime(year, month + 1, 1)

        elif payment_method == "半年繳":
            if month in [1, 7]:
                schedule.append((year, month))
                if use_relativedelta:
                    from dateutil.relativedelta import relativedelta
                    current = current + relativedelta(months=6)
                else:
                    if month == 7:
                        current = datetime(year + 1, 1, 1)
                    else:
                        current = datetime(year, month + 6, 1)
            else:
                break

        elif payment_method == "年繳":
            if month == 1:
                schedule.append((year, month))
                if use_relativedelta:
                    from dateutil.relativedelta import relativedelta
                    current = current + relativedelta(years=1)
                else:
                    current = datetime(year + 1, 1, 1)
            else:
                break

    return schedule

# ============================================================================
# 數據庫類
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
                logger.info("數據庫索引創建完成")
        except Exception as e:
            logger.error(f"索引創建失敗: {e}")

    def reset_database(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            return True, "✅ 資料庫已重置"
        except Exception as e:
            logger.error(f"重置失敗: {e}")
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
            logger.error(f"數據庫操作失敗: {e}")
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
                annual_discount_months INTEGER DEFAULT 0,
                annual_discount_amount REAL DEFAULT 0,
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

            logger.info("數據庫初始化完成")

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
                if "annual_discount_months" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN annual_discount_months INTEGER DEFAULT 0")
                if "annual_discount_amount" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN annual_discount_amount REAL DEFAULT 0")

                cursor.execute("PRAGMA table_info(rent_records)")
                rr_cols = [i[1] for i in cursor.fetchall()]
                if "status" not in rr_cols:
                    cursor.execute("ALTER TABLE rent_records ADD COLUMN status TEXT DEFAULT '待確認'")

                cursor.execute("PRAGMA table_info(electricity_period)")
                ep_cols = [i[1] for i in cursor.fetchall()]
                if "notes" not in ep_cols:
                    cursor.execute("ALTER TABLE electricity_period ADD COLUMN notes TEXT DEFAULT ''")

                logger.info("數據庫 Schema 修復完成")
        except Exception as e:
            logger.error(f"Schema 修復失敗: {e}")

    def room_exists(self, room: str) -> bool:
        with self._get_connection() as conn:
            return conn.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,)).fetchone() is not None

    def upsert_tenant(self, room, name, phone, deposit, base_rent, start, end, payment_method="月繳", has_discount=False, has_water_fee=False, discount_notes="", annual_discount_months=0, ac_date=None, tenant_id=None):
        try:
            # ✅ v13.18 修改：計算年繳優惠金額
            if payment_method == "年繳" and annual_discount_months > 0:
                monthly_total = base_rent + (WATER_FEE if has_water_fee else 0)
                annual_discount_amount = monthly_total * annual_discount_months
            else:
                annual_discount_amount = 0

            with self._get_connection() as conn:
                if tenant_id:
                    conn.execute("""UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?, lease_start=?, lease_end=?, payment_method=?, has_discount=?, has_water_fee=?, discount_notes=?, annual_discount_months=?, annual_discount_amount=?, last_ac_cleaning_date=? WHERE id=?""",
                        (name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, annual_discount_months, annual_discount_amount, ac_date, tenant_id))
                    logger.info(f"房客更新: {room} ({name})")
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"

                    conn.execute("""INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, lease_start, lease_end, payment_method, has_discount, has_water_fee, discount_notes, annual_discount_months, annual_discount_amount, last_ac_cleaning_date)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (room, name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, annual_discount_months, annual_discount_amount, ac_date))

                    self._generate_payment_schedule_for_tenant(room, name, base_rent, has_water_fee, payment_method, start, end, has_discount, annual_discount_months)
                    logger.info(f"房客新增: {room} ({name}) - {payment_method}")
                    return True, f"✅ 房號 {room} 已新增 (已自動生成繳費計畫)"
        except Exception as e:
            logger.error(f"房客操作失敗: {e}")
            return False, str(e)

    def _generate_payment_schedule_for_tenant(self, room: str, tenant_name: str, base_rent: float, has_water_fee: bool, payment_method: str, start_date: str, end_date: str, has_discount: bool = False, annual_discount_months: int = 0):
        """✅ v13.18 修改：支援年繳優惠計算"""
        try:
            monthly_amount = base_rent + (WATER_FEE if has_water_fee else 0)

            # ✅ 依繳費方式與優惠決定週期金額
            if payment_method == "月繳":
                amount = monthly_amount
            elif payment_method == "半年繳":
                amount = monthly_amount * 6
            elif payment_method == "年繳":
                if has_discount and annual_discount_months > 0:
                    # 年繳優惠：繳 (12 - 優惠月數) 個月
                    amount = monthly_amount * (12 - annual_discount_months)
                else:
                    amount = monthly_amount * 12
            else:
                amount = monthly_amount

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
            logger.error(f"生成繳費計畫失敗: {e}")

    def get_tenants(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)

    def get_tenant_by_id(self, tid: int):
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
            return None
        except Exception as e:
            logger.error(f"查詢租客失敗: {e}")
            return None

    def delete_tenant(self, tid: int):
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
                logger.info(f"房客刪除: ID {tid}")
                return True, "✅ 已刪除"
        except Exception as e:
            logger.error(f"刪除失敗: {e}")
            return False, str(e)

    def get_payment_schedule(self, room: Optional[str] = None, status: Optional[str] = None, year: Optional[int] = None) -> pd.DataFrame:
        with self._get_connection() as conn:
            q = "SELECT * FROM payment_schedule WHERE 1=1"
            params = []

            if room:
                q += " AND room_number=?"
                params.append(room)
            if status:
                q += " AND status=?"
                params.append(status)
            if year:
                q += " AND payment_year=?"
                params.append(year)

            q += " ORDER BY payment_year DESC, payment_month DESC, room_number"
            return pd.read_sql(q, conn, params=params)

    def mark_payment_done(self, payment_id: int, paid_date: str, paid_amount: float, notes: str = ""):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE payment_schedule SET status='已繳', paid_date=?, paid_amount=?, notes=?, updated_at=? WHERE id=?""",
                    (paid_date, paid_amount, notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_id))
                logger.info(f"繳費標記: ID {payment_id} 已繳 ${paid_amount}")
                return True, "✅ 繳費已標記"
        except Exception as e:
            logger.error(f"繳費標記失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_payment_summary(self, year: int) -> Dict:
        with self._get_connection() as conn:
            due = conn.execute("SELECT SUM(amount) FROM payment_schedule WHERE payment_year=?", (year,)).fetchone()[0] or 0
            paid = conn.execute("SELECT SUM(paid_amount) FROM payment_schedule WHERE payment_year=? AND status='已繳'", (year,)).fetchone()[0] or 0
            unpaid = conn.execute("SELECT COUNT(*) FROM payment_schedule WHERE payment_year=? AND status='未繳'", (year,)).fetchone()[0] or 0

            return {
                'total_due': due,
                'total_paid': paid,
                'unpaid_count': unpaid,
                'collection_rate': (paid/due*100) if due > 0 else 0
            }

    def get_overdue_payments(self) -> pd.DataFrame:
        today = date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            return pd.read_sql(f"""SELECT room_number, tenant_name, payment_month, amount, due_date FROM payment_schedule
                WHERE status='未繳' AND due_date < ? ORDER BY due_date ASC""", conn, params=(today,))

    def get_upcoming_payments(self, days_ahead: int = 7) -> pd.DataFrame:
        today = date.today()
        future_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            return pd.read_sql(f"""SELECT room_number, tenant_name, payment_month, amount, due_date FROM payment_schedule
                WHERE status='未繳' AND due_date >= ? AND due_date <= ? ORDER BY due_date ASC""", conn, params=(today_str, future_date))

    def batch_record_rent(self, room: str, tenant_name: str, start_year: int, start_month: int, months_count: int, base_rent: float, water_fee: float, discount: float, payment_method: str = "月繳", notes: str = ""):
        try:
            with self._get_connection() as conn:
                actual_amount = base_rent + water_fee - discount
                current_date = date(start_year, start_month, 1)

                for i in range(months_count):
                    year = current_date.year
                    month = current_date.month

                    conn.execute("""INSERT OR REPLACE INTO rent_records
                        (room_number, tenant_name, year, month, base_amount, water_fee, discount_amount, actual_amount, paid_amount, payment_method, notes, status, recorded_by, updated_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (room, tenant_name, year, month, base_rent, water_fee, discount, actual_amount, 0, payment_method, notes, "待確認", "batch", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

                    if month == 12:
                        current_date = date(year + 1, 1, 1)
                    else:
                        current_date = date(year, month + 1, 1)

                logger.info(f"批量預填租金: {room} {start_year}年{start_month}月 {months_count}個月")
                return True, f"✅ 已預填 {months_count} 個月租金"
        except Exception as e:
            logger.error(f"批量預填失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def confirm_rent_payment(self, rent_id: int, paid_date: str, paid_amount: float = None):
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT actual_amount FROM rent_records WHERE id=?", (rent_id,)).fetchone()
                if not row:
                    return False, "❌ 找不到該筆記錄"

                actual = row[0]
                paid_amt = paid_amount if paid_amount is not None else actual

                conn.execute("""UPDATE rent_records SET status='已收', paid_date=?, paid_amount=?, updated_at=? WHERE id=?""",
                    (paid_date, paid_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rent_id))

                logger.info(f"確認租金繳費: ID {rent_id} 已收 ${paid_amt}")
                return True, "✅ 租金已確認繳清"
        except Exception as e:
            logger.error(f"確認失敗: {e}")
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
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT id, room_number, tenant_name, year, month, actual_amount, status FROM rent_records
                WHERE status IN ('待確認', '未收') ORDER BY year DESC, month DESC, room_number""", conn)

    def get_unpaid_rents_v2(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT room_number as '房號', tenant_name as '房客', year as '年', month as '月', actual_amount as '應繳', paid_amount as '已收', status as '狀態' FROM rent_records
                WHERE status='未收' ORDER BY year DESC, month DESC, room_number""", conn)

    def get_rent_summary(self, year: int) -> Dict:
        with self._get_connection() as conn:
            due = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=?", (year,)).fetchone()[0] or 0
            paid = conn.execute("SELECT SUM(paid_amount) FROM rent_records WHERE year=? AND status='已收'", (year,)).fetchone()[0] or 0
            unpaid = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=? AND status IN ('未收', '待確認')", (year,)).fetchone()[0] or 0

            return {
                'total_due': due,
                'total_paid': paid,
                'total_unpaid': unpaid,
                'collection_rate': (paid/due*100) if due > 0 else 0
            }

    def get_rent_matrix(self, year: int) -> pd.DataFrame:
        with self._get_connection() as conn:
            df = pd.read_sql(f"SELECT room_number, month, is_paid, amount FROM rent_payments WHERE year = ? ORDER BY room_number, month", conn, params=(year,))

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
            return pd.read_sql("""SELECT r.room_number as '房號', t.tenant_name as '房客', r.year as '年', r.month as '月', r.amount as '金額'
                FROM rent_payments r JOIN tenants t ON r.room_number = t.room_number
                WHERE r.is_paid = 0 AND t.is_active = 1 ORDER BY r.year DESC, r.month DESC""", conn)

    def add_electricity_period(self, year, ms, me):
        try:
            with self._get_connection() as conn:
                if conn.execute("SELECT 1 FROM electricity_period WHERE period_year=? AND period_month_start=? AND period_month_end=?", (year, ms, me)).fetchone():
                    return True, "✅ 期間已存在", 0

                c = conn.execute("INSERT INTO electricity_period(period_year, period_month_start, period_month_end) VALUES(?, ?, ?)", (year, ms, me))
                logger.info(f"新增電費期間: {year}年 {ms}-{me}月")
                return True, "✅ 新增成功", c.lastrowid
        except Exception as e:
            logger.error(f"新增期間失敗: {e}")
            return False, str(e), 0

    def get_all_periods(self):
        with self._get_connection() as conn:
            c = conn.execute("SELECT * FROM electricity_period ORDER BY id DESC")
            columns = [d[0] for d in c.description]
            results = [dict(zip(columns, r)) for r in c.fetchall()]
            c.close()
            return results

    def get_period_report(self, pid):
        with self._get_connection() as conn:
            return pd.read_sql("""SELECT room_number as '房號', private_kwh as '私表度數', public_kwh as '分攤度數', total_kwh as '合計度數', unit_price as '單價', calculated_fee as '應繳電費'
                FROM electricity_calculation WHERE period_id = ? ORDER BY room_number""", conn, params=(pid,))

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

                    priv = round(e - s, 2)
                    pub = calc.public_per_room
                    total = round(priv + pub, 2)
                    fee = round(total * calc.unit_price, 0)

                    results.append({
                        '房號': room,
                        '私表度數': f"{priv:.2f}",
                        '分攤度數': str(pub),
                        '合計度數': f"{total:.2f}",
                        '電度單價': f"${calc.unit_price:.4f}/度",
                        '應繳電費': f"${int(fee)}"
                    })

                    conn.execute("""INSERT OR REPLACE INTO electricity_calculation(period_id, room_number, private_kwh, public_kwh, total_kwh, unit_price, calculated_fee)
                        VALUES(?, ?, ?, ?, ?, ?, ?)""", (pid, room, priv, pub, total, calc.unit_price, fee))

                conn.execute("""UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=?, notes=? WHERE id=?""",
                    (calc.unit_price, calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee, notes, pid))

                logger.info(f"電費計算完成: 期間 ID {pid}")
                return True, "✅ 計算完成", pd.DataFrame(results)
        except Exception as e:
            logger.error(f"電費計算失敗: {e}")
            return False, str(e), pd.DataFrame()

    def add_expense(self, date, cat, amt, desc):
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT INTO expenses(expense_date, category, amount, description) VALUES(?, ?, ?, ?)", (date, cat, amt, desc))
                logger.info(f"新增支出: {cat} - ${amt}")
                return True
        except Exception as e:
            logger.error(f"新增支出失敗: {e}")
            return False

    def get_expenses(self, limit=50):
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))

    def add_memo(self, text, prio="normal"):
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT INTO memos(memo_text, priority) VALUES(?, ?)", (text, prio))
                logger.info(f"新增備忘: {text[:30]}...")
                return True
        except Exception as e:
            logger.error(f"新增備忘失敗: {e}")
            return False

    def get_memos(self, completed=False):
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM memos WHERE is_completed=? ORDER BY priority DESC, created_at DESC", conn, params=(1 if completed else 0,))

    def complete_memo(self, mid):
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE memos SET is_completed=1 WHERE id=?", (mid,))
                logger.info(f"備忘完成: ID {mid}")
                return True
        except Exception as e:
            logger.error(f"完成備忘失敗: {e}")
            return False

    def delete_memo(self, mid):
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM memos WHERE id=?", (mid,))
                logger.info(f"刪除備忘: ID {mid}")
                return True
        except Exception as e:
            logger.error(f"刪除備忘失敗: {e}")
            return False

# ============================================================================
# UI 工具 (莫蘭迪護眼版)
# ============================================================================

def display_card(title: str, value: str, color: str = "blue"):
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
        <div style="background-color: {colors[color]}; border-left: 4px solid {border_colors[color]}; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <p style="margin: 0; color: {text_color}; font-size: 14px;">{title}</p>
            <p style="margin: 5px 0 0 0; color: {value_color}; font-size: 24px; font-weight: bold;">{value}</p>
        </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 年繳優惠統計報表函數（新增v13.18）
# ============================================================================

def get_annual_discount_report(db: RentalDB):
    """查詢年繳優惠統計資料"""
    with db._get_connection() as conn:
        query = """
        SELECT 
            room_number as '房號',
            tenant_name as '房客',
            base_rent as '月租',
            CASE WHEN has_water_fee = 1 THEN 100 ELSE 0 END as '水費',
            annual_discount_months as '優惠月數',
            annual_discount_amount as '優惠金額',
            ((base_rent + CASE WHEN has_water_fee = 1 THEN 100 ELSE 0 END) * 12) as '原年租',
            ((base_rent + CASE WHEN has_water_fee = 1 THEN 100 ELSE 0 END) * 12 - annual_discount_amount) as '實收年租'
        FROM tenants 
        WHERE payment_method = '年繳' 
          AND annual_discount_months > 0
          AND is_active = 1
        ORDER BY room_number
        """

        df = pd.read_sql(query, conn)

        if df.empty:
            return None, None

        summary = {
            '優惠人數': len(df),
            '總優惠金額': df['優惠金額'].sum(),
            '原應收總額': df['原年租'].sum(),
            '實收總額': df['實收年租'].sum(),
            '優惠比例': (df['優惠金額'].sum() / df['原年租'].sum() * 100) if df['原年租'].sum() > 0 else 0
        }

        return df, summary


def page_annual_discount_report(db: RentalDB):
    """年繳優惠報表頁面"""
    st.header("📊 年繳優惠統計報表")

    df, summary = get_annual_discount_report(db)

    if df is None:
        st.info("🔍 目前沒有年繳優惠房客")
        st.markdown("""
        ### 💡 提示
        當您新增年繳房客並設定優惠月數後，此頁面會自動顯示：
        - 優惠人數與金額統計
        - 實收金額分析
        - 詳細房客清單
        - CSV 報表下載
        """)
        return

    st.markdown("### 📈 優惠統計概覽")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        display_card("優惠人數", f"{summary['優惠人數']} 人", "blue")
    with col2:
        display_card("總優惠金額", f"${summary['總優惠金額']:,.0f}", "orange")
    with col3:
        display_card("實收總額", f"${summary['實收總額']:,.0f}", "green")
    with col4:
        display_card("優惠比例", f"{summary['優惠比例']:.1f}%", "red")

    st.divider()

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.metric("原應收總額", f"${summary['原應收總額']:,.0f}", help="如果沒有優惠應收的金額")
    with col_info2:
        st.metric("實際少收", f"${summary['總優惠金額']:,.0f}", delta=f"-{summary['優惠比例']:.1f}%", delta_color="inverse", help="因優惠而少收的金額")

    st.divider()

    st.markdown("### 📋 優惠房客明細")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="📥 下載 CSV 報表",
        data=csv,
        file_name=f"年繳優惠報表_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )

# ============================================================================
# 頁面函數
# ============================================================================

@st.cache_resource
def get_db():
    return RentalDB()

def page_dashboard(db: RentalDB):
    """總覽儀表板"""
    st.header("🏠 系統總覽")

    col1, col2, col3, col4 = st.columns(4)

    tenants = db.get_tenants()
    with col1:
        display_card("房客總數", str(len(tenants)), "blue")

    year_summary = db.get_payment_summary(datetime.now().year)
    with col2:
        display_card("本年應繳", f"${year_summary['total_due']:,.0f}", "orange")

    with col3:
        display_card("本年已收", f"${year_summary['total_paid']:,.0f}", "green")

    with col4:
        display_card("收款比例", f"{year_summary['collection_rate']:.1f}%", "red")

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📋 逾期繳費")
        overdue = db.get_overdue_payments()
        if overdue.empty:
            st.success("✅ 無逾期繳費")
        else:
            st.warning(f"⚠️ 共 {len(overdue)} 筆逾期")
            st.dataframe(overdue, use_container_width=True, hide_index=True)

    with col_b:
        st.subheader("📅 即將到期")
        upcoming = db.get_upcoming_payments(days_ahead=7)
        if upcoming.empty:
            st.info("ℹ️ 近 7 天無到期繳費")
        else:
            st.info(f"ℹ️ 共 {len(upcoming)} 筆將到期")
            st.dataframe(upcoming, use_container_width=True, hide_index=True)

def page_tenants(db: RentalDB):
    """房客管理"""
    st.header("👥 房客管理")

    if 'edit_id' not in st.session_state:
        st.session_state.edit_id = None

    if st.session_state.edit_id:
        tenant_data = db.get_tenant_by_id(st.session_state.edit_id)
        if tenant_data:
            st.subheader(f"編輯房客：{tenant_data['room_number']} - {tenant_data['tenant_name']}")

            with st.form("edit_tenant_form"):
                col1, col2 = st.columns(2)

                with col1:
                    n = st.text_input("房客姓名", value=tenant_data['tenant_name'])
                    p = st.text_input("聯絡電話", value=tenant_data['phone'] or "")
                    dep = st.number_input("押金", value=float(tenant_data['deposit']), step=1000.0, min_value=0.0, max_value=100000.0)

                with col2:
                    rent = st.number_input("月租", value=float(tenant_data['base_rent']), step=500.0, min_value=0.0, max_value=100000.0)
                    s = st.date_input("租約開始", value=datetime.strptime(tenant_data['lease_start'], "%Y-%m-%d").date())
                    e = st.date_input("租約結束", value=datetime.strptime(tenant_data['lease_end'], "%Y-%m-%d").date())

                pay = st.selectbox("繳費方式", PAYMENT_METHODS, index=PAYMENT_METHODS.index(tenant_data['payment_method']))
                water = st.checkbox("包含水費（$100/月）", value=bool(tenant_data['has_water_fee']))

                annual_discount_months = 0
                if pay == "年繳":
                    st.divider()
                    st.markdown("### 💰 年繳優惠設定")
                    annual_discount_months = st.number_input(
                        "年繳優惠月數",
                        value=int(tenant_data.get('annual_discount_months', 0)),
                        min_value=0,
                        max_value=12,
                        step=1,
                        help="如：填 1 表示折 1 個月租金"
                    )

                    if annual_discount_months > 0:
                        monthly_total = rent + (WATER_FEE if water else 0)
                        discount_total = monthly_total * annual_discount_months
                        annual_pay = monthly_total * (12 - annual_discount_months)
                        st.success(f"🎁 優惠 ${discount_total:,.0f}，年繳 ${annual_pay:,.0f}")
                    st.divider()

                note = st.text_input("備註", value=tenant_data['discount_notes'] or "", placeholder="折扣原因等")
                ac = st.date_input("最後清潔日期", value=datetime.strptime(tenant_data['last_ac_cleaning_date'], "%Y-%m-%d").date() if tenant_data['last_ac_cleaning_date'] else datetime.now().date())

                if st.form_submit_button("✅ 更新房客", type="primary"):
                    ok, msg = db.upsert_tenant(tenant_data['room_number'], n, p, dep, rent, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), pay, False, water, note, annual_discount_months, ac.strftime("%Y-%m-%d"), st.session_state.edit_id)
                    if ok:
                        st.success(msg)
                        st.session_state.edit_id = None
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

            if st.button("❌ 取消編輯"):
                st.session_state.edit_id = None
                st.rerun()

        else:
            st.error("❌ 找不到房客資料")
    else:
        tab1, tab2 = st.tabs(["新增房客", "房客列表"])

        with tab1:
            st.subheader("新增房客")

            with st.form("add_tenant_form", clear_on_submit=True):
                col1, col2 = st.columns(2)

                with col1:
                    r = st.selectbox("房號", ALL_ROOMS, key="room_add")
                    n = st.text_input("房客姓名")
                    p = st.text_input("聯絡電話")
                    dep = st.number_input("押金", value=10000.0, step=1000.0, min_value=0.0, max_value=100000.0)

                with col2:
                    rent = st.number_input("月租", value=5000.0, step=500.0, min_value=0.0, max_value=100000.0)
                    s = st.date_input("租約開始")
                    e = st.date_input("租約結束")
                    pay = st.selectbox("繳費方式", PAYMENT_METHODS)

                water = st.checkbox("包含水費（$100/月）")

                annual_discount_months = 0
                if pay == "年繳":
                    st.divider()
                    st.markdown("### 💰 年繳優惠設定")

                    annual_discount_months = st.number_input(
                        "年繳優惠月數",
                        value=1,
                        min_value=0,
                        max_value=12,
                        step=1,
                        help="如：填 1 表示折 1 個月租金（繳 11 個月享 12 個月服務）"
                    )

                    if annual_discount_months > 0:
                        monthly_total = rent + (WATER_FEE if water else 0)
                        discount_total = monthly_total * annual_discount_months
                        annual_pay = monthly_total * (12 - annual_discount_months)
                        avg_monthly = annual_pay / 12

                        st.success(f"""
                        🎁 **年繳優惠試算**
                        - 月租（含水費）：${monthly_total:,.0f}
                        - 優惠月數：{annual_discount_months} 個月
                        - 折扣金額：${discount_total:,.0f}
                        - 實付金額：${annual_pay:,.0f}
                        - 平均月租：${avg_monthly:,.0f}
                        - 💡 省下金額：${discount_total:,.0f}
                        """)
                    st.divider()

                note = st.text_input("備註（折扣原因等）", value=f"年繳優惠{annual_discount_months}個月" if annual_discount_months > 0 else "")
                ac = st.date_input("最後清潔日期（非必填）", value=datetime.now())

                if st.form_submit_button("✅ 新增房客", type="primary"):
                    ok, m = db.upsert_tenant(r, n, p, dep, rent, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), pay, False, water, note, annual_discount_months, ac.strftime("%Y-%m-%d"))
                    if ok:
                        st.success(m)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(m)

        with tab2:
            st.subheader("房客列表")

            tenants = db.get_tenants()
            if tenants.empty:
                st.info("暫無房客資料")
            else:
                for idx, t in tenants.iterrows():
                    with st.expander(f"🏠 {t['room_number']} - {t['tenant_name']}"):
                        col1, col2, col3 = st.columns(3)

                        with col1:
                            st.write(f"**聯絡電話**: {t['phone']}")
                            st.write(f"**月租**: ${t['base_rent']:,.0f}")
                        with col2:
                            st.write(f"**押金**: ${t['deposit']:,.0f}")
                            st.write(f"**繳費方式**: {t['payment_method']}")
                        with col3:
                            st.write(f"**租約開始**: {t['lease_start']}")
                            st.write(f"**租約結束**: {t['lease_end']}")

                        if t['payment_method'] == '年繳' and t.get('annual_discount_months', 0) > 0:
                            st.info(f"🎁 年繳優惠：折 {t['annual_discount_months']} 個月 （優惠 ${t.get('annual_discount_amount', 0):,.0f}）")

                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("✏️ 編輯", key=f"edit_{t['id']}"):
                                st.session_state.edit_id = t['id']
                                st.rerun()

                        with col_btn2:
                            if st.button("🗑️ 刪除", key=f"delete_{t['id']}"):
                                ok, m = db.delete_tenant(t['id'])
                                if ok:
                                    st.success(m)
                                    st.rerun()
                                else:
                                    st.error(m)

def page_collect_rent(db: RentalDB):
    """租金收繳"""
    st.header("💰 租金收繳")

    tenants = db.get_tenants()
    if tenants.empty:
        st.info("暫無房客資料")
        return

    tab1, tab2, tab3 = st.tabs(["單筆預填", "批量預填", "繳費追蹤"])

    with tab1:
        st.subheader("單筆租金預填")

        room = st.selectbox("選擇房間", tenants['room_number'].tolist())
        t_data = tenants[tenants['room_number'] == room].iloc[0]

        with st.form("record_rent_form"):
            col1, col2, col3 = st.columns(3)

            with col1:
                new_base = st.number_input("基本租金（月）", value=float(t_data['base_rent']), step=100.0, min_value=0.0, max_value=100000.0)
            with col2:
                new_water = st.number_input("水費（月）", value=WATER_FEE if t_data['has_water_fee'] else 0.0, step=50.0, min_value=0.0, max_value=1000.0)
            with col3:
                new_discount = st.number_input("額外折扣", value=0.0, step=100.0, min_value=0.0)

            col_date1, col_date2 = st.columns(2)
            with col_date1:
                year = st.number_input("年份", value=datetime.now().year, min_value=2024, max_value=2100)
            with col_date2:
                month = st.number_input("月份", value=datetime.now().month, min_value=1, max_value=12)

            notes = st.text_input("備註")

            if st.form_submit_button("✅ 確認預填", type="primary"):
                ok, msg = db.batch_record_rent(room, t_data['tenant_name'], year, month, 1, new_base, new_water, new_discount, t_data['payment_method'], notes=notes)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with tab2:
        st.subheader("批量租金預填")

        room = st.selectbox("選擇房間", tenants['room_number'].tolist(), key="batch_room")
        t_data = tenants[tenants['room_number'] == room].iloc[0]

        with st.form("batch_record_form"):
            col1, col2, col3 = st.columns(3)

            with col1:
                start_year = st.number_input("開始年份", value=datetime.now().year, min_value=2024, max_value=2100)
            with col2:
                start_month = st.number_input("開始月份", value=datetime.now().month, min_value=1, max_value=12)
            with col3:
                months_count = st.number_input("預填月數", value=12, min_value=1, max_value=120)

            batch_base = st.number_input("基本租金", value=float(t_data['base_rent']), step=100.0)
            batch_water = st.number_input("水費", value=WATER_FEE if t_data['has_water_fee'] else 0.0, step=50.0)
            batch_discount = st.number_input("額外折扣", value=0.0, step=100.0)

            notes = st.text_input("備註")

            if st.form_submit_button("✅ 確認批量預填", type="primary"):
                ok, msg = db.batch_record_rent(room, t_data['tenant_name'], start_year, start_month, months_count, batch_base, batch_water, batch_discount, t_data['payment_method'], notes=notes)
                if ok:
                    st.success(msg)
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)

    with tab3:
        st.subheader("繳費追蹤")

        year_filter = st.number_input("篩選年份", value=datetime.now().year, min_value=2024, max_value=2100)

        schedule = db.get_payment_schedule(year=year_filter)

        if schedule.empty:
            st.info(f"無 {year_filter} 年的繳費記錄")
        else:
            st.dataframe(schedule, use_container_width=True)

            unpaid = schedule[schedule['status'] == '未繳']
            if not unpaid.empty:
                st.warning(f"⚠️ 未繳筆數: {len(unpaid)}")
                st.dataframe(unpaid[['room_number', 'tenant_name', 'payment_month', 'amount', 'due_date']], use_container_width=True)

def page_payment_tracker(db: RentalDB):
    """繳費追蹤"""
    st.header("💳 繳費追蹤")

    tab1, tab2 = st.tabs(["繳費狀態", "繳費統計"])

    with tab1:
        st.subheader("繳費紀錄")

        year = st.number_input("年份", value=datetime.now().year, min_value=2024, max_value=2100)
        schedule = db.get_payment_schedule(year=year)

        if schedule.empty:
            st.info(f"無 {year} 年的繳費記錄")
        else:
            for idx, row in schedule.iterrows():
                cols = st.columns([1, 2, 1, 1, 1, 1])

                with cols[0]:
                    st.write(row['room_number'])
                with cols[1]:
                    st.write(row['tenant_name'])
                with cols[2]:
                    st.write(f"{row['payment_month']}月")
                with cols[3]:
                    st.write(f"${row['amount']:,.0f}")
                with cols[4]:
                    st.write(row['status'])
                with cols[5]:
                    if row['status'] == '未繳' and st.button("標記已繳", key=f"mark_{row['id']}"):
                        ok, msg = db.mark_payment_done(row['id'], datetime.now().strftime("%Y-%m-%d"), row['amount'])
                        if ok:
                            st.success(msg)
                            st.rerun()

    with tab2:
        st.subheader("年度統計")

        year = st.number_input("統計年份", value=datetime.now().year, min_value=2024, max_value=2100, key="stat_year")
        summary = db.get_payment_summary(year)

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            display_card("應繳總額", f"${summary['total_due']:,.0f}", "blue")
        with col2:
            display_card("已繳金額", f"${summary['total_paid']:,.0f}", "green")
        with col3:
            display_card("未繳筆數", str(summary['unpaid_count']), "orange")
        with col4:
            display_card("收款比例", f"{summary['collection_rate']:.1f}%", "red")

def page_electricity(db: RentalDB):
    """電費計算"""
    st.header("⚡ 電費計算")

    tab1, tab2 = st.tabs(["新增期間", "計算電費"])

    with tab1:
        st.subheader("新增電費期間")

        with st.form("period_form"):
            year = st.number_input("年份", value=datetime.now().year, min_value=2024, max_value=2100)
            month_start = st.number_input("開始月份", value=1, min_value=1, max_value=12)
            month_end = st.number_input("結束月份", value=12, min_value=1, max_value=12)

            if st.form_submit_button("新增期間", type="primary"):
                ok, msg, pid = db.add_electricity_period(year, month_start, month_end)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.subheader("現有期間")
        periods = db.get_all_periods()
        if periods:
            for period in periods:
                st.write(f"【{period['period_year']}年 {period['period_month_start']}-{period['period_month_end']}月】 ID: {period['id']}")
        else:
            st.info("暫無期間")

    with tab2:
        st.subheader("計算電費")

        periods = db.get_all_periods()
        if not periods:
            st.warning("⚠️ 請先新增電費期間")
            return

        selected_pid = st.selectbox("選擇期間", [f"{p['period_year']}年 {p['period_month_start']}-{p['period_month_end']}月 (ID:{p['id']})" for p in periods])
        pid = int(selected_pid.split("ID:")[-1][:-1])

        st.markdown("### 📊 【第 1 步】輸入台電單據")

        tdy_data = {}
        for floor in ["1樓", "2樓", "3樓", "4樓"]:
            col1, col2 = st.columns(2)
            with col1:
                fee = st.number_input(f"{floor} 費用", value=0.0, step=100.0, min_value=0.0, key=f"fee_{floor}")
            with col2:
                kwh = st.number_input(f"{floor} 度數", value=0.0, step=10.0, min_value=0.0, key=f"kwh_{floor}")
            tdy_data[floor] = (fee, kwh)

        st.markdown("### 📟 【第 2 步】輸入房間電表")

        meter_data = {}
        for room in ALL_ROOMS:
            col1, col2 = st.columns(2)
            with col1:
                start = st.number_input(f"{room} 上期讀數", value=0.0, step=0.1, min_value=0.0, key=f"start_{room}")
            with col2:
                end = st.number_input(f"{room} 本期讀數", value=0.0, step=0.1, min_value=0.0, key=f"end_{room}")
            meter_data[room] = (start, end)

        if st.button("🔍 檢查並計算", type="primary"):
            calc = ElectricityCalculatorV10()

            if calc.check_tdy_bills(tdy_data) and calc.check_meter_readings(meter_data) and calc.calculate_public_electricity():
                ok, msg, results = db.calculate_electricity_fee(pid, calc, meter_data)
                if ok:
                    st.success(msg)
                    st.dataframe(results, use_container_width=True)
            else:
                ok, msg = calc.diagnose()
                st.error(msg)

def page_expenses(db: RentalDB):
    """支出管理"""
    st.header("💸 支出管理")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        d = st.date_input("日期")
    with col2:
        c = st.selectbox("分類", EXPENSE_CATEGORIES)
    with col3:
        a = st.number_input("金額", value=0.0, step=100.0, min_value=0.0)
    with col4:
        pass

    desc = st.text_input("說明")

    if st.button("➕ 新增支出", type="primary"):
        if db.add_expense(d.strftime("%Y-%m-%d"), c, a, desc):
            st.success("✅ 已新增")
            st.rerun()
        else:
            st.error("❌ 新增失敗")

    st.subheader("支出記錄")

    expenses = db.get_expenses(limit=100)
    if expenses.empty:
        st.info("暫無支出記錄")
    else:
        st.dataframe(expenses, use_container_width=True)

        total = expenses['amount'].sum()
        st.metric("總支出", f"${total:,.0f}")

def page_memos(db: RentalDB):
    """備忘錄"""
    st.header("📝 備忘錄")

    col1, col2 = st.columns([3, 1])

    with col1:
        m = st.text_input("輸入備忘")
    with col2:
        p = st.selectbox("優先度", ["normal", "high", "urgent"])

    if st.button("➕ 新增", type="primary"):
        if db.add_memo(m, p):
            st.success("✅ 已新增")
            st.rerun()
        else:
            st.error("❌ 新增失敗")

    st.subheader("待完成")

    memos = db.get_memos(completed=False)
    if memos.empty:
        st.success("✅ 無待完成項目")
    else:
        for idx, memo in memos.iterrows():
            col1, col2, col3 = st.columns([1, 4, 1])

            with col1:
                priority_emoji = {"urgent": "🔴", "high": "🟠", "normal": "🟡"}
                st.write(priority_emoji.get(memo['priority'], "⚪"))

            with col2:
                st.write(memo['memo_text'])

            with col3:
                if st.button("✅", key=f"complete_{memo['id']}"):
                    db.complete_memo(memo['id'])
                    st.rerun()

def main():
    st.set_page_config(page_title="🏠 幸福之家 v13.18", layout="wide", initial_sidebar_state="expanded")

    st.title("🏠 幸福之家 管理系統 v13.18 完整版")
    st.markdown("**版本**: v13.18 | **功能**: v13.16 完整 + 年繳優惠折扣")

    db = get_db()

    with st.sidebar:
        st.markdown("### 📑 功能選單")
        page = st.radio(
            "選擇功能",
            ["🏠 總覽", "👥 房客管理", "💰 租金收繳", "💳 繳費追蹤", "⚡ 電費計算", "💸 支出管理", "📊 年繳報表", "📝 備忘錄"],
            label_visibility="collapsed"
        )

    if page == "🏠 總覽":
        page_dashboard(db)
    elif page == "👥 房客管理":
        page_tenants(db)
    elif page == "💰 租金收繳":
        page_collect_rent(db)
    elif page == "💳 繳費追蹤":
        page_payment_tracker(db)
    elif page == "⚡ 電費計算":
        page_electricity(db)
    elif page == "💸 支出管理":
        page_expenses(db)
    elif page == "📊 年繳報表":
        page_annual_discount_report(db)
    elif page == "📝 備忘錄":
        page_memos(db)

    st.sidebar.divider()
    st.sidebar.markdown("---\n**v13.18 完整版** | ✨ 年繳優惠版\n")

if __name__ == "__main__":
    main()

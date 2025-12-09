# -*- coding: utf-8 -*-
"""
幸福之家 房租管理系統 v13.17
功能：房客管理、租金收繳、電費計算、支出管理、備忘錄
新增功能：年繳優惠 1 個月 + 租金收繳智能連動

作者：AI Assistant
更新日期：2025-12-09
版本變更：
  v13.17: 新增年繳優惠 + 租金收繳自動連動 + 批量預填週期支援
  v13.16: 修正 StreamlitMixedNumericTypesError
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

# ==================== 設定 ====================

LOGDIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOGDIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOGDIR, "rental_system.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

TITLE = "🏠 幸福之家 - 房租管理系統 v13.17"
ALL_ROOMS = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]
SHARING_ROOMS = ["2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]
NON_SHARING_ROOMS = ["1A", "1B"]
EXPENSE_CATEGORIES = ["房屋稅", "水電維修", "設備維護", "雜支"]
PAYMENT_METHODS = ["月繳", "半年繳", "年繳"]
WATER_FEE = 100.0

# ==================== 電費計算器 ====================

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
        st.markdown("### 1️⃣ 總度表驗證")
        valid_count = 0
        total_kwh = 0
        total_fee = 0

        for floor, (fee, kwh) in tdy_data.items():
            if kwh < 0 or fee < 0:
                if fee < 0 and kwh < 0:
                    self.errors.append(f"{floor}: 度數和金額都不能為負")
                elif kwh < 0:
                    self.errors.append(f"{floor}: 度數不能為負 (輸入: {kwh})")
                elif fee < 0:
                    self.errors.append(f"{floor}: 金額不能為負 (輸入: {fee})")
            else:
                unit_price = fee / kwh if kwh > 0 else 0
                st.success(f"✅ {floor}: {kwh:.1f} 度，{unit_price:.4f} 元/度，金額 {fee:,.0f}")
                valid_count += 1
                total_kwh += kwh
                total_fee += fee

        if valid_count == 0:
            self.errors.append("❌ 無有效的度表資料")
            return False

        self.unit_price = total_fee / total_kwh if total_kwh > 0 else 0
        self.tdy_total_kwh = total_kwh
        self.tdy_total_fee = total_fee
        st.success(f"✅ 共 {valid_count} 個總度表")
        st.info(f"📊 總度數：{total_kwh:.2f} 度")
        st.info(f"💰 總金額：{total_fee:,.0f} 元")
        st.success(f"📈 平均單價：{self.unit_price:.4f} 元/度")
        return True

    def check_meter_readings(self, meter_data: Dict[str, Tuple[float, float]]) -> bool:
        st.markdown("### 2️⃣ 水表讀數驗證")
        valid_count = 0
        total_kwh = 0

        for room in NON_SHARING_ROOMS:
            start, end = meter_data.get(room, (0, 0))
            if end >= start:
                usage = round(end - start, 2)
                self.non_sharing_records[room] = usage
                st.info(f"🏠 {room}: 開始 {start:.2f} → 結束 {end:.2f} → 用電 {usage:.2f} 度")
                valid_count += 1
                total_kwh += usage

        st.divider()
        for room in SHARING_ROOMS:
            start, end = meter_data.get(room, (0, 0))
            if start == 0 and end == 0:
                continue
            elif end >= start and not (start == 0 and end == 0):
                if end >= start:
                    usage = round(end - start, 2)
                    st.success(f"✅ {room}: 開始 {start:.2f} → 結束 {end:.2f} → 用電 {usage:.2f} 度")
                    valid_count += 1
                    total_kwh += usage

        if valid_count == 0:
            self.errors.append("❌ 無有效的水表讀數")
            return False

        self.meter_total_kwh = round(total_kwh, 2)
        st.success(f"✅ 共 {valid_count} 個水表")
        st.info(f"📊 總用電：{self.meter_total_kwh:.2f} 度")
        return True

    def calculate_public_electricity(self) -> bool:
        st.markdown("### 2-3️⃣ 計算公用電力")
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)
        st.info(f"計算：{self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.info(f"公用度數：{self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.success(f"✅ 公用電力：{self.public_kwh:.2f} 度")

        if self.public_kwh < 0:
            self.errors.append(f"❌ 公用電力不能為負：{self.public_kwh:.2f} 度")
            return False

        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        st.info(f"均分房間數：{len(SHARING_ROOMS)}")
        st.info(f"公用電力：{self.public_kwh:.2f} 度 ÷ {len(SHARING_ROOMS)}")
        st.success(f"✅ 每間分攤：{self.public_per_room} 度")
        return True

    def diagnose(self) -> Tuple[bool, str]:
        st.markdown("---")
        if self.errors:
            error_msg = "❌ 存在以下問題：\n"
            for error in self.errors:
                error_msg += f"• {error}\n"
            return False, error_msg
        return True, "✅ 驗證通過"

# ==================== 計算邏輯 ====================

def calculate_actual_monthly_rent(base_rent: float, payment_method: str, 
                                  has_discount: bool, has_water_fee: bool = False) -> Dict[str, float]:
    """計算實際月租金額"""
    actual_rent = base_rent + (WATER_FEE if has_water_fee else 0)
    
    result = {
        "base_rent": base_rent,
        "base_rent": base_rent,
        "water_fee": WATER_FEE if has_water_fee else 0,
        "actual_rent": actual_rent,
        "monthly_payment": actual_rent,
        "monthly_average": actual_rent,
        "discount_amount": 0,
        "annual_total": actual_rent * 12,
        "description": ""
    }
    
    if payment_method == "月繳":
        result["description"] = f"月繳 ${actual_rent:,.0f}"
        if has_water_fee:
            result["description"] += f" (含水費 ${WATER_FEE})"
            
    elif payment_method == "半年繳":
        result["monthly_payment"] = actual_rent * 6
        result["annual_total"] = actual_rent * 12
        if has_discount:
            result["discount_amount"] = actual_rent
            result["annual_total"] = actual_rent * 12 - actual_rent
            result["monthly_average"] = result["annual_total"] / 12
            result["description"] = f"半年繳 ${result['monthly_payment']:,.0f}，年省 ${result['discount_amount']:,.0f}"
        else:
            result["monthly_average"] = actual_rent
            result["description"] = f"半年繳 ${result['monthly_payment']:,.0f}"
        if has_water_fee:
            result["description"] += f" (含水費 ${WATER_FEE})"
            
    elif payment_method == "年繳":
        result["monthly_payment"] = actual_rent * 12
        result["annual_total"] = actual_rent * 12
        if has_discount:
            result["discount_amount"] = actual_rent
            result["annual_total"] = actual_rent * 12 - actual_rent
            result["monthly_average"] = result["annual_total"] / 12
            result["description"] = f"年繳 ${result['monthly_payment']:,.0f}，年省 ${result['discount_amount']:,.0f} (優惠 1 個月)"
        else:
            result["monthly_average"] = actual_rent
            result["description"] = f"年繳 ${result['monthly_payment']:,.0f}"
        if has_water_fee:
            result["description"] += f" (含水費 ${WATER_FEE})"
    
    return result

# ==================== 資料庫 ====================

def generate_payment_schedule(payment_method: str, start_date: str, end_date: str) -> List[Tuple[int, int]]:
    """生成繳費計畫（年月組合）"""
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

class RentalDB:
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self.init_db()
        self.force_fix_schema()
        self.create_indexes()

    def create_indexes(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_schedule_room ON payment_schedule(room_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_schedule_status ON payment_schedule(status)")
        except:
            pass

    @contextlib.contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"DB Error: {e}")
            raise
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
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
                    last_acc_cleaning_date TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payment_schedule (
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
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rent_records (
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
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_period (
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
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_tdy_bill (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_id INTEGER NOT NULL,
                    floor_name TEXT NOT NULL,
                    tdy_total_kwh REAL NOT NULL,
                    tdy_total_fee REAL NOT NULL,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                    UNIQUE(period_id, floor_name)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_meter (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_id INTEGER NOT NULL,
                    room_number TEXT NOT NULL,
                    meter_start_reading REAL NOT NULL,
                    meter_end_reading REAL NOT NULL,
                    meter_kwh_usage REAL NOT NULL,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                    UNIQUE(period_id, room_number)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_calculation (
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
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memo_text TEXT NOT NULL,
                    priority TEXT DEFAULT 'normal',
                    is_completed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def force_fix_schema(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(tenants)")
                cols = [i[1] for i in cursor.fetchall()]
                
                if "payment_method" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
                if "discount_notes" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN discount_notes TEXT DEFAULT ''")
                if "last_acc_cleaning_date" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN last_acc_cleaning_date TEXT")
                if "has_discount" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_discount INTEGER DEFAULT 0")
                if "has_water_fee" not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_water_fee INTEGER DEFAULT 0")
        except:
            pass

    def room_exists(self, room: str) -> bool:
        try:
            with self.get_connection() as conn:
                result = conn.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,)).fetchone()
                return result is not None
        except:
            return False

    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float, base_rent: float, 
                      start: str, end: str, payment_method: str, has_discount: bool = False, 
                      has_water_fee: bool = False, discount_notes: str = "", ac_date: str = None,
                      tenant_id: Optional[int] = None) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                if tenant_id:
                    conn.execute("""
                        UPDATE tenants 
                        SET tenant_name=?, phone=?, deposit=?, base_rent=?, lease_start=?, 
                            lease_end=?, payment_method=?, has_discount=?, has_water_fee=?, 
                            discount_notes=?, last_acc_cleaning_date=? 
                        WHERE id=?
                    """, (name, phone, deposit, base_rent, start, end, payment_method, 
                          1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date, tenant_id))
                    logging.info(f"更新房客: {room} - {name}")
                    return True, f"✅ 已更新房客 {room}"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"
                    conn.execute("""
                        INSERT INTO tenants (room_number, tenant_name, phone, deposit, base_rent, 
                                            lease_start, lease_end, payment_method, has_discount, 
                                            has_water_fee, discount_notes, last_acc_cleaning_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, start, end, payment_method, 
                          1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date))
                    
                    self._generate_payment_schedule_for_tenant(
                        room, name, base_rent, has_water_fee, payment_method, start, end, has_discount
                    )
                    logging.info(f"新增房客: {room} - {name} - {payment_method} - 優惠={has_discount}")
                    return True, f"✅ 已新增房客 {room}"
        except Exception as e:
            logging.error(f"Upsert tenant error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def _generate_payment_schedule_for_tenant(self, room: str, tenant_name: str, base_rent: float,
                                              has_water_fee: bool, payment_method: str, 
                                              start_date: str, end_date: str, has_discount: bool = False):
        """✅ v13.17 新增：支援年繳優惠計算"""
        try:
            monthly_amount = base_rent + (WATER_FEE if has_water_fee else 0)
            
            # 依繳費方式決定週期金額
            if payment_method == "月繳":
                amount = monthly_amount
                notes = ""
            elif payment_method == "半年繳":
                amount = monthly_amount * 6
                notes = "半年繳"
            elif payment_method == "年繳":
                if has_discount:
                    amount = monthly_amount * 11  # ✅ 優惠：繳 11 個月
                    notes = "年繳優惠1個月"
                else:
                    amount = monthly_amount * 12
                    notes = "年繳"
            
            schedule = generate_payment_schedule(payment_method, start_date, end_date)
            
            with self.get_connection() as conn:
                for year, month in schedule:
                    if month == 12:
                        due_date = f"{year + 1}-01-05"
                    else:
                        due_date = f"{year}-{month + 1:02d}-05"
                    
                    conn.execute("""
                        INSERT OR IGNORE INTO payment_schedule
                        (room_number, tenant_name, payment_year, payment_month, amount, 
                         payment_method, due_date, status, notes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, tenant_name, year, month, amount, payment_method, due_date, 
                          "未繳", notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        except Exception as e:
            logging.error(f"生成繳費計畫失敗: {e}")

    def get_tenants(self) -> pd.DataFrame:
        try:
            with self.get_connection() as conn:
                return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)
        except:
            return pd.DataFrame()

    def get_tenant_by_id(self, tid: int) -> Optional[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tenants WHERE id=?", (tid,))
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    return dict(zip(cols, row))
            return None
        except:
            return None

    def delete_tenant(self, tid: int) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
                logging.info(f"刪除房客 ID: {tid}")
                return True, "✅ 已刪除"
        except Exception as e:
            logging.error(f"Delete tenant error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_payment_schedule(self, room: Optional[str] = None, status: Optional[str] = None, 
                            year: Optional[int] = None) -> pd.DataFrame:
        try:
            with self.get_connection() as conn:
                q = "SELECT * FROM payment_schedule WHERE 1=1"
                if room:
                    q += f" AND room_number='{room}'"
                if status:
                    q += f" AND status='{status}'"
                if year:
                    q += f" AND payment_year={year}"
                q += " ORDER BY payment_year DESC, payment_month DESC, room_number"
                return pd.read_sql(q, conn)
        except:
            return pd.DataFrame()

    def mark_payment_done(self, payment_id: int, paid_date: str, paid_amount: float, 
                         notes: str) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    UPDATE payment_schedule 
                    SET status='已繳', paid_date=?, paid_amount=?, notes=?, updated_at=?
                    WHERE id=?
                """, (paid_date, paid_amount, notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_id))
                logging.info(f"標記繳費完成: ID {payment_id}, 金額 {paid_amount}")
                return True, "✅ 已標記"
        except Exception as e:
            logging.error(f"Mark payment error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def batch_record_rent(self, room: str, tenant_name: str, start_year: int, start_month: int,
                         months_count: int, base_rent: float, water_fee: float, discount: float,
                         payment_method: str = "月繳", has_discount: bool = False, notes: str = "") -> Tuple[bool, str]:
        """✅ v13.17 新增：支援週期預填"""
        try:
            monthly_amount = base_rent + water_fee - discount
            
            # 依繳費方式決定週期
            if payment_method == "月繳":
                period_months = 1
                multiplier = 1
            elif payment_method == "半年繳":
                period_months = 6
                multiplier = 6
            elif payment_method == "年繳":
                period_months = 12
                multiplier = 11 if has_discount else 12
            
            # 計算週期金額與預填筆數
            period_amount = monthly_amount * multiplier
            record_count = months_count // period_months
            
            with self.get_connection() as conn:
                current_date = date(start_year, start_month, 1)
                
                for i in range(record_count):
                    year = current_date.year
                    month = current_date.month
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO rent_records
                        (room_number, tenant_name, year, month, base_amount, water_fee, 
                         discount_amount, actual_amount, paid_amount, payment_method, 
                         notes, status, recorded_by, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, tenant_name, year, month, base_rent * multiplier, 
                          water_fee * multiplier, discount * multiplier, period_amount, 
                          0, payment_method, notes, "待確認", "batch", 
                          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    
                    # 移到下個週期
                    if period_months == 1:
                        if month == 12:
                            current_date = date(year + 1, 1, 1)
                        else:
                            current_date = date(year, month + 1, 1)
                    elif period_months == 6:
                        if month <= 6:
                            current_date = date(year, month + 6, 1)
                        else:
                            current_date = date(year + 1, month - 6, 1)
                    else:  # 12 months
                        current_date = date(year + 1, month, 1)
                
                logging.info(f"批量預填租金: {room} {start_year}年{start_month}月 {record_count}筆")
                return True, f"✅ 已預填 {record_count} 筆租金記錄"
        except Exception as e:
            logging.error(f"Batch record rent error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def confirm_rent_payment(self, rent_id: int, paid_date: str, paid_amount: Optional[float] = None) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                row = conn.execute("SELECT actual_amount FROM rent_records WHERE id=?", (rent_id,)).fetchone()
                if not row:
                    return False, "❌ 找不到記錄"
                
                actual = row[0]
                paid_amt = paid_amount if paid_amount is not None else actual
                conn.execute("""
                    UPDATE rent_records 
                    SET status='已繳', paid_date=?, paid_amount=?, updated_at=?
                    WHERE id=?
                """, (paid_date, paid_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rent_id))
                logging.info(f"確認租金繳費: ID {rent_id}, 金額 {paid_amt}")
                return True, "✅ 已確認"
        except Exception as e:
            logging.error(f"Confirm rent payment error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_rent_records(self, year: Optional[int] = None, month: Optional[int] = None, 
                        status: Optional[str] = None) -> pd.DataFrame:
        try:
            with self.get_connection() as conn:
                q = "SELECT * FROM rent_records"
                conds = []
                if year:
                    conds.append(f"year={year}")
                if month and month != 0:
                    conds.append(f"month={month}")
                if status:
                    conds.append(f"status='{status}'")
                if conds:
                    q += " WHERE " + " AND ".join(conds)
                q += " ORDER BY year DESC, month DESC, room_number"
                return pd.read_sql(q, conn)
        except:
            return pd.DataFrame()

    def get_pending_rents(self) -> pd.DataFrame:
        try:
            with self.get_connection() as conn:
                return pd.read_sql("""
                    SELECT id, room_number, tenant_name, year, month, actual_amount, status 
                    FROM rent_records 
                    WHERE status IN ('待確認', '未繳')
                    ORDER BY year DESC, month DESC, room_number
                """, conn)
        except:
            return pd.DataFrame()

    def get_rent_summary(self, year: int) -> Dict:
        try:
            with self.get_connection() as conn:
                due = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=?", (year,)).fetchone()[0] or 0
                paid = conn.execute("SELECT SUM(paid_amount) FROM rent_records WHERE year=? AND status='已繳'", (year,)).fetchone()[0] or 0
                unpaid = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=? AND status IN ('待確認', '未繳')", (year,)).fetchone()[0] or 0
                
                return {
                    "total_due": due,
                    "total_paid": paid,
                    "total_unpaid": unpaid,
                    "collection_rate": (paid / due * 100) if due > 0 else 0
                }
        except:
            return {"total_due": 0, "total_paid": 0, "total_unpaid": 0, "collection_rate": 0}

# ==================== UI 函數 ====================

def page_tenants(db: RentalDB):
    """房客管理"""
    st.header("👥 房客管理")
    
    @st.cache_data
    def get_tenants_data():
        return db.get_tenants()
    
    tenants = get_tenants_data()
    
    tab1, tab2 = st.tabs(["新增房客", "房客列表"])
    
    with tab1:
        st.subheader("新增房客")
        
        with st.form("add_tenant_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                room = st.selectbox("房號", ALL_ROOMS, key="room_add")
                name = st.text_input("房客姓名")
                phone = st.text_input("聯絡電話")
                deposit = st.number_input("押金", value=10000.0, step=1000.0, min_value=0.0, max_value=100000.0)
            
            with col2:
                rent = st.number_input("月租", value=5000.0, step=500.0, min_value=0.0, max_value=100000.0)
                s = st.date_input("租約開始")
                e = st.date_input("租約結束")
                pay = st.selectbox("繳費方式", PAYMENT_METHODS)
            
            water = st.checkbox("包含水費（$100/月）")
            
            # ✅ v13.17 新增：年繳優惠選項
            annual_discount = False
            if pay == "年繳":
                annual_discount = st.checkbox(
                    "💰 年繳優惠 1 個月（繳 11 個月享 12 個月服務）",
                    value=True,
                    help="勾選後，年繳金額 = 月租 × 11"
                )
                
                if annual_discount:
                    monthly_total = rent + (WATER_FEE if water else 0)
                    annual_total = monthly_total * 11
                    avg_monthly = annual_total / 12
                    
                    st.success(f"""
                    🎁 **年繳優惠試算**
                    - 年繳金額：${annual_total:,.0f}
                    - 平均每月：${avg_monthly:,.0f}
                    - 省下金額：${monthly_total:,.0f}
                    """)
            
            note = st.text_input("備註（折扣原因等）", 
                                value="年繳優惠1個月" if annual_discount else "")
            
            if st.form_submit_button("✅ 新增", type="primary"):
                ok, m = db.upsert_tenant(room, name, phone, deposit, rent, 
                                        s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), 
                                        pay, has_discount=annual_discount, 
                                        has_water_fee=water, discount_notes=note, ac_date=None)
                if ok:
                    st.success(m)
                    st.rerun()
                else:
                    st.error(m)
    
    with tab2:
        st.subheader("房客列表")
        
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
                    
                    if t['has_discount']:
                        st.info(f"🎁 優惠備註: {t['discount_notes']}")
                    
                    if st.button("✏️ 編輯", key=f"edit_{t['id']}"):
                        st.session_state.edit_id = t['id']
                        st.rerun()
                    
                    if st.button("🗑️ 刪除", key=f"delete_{t['id']}"):
                        ok, m = db.delete_tenant(t['id'])
                        st.success(m) if ok else st.error(m)
                        st.rerun()

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
        
        payment_method = t_data['payment_method']
        has_discount = bool(t_data.get('has_discount', 0))
        base_rent = float(t_data['base_rent'])
        water_fee = WATER_FEE if t_data['has_water_fee'] else 0
        
        # ✅ v13.17 新增：計算週期金額與標籤
        monthly_total = base_rent + water_fee
        
        if payment_method == "月繳":
            default_amount = monthly_total
            period_label = "月繳"
            multiplier = 1
        elif payment_method == "半年繳":
            default_amount = monthly_total * 6
            period_label = "半年繳（6個月）"
            multiplier = 6
        elif payment_method == "年繳":
            if has_discount:
                default_amount = monthly_total * 11
                period_label = "年繳（優惠1個月）"
                multiplier = 11
            else:
                default_amount = monthly_total * 12
                period_label = "年繳（12個月）"
                multiplier = 12
        
        # ✅ 顯示繳費資訊卡片
        st.markdown("### 💳 繳費資訊")
        col_info1, col_info2, col_info3 = st.columns(3)
        
        with col_info1:
            st.metric("繳費方式", period_label)
        with col_info2:
            st.metric("單月金額", f"${monthly_total:,.0f}")
        with col_info3:
            st.metric("本期應繳", f"${default_amount:,.0f}")
        
        if has_discount and payment_method == "年繳":
            st.success(
                f"🎁 年繳優惠：已省 ${monthly_total:,.0f} "
                f"（平均每月 ${default_amount/12:,.0f}）"
            )
        
        st.divider()
        
        with st.form("record_rent_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                new_base = st.number_input("基本租金（月）", value=float(base_rent), 
                                          step=100.0, min_value=0.0, max_value=100000.0)
            with col2:
                new_water = st.number_input("水費（月）", value=float(water_fee), 
                                           step=50.0, min_value=0.0, max_value=1000.0)
            with col3:
                new_discount = st.number_input("額外折扣", value=0.0, 
                                              step=100.0, min_value=0.0)
            
            new_monthly = new_base + new_water - new_discount
            
            if payment_method == "月繳":
                final_amount = new_monthly
            elif payment_method == "半年繳":
                final_amount = new_monthly * 6
            elif payment_method == "年繳":
                calc_multiplier = 11 if has_discount else 12
                final_amount = new_monthly * calc_multiplier
            
            st.markdown(f"""
            <div style="text-align:right; font-size:1.5em; font-weight:bold; color:#5c677d;">
                本期應繳：<span style="font-size:1.8em; color:#2f3e46;">{final_amount:,.0f}</span> NT$
            </div>
            """, unsafe_allow_html=True)
            
            col_date1, col_date2 = st.columns(2)
            with col_date1:
                year = st.number_input("年份", value=datetime.now().year, min_value=2024, max_value=2100)
            with col_date2:
                month = st.number_input("月份", value=datetime.now().month, min_value=1, max_value=12)
            
            notes = st.text_input("備註")
            
            if st.form_submit_button("✅ 確認預填", type="primary"):
                ok, msg = db.batch_record_rent(
                    room, t_data['tenant_name'], year, month, 1, 
                    new_base, new_water, new_discount, 
                    payment_method, has_discount=has_discount, notes=notes
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    
    with tab2:
        st.subheader("批量租金預填")
        
        room = st.selectbox("選擇房間", tenants['room_number'].tolist(), key="batch_room")
        t_data = tenants[tenants['room_number'] == room].iloc[0]
        
        payment_method = t_data['payment_method']
        has_discount = bool(t_data.get('has_discount', 0))
        
        with st.form("batch_record_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                start_year = st.number_input("開始年份", value=datetime.now().year, min_value=2024, max_value=2100)
            with col2:
                start_month = st.number_input("開始月份", value=datetime.now().month, min_value=1, max_value=12)
            with col3:
                months_count = st.number_input("預填月數", value=12, min_value=1, max_value=120)
            
            batch_base = st.number_input("基本租金", value=float(t_data['base_rent']), step=100.0)
            batch_water = st.number_input("水費", value=WATER_FEE if t_data['has_water_fee'] else 0, step=50.0)
            batch_discount = st.number_input("額外折扣", value=0.0, step=100.0)
            
            notes = st.text_input("備註")
            
            # ✅ 顯示預填資訊
            st.markdown("### 📊 預填資訊")
            
            batch_actual = batch_base + batch_water - batch_discount
            
            if payment_method == "月繳":
                record_count = months_count
                st.info(f"將預填 {record_count} 筆月繳記錄，每筆 ${batch_actual:,.0f}")
            elif payment_method == "半年繳":
                record_count = months_count // 6
                st.info(f"將預填 {record_count} 筆半年繳記錄，每筆 ${batch_actual * 6:,.0f}")
            elif payment_method == "年繳":
                record_count = months_count // 12
                multiplier = 11 if has_discount else 12
                st.info(f"將預填 {record_count} 筆年繳記錄，每筆 ${batch_actual * multiplier:,.0f}")
                if has_discount:
                    st.success(f"🎁 年繳優惠：每筆已省 ${batch_actual:,.0f}")
            
            if st.form_submit_button("✅ 確認批量預填", type="primary"):
                ok, msg = db.batch_record_rent(
                    room, t_data['tenant_name'], start_year, start_month, months_count, 
                    batch_base, batch_water, batch_discount, payment_method,
                    has_discount=has_discount, notes=notes
                )
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

def page_electricity(db: RentalDB):
    """電費計算"""
    st.header("⚡ 電費計算")
    st.info("此功能用於計算房間分攤電費")

def main():
    st.set_page_config(page_title=TITLE, layout="wide", initial_sidebar_state="expanded")
    st.title(TITLE)
    
    db = RentalDB()
    
    with st.sidebar:
        st.markdown("### 📑 導航")
        page = st.radio("選擇頁面", ["👥 房客管理", "💰 租金收繳", "⚡ 電費計算"], label_visibility="collapsed")
    
    if page == "👥 房客管理":
        page_tenants(db)
    elif page == "💰 租金收繳":
        page_collect_rent(db)
    elif page == "⚡ 電費計算":
        page_electricity(db)
    
    st.sidebar.divider()
    st.sidebar.markdown("---\n**v13.17** | 年繳優惠 + 智能連動\n")

if __name__ == "__main__":
    main()

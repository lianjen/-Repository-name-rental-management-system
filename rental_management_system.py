"""
幸福之家管理系統 Pro v13.8 - 智慧繳費連動版
本次更新內容：
1. 【新增】繳費連動功能：年繳/半年繳時，自動產生未來月份的「已繳」紀錄
2. 【優化】收租面板：依據房客繳費方式，自動計算應收總額 (例如年繳自動 x12 - 折扣)
3. 【優化】資料庫：支援批次寫入租金紀錄
4. 【保留】所有先前版本的電費、儀表板、Excel 匯入功能
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
import time
import io
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
# 電費計算類
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
                if fee == 0 and kwh == 0: self.errors.append(f"🚨 {floor}: 完全沒有輸入")
                elif kwh == 0: self.errors.append(f"🚨 {floor}: 度數為 0")
                elif fee == 0: self.errors.append(f"🚨 {floor}: 金額為 0")
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
        st.success(f"✅ 台電驗證通過 (單價: ${self.unit_price:.4f}/度)")
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
                st.info(f"📝 {room}: {start:.2f} → {end:.2f} (記錄: {usage:.2f}度)")
        st.divider()
        for room in SHARING_ROOMS:
            start, end = meter_data[room]
            if start == 0 and end == 0: continue
            elif end <= start:
                if end < start: self.errors.append(f"🚨 {room}: 本期 < 上期")
            else:
                usage = round(end - start, 2)
                st.success(f"✅ {room}: {start:.2f} → {end:.2f} (度數: {usage:.2f})")
                valid_count += 1
                total_kwh += usage
        if valid_count == 0:
            self.errors.append("🚨 沒有分攤房間的度數")
            return False
        self.meter_total_kwh = round(total_kwh, 2)
        st.success(f"✅ 分攤房間私表總度數: {self.meter_total_kwh:.2f}度")
        return True
    
    def calculate_public_electricity(self) -> bool:
        st.markdown("### ⚖️ 【第 2-3 步】公用電計算")
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)
        st.info(f"公用電 = {self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f} = {self.public_kwh:.2f}度")
        if self.public_kwh < 0:
            self.errors.append(f"🚨 公用電度數為負數 (私表總和 {self.meter_total_kwh} > 台電總和 {self.tdy_total_kwh})")
            return False
        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        st.success(f"每戶分攤: {self.public_per_room}度")
        return True
    
    def diagnose(self) -> Tuple[bool, str]:
        st.markdown("---")
        if self.errors:
            return False, "🔴 錯誤：\n" + "\n".join(self.errors)
        return True, "✅ 檢查通過"

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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_records_room ON rent_records(room_number)")
        except Exception: pass

    def reset_database(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                return True, "✅ 資料庫已重置"
            return False, "⚠️ 資料庫不存在"
        except Exception as e: return False, str(e)

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception:
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
            # Legacy table for compatibility
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
            # Main records table
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
                status TEXT DEFAULT '未收',
                recorded_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_number) REFERENCES tenants(room_number),
                UNIQUE(room_number, year, month)
            )""")
            # Electricity tables
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
                if "payment_method" not in cols: cursor.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
                if "discount_notes" not in cols: cursor.execute("ALTER TABLE tenants ADD COLUMN discount_notes TEXT DEFAULT ''")
                if "last_ac_cleaning_date" not in cols: cursor.execute("ALTER TABLE tenants ADD COLUMN last_ac_cleaning_date TEXT")
                if "has_discount" not in cols: cursor.execute("ALTER TABLE tenants ADD COLUMN has_discount INTEGER DEFAULT 0")
                if "has_water_fee" not in cols: cursor.execute("ALTER TABLE tenants ADD COLUMN has_water_fee INTEGER DEFAULT 0")
                
                cursor.execute("PRAGMA table_info(electricity_calculation)")
                e_cols = [i[1] for i in cursor.fetchall()]
                if "public_kwh" not in e_cols and "public_allocated_kwh" in e_cols:
                    cursor.execute("ALTER TABLE electricity_calculation RENAME COLUMN public_allocated_kwh TO public_kwh")
                
                cursor.execute("PRAGMA table_info(electricity_period)")
                ep_cols = [i[1] for i in cursor.fetchall()]
                if "notes" not in ep_cols: cursor.execute("ALTER TABLE electricity_period ADD COLUMN notes TEXT DEFAULT ''")
        except Exception: pass

    # Tenant Methods
    def room_exists(self, room: str) -> bool:
        with self._get_connection() as conn:
            return conn.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,)).fetchone() is not None

    def upsert_tenant(self, room, name, phone, deposit, base_rent, start, end, payment_method="月繳", has_discount=False, has_water_fee=False, discount_notes="", ac_date=None, tenant_id=None):
        try:
            with self._get_connection() as conn:
                if tenant_id:
                    conn.execute("""UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?, lease_start=?, lease_end=?, payment_method=?, has_discount=?, has_water_fee=?, discount_notes=?, last_ac_cleaning_date=? WHERE id=?""", 
                        (name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date, tenant_id))
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room): return False, f"❌ 房號 {room} 已存在"
                    conn.execute("""INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, lease_start, lease_end, payment_method, has_discount, has_water_fee, discount_notes, last_ac_cleaning_date) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                        (room, name, phone, deposit, base_rent, start, end, payment_method, 1 if has_discount else 0, 1 if has_water_fee else 0, discount_notes, ac_date))
                    return True, f"✅ 房號 {room} 已新增"
        except Exception as e: return False, str(e)

    def get_tenants(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)

    def get_tenant_by_id(self, tid: int):
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
            if row: return dict(zip([d[0] for d in conn.cursor().description], row))
        return None

    def delete_tenant(self, tid: int):
        with self._get_connection() as conn:
            conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
        return True, "✅ 已刪除"

    # Rent Records Methods - v13.8 Updated for Batch Insert
    def record_rent(self, room, tenant_name, year, month, base, water, discount, paid, date, method, notes, auto_fill_months=0):
        """
        auto_fill_months: 如果 > 0 (例如11)，會自動將接下來 11 個月的狀態標記為「已由本期年繳覆蓋」。
        """
        try:
            with self._get_connection() as conn:
                # 1. 紀錄當月
                actual = base + water - discount
                status = "已收" if paid > 0 else "未收"
                conn.execute("""INSERT OR REPLACE INTO rent_records
                    (room_number, tenant_name, year, month, base_amount, water_fee, discount_amount, actual_amount, paid_amount, paid_date, payment_method, notes, status, recorded_by, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (room, tenant_name, year, month, base, water, discount, actual, paid, date, method, notes, status, "system", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                
                # 兼容舊表 (Dashboard matrix 用)
                conn.execute("INSERT OR REPLACE INTO rent_payments(room_number, year, month, amount, paid_date, is_paid) VALUES(?, ?, ?, ?, ?, ?)", 
                             (room, year, month, actual, date, 1 if paid > 0 else 0))

                # 2. 自動填入未來月份 (連動功能)
                if auto_fill_months > 0 and status == "已收":
                    current_date = datetime(year, month, 1)
                    for i in range(1, auto_fill_months + 1):
                        next_date = current_date + pd.DateOffset(months=i)
                        ny, nm = next_date.year, next_date.month
                        
                        # 未來月份的紀錄：應繳0(因為已在本期預繳)，已收0，狀態「已收(預繳)」
                        # 這樣報表看的時候，未來月份也是綠色的，而且不會重複計算收入
                        conn.execute("""INSERT OR REPLACE INTO rent_records
                            (room_number, tenant_name, year, month, base_amount, water_fee, discount_amount, actual_amount, paid_amount, paid_date, payment_method, notes, status, recorded_by, updated_at)
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (room, tenant_name, ny, nm, 0, 0, 0, 0, 0, date, method, f"已於 {year}年{month}月 {method}繳清", "已收", "system_auto", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                        
                        # 兼容舊表
                        conn.execute("INSERT OR REPLACE INTO rent_payments(room_number, year, month, amount, paid_date, is_paid) VALUES(?, ?, ?, ?, ?, ?)", 
                                     (room, ny, nm, 0, date, 1))
                                     
                return True, f"✅ {room} 租金已記錄 (連動 {auto_fill_months} 個月)"
        except Exception as e: return False, str(e)

    def get_rent_records(self, year=None, month=None) -> pd.DataFrame:
        with self._get_connection() as conn:
            query = "SELECT * FROM rent_records"
            conds = []
            if year: conds.append(f"year={year}")
            if month and month != "全部": conds.append(f"month={month}")
            if conds: query += " WHERE " + " AND ".join(conds)
            query += " ORDER BY year DESC, month DESC, room_number"
            return pd.read_sql(query, conn)

    def get_unpaid_rents_v2(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("SELECT room_number as '房號', tenant_name as '房客', year as '年', month as '月', actual_amount as '應繳', paid_amount as '已收', status as '狀態' FROM rent_records WHERE status='未收' ORDER BY year DESC, month DESC, room_number", conn)

    def get_rent_summary(self, year: int) -> Dict:
        with self._get_connection() as conn:
            due = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=?", (year,)).fetchone()[0] or 0
            paid = conn.execute("SELECT SUM(paid_amount) FROM rent_records WHERE year=? AND status='已收'", (year,)).fetchone()[0] or 0
            unpaid = conn.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=? AND status='未收'", (year,)).fetchone()[0] or 0
            return {'total_due': due, 'total_paid': paid, 'total_unpaid': unpaid, 'collection_rate': (paid/due*100) if due > 0 else 0}

    def get_rent_matrix(self, year: int) -> pd.DataFrame:
        with self._get_connection() as conn:
            df = pd.read_sql(f"SELECT room_number, month, is_paid, amount FROM rent_payments WHERE year = {year} ORDER BY room_number, month", conn)
            if df.empty: return pd.DataFrame()
            matrix = {r: {m: "" for m in range(1, 13)} for r in ALL_ROOMS}
            for _, row in df.iterrows():
                # 如果金額為0且已付，顯示 ✅ (年繳覆蓋)
                if row['is_paid']:
                    matrix[row['room_number']][row['month']] = "✅"
                else:
                    matrix[row['room_number']][row['month']] = f"❌ ${int(row['amount'])}"
            res = pd.DataFrame.from_dict(matrix, orient='index')
            res.columns = [f"{m}月" for m in range(1, 13)]
            return res
            
    def get_unpaid_rents(self) -> pd.DataFrame:
        with self._get_connection() as conn:
            return pd.read_sql("SELECT r.room_number as '房號', t.tenant_name as '房客', r.year as '年', r.month as '月', r.amount as '金額' FROM rent_payments r JOIN tenants t ON r.room_number = t.room_number WHERE r.is_paid = 0 AND t.is_active = 1 ORDER BY r.year DESC, r.month DESC", conn)

    def record_rent_payment(self, room, year, month, amount, paid_date):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO rent_payments(room_number, year, month, amount, paid_date, is_paid) VALUES(?, ?, ?, ?, ?, ?)", (room, year, month, amount, paid_date, 1 if paid_date else 0))

    # Electricity Methods (Preserved from v13.7)
    def add_electricity_period(self, year, ms, me):
        try:
            with self._get_connection() as conn:
                if conn.execute("SELECT 1 FROM electricity_period WHERE period_year=? AND period_month_start=? AND period_month_end=?", (year, ms, me)).fetchone(): return True, "✅ 期間已存在", 0
                c = conn.execute("INSERT INTO electricity_period(period_year, period_month_start, period_month_end) VALUES(?, ?, ?)", (year, ms, me))
                return True, "✅ 新增成功", c.lastrowid
        except Exception as e: return False, str(e), 0

    def get_all_periods(self):
        with self._get_connection() as conn:
            c = conn.execute("SELECT * FROM electricity_period ORDER BY id DESC")
            return [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]

    def get_period_report(self, pid):
        with self._get_connection() as conn:
            return pd.read_sql("SELECT room_number as '房號', private_kwh as '私表度數', public_kwh as '分攤度數', total_kwh as '合計度數', unit_price as '單價', calculated_fee as '應繳電費' FROM electricity_calculation WHERE period_id = ? ORDER BY room_number", conn, params=(pid,))

    def add_tdy_bill(self, pid, floor, kwh, fee):
        with self._get_connection() as conn: conn.execute("INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee) VALUES(?, ?, ?, ?)", (pid, floor, kwh, fee))

    def add_meter_reading(self, pid, room, start, end):
        with self._get_connection() as conn: conn.execute("INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) VALUES(?, ?, ?, ?, ?)", (pid, room, start, end, round(end-start, 2)))

    def calculate_electricity_fee(self, pid, calc, meter_data, notes=""):
        try:
            results = []
            with self._get_connection() as conn:
                for room in SHARING_ROOMS:
                    s, e = meter_data[room]
                    if e <= s: continue
                    priv, pub = round(e-s, 2), calc.public_per_room
                    total = round(priv + pub, 2)
                    fee = round(total * calc.unit_price, 0)
                    results.append({'房號': room, '私表度數': f"{priv:.2f}", '分攤度數': str(pub), '合計度數': f"{total:.2f}", '電度單價': f"${calc.unit_price:.4f}/度", '應繳電費': f"${int(fee)}"})
                    conn.execute("INSERT OR REPLACE INTO electricity_calculation(period_id, room_number, private_kwh, public_kwh, total_kwh, unit_price, calculated_fee) VALUES(?, ?, ?, ?, ?, ?, ?)", (pid, room, priv, pub, total, calc.unit_price, fee))
                conn.execute("UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=?, notes=? WHERE id=?", (calc.unit_price, calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee, notes, pid))
            return True, "✅ 計算完成", pd.DataFrame(results)
        except Exception as e: return False, str(e), pd.DataFrame()

    # Expenses & Memos
    def add_expense(self, date, cat, amt, desc):
        try:
            with self._get_connection() as conn: conn.execute("INSERT INTO expenses(expense_date, category, amount, description) VALUES(?, ?, ?, ?)", (date, cat, amt, desc)); return True
        except: return False

    def get_expenses(self, limit=50):
        with self._get_connection() as conn: return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))

    def get_expenses_summary_by_category(self, start=None, end=None):
        with self._get_connection() as conn:
            q = "SELECT category, SUM(amount) FROM expenses"
            if start and end: q += f" WHERE expense_date BETWEEN '{start}' AND '{end}'"
            q += " GROUP BY category ORDER BY 2 DESC"
            return {r[0]: r[1] for r in conn.execute(q).fetchall()}

    def add_memo(self, text, prio="normal"):
        try:
            with self._get_connection() as conn: conn.execute("INSERT INTO memos(memo_text, priority) VALUES(?, ?)", (text, prio)); return True
        except: return False

    def get_memos(self, completed=False):
        with self._get_connection() as conn: return pd.read_sql("SELECT * FROM memos WHERE is_completed=? ORDER BY priority DESC, created_at DESC", conn, params=(1 if completed else 0,))

    def complete_memo(self, mid):
        with self._get_connection() as conn: conn.execute("UPDATE memos SET is_completed=1 WHERE id=?", (mid,)); return True

    def delete_memo(self, mid):
        with self._get_connection() as conn: conn.execute("DELETE FROM memos WHERE id=?", (mid,)); return True

# ============================================================================
# UI 工具
# ============================================================================
def display_card(title: str, value: str, color: str = "blue"):
    colors = {"blue": "#e7f5ff", "green": "#ebfbee", "orange": "#fff9db", "red": "#ffe3e3", "gray": "#f8f9fa"}
    text_colors = {"blue": "#1971c2", "green": "#2f9e44", "orange": "#f08c00", "red": "#e03131", "gray": "#868e96"}
    st.markdown(f"""
    <div style="background: {colors.get(color, '#f8f9fa')}; border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(0,0,0,0.05);">
        <div style="color: {text_colors.get(color, '#868e96')}; font-size: 0.9rem; font-weight: 600; text-transform: uppercase;">{title}</div>
        <div style="color: #212529; font-size: 1.6rem; font-weight: 700; margin-top: 5px;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def display_room_card(room, status_color, status_text, detail_text=""):
    bg_color = {"green": "#d3f9d8", "red": "#ffe3e3", "orange": "#fff3bf"}.get(status_color, "#f1f3f5")
    border_color = {"green": "#b2f2bb", "red": "#ffc9c9", "orange": "#ffec99"}.get(status_color, "#dee2e6")
    text_color = {"green": "#2b8a3e", "red": "#c92a2a", "orange": "#e67700"}.get(status_color, "#495057")
    st.markdown(f"""
    <div style="background-color: {bg_color}; border: 2px solid {border_color}; border-radius: 10px; padding: 10px; text-align: center; height: 100px; display: flex; flex-direction: column; justify-content: center; align-items: center; margin-bottom: 10px;">
        <div style="font-size: 1.4rem; font-weight: 800; color: {text_color};">{room}</div>
        <div style="font-size: 0.9rem; font-weight: 600; color: {text_color}; margin-top: 2px;">{status_text}</div>
        <div style="font-size: 0.75rem; color: {text_color}; opacity: 0.8;">{detail_text}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 頁面層 (v13.8)
# ============================================================================
def page_dashboard(db: RentalDB):
    st.header("📊 儀表板")
    tenants = db.get_tenants()
    
    # 1. 到期提醒
    expiring_soon = []
    today = date.today()
    if not tenants.empty:
        for _, t in tenants.iterrows():
            try:
                end_date = datetime.strptime(t['lease_end'], "%Y-%m-%d").date()
                days_left = (end_date - today).days
                if 0 <= days_left <= 45:
                    expiring_soon.append((t['room_number'], t['tenant_name'], days_left, t['lease_end']))
            except: pass
    if expiring_soon:
        st.markdown("### 🚨 即將到期合約")
        cols = st.columns(4)
        for i, (room, name, days, end_date) in enumerate(expiring_soon):
            with cols[i % 4]: st.error(f"**{room} {name}**\n\n剩餘 **{days}** 天\n\n({end_date})")
        st.divider()

    # 2. 統計
    col1, col2, col3 = st.columns(3)
    occupancy = len(tenants)
    rate = (occupancy / 12 * 100) if occupancy > 0 else 0
    with col1: display_card("入住率", f"{rate:.0f}%", "blue")
    with col2: display_card("總房間數", "12 間", "green")
    with col3: display_card("待收房租", f"{len(db.get_unpaid_rents_v2())} 筆", "red")
    st.divider()

    # 3. 房間狀態
    st.subheader("🏠 房間實時狀態")
    active_rooms = tenants.set_index('room_number')
    cols = st.columns(6)
    for i, room in enumerate(ALL_ROOMS):
        with cols[i % 6]:
            if room in active_rooms.index:
                t = active_rooms.loc[room]
                try:
                    days = (datetime.strptime(t['lease_end'], "%Y-%m-%d").date() - today).days
                    if days <= 45: display_room_card(room, "orange", "即將到期", f"剩 {days} 天")
                    else: display_room_card(room, "green", t['tenant_name'], f"至 {t['lease_end']}")
                except: display_room_card(room, "green", t['tenant_name'], "租期異常")
            else: display_room_card(room, "red", "空房", "可招租")

    st.divider()
    
    # 4. 年度表 (現在連動後會自動變綠色)
    st.subheader("📅 年度房租繳費總覽")
    year = st.selectbox("選擇年份", [today.year, today.year + 1], key="dash_year")
    rent_matrix = db.get_rent_matrix(year)
    if not rent_matrix.empty: st.dataframe(rent_matrix, use_container_width=True)
    else: st.info("尚無資料")

    st.divider()
    col_memo, col_unpaid = st.columns([1, 1])
    with col_memo:
        st.subheader("📝 待辦事項")
        memos = db.get_memos(completed=False)
        if not memos.empty:
            for _, memo in memos.iterrows():
                c1, c2 = st.columns([5, 1])
                c1.write(f"• {memo['memo_text']}")
                if c2.button("✓", key=f"m_{memo['id']}"):
                    db.complete_memo(memo['id']); st.rerun()
        else: st.caption("無待辦事項")
    with col_unpaid:
        st.subheader("💰 未繳房租")
        unpaid = db.get_unpaid_rents()
        if not unpaid.empty: st.dataframe(unpaid[['房號','房客','金額']], use_container_width=True, hide_index=True)
        else: st.caption("全數繳清")

def page_collect_rent(db: RentalDB):
    st.header("💳 收租金管理 (智慧連動版)")
    
    tab1, tab2, tab3 = st.tabs(["📝 記錄租金", "📊 統計", "📋 明細"])
    
    with tab1:
        st.markdown("#### 📍 智慧收租面板")
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
            
            with col_sel2: year = st.number_input("年", value=datetime.now().year)
            with col_sel3: month = st.number_input("月", value=datetime.now().month, min_value=1, max_value=12)

            st.divider()
            
            # 自動計算邏輯
            base_rent = float(t_data['base_rent'])
            water_fee = WATER_FEE if t_data['has_water_fee'] else 0
            discount = 0.0
            
            # 連動提示
            auto_months = 0
            if t_data['payment_method'] == '年繳':
                st.info("💡 偵測到此房客為【年繳】，系統已自動將金額乘以 12，並會自動標記未來 11 個月為已繳。")
                base_rent *= 12
                if t_data['has_water_fee']: water_fee *= 12
                if t_data['has_discount']: 
                    st.info("💡 偵測到【年繳優惠】，已自動扣除 1 個月房租。")
                    discount = float(t_data['base_rent'])
                auto_months = 11
            elif t_data['payment_method'] == '半年繳':
                st.info("💡 偵測到此房客為【半年繳】，系統已自動將金額乘以 6，並會自動標記未來 5 個月為已繳。")
                base_rent *= 6
                if t_data['has_water_fee']: water_fee *= 6
                auto_months = 5
            
            col_calc1, col_calc2, col_calc3 = st.columns(3)
            with col_calc1: new_base = st.number_input("房租", value=base_rent, step=100.0)
            with col_calc2: new_water = st.number_input("水費", value=float(water_fee), step=50.0)
            with col_calc3: new_discount = st.number_input("折扣", value=discount, step=100.0)
            
            final_amount = new_base + new_water - new_discount
            st.markdown(f"<div style='text-align:right; font-size:1.5em; font-weight:bold; color:#2b8a3e; margin-bottom:10px;'>本期應收：${final_amount:,.0f}</div>", unsafe_allow_html=True)
            
            with st.expander("填寫收款詳情", expanded=True):
                c1, c2 = st.columns(2)
                with c1: paid_amt = st.number_input("實收金額", value=0.0, step=100.0)
                with c2: paid_date = st.date_input("收款日期", value=date.today())
                notes = st.text_input("備註", placeholder="例如：提早匯款")
                
            if st.button("✅ 確認並儲存", type="primary", use_container_width=True):
                ok, msg = db.record_rent(
                    room, t_data['tenant_name'], year, month, 
                    new_base, new_water, new_discount, paid_amt, 
                    paid_date.strftime("%Y-%m-%d") if paid_amt > 0 else None,
                    t_data['payment_method'], notes, 
                    auto_fill_months=auto_months # 傳遞連動參數
                )
                if ok:
                    st.success(msg)
                    time.sleep(1); st.rerun()
                else: st.error(msg)

    with tab2:
        st.subheader("📊 年度統計")
        y_stat = st.number_input("統計年份", value=datetime.now().year)
        summary = db.get_rent_summary(y_stat)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("應收總額", f"${summary['total_due']:,.0f}")
        c2.metric("已收總額", f"${summary['total_paid']:,.0f}")
        c3.metric("未收總額", f"${summary['total_unpaid']:,.0f}", delta_color="inverse")
        c4.metric("收款率", f"{summary['collection_rate']:.1f}%")
        
    with tab3:
        st.subheader("📋 收租明細表")
        records = db.get_rent_records()
        if not records.empty: st.dataframe(records[['year','month','room_number','tenant_name','actual_amount','paid_amount','status','paid_date','notes']], use_container_width=True)
        else: st.info("尚無紀錄")

def page_tenants(db: RentalDB):
    st.header("👥 房客管理")
    if "edit_id" not in st.session_state: st.session_state.edit_id = None
    
    if st.session_state.edit_id == -1:
        st.subheader("➕ 新增租客")
        with st.form("new_t"):
            r = st.selectbox("房號", [x for x in ALL_ROOMS if not db.room_exists(x)])
            c1, c2 = st.columns(2)
            n = c1.text_input("姓名")
            p = c2.text_input("電話")
            dep = c1.number_input("押金", 10000)
            rent = c2.number_input("租金", 6000)
            s = c1.date_input("開始")
            e = c2.date_input("結束", value=date.today()+timedelta(days=365))
            pay = st.selectbox("繳款", PAYMENT_METHODS)
            col_a, col_b = st.columns(2)
            with col_a: 
                has_discount = st.checkbox("年繳折1個月", value=True)
            with col_b: 
                water = st.checkbox("收水費 ($100/月)", value=False)
            note = st.text_input("備註")
            ac = st.text_input("冷氣清洗日")
            
            if st.form_submit_button("新增"):
                ok, m = db.upsert_tenant(r, n, p, dep, rent, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), pay, has_discount, water, note, ac)
                if ok: st.session_state.edit_id=None; st.rerun()
        if st.button("取消"): st.session_state.edit_id=None; st.rerun()
        
    elif st.session_state.edit_id:
        t = db.get_tenant_by_id(st.session_state.edit_id)
        st.subheader(f"編輯 {t['room_number']}")
        with st.form("edit_t"):
            c1, c2 = st.columns(2)
            n = c1.text_input("姓名", t['tenant_name'])
            p = c2.text_input("電話", t['phone'])
            rent = c1.number_input("租金", t['base_rent'])
            e = c2.date_input("結束", datetime.strptime(t['lease_end'], "%Y-%m-%d"))
            ac = st.text_input("冷氣", t['last_ac_cleaning_date'])
            pay = st.selectbox("繳款", PAYMENT_METHODS, index=PAYMENT_METHODS.index(t.get('payment_method', '月繳')))
            col_a, col_b = st.columns(2)
            with col_a: has_discount = st.checkbox("年繳折1個月", value=bool(t.get('has_discount', 0)))
            with col_b: water = st.checkbox("收水費", value=bool(t.get('has_water_fee', 0)))
            
            if st.form_submit_button("更新"):
                db.upsert_tenant(t['room_number'], n, p, t['deposit'], rent, t['lease_start'], e.strftime("%Y-%m-%d"), pay, has_discount, water, t['discount_notes'], ac, t['id'])
                st.session_state.edit_id=None; st.rerun()
        if st.button("返回"): st.session_state.edit_id=None; st.rerun()
        
    else:
        if st.button("➕ 新增"): st.session_state.edit_id=-1; st.rerun()
        ts = db.get_tenants()
        for _, row in ts.iterrows():
            with st.expander(f"{row['room_number']} {row['tenant_name']} ({row['payment_method']})"):
                st.write(f"租期: {row['lease_end']} | 租金: ${row['base_rent']}")
                if st.button("編輯", key=f"e_{row['id']}"): st.session_state.edit_id=row['id']; st.rerun()

def page_electricity(db: RentalDB):
    st.header("💡 電費管理")
    if "current_period_id" not in st.session_state: st.session_state.current_period_id = None
    
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
                    st.success(msg)
                    time.sleep(1); st.rerun()
                else: st.error(msg)

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
                        with c1: st.write(f"**{room}**")
                        with c2: st.number_input("上期", min_value=0.0, format="%.2f", key=f"start_{room}")
                        with c3: st.number_input("本期", min_value=0.0, format="%.2f", key=f"end_{room}")
                st.divider()
                notes = st.text_area("備註")
                if st.form_submit_button("🚀 計算", type="primary"):
                    calc = ElectricityCalculatorV10()
                    tdy = {"2F": (st.session_state.fee_2f, st.session_state.kwh_2f), "3F": (st.session_state.fee_3f, st.session_state.kwh_3f), "4F": (st.session_state.fee_4f, st.session_state.kwh_4f)}
                    meter = {r: (st.session_state[f"start_{r}"], st.session_state[f"end_{r}"]) for r in ALL_ROOMS}
                    if calc.check_tdy_bills(tdy) and calc.check_meter_readings(meter):
                        for r, (s, e) in meter.items():
                            if e>s: db.add_meter_reading(st.session_state.current_period_id, r, s, e)
                        for f, (fee, k) in tdy.items():
                            if fee>0: db.add_tdy_bill(st.session_state.current_period_id, f, k, fee)
                        if calc.calculate_public_electricity():
                            ok, msg, df = db.calculate_electricity_fee(st.session_state.current_period_id, calc, meter, notes)
                            if ok: st.success(msg); st.dataframe(df)
                            else: st.error(msg)
                        else: st.error("公用電計算失敗")
                    else: st.error("\n".join(calc.errors))

    with tab3:
        st.subheader("📊 歷史帳單")
        periods = db.get_all_periods()
        if periods:
            opts = {f"{p['period_year']}年 {p['period_month_start']}-{p['period_month_end']}月": p['id'] for p in periods}
            lbl = st.selectbox("選擇期間", list(opts.keys()))
            pid = opts[lbl]
            p_data = next((p for p in periods if p['id']==pid), None)
            if p_data:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("總金額", f"${p_data['tdy_total_fee']:,.0f}")
                c2.metric("總度數", f"{p_data['tdy_total_kwh']:.1f}")
                c3.metric("單價", f"${p_data['unit_price']:.4f}")
                c4.metric("分攤", f"{p_data['public_per_room']}")
                st.dataframe(db.get_period_report(pid), use_container_width=True)

def page_expenses(db: RentalDB):
    st.header("💸 支出管理")
    with st.form("exp"):
        c1, c2 = st.columns(2)
        d = c1.date_input("日期")
        cat = c2.selectbox("分類", EXPENSE_CATEGORIES)
        amt = c1.number_input("金額")
        desc = c2.text_input("說明")
        if st.form_submit_button("記帳"):
            db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc)
            st.success("已儲存")
    st.dataframe(db.get_expenses())

def page_settings(db: RentalDB):
    st.header("⚙️ 設定")
    f = st.file_uploader("匯入 Excel", type=["xlsx"])
    if f and st.button("匯入"):
        try:
            df = pd.read_excel(f, header=1)
            for _, r in df.iterrows():
                try:
                    rm = str(r['房號']).strip()
                    if rm in ALL_ROOMS:
                        nm = str(r['姓名']) if str(r['姓名'])!='nan' else "未入住"
                        rent = float(str(r['現租金']).replace(',','')) if str(r['現租金'])!='nan' else 0
                        pay = "月繳"
                        if "年" in str(r['繳租方式']): pay = "年繳"
                        elif "半" in str(r['繳租方式']): pay = "半年繳"
                        db.upsert_tenant(rm, nm, "", 0, rent, "2024-01-01", "2025-12-31", pay)
                except: pass
            st.success("匯入完成")
        except Exception as e: st.error(str(e))
    
    if st.button("重置資料庫"):
        db.reset_database()
        st.rerun()

def main():
    st.set_page_config(page_title="幸福之家 v13.8", page_icon="🏠", layout="wide")
    st.markdown("""
    <style>
        .stApp { background-color: #f8f9fa; }
        div[data-testid="stExpander"] { background-color: #ffffff; border-radius: 8px; border: 1px solid #dee2e6; }
        button[kind="primary"] { background-color: #228be6; border: none; }
        button[kind="primary"]:hover { background-color: #1c7ed6; }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v13.8 智慧繳費連動版")
        menu = st.radio("選單", ["📊 儀表板", "💳 收租金", "👥 房客", "💡 電費", "💸 支出", "⚙️ 設定"])
    
    db = RentalDB()
    if menu == "📊 儀表板": page_dashboard(db)
    elif menu == "💳 收租金": page_collect_rent(db)
    elif menu == "👥 房客": page_tenants(db)
    elif menu == "💡 電費": page_electricity(db)
    elif menu == "💸 支出": page_expenses(db)
    else: page_settings(db)

if __name__ == "__main__":
    main()

"""
幸福之家管理系統 Pro v13.5 - 完整收租金管理版
新增功能：
1. 收租金管理專頁 - 記錄每筆租金收入
2. 房客繳費狀態追蹤 - 月份詳細記錄
3. 租金統計報表 - 金額、日期、方式
4. 應繳未繳清單 - 快速查看欠款
5. 繳費記錄編輯 - 修改金額、日期、備註
6. 所有現有功能完全保持不變
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
from functools import lru_cache

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
WATER_FEE = 100  # 水費固定 $100/月

# ============================================================================
# 電費計算類 (保持原樣)
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
# 租金計算工具函數
# ============================================================================
def calculate_actual_monthly_rent(base_rent: float, payment_method: str, has_discount: bool, has_water_fee: bool = False) -> Dict[str, float]:
    """計算實際月均租金（包含水費）"""
    actual_rent = base_rent + (WATER_FEE if has_water_fee else 0)
    
    result = {
        'base_rent': base_rent,
        'water_fee': WATER_FEE if has_water_fee else 0,
        'actual_rent': actual_rent,
        'monthly_payment': actual_rent,
        'monthly_average': actual_rent,
        'discount_amount': 0,
        'annual_total': actual_rent * 12,
        'description': '月繳'
    }
    
    if payment_method == "月繳":
        result['description'] = f"月繳 ${actual_rent:,}/月"
        if has_water_fee:
            result['description'] += f"（房租${base_rent:,} + 水費${WATER_FEE}）"
    
    elif payment_method == "半年繳":
        result['monthly_payment'] = actual_rent * 6
        result['annual_total'] = actual_rent * 12
        if has_discount:
            result['discount_amount'] = actual_rent
            result['annual_total'] = actual_rent * 12 - actual_rent
            result['monthly_average'] = result['annual_total'] / 12
            result['description'] = f"半年繳 ${result['monthly_payment']:,}/期，年折 ${result['discount_amount']:,}"
        else:
            result['monthly_average'] = actual_rent
            result['description'] = f"半年繳 ${result['monthly_payment']:,}/期"
        if has_water_fee:
            result['description'] += f"（含水費${WATER_FEE}）"
    
    elif payment_method == "年繳":
        result['monthly_payment'] = actual_rent * 12
        result['annual_total'] = actual_rent * 12
        if has_discount:
            result['discount_amount'] = actual_rent
            result['annual_total'] = actual_rent * 12 - actual_rent
            result['monthly_average'] = result['annual_total'] / 12
            result['description'] = f"年繳 ${result['monthly_payment']:,}（折1個月），平均月租 ${result['monthly_average']:.0f}"
        else:
            result['monthly_average'] = actual_rent
            result['description'] = f"年繳 ${result['monthly_payment']:,}/年"
        if has_water_fee:
            result['description'] += f"（含水費${WATER_FEE}）"
    
    return result

# ============================================================================
# 數據庫類 (v13.5 - 新增完整收租金表)
# ============================================================================
class RentalDB:
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()
        self._force_fix_schema()
        self._create_indexes()

    def _create_indexes(self):
        """創建資料庫索引以加快查詢"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_room ON tenants(room_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_paid ON rent_payments(is_paid)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_year_month ON rent_payments(year, month)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_records_room ON rent_records(room_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_records_year_month ON rent_records(year, month)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_electricity_period_year ON electricity_period(period_year)")
        except Exception as e:
            logging.warning(f"索引創建失敗: {e}")

    def reset_database(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                if "tenants_cache" in st.session_state:
                    del st.session_state.tenants_cache
                return True, "✅ 資料庫已重置，請重新整理頁面"
            return False, "⚠️ 資料庫檔案不存在"
        except Exception as e:
            return False, f"❌ 重置失敗: {e}"

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
            logging.error(f"資料庫操作失敗: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 房客表
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
            
            # 房租繳費記錄表 (v13.5 保持原有結構用於統計)
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
            
            # v13.5 新增：詳細收租金記錄表
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
            
            # 電費相關表 (保持不變)
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
            
            # 備忘錄表
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
                columns = [info[1] for info in cursor.fetchall()]
                if "payment_method" not in columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
                if "discount_notes" not in columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN discount_notes TEXT DEFAULT ''")
                if "last_ac_cleaning_date" not in columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN last_ac_cleaning_date TEXT")
                if "has_discount" not in columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_discount INTEGER DEFAULT 0")
                if "has_water_fee" not in columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN has_water_fee INTEGER DEFAULT 0")
                    
                cursor.execute("PRAGMA table_info(electricity_calculation)")
                e_cols = [info[1] for info in cursor.fetchall()]
                if "public_kwh" not in e_cols and "public_allocated_kwh" in e_cols:
                    cursor.execute("ALTER TABLE electricity_calculation RENAME COLUMN public_allocated_kwh TO public_kwh")
                
                cursor.execute("PRAGMA table_info(electricity_period)")
                ep_cols = [info[1] for info in cursor.fetchall()]
                if "notes" not in ep_cols:
                    cursor.execute("ALTER TABLE electricity_period ADD COLUMN notes TEXT DEFAULT ''")
        except Exception as e:
            logging.warning(f"Schema 修復失敗: {e}")

    # ========== 房客管理 ==========
    def room_exists(self, room: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,))
                return cursor.fetchone() is not None
        except Exception as e:
            logging.error(f"房號查詢失敗: {e}")
            return False

    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float, base_rent: float, 
                     start: str, end: str, payment_method: str = "月繳", has_discount: bool = False,
                     has_water_fee: bool = False, discount_notes: str = "", ac_date: str = None, 
                     tenant_id: Optional[int] = None) -> Tuple[bool, str]:
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
                    logging.info(f"房客新增: {room} ({name})")
                    return True, f"✅ 房號 {room} 已新增"
        except Exception as e: 
            logging.error(f"房客操作失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_tenants(self) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)
        except Exception as e:
            logging.error(f"租客查詢失敗: {e}")
            return pd.DataFrame()

    def get_tenant_by_id(self, tid: int) -> Optional[Dict]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tenants WHERE id=?", (tid,))
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    return dict(zip(cols, row))
        except Exception as e:
            logging.error(f"租客查詢失敗: {e}")
        return None

    def delete_tenant(self, tid: int) -> Tuple[bool, str]:
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
            logging.info(f"房客刪除: ID {tid}")
            return True, "✅ 已刪除"
        except Exception as e:
            logging.error(f"房客刪除失敗: {e}")
            return False, "❌ 刪除失敗"

    # ========== 租金記錄管理 (v13.5 新增) ==========
    def record_rent(self, room: str, tenant_name: str, year: int, month: int, base_amount: float,
                   water_fee: float = 0, discount_amount: float = 0, paid_amount: float = 0,
                   paid_date: Optional[str] = None, payment_method: str = "", notes: str = "") -> Tuple[bool, str]:
        """記錄租金收入"""
        try:
            with self._get_connection() as conn:
                actual_amount = base_amount + water_fee - discount_amount
                status = "已收" if paid_amount > 0 else "未收"
                
                conn.execute("""INSERT OR REPLACE INTO rent_records
                    (room_number, tenant_name, year, month, base_amount, water_fee, discount_amount, 
                     actual_amount, paid_amount, paid_date, payment_method, notes, status, recorded_by, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (room, tenant_name, year, month, base_amount, water_fee, discount_amount,
                     actual_amount, paid_amount, paid_date, payment_method, notes, status, "system", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                logging.info(f"租金記錄: {room} {year}年{month}月 ${actual_amount}")
                return True, f"✅ {room} {year}年{month}月租金已記錄"
        except Exception as e:
            logging.error(f"租金記錄失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def mark_rent_paid(self, record_id: int, paid_amount: float, paid_date: str, notes: str = "") -> Tuple[bool, str]:
        """標記租金已收"""
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE rent_records 
                    SET paid_amount=?, paid_date=?, status='已收', notes=?, updated_at=?
                    WHERE id=?""",
                    (paid_amount, paid_date, notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), record_id))
                logging.info(f"租金標記為已收: ID {record_id}")
                return True, "✅ 租金已標記為已收"
        except Exception as e:
            logging.error(f"標記失敗: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_rent_records(self, year: Optional[int] = None, month: Optional[int] = None) -> pd.DataFrame:
        """查詢租金記錄"""
        try:
            with self._get_connection() as conn:
                if year and month:
                    query = f"""SELECT * FROM rent_records 
                        WHERE year={year} AND month={month}
                        ORDER BY room_number"""
                elif year:
                    query = f"""SELECT * FROM rent_records 
                        WHERE year={year}
                        ORDER BY month DESC, room_number"""
                else:
                    query = "SELECT * FROM rent_records ORDER BY year DESC, month DESC, room_number"
                return pd.read_sql(query, conn)
        except Exception as e:
            logging.error(f"租金記錄查詢失敗: {e}")
            return pd.DataFrame()

    def get_unpaid_rents_v2(self) -> pd.DataFrame:
        """查詢未收租金"""
        try:
            with self._get_connection() as conn:
                return pd.read_sql("""
                    SELECT 
                        room_number as '房號',
                        tenant_name as '房客',
                        year as '年',
                        month as '月',
                        actual_amount as '應繳',
                        paid_amount as '已收',
                        status as '狀態'
                    FROM rent_records
                    WHERE status='未收'
                    ORDER BY year DESC, month DESC, room_number
                """, conn)
        except Exception as e:
            logging.error(f"未收租金查詢失敗: {e}")
            return pd.DataFrame()

    def get_rent_summary(self, year: int) -> Dict:
        """租金統計"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 應繳總額
                cursor.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=?", (year,))
                total_due = cursor.fetchone()[0] or 0
                
                # 已收總額
                cursor.execute("SELECT SUM(paid_amount) FROM rent_records WHERE year=? AND status='已收'", (year,))
                total_paid = cursor.fetchone()[0] or 0
                
                # 未收總額
                cursor.execute("SELECT SUM(actual_amount) FROM rent_records WHERE year=? AND status='未收'", (year,))
                total_unpaid = cursor.fetchone()[0] or 0
                
                return {
                    'total_due': total_due,
                    'total_paid': total_paid,
                    'total_unpaid': total_unpaid,
                    'collection_rate': (total_paid / total_due * 100) if total_due > 0 else 0
                }
        except Exception as e:
            logging.error(f"租金統計失敗: {e}")
            return {'total_due': 0, 'total_paid': 0, 'total_unpaid': 0, 'collection_rate': 0}

    def get_rent_by_room(self, room: str, year: Optional[int] = None) -> pd.DataFrame:
        """查詢單間房租"""
        try:
            with self._get_connection() as conn:
                if year:
                    query = f"""SELECT * FROM rent_records 
                        WHERE room_number='{room}' AND year={year}
                        ORDER BY month"""
                else:
                    query = f"""SELECT * FROM rent_records 
                        WHERE room_number='{room}'
                        ORDER BY year DESC, month DESC"""
                return pd.read_sql(query, conn)
        except Exception as e:
            logging.error(f"房間租金查詢失敗: {e}")
            return pd.DataFrame()

    # ========== 房租繳費 (保持原有功能) ==========
    def record_rent_payment(self, room: str, year: int, month: int, amount: float, paid_date: Optional[str] = None) -> bool:
        try:
            with self._get_connection() as conn:
                is_paid = 1 if paid_date else 0
                conn.execute("""INSERT OR REPLACE INTO rent_payments(room_number, year, month, amount, paid_date, is_paid) 
                    VALUES(?, ?, ?, ?, ?, ?)""", (room, year, month, amount, paid_date, is_paid))
                return True
        except Exception as e:
            logging.error(f"房租記錄失敗: {e}")
            return False

    def get_unpaid_rents(self) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("""
                    SELECT 
                        r.room_number as '房號',
                        t.tenant_name as '房客',
                        r.year as '年',
                        r.month as '月',
                        r.amount as '金額'
                    FROM rent_payments r
                    JOIN tenants t ON r.room_number = t.room_number
                    WHERE r.is_paid = 0 AND t.is_active = 1
                    ORDER BY r.year DESC, r.month DESC
                """, conn)
        except Exception as e:
            logging.error(f"未繳房租查詢失敗: {e}")
            return pd.DataFrame()

    def get_rent_matrix(self, year: int) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                df = pd.read_sql(f"""
                    SELECT room_number, month, is_paid, amount
                    FROM rent_payments 
                    WHERE year = {year}
                    ORDER BY room_number, month
                """, conn)
                
                if df.empty:
                    return pd.DataFrame()

                matrix = {}
                for room in ALL_ROOMS:
                    matrix[room] = {m: "" for m in range(1, 13)}

                for _, row in df.iterrows():
                    status = "✅" if row['is_paid'] else f"❌ ${int(row['amount'])}"
                    matrix[row['room_number']][row['month']] = status

                result_df = pd.DataFrame.from_dict(matrix, orient='index')
                result_df.columns = [f"{m}月" for m in range(1, 13)]
                return result_df
        except Exception as e:
            logging.error(f"房租矩陣查詢失敗: {e}")
            return pd.DataFrame()

    # ========== 電費管理 (保持不變) ==========
    def add_electricity_period(self, year: int, month_start: int, month_end: int) -> Tuple[bool, str, int]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM electricity_period WHERE period_year=? AND period_month_start=? AND period_month_end=?", (year, month_start, month_end))
                row = cursor.fetchone()
                if row: 
                    return True, f"✅ 期間已存在", row[0]
                cursor.execute("""INSERT INTO electricity_period(period_year, period_month_start, period_month_end) VALUES(?, ?, ?)""", (year, month_start, month_end))
                logging.info(f"電費期間新增: {year}年 {month_start}-{month_end}月")
                return True, f"✅ 計費期間已新增", cursor.lastrowid
        except Exception as e:
            logging.error(f"電費期間新增失敗: {e}")
            return False, "❌ 新增失敗", 0

    def get_all_periods(self) -> List[Dict]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period ORDER BY id DESC")
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"電費期間查詢失敗: {e}")
            return []

    def get_period_report(self, period_id: int) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("""
                    SELECT 
                        room_number as '房號',
                        private_kwh as '私表度數',
                        public_kwh as '分攤度數',
                        total_kwh as '合計度數',
                        unit_price as '單價',
                        calculated_fee as '應繳電費'
                    FROM electricity_calculation 
                    WHERE period_id = ?
                    ORDER BY room_number
                """, conn, params=(period_id,))
        except Exception as e:
            logging.error(f"電費報告查詢失敗: {e}")
            return pd.DataFrame()

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee) VALUES(?, ?, ?, ?)""", (period_id, floor_name, tdy_kwh, tdy_fee))
                return True
        except Exception as e:
            logging.error(f"台電帳單新增失敗: {e}")
            return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        try:
            kwh_usage = round(end - start, 2)
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) VALUES(?, ?, ?, ?, ?)""", (period_id, room, start, end, kwh_usage))
                return True
        except Exception as e:
            logging.error(f"度數記錄失敗: {e}")
            return False

    def update_period_calculations(self, period_id: int, unit_price: float, public_kwh: float, public_per_room: int, tdy_total_kwh: float, tdy_total_fee: float, notes: str = ""):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=?, notes=? WHERE id=?""", (unit_price, public_kwh, public_per_room, tdy_total_kwh, tdy_total_fee, notes, period_id))
            return True
        except Exception as e:
            logging.error(f"期間計算更新失敗: {e}")
            return False

    def calculate_electricity_fee(self, period_id: int, calc: ElectricityCalculatorV10, meter_data: Dict, notes: str = "") -> Tuple[bool, str, pd.DataFrame]:
        try:
            results = []
            with self._get_connection() as conn:
                for room in SHARING_ROOMS:
                    start, end = meter_data[room]
                    if end <= start: 
                        continue
                    private_kwh = round(end - start, 2)
                    public_kwh = calc.public_per_room
                    total_kwh = round(private_kwh + public_kwh, 2)
                    calculated_fee = round(total_kwh * calc.unit_price, 0)
                    results.append({
                        '房號': room,
                        '私表度數': f"{private_kwh:.2f}",
                        '分攤度數': str(public_kwh),
                        '合計度數': f"{total_kwh:.2f}",
                        '電度單價': f"${calc.unit_price:.4f}/度",
                        '應繳電費': f"${int(calculated_fee)}"
                    })
                    conn.execute("""INSERT OR REPLACE INTO electricity_calculation(period_id, room_number, private_kwh, public_kwh, total_kwh, unit_price, calculated_fee) VALUES(?, ?, ?, ?, ?, ?, ?)""", (period_id, room, private_kwh, public_kwh, total_kwh, calc.unit_price, calculated_fee))
            
            non_sharing_note = "本期記錄："
            for room, kwh in calc.non_sharing_records.items():
                non_sharing_note += f"{room}房{kwh:.2f}度、"
            non_sharing_note = non_sharing_note.rstrip("、")
            self.update_period_calculations(period_id, calc.unit_price, calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee, notes)
            results_df = pd.DataFrame(results)
            if len(results_df) > 0:
                results_df.loc[len(results_df)-1, '應繳電費'] = f"{results_df.loc[len(results_df)-1, '應繳電費']}\n\n{non_sharing_note}"
            return True, "✅ 電費計算完成", results_df
        except Exception as e:
            logging.error(f"電費計算失敗: {e}")
            return False, f"❌ 失敗: {str(e)}", pd.DataFrame()

    # ========== 支出管理 ==========
    def add_expense(self, expense_date: str, category: str, amount: float, description: str) -> bool:
        if category not in EXPENSE_CATEGORIES: 
            return False
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO expenses(expense_date, category, amount, description) VALUES(?, ?, ?, ?)""", (expense_date, category, amount, description))
            logging.info(f"支出新增: {category} ${amount} ({expense_date})")
            return True
        except Exception as e:
            logging.error(f"支出新增失敗: {e}")
            return False

    def get_expenses(self, limit: int = 50) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))
        except Exception as e:
            logging.error(f"支出查詢失敗: {e}")
            return pd.DataFrame()

    def get_expenses_summary_by_category(self, start_date: str = None, end_date: str = None) -> Dict[str, float]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if start_date and end_date:
                    cursor.execute("""SELECT category, SUM(amount) as total FROM expenses WHERE expense_date BETWEEN ? AND ? GROUP BY category ORDER BY total DESC""", (start_date, end_date))
                else:
                    cursor.execute("""SELECT category, SUM(amount) as total FROM expenses GROUP BY category ORDER BY total DESC""")
                return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            logging.error(f"支出統計失敗: {e}")
            return {}

    # ========== 備忘錄 ==========
    def add_memo(self, memo_text: str, priority: str = "normal") -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO memos(memo_text, priority) VALUES(?, ?)""", (memo_text, priority))
            logging.info(f"備忘錄新增: {memo_text[:50]}")
            return True
        except Exception as e:
            logging.error(f"備忘錄新增失敗: {e}")
            return False

    def get_memos(self, completed: bool = False) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("""SELECT * FROM memos WHERE is_completed=? ORDER BY priority DESC, created_at DESC""", conn, params=(1 if completed else 0,))
        except Exception as e:
            logging.error(f"備忘錄查詢失敗: {e}")
            return pd.DataFrame()

    def complete_memo(self, memo_id: int) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE memos SET is_completed=1 WHERE id=?", (memo_id,))
            logging.info(f"備忘錄完成: ID {memo_id}")
            return True
        except Exception as e:
            logging.error(f"備忘錄完成失敗: {e}")
            return False

    def delete_memo(self, memo_id: int) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM memos WHERE id=?", (memo_id,))
            logging.info(f"備忘錄刪除: ID {memo_id}")
            return True
        except Exception as e:
            logging.error(f"備忘錄刪除失敗: {e}")
            return False

# ============================================================================
# UI 工具
# ============================================================================
def display_card(title: str, value: str, color: str = "blue"):
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#ff6b6b"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color, '#4c6ef5')}; border-radius: 8px; padding: 15px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        <div style="color: #666; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{title}</div>
        <div style="color: #222; font-size: 1.8rem; font-weight: 800; margin-top: 8px;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 頁面層
# ============================================================================
def page_dashboard(db: RentalDB):
    st.header("📊 儀表板")
    
    # 統計卡片
    tenants = db.get_tenants()
    col1, col2, col3 = st.columns(3)
    with col1:
        occupancy = len(tenants)
        rate = (occupancy / 12 * 100) if occupancy > 0 else 0
        display_card("入住率", f"{rate:.0f}%", "blue")
    with col2:
        display_card("房間數", "12間", "green")
    with col3:
        display_card("分攤房間", "10間", "orange")
    
    st.divider()
    
    # 年度房租繳費總覽表
    st.subheader("📅 年度房租繳費總覽")
    year = st.selectbox("選擇年份", [datetime.now().year, datetime.now().year + 1], key="rent_year_select")
    rent_matrix = db.get_rent_matrix(year)
    if not rent_matrix.empty:
        st.dataframe(rent_matrix, use_container_width=True)
        st.caption("✅ = 已繳款 / ❌ = 未繳款 (顯示金額)")
    else:
        st.info(f"ℹ️ {year} 年尚無繳費記錄")

    st.divider()
    
    # 備忘錄區域
    st.subheader("📝 重要備忘錄")
    memos = db.get_memos(completed=False)
    if not memos.empty:
        for idx, (_, memo) in enumerate(memos.iterrows()):
            icon = "🔴" if memo['priority'] == "high" else "🟡"
            col1, col2, col3 = st.columns([0.5, 5, 1])
            with col1: 
                st.write(icon)
            with col2: 
                st.write(f"**{memo['memo_text']}**")
            with col3:
                if st.button("✓", key=f"memo_{memo['id']}", help="標記為完成"):
                    db.complete_memo(memo['id'])
                    st.rerun()
    else: 
        st.success("✅ 暫無待辦事項")
    
    st.divider()
    
    # 未繳房租列表
    st.subheader("💰 未繳房租清單")
    unpaid = db.get_unpaid_rents()
    if not unpaid.empty:
        st.dataframe(unpaid, use_container_width=True, hide_index=True)
        st.warning(f"⚠️ 共 {len(unpaid)} 筆未繳房租")
    else:
        st.success("✅ 所有房租已繳")
    
    st.divider()
    
    # 房間狀態
    st.subheader("🏠 房間狀態")
    active_rooms = tenants['room_number'].tolist() if not tenants.empty else []
    cols = st.columns(6)
    for i, room in enumerate(ALL_ROOMS):
        with cols[i % 6]:
            if room in active_rooms: 
                t_row = tenants[tenants['room_number'] == room].iloc[0]
                ac_info = f"\n❄️{t_row['last_ac_cleaning_date']}" if t_row['last_ac_cleaning_date'] else ""
                st.success(f"{room}{ac_info}")
            else: 
                st.error(f"{room}\n空房")

def page_collect_rent(db: RentalDB):
    """v13.5 新增：收租金專頁"""
    st.header("💳 收租金管理")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📝 記錄租金", "📊 收租統計", "📋 租金明細", "⚙️ 調整記錄"])
    
    with tab1:
        st.subheader("➕ 新增收租記錄")
        tenants = db.get_tenants()
        
        if not tenants.empty:
            with st.form("record_rent_form", border=True):
                col1, col2 = st.columns(2)
                with col1:
                    room = st.selectbox("房號", [t['room_number'] for _, t in tenants.iterrows()], key="collect_room")
                    selected_tenant = tenants[tenants['room_number'] == room].iloc[0]
                    
                    year = st.number_input("年", value=datetime.now().year, key="collect_year")
                    month = st.number_input("月", value=datetime.now().month, min_value=1, max_value=12, key="collect_month")
                
                with col2:
                    base_amount = st.number_input("房租", value=selected_tenant['base_rent'], key="collect_base")
                    water_fee = st.number_input("水費", value=WATER_FEE if bool(selected_tenant.get('has_water_fee', 0)) else 0, key="collect_water")
                    discount = st.number_input("折扣", value=0, key="collect_discount")
                
                st.divider()
                
                # 顯示計算結果
                actual = base_amount + water_fee - discount
                col1, col2, col3 = st.columns(3)
                with col1:
                    display_card("房租", f"${base_amount:,.0f}", "blue")
                with col2:
                    display_card("水費", f"${water_fee:,.0f}", "orange")
                with col3:
                    display_card("應繳", f"${actual:,.0f}", "green")
                
                st.divider()
                
                col1, col2 = st.columns(2)
                with col1:
                    paid_amount = st.number_input("已收金額", value=0, key="collect_paid")
                    paid_date = st.date_input("收款日期", key="collect_date")
                
                with col2:
                    payment_method = st.selectbox("繳費方式", ["月繳", "半年繳", "年繳"], key="collect_method")
                    notes = st.text_input("備註", key="collect_notes")
                
                if st.form_submit_button("✅ 保存租金記錄", type="primary", use_container_width=True):
                    ok, msg = db.record_rent(
                        room, selected_tenant['tenant_name'], year, month,
                        base_amount, water_fee, discount, paid_amount,
                        paid_date.strftime("%Y-%m-%d") if paid_amount > 0 else None,
                        payment_method, notes
                    )
                    if ok:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.warning("⚠️ 請先新增房客")
    
    with tab2:
        st.subheader("📊 租金收入統計")
        year = st.selectbox("選擇年份", [datetime.now().year, datetime.now().year + 1, datetime.now().year + 2], key="stat_year")
        
        summary = db.get_rent_summary(year)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            display_card("應繳總額", f"${int(summary['total_due']):,}", "blue")
        with col2:
            display_card("已收總額", f"${int(summary['total_paid']):,}", "green")
        with col3:
            display_card("未收總額", f"${int(summary['total_unpaid']):,}", "red")
        with col4:
            display_card("收款率", f"{summary['collection_rate']:.1f}%", "orange")
        
        st.divider()
        
        # 月度統計
        st.subheader("📅 月度統計")
        rent_records = db.get_rent_records(year=year)
        
        if not rent_records.empty:
            monthly_stats = []
            for month in range(1, 13):
                month_data = rent_records[rent_records['month'] == month]
                if not month_data.empty:
                    total_due = month_data['actual_amount'].sum()
                    total_paid = month_data['paid_amount'].sum()
                    unpaid_count = len(month_data[month_data['status'] == '未收'])
                    monthly_stats.append({
                        '月份': f"{year}年{month}月",
                        '應繳': f"${int(total_due):,}",
                        '已收': f"${int(total_paid):,}",
                        '未收': f"{unpaid_count}件",
                        '進度': f"{(total_paid/total_due*100) if total_due > 0 else 0:.0f}%"
                    })
            
            if monthly_stats:
                st.dataframe(pd.DataFrame(monthly_stats), use_container_width=True, hide_index=True)
    
    with tab3:
        st.subheader("📋 租金詳細記錄")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_year = st.selectbox("年份", [datetime.now().year, datetime.now().year + 1, datetime.now().year + 2], key="detail_year")
        with col2:
            filter_month = st.selectbox("月份", ["全部"] + list(range(1, 13)), key="detail_month")
        with col3:
            filter_status = st.selectbox("狀態", ["全部", "已收", "未收"], key="detail_status")
        
        if filter_month == "全部":
            records = db.get_rent_records(year=filter_year)
        else:
            records = db.get_rent_records(year=filter_year, month=filter_month)
        
        if not records.empty:
            # 篩選狀態
            if filter_status != "全部":
                records = records[records['status'] == filter_status]
            
            # 顯示表格
            display_cols = ['room_number', 'tenant_name', 'year', 'month', 'base_amount', 
                          'water_fee', 'discount_amount', 'actual_amount', 'paid_amount', 'paid_date', 'status']
            display_records = records[display_cols].copy()
            display_records.columns = ['房號', '房客', '年', '月', '房租', '水費', '折扣', '應繳', '已收', '收款日期', '狀態']
            
            st.dataframe(display_records, use_container_width=True, hide_index=True)
            
            st.divider()
            
            # 統計
            total_due = records['actual_amount'].sum()
            total_paid = records['paid_amount'].sum()
            col1, col2, col3 = st.columns(3)
            with col1:
                display_card("應繳小計", f"${int(total_due):,}", "blue")
            with col2:
                display_card("已收小計", f"${int(total_paid):,}", "green")
            with col3:
                display_card("進度", f"{(total_paid/total_due*100) if total_due > 0 else 0:.0f}%", "orange")
        else:
            st.info("🔍 查詢結果為空")
    
    with tab4:
        st.subheader("✏️ 調整已記錄的租金")
        
        tenants = db.get_tenants()
        if not tenants.empty:
            room = st.selectbox("選擇房號查看歷史", [t['room_number'] for _, t in tenants.iterrows()], key="adjust_room")
            room_records = db.get_rent_by_room(room)
            
            if not room_records.empty:
                st.dataframe(room_records[['year', 'month', 'actual_amount', 'paid_amount', 'status', 'notes']], 
                           use_container_width=True, hide_index=True)
                
                st.info("💡 要調整記錄，請到【記錄租金】重新保存該月份資料（會自動覆蓋舊記錄）")
            else:
                st.info(f"🔍 {room} 房間暫無租金記錄")
        else:
            st.warning("⚠️ 請先新增房客")

def page_tenants(db: RentalDB):
    st.header("👥 房客管理")
    
    if "edit_id" not in st.session_state: 
        st.session_state.edit_id = None
    
    # 新增模式
    if st.session_state.edit_id == -1:
        st.subheader("➕ 新增租客")
        tenants_df = db.get_tenants()
        existing = tenants_df['room_number'].tolist() if not tenants_df.empty else []
        available = [r for r in ALL_ROOMS if r not in existing]
        
        if available:
            with st.form("add_form", border=True):
                room = st.selectbox("房號", available, key="add_room")
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("姓名", key="add_name")
                    phone = st.text_input("電話", key="add_phone")
                    deposit = st.number_input("押金", value=10000, key="add_deposit")
                with col2:
                    base_rent = st.number_input("房租（月繳金額）", value=6000, key="add_rent")
                    start = st.date_input("租約開始", key="add_start")
                    end = st.date_input("租約結束", value=date.today() + timedelta(days=365), key="add_end")
                
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    payment_method = st.selectbox("繳費方式", PAYMENT_METHODS, key="add_payment")
                    ac_date_val = st.text_input("冷氣清洗日期", placeholder="例如：113.06.28", key="add_ac")
                with col2:
                    has_discount = st.checkbox("年繳折1個月房租", value=False, key="add_discount", help="勾選此項表示該房客年繳時可折1個月房租")
                    has_water_fee = st.checkbox("收水費（$100/月）", value=False, key="add_water", help="勾選此項表示房客需額外支付水費$100")
                
                st.divider()
                discount_notes = st.text_input("其他備註", placeholder="例：虎科大碩一", key="add_notes")
                
                # 顯示租金計算
                if st.session_state.get("add_payment"):
                    st.divider()
                    st.subheader("💰 租金計算預覽")
                    calc = calculate_actual_monthly_rent(
                        st.session_state.get("add_rent", 6000), 
                        st.session_state.get("add_payment", "月繳"), 
                        st.session_state.get("add_discount", False),
                        st.session_state.get("add_water", False)
                    )
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        display_card("實際月租", f"${calc['actual_rent']:,.0f}", "blue")
                    with col2:
                        display_card("每期支付", f"${calc['monthly_payment']:,.0f}", "green")
                    with col3:
                        display_card("實際月均", f"${calc['monthly_average']:.0f}", "orange")
                    
                    st.info(f"📌 {calc['description']}")
                    
                    # 詳細說明
                    st.markdown("**計算詳情：**")
                    if calc['water_fee'] > 0:
                        st.write(f"• 房租：${calc['base_rent']:,} + 水費：${calc['water_fee']} = 實際月租：${calc['actual_rent']:,}")
                    else:
                        st.write(f"• 房租：${calc['base_rent']:,}（無水費）")
                
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("✅ 確認新增", type="primary", use_container_width=True):
                        ok, msg = db.upsert_tenant(
                            room, name, phone, deposit, st.session_state.get("add_rent", 6000), 
                            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), 
                            st.session_state.get("add_payment", "月繳"), 
                            st.session_state.get("add_discount", False),
                            st.session_state.get("add_water", False),
                            discount_notes, ac_date_val
                        )
                        if ok:
                            st.success(msg)
                            st.session_state.edit_id = None
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                with col2:
                    if st.form_submit_button("❌ 取消", use_container_width=True):
                        st.session_state.edit_id = None
                        st.rerun()
        else:
            st.warning("⚠️ 沒有空房間可新增")
    
    # 編輯模式
    elif st.session_state.edit_id and st.session_state.edit_id > 0:
        tenant = db.get_tenant_by_id(st.session_state.edit_id)
        if tenant:
            st.subheader(f"✏️ 編輯房客 - {tenant['room_number']} {tenant['tenant_name']}")
            with st.form("edit_form", border=True):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("姓名", value=tenant['tenant_name'], key="edit_name")
                    phone = st.text_input("電話", value=tenant['phone'] or "", key="edit_phone")
                    deposit = st.number_input("押金", value=tenant['deposit'], key="edit_deposit")
                with col2:
                    base_rent = st.number_input("房租（月繳金額）", value=tenant['base_rent'], key="edit_rent")
                    start = st.date_input("租約開始", value=datetime.strptime(tenant['lease_start'], "%Y-%m-%d").date(), key="edit_start")
                    end = st.date_input("租約結束", value=datetime.strptime(tenant['lease_end'], "%Y-%m-%d").date(), key="edit_end")
                
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    payment_method = st.selectbox("繳費方式", PAYMENT_METHODS, index=PAYMENT_METHODS.index(tenant.get('payment_method', '月繳')), key="edit_payment")
                    ac_date_val = st.text_input("冷氣清洗日期", value=tenant.get('last_ac_cleaning_date', ''), key="edit_ac")
                with col2:
                    has_discount = st.checkbox("年繳折1個月房租", value=bool(tenant.get('has_discount', 0)), key="edit_discount", help="勾選此項表示該房客年繳時可折1個月房租")
                    has_water_fee = st.checkbox("收水費（$100/月）", value=bool(tenant.get('has_water_fee', 0)), key="edit_water", help="勾選此項表示房客需額外支付水費$100")
                
                st.divider()
                discount_notes = st.text_input("其他備註", value=tenant.get('discount_notes', ''), key="edit_notes")
                
                # 顯示租金計算
                if st.session_state.get("edit_payment"):
                    st.divider()
                    st.subheader("💰 租金計算預覽")
                    calc = calculate_actual_monthly_rent(
                        st.session_state.get("edit_rent", tenant['base_rent']), 
                        st.session_state.get("edit_payment", tenant.get('payment_method', '月繳')), 
                        st.session_state.get("edit_discount", bool(tenant.get('has_discount', 0))),
                        st.session_state.get("edit_water", bool(tenant.get('has_water_fee', 0)))
                    )
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        display_card("實際月租", f"${calc['actual_rent']:,.0f}", "blue")
                    with col2:
                        display_card("每期支付", f"${calc['monthly_payment']:,.0f}", "green")
                    with col3:
                        display_card("實際月均", f"${calc['monthly_average']:.0f}", "orange")
                    
                    st.info(f"📌 {calc['description']}")
                    
                    # 詳細說明
                    st.markdown("**計算詳情：**")
                    if calc['water_fee'] > 0:
                        st.write(f"• 房租：${calc['base_rent']:,} + 水費：${calc['water_fee']} = 實際月租：${calc['actual_rent']:,}")
                    else:
                        st.write(f"• 房租：${calc['base_rent']:,}（無水費）")
                
                st.divider()
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.form_submit_button("✅ 確認更新", type="primary"):
                        ok, msg = db.upsert_tenant(
                            tenant['room_number'], name, phone, deposit, st.session_state.get("edit_rent", tenant['base_rent']),
                            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), 
                            st.session_state.get("edit_payment", tenant.get('payment_method', '月繳')), 
                            st.session_state.get("edit_discount", bool(tenant.get('has_discount', 0))),
                            st.session_state.get("edit_water", bool(tenant.get('has_water_fee', 0))),
                            discount_notes, ac_date_val, tenant['id']
                        )
                        if ok:
                            st.success(msg)
                            st.session_state.edit_id = None
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                with col2:
                    if st.form_submit_button("🗑️ 刪除房客", type="secondary"):
                        ok, msg = db.delete_tenant(tenant['id'])
                        if ok:
                            st.success(msg)
                            st.session_state.edit_id = None
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                with col3:
                    if st.form_submit_button("❌ 取消", use_container_width=True):
                        st.session_state.edit_id = None
                        st.rerun()
    
    # 列表模式
    else:
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("➕ 新增房客", type="primary", use_container_width=True):
                st.session_state.edit_id = -1
                st.rerun()
        
        tenants_df = db.get_tenants()
        if not tenants_df.empty:
            for idx, (_, row) in enumerate(tenants_df.iterrows()):
                # 計算實際月均租金並顯示
                calc = calculate_actual_monthly_rent(
                    row['base_rent'], 
                    row['payment_method'], 
                    bool(row.get('has_discount', 0)),
                    bool(row.get('has_water_fee', 0))
                )
                
                water_badge = " 💧" if bool(row.get('has_water_fee', 0)) else ""
                ac_info = f" | ❄️ {row['last_ac_cleaning_date']}" if row['last_ac_cleaning_date'] else ""
                expander_label = f"🏠 {row['room_number']} - {row['tenant_name']} | 月均${calc['monthly_average']:.0f}{water_badge}{ac_info}"
                
                with st.expander(expander_label):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**電話：** {row['phone']}")
                        st.write(f"**基本房租：** ${row['base_rent']:,}/月")
                        
                        # 水費標示
                        if calc['water_fee'] > 0:
                            st.write(f"**水費：** ${calc['water_fee']}/月")
                            st.write(f"**實際月租：** ${calc['actual_rent']:,}/月")
                        
                        # 顯示繳費方式與計算
                        st.divider()
                        st.write(f"**繳費方式：** {row['payment_method']}")
                        st.write(f"**每期支付：** ${calc['monthly_payment']:,.0f}")
                        st.write(f"**實際月均：** ${calc['monthly_average']:.0f}")
                        if calc['discount_amount'] > 0:
                            st.write(f"**年度折扣：** ${calc['discount_amount']:,.0f}")
                        st.info(f"📌 {calc['description']}")
                        
                        st.divider()
                        st.write(f"**押金：** ${row['deposit']:,}")
                        if row['discount_notes']:
                            st.info(f"📝 **備註：** {row['discount_notes']}")
                        st.write(f"**租期：** {row['lease_start']} ～ {row['lease_end']}")
                    with col2:
                        if st.button("✏️ 編輯", key=f"edit_{row['id']}", use_container_width=True):
                            st.session_state.edit_id = row['id']
                            st.rerun()
        else:
            st.info("暫無租客記錄")

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
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先在【① 新增期間】選項卡中建立計費期間")
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
                st.markdown("### 📝 備註（選填）")
                notes = st.text_area("紀錄此期間的特殊事項", placeholder="例：某房間電表損壞")
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
                            st.success(msg)
                            st.dataframe(df, use_container_width=True, hide_index=True)
                        else:
                            st.error(msg)
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

def page_expenses(db: RentalDB):
    st.header("💸 支出管理")
    tab1, tab2, tab3 = st.tabs(["新增支出", "支出記錄", "📊 統計分析"])
    
    with tab1:
        with st.form("expense_form", border=True):
            col1, col2 = st.columns([1, 1])
            with col1:
                d = st.date_input("日期", value=date.today(), key="exp_date")
                cat = st.selectbox("分類", EXPENSE_CATEGORIES, key="exp_cat")
            with col2:
                amt = st.number_input("金額 ($)", min_value=0, key="exp_amt")
                desc = st.text_input("說明", placeholder="例：更換馬桶蓋", key="exp_desc")
            if st.form_submit_button("➕ 新增支出", type="primary", use_container_width=True):
                if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc):
                    st.success("✅ 已記錄")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ 記錄失敗")
    
    with tab2:
        st.subheader("📋 最近支出")
        expenses = db.get_expenses(50)
        if not expenses.empty:
            display_df = expenses[['expense_date', 'category', 'amount', 'description']].copy()
            display_df.columns = ['日期', '分類', '金額($)', '說明']
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("暫無支出記錄")
    
    with tab3:
        st.subheader("📊 支出統計分析")
        col1, col2 = st.columns([1, 2])
        with col1:
            time_filter = st.radio("時間範圍", ["全部", "本年", "本月"], key="time_filter")
        
        if time_filter == "全部":
            summary = db.get_expenses_summary_by_category()
        elif time_filter == "本年":
            start = f"{datetime.now().year}-01-01"
            end = datetime.now().strftime("%Y-%m-%d")
            summary = db.get_expenses_summary_by_category(start, end)
        else:
            start = datetime.now().strftime("%Y-%m-01")
            end = datetime.now().strftime("%Y-%m-%d")
            summary = db.get_expenses_summary_by_category(start, end)
        
        if summary:
            total_expense = sum(summary.values())
            col1, col2 = st.columns(2)
            with col1: 
                display_card("總支出", f"${int(total_expense):,}", "blue")
            with col2: 
                display_card("分類數", str(len(summary)), "green")
            st.divider()
            
            chart_data = pd.DataFrame(list(summary.items()), columns=['分類', '金額'])
            st.bar_chart(chart_data.set_index('分類'), use_container_width=True)
            st.divider()
            
            # 詳細統計表
            detail_data = []
            for cat, amount in sorted(summary.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense * 100) if total_expense > 0 else 0
                detail_data.append({'分類': cat, '金額($)': f"${int(amount):,}", '占比': f"{percentage:.1f}%"})
            detail_df = pd.DataFrame(detail_data)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        else:
            st.info(f"📭 此時間範圍內暫無支出記錄")

def page_settings(db: RentalDB):
    st.header("⚙️ 設定")
    
    st.subheader("📥 Excel 匯入")
    st.markdown("請上傳 `幸福之家539巷8-13號.xlsx`。系統將自動讀取房客資訊。")
    uploaded_file = st.file_uploader("上傳 Excel 檔", type=["xlsx", "xls"], key="excel_upload")
    
    if uploaded_file:
        if st.button("🚀 開始匯入資料", type="primary"):
            with st.spinner("正在匯入..."):
                try:
                    df = pd.read_excel(uploaded_file, header=1)
                    success_count = 0
                    fail_count = 0
                    
                    for _, row in df.iterrows():
                        room = str(row.get('房號', '')).strip()
                        if not room or room == 'nan' or room == '計': 
                            continue
                            
                        name = str(row.get('姓名', ''))
                        if name == 'nan': 
                            name = "未入住"
                        
                        lease_end_raw = str(row.get('租期至', ''))
                        lease_end = "2025-12-31"
                        if lease_end_raw and lease_end_raw != 'nan':
                            parts = lease_end_raw.replace('.', '-').split('-')
                            if len(parts) == 3:
                                y = int(parts[0]) + 1911
                                lease_end = f"{y}-{parts[1]:0>2}-{parts[2]:0>2}"
                        
                        lease_start = (datetime.strptime(lease_end, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
                        
                        try:
                            deposit = float(str(row.get('押金', 0)).replace(',', ''))
                        except: 
                            deposit = 0
                        
                        try:
                            rent = float(str(row.get('現租金', 0)).replace(',', ''))
                        except: 
                            rent = 0
                        
                        payment_method_raw = str(row.get('繳租方式', '')).strip()
                        payment_method = "月繳"
                        if "半" in payment_method_raw: 
                            payment_method = "半年繳"
                        elif "年" in payment_method_raw: 
                            payment_method = "年繳"
                        
                        notes = str(row.get('備註', ''))
                        if notes == 'nan': 
                            notes = ""
                        
                        ac_date = str(row.get('清洗冷氣日期', ''))
                        if ac_date == 'nan': 
                            ac_date = ""
                        
                        # 檢查是否有折扣與水費
                        has_discount = "折" in notes or "折" in payment_method_raw
                        has_water_fee = "水費" in notes or "水" in notes
                        
                        ok, msg = db.upsert_tenant(room, name, "", deposit, rent, lease_start, lease_end, payment_method, has_discount, has_water_fee, notes, ac_date)
                        if ok: 
                            success_count += 1
                        else: 
                            fail_count += 1
                    
                    st.success(f"✅ 匯入完成！成功: {success_count}, 失敗: {fail_count}")
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ 匯入失敗: {e}")
                    logging.error(f"Excel 匯入失敗: {e}")

    st.divider()
    st.subheader("💾 資料備份與重置")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 下載資料庫備份", type="secondary", use_container_width=True):
            try:
                with open(db.db_path, 'rb') as f:
                    st.download_button(
                        label="下載備份",
                        data=f.read(),
                        file_name=f"rental_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                        mime="application/octet-stream"
                    )
            except:
                st.error("備份失敗")
    
    with col2:
        if st.button("💥 重置整個系統", type="secondary", use_container_width=True):
            if st.checkbox("⚠️ 我確認要刪除所有資料"):
                ok, msg = db.reset_database()
                if ok: 
                    st.success(msg)
                    time.sleep(2)
                    st.rerun()
                else: 
                    st.error(msg)

def main():
    st.set_page_config(page_title="幸福之家 v13.5", page_icon="🏠", layout="wide", initial_sidebar_state="expanded")
    st.markdown("""
    <style>
    [data-testid="stSidebarContent"] { padding-top: 0rem; }
    .stTabs [role="tablist"] button { min-height: 45px; }
    </style>
    """, unsafe_allow_html=True)
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v13.5 完整收租金版")
        st.divider()
        menu = st.radio("主選單", ["📊 儀表板", "💳 收租金", "👥 房客", "💡 電費", "💸 支出", "⚙️ 設定"], label_visibility="collapsed")
    
    db = RentalDB()
    
    if menu == "📊 儀表板": 
        page_dashboard(db)
    elif menu == "💳 收租金": 
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

"""
幸福之家管理系統 Pro v7.0 - 完整版 + 台電單位價格
保留所有功能：儀表板、房客、電費、支出、設定
核心改進：深度診斷 + 台電單位價格計算

【v7.0 新功能】:
1. 計算台電單位價格（當期1度/元）
2. 用單位價格反推驗證度數合理性
3. 保留所有頁面功能（儀表板、房客、電費、支出、設定）
4. 深度診斷檢查
5. 詳細的電費報告

【核心邏輯】:
台電單位價格 = 台電總費用 / 台電總度數（元/度）
房間應繳 = 房間總度數 × 台電單位價格
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
ROOM_FLOOR_MAP = {
    "1A": "1F", "1B": "1F",
    "2A": "2F", "2B": "2F",
    "3A": "3F", "3B": "3F", "3C": "3F", "3D": "3F",
    "4A": "4F", "4B": "4F", "4C": "4F", "4D": "4F"
}

# ============================================================================
# 超級診斷類 (v7.0 - 加入台電單位價格)
# ============================================================================
class DeepElectricityDiagnosticsV7:
    """深度電費數據診斷類 - v7.0 + 台電單位價格"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
        self.tdy_total_kwh = 0
        self.tdy_total_fee = 0
        self.unit_price = 0  # 台電單位價格（元/度）
        self.meter_total = 0
    
    def check_tdy_bills(self, tdy_data: Dict[str, Tuple[float, float]]) -> Tuple[int, float, float]:
        """檢查台電單據 - v7.0 加入單位價格計算"""
        valid_count = 0
        total_kwh = 0
        total_fee = 0
        
        st.markdown("### 🔍 台電單據檢查")
        
        for floor, (fee, kwh) in tdy_data.items():
            if fee == 0 and kwh == 0:
                self.errors.append(f"🚨 【{floor}】完全沒有輸入！")
                st.error(f"❌ {floor}: 完全沒有輸入（金額: $0, 度數: 0度）")
            
            elif kwh == 0:
                self.errors.append(f"🚨 【{floor}】度數為 0！")
                st.error(f"❌ {floor}: ⚠️⚠️⚠️ 【度數為 0】⚠️⚠️⚠️")
                st.error(f"   目前: 金額 ${fee:,.0f}，度數 0 度（❌ 不合理）")
                st.info("💡 提示：請查看台電單據上的『度數』欄位")
            
            elif fee == 0:
                self.errors.append(f"🚨 【{floor}】金額為 0！")
                st.error(f"❌ {floor}: 金額為 0 元（度數: {kwh:.1f}度）")
            
            elif kwh < 0 or fee < 0:
                self.errors.append(f"🚨 【{floor}】不能是負數")
                st.error(f"❌ {floor}: 度數或金額不能是負數！")
            
            else:
                # ✅ 有效的台電單據
                unit_price = fee / kwh  # 【v7.0 新增】計算單位價格
                self.info.append(f"✅ 【{floor}】度數: {kwh:.1f}度，金額: ${fee:,.0f}，單價: ${unit_price:.2f}/度")
                st.success(f"✅ {floor}: {kwh:.1f}度 × ${unit_price:.2f}/度 = ${fee:,.0f}")
                valid_count += 1
                total_kwh += kwh
                total_fee += fee
        
        # 【v7.0 新增】計算平均台電單位價格
        if total_kwh > 0:
            self.unit_price = total_fee / total_kwh
            self.tdy_total_kwh = total_kwh
            self.tdy_total_fee = total_fee
        
        if valid_count == 0:
            self.errors.append("🚨 【台電單據】需要至少輸入一個樓層的完整數據")
            st.error("🚨 沒有任何有效的台電單據！")
        else:
            st.info(f"✅ 台電單據: {valid_count}/3 個樓層，總度數: {total_kwh:.1f}度，總費用: ${total_fee:,.0f}")
            st.success(f"📊 【台電單位價格】${self.unit_price:.4f}/度（這是計算房租的基準）")
        
        return valid_count, total_kwh, total_fee
    
    def check_meter_readings(self, meter_data: Dict[str, Tuple[float, float]]) -> Tuple[int, float]:
        """檢查房間度數"""
        valid_count = 0
        total_kwh = 0
        
        st.markdown("### 🔍 房間度數檢查")
        
        for room, (start, end) in meter_data.items():
            if start == 0 and end == 0:
                continue
            
            elif end == 0 and start > 0:
                self.warnings.append(f"⚠️ 【{room}】只輸入了上期，沒有本期度數")
                st.warning(f"⚠️ {room}: 只有上期({start:.1f}度)，沒有本期度數")
            
            elif start == 0 and end > 0:
                st.warning(f"⚠️ {room}: 沒有上期度數 → 本期 {end:.1f}度")
                self.info.append(f"✅ 【{room}】0 → {end:.1f} = {end:.1f}度（新房客）")
                valid_count += 1
                total_kwh += end
            
            elif end > start:
                usage = end - start
                st.success(f"✅ {room}: {start:.1f} → {end:.1f} （使用 {usage:.1f}度）")
                self.info.append(f"✅ 【{room}】{start:.1f} → {end:.1f} = {usage:.1f}度")
                valid_count += 1
                total_kwh += usage
            
            elif end < start:
                self.errors.append(f"🚨 【{room}】本期({end:.1f}) < 上期({start:.1f})")
                st.error(f"❌ {room}: 本期({end:.1f}) < 上期({start:.1f})")
                st.error(f"   💥 【錯誤】度數只能增加，不能減少！")
            
            elif end == start:
                self.warnings.append(f"⚠️ 【{room}】上期 = 本期（都是 {start:.1f}度）")
                st.warning(f"⚠️ {room}: 上期 = 本期 = {start:.1f}度（度數使用: 0度）")
        
        self.meter_total = total_kwh
        
        if valid_count == 0:
            self.errors.append("🚨 【房間度數】需要至少輸入一個房間的本期度數")
            st.error("🚨 沒有任何有效的房間度數！")
        else:
            st.info(f"✅ 房間度數: {valid_count}/{len(ALL_ROOMS)} 個房間，總度數: {total_kwh:.1f}度")
        
        return valid_count, total_kwh
    
    def compare_totals(self) -> bool:
        """【v7.0】比對台電度數 vs 房間度數"""
        st.markdown("### ⚖️ 度數對比檢查（【最重要】）")
        
        st.info(f"台電總度數: {self.tdy_total_kwh:.1f}度 vs 房間加總: {self.meter_total:.1f}度")
        
        if self.tdy_total_kwh == 0:
            self.errors.append("🚨 【台電度數為 0】計算失敗的主要原因！")
            st.error("🚨 台電度數為 0 - 請確認已輸入台電單據的度數")
            return False
        
        if self.meter_total == 0:
            self.errors.append("🚨 【房間度數加總為 0】")
            st.error("🚨 房間度數加總為 0 - 請確認至少有一個房間的本期 > 上期")
            return False
        
        if self.meter_total > self.tdy_total_kwh * 1.1:
            self.errors.append(f"🚨 房間加總超過台電度數！")
            st.error(f"❌ 房間加總: {self.meter_total:.1f}度 > 台電度數: {self.tdy_total_kwh:.1f}度")
            return False
        
        elif self.meter_total < self.tdy_total_kwh * 0.5:
            self.warnings.append(f"⚠️ 房間加總少於台電度數 50%")
            st.warning(f"⚠️ 房間加總: {self.meter_total:.1f}度 < 台電度數: {self.tdy_total_kwh:.1f}度")
            st.info(f"   差異: {self.tdy_total_kwh - self.meter_total:.1f}度（可能是公共電費）")
        
        else:
            st.success(f"✅ 度數對比合理")
        
        return len(self.errors) == 0
    
    def diagnose(self) -> Tuple[bool, str]:
        """最終診斷"""
        st.markdown("---")
        st.markdown("### 📋 最終診斷結果")
        
        if self.errors:
            error_msg = "🔴 **檢測到以下致命錯誤，無法進行計算：**\n\n"
            for i, error in enumerate(self.errors, 1):
                error_msg += f"{i}. {error}\n"
            return False, error_msg
        
        if self.warnings:
            warning_msg = "🟡 **警告信息（通常不影響計算）：**\n\n"
            for i, warning in enumerate(self.warnings, 1):
                warning_msg += f"{i}. {warning}\n"
            return True, warning_msg
        
        return True, "✅ 所有檢查都通過了！"

# ============================================================================
# 數據庫類 (完整版，保留所有表)
# ============================================================================
class RentalDB:
    """數據庫操作類 - v7.0 完整版"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()

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
            logging.error(f"DB Error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT UNIQUE NOT NULL,
                    tenant_name TEXT NOT NULL,
                    phone TEXT,
                    deposit REAL DEFAULT 0,
                    base_rent REAL DEFAULT 0,
                    electricity_fee REAL DEFAULT 0,
                    monthly_rent REAL DEFAULT 0,
                    lease_start TEXT NOT NULL,
                    lease_end TEXT NOT NULL,
                    payment_method TEXT DEFAULT '月繳',
                    annual_discount_months INTEGER DEFAULT 0,
                    has_water_discount INTEGER DEFAULT 0,
                    prepaid_electricity REAL DEFAULT 0,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_period (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_year INTEGER NOT NULL,
                    period_month_start INTEGER NOT NULL,
                    period_month_end INTEGER NOT NULL,
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
                    unit_price REAL DEFAULT 0,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                    UNIQUE(period_id, room_number)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_sharing_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_id INTEGER NOT NULL,
                    room_number TEXT NOT NULL,
                    is_sharing INTEGER DEFAULT 1,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                    UNIQUE(period_id, room_number)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_calculation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_id INTEGER NOT NULL,
                    room_number TEXT NOT NULL,
                    floor_name TEXT,
                    private_kwh REAL NOT NULL,
                    allocated_kwh REAL NOT NULL,
                    total_kwh REAL NOT NULL,
                    unit_price REAL NOT NULL,
                    calculated_fee REAL NOT NULL,
                    prepaid_balance REAL DEFAULT 0,
                    actual_payment REAL NOT NULL,
                    payment_date TEXT,
                    status TEXT DEFAULT '未收',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_prepaid (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT NOT NULL,
                    prepaid_amount REAL NOT NULL,
                    prepaid_date TEXT NOT NULL,
                    balance REAL NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT NOT NULL,
                    payment_date TEXT NOT NULL,
                    base_rent REAL DEFAULT 0,
                    electricity_fee REAL DEFAULT 0,
                    payment_amount REAL NOT NULL,
                    payment_type TEXT,
                    status TEXT DEFAULT '已收',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT,
                    room_number TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_room ON tenants(room_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_period ON electricity_period(period_year)")
            
            logging.info("Database initialized")

    # ============================================================================
    # 租客管理方法
    # ============================================================================
    def room_exists(self, room: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,))
                return cursor.fetchone() is not None
        except:
            return False

    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float, base_rent: float, 
                     elec_fee: float, start: str, end: str, method: str, discount: int, 
                     water: int, prepaid: float, notes: str, tenant_id: Optional[int] = None) -> Tuple[bool, str]:
        try:
            monthly_rent = base_rent + elec_fee
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if tenant_id:
                    cursor.execute("""
                        UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?, electricity_fee=?,
                        monthly_rent=?, lease_start=?, lease_end=?, payment_method=?, annual_discount_months=?,
                        has_water_discount=?, prepaid_electricity=?, notes=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (name, phone, deposit, base_rent, elec_fee, monthly_rent, start, end, method, 
                          discount, water, prepaid, notes, tenant_id))
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"
                    cursor.execute("""
                        INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, electricity_fee,
                        monthly_rent, lease_start, lease_end, payment_method, annual_discount_months,
                        has_water_discount, prepaid_electricity, notes)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, elec_fee, monthly_rent, start, end, 
                          method, discount, water, prepaid, notes))
                    return True, f"✅ 房號 {room} 已新增"
        except Exception as e:
            logging.error(f"upsert_tenant error: {e}")
            return False, f"❌ 保存失敗: {str(e)}"

    def get_tenants(self) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                df = pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)
                return df if not df.empty else pd.DataFrame()
        except:
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
        except:
            pass
        return None

    def delete_tenant(self, tid: int) -> Tuple[bool, str]:
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
            return True, "✅ 已刪除"
        except Exception as e:
            return False, f"❌ 刪除失敗: {str(e)}"

    # ============================================================================
    # 電費管理方法
    # ============================================================================
    def get_period_info(self, period_id: int) -> Optional[Dict]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period WHERE id=?", (period_id,))
                row = cursor.fetchone()
                if row:
                    return {"id": row[0], "year": row[1], "month_start": row[2], "month_end": row[3]}
        except:
            pass
        return None

    def add_electricity_period(self, year: int, month_start: int, month_end: int, notes: str = "") -> Tuple[bool, str, int]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO electricity_period(period_year, period_month_start, period_month_end, notes) VALUES(?, ?, ?, ?)", (year, month_start, month_end, notes))
                period_id = cursor.lastrowid
                return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float, unit_price: float = 0) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee, unit_price) VALUES(?, ?, ?, ?, ?)", (period_id, floor_name, tdy_kwh, tdy_fee, unit_price))
                return True
        except Exception as e:
            logging.error(f"add_tdy_bill error: {e}")
            return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                conn.execute("INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) VALUES(?, ?, ?, ?, ?)", (period_id, room, start, end, kwh_usage))
                return True
        except Exception as e:
            logging.error(f"add_meter_reading error: {e}")
            return False

    def get_sharing_config(self, period_id: int, room_number: str) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_sharing FROM electricity_sharing_config WHERE period_id=? AND room_number=?", (period_id, room_number))
                row = cursor.fetchone()
                return row[0] if row else 1
        except:
            return 1

    def calculate_electricity_fee(self, period_id: int, unit_price: float) -> Tuple[bool, str, pd.DataFrame]:
        """【v7.0】用台電單位價格計算電費"""
        logging.info("="*60)
        logging.info(f"CALC: Starting with unit_price=${unit_price:.4f}/degree")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT room_number, meter_kwh_usage FROM electricity_meter WHERE period_id=?", (period_id,))
                meters = cursor.fetchall()
                
                if not meters:
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()
                
                results = []
                
                for room, kwh_usage in meters:
                    floor = ROOM_FLOOR_MAP.get(room)
                    # 【v7.0】用單位價格計算
                    calculated_fee = kwh_usage * unit_price
                    
                    cursor.execute("SELECT balance FROM electricity_prepaid WHERE room_number=? ORDER BY created_at DESC LIMIT 1", (room,))
                    prepaid_row = cursor.fetchone()
                    prepaid_balance = prepaid_row[0] if prepaid_row else 0
                    actual_payment = max(0, calculated_fee - prepaid_balance)
                    
                    cursor.execute("""INSERT OR REPLACE INTO electricity_calculation(
                        period_id, room_number, floor_name, private_kwh, allocated_kwh, total_kwh,
                        unit_price, calculated_fee, prepaid_balance, actual_payment)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                        (period_id, room, floor, kwh_usage, 0, kwh_usage, unit_price, calculated_fee, prepaid_balance, actual_payment))
                    
                    results.append({
                        '房號': room,
                        '樓層': floor,
                        '度數': f"{kwh_usage:.1f}",
                        '單價': f"${unit_price:.4f}/度",
                        '應繳': f"${calculated_fee:.0f}",
                        '預繳': f"${prepaid_balance:.0f}",
                        '實收': f"${actual_payment:.0f}"
                    })
                
                logging.info(f"CALC: Success - {len(results)} records")
                logging.info("="*60)
                return True, "✅ 電費計算完成", pd.DataFrame(results)

        except Exception as e:
            logging.error(f"CALC: Error: {e}")
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

    def add_expense(self, expense_date: str, category: str, amount: float, description: str, room_number: str = "") -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("INSERT INTO expenses(expense_date, category, amount, description, room_number) VALUES(?, ?, ?, ?, ?)", (expense_date, category, amount, description, room_number))
                return True
        except Exception as e:
            logging.error(f"add_expense error: {e}")
            return False

    def get_expenses(self, limit: int = 20) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))
        except:
            return pd.DataFrame()

# ============================================================================
# UI 工具函數
# ============================================================================
def display_card(title: str, value: str, color: str = "blue"):
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color, '#ccc')}; border-radius: 8px; padding: 15px; margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until_date(date_str: str) -> int:
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (target - date.today()).days
    except:
        return 999

# ============================================================================
# UI 頁面層
# ============================================================================
def page_dashboard(db: RentalDB):
    """儀表板頁面"""
    st.header("📊 儀表板")
    
    tenants = db.get_tenants()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        occupancy = len(tenants)
        rate = (occupancy / 12 * 100) if occupancy > 0 else 0
        display_card("入住率", f"{rate:.0f}%", "blue")
    
    with col2:
        total = tenants['monthly_rent'].sum() if not tenants.empty else 0
        display_card("月租金", f"${total:,.0f}", "green")
    
    with col3:
        elec = tenants['electricity_fee'].sum() if not tenants.empty else 0
        display_card("月電費", f"${elec:,.0f}", "orange")
    
    with col4:
        prepaid = tenants['prepaid_electricity'].sum() if not tenants.empty else 0
        display_card("預繳電費", f"${prepaid:,.0f}", "blue")
    
    st.divider()
    
    st.subheader("🏠 房間狀態")
    active_rooms = tenants['room_number'].tolist() if not tenants.empty else []
    cols = st.columns(6)
    for i, room in enumerate(ALL_ROOMS):
        with cols[i % 6]:
            if room in active_rooms:
                t = tenants[tenants['room_number'] == room].iloc[0]
                days = days_until_date(t['lease_end'])
                st.success(f"{room}\n{t['tenant_name']}")
                if days < 60:
                    st.caption(f"⚠️ {days}天")
            else:
                st.error(f"{room}\n空房")

def page_tenants(db: RentalDB):
    """房客管理頁面"""
    st.header("👥 房客管理")
    
    if "edit_id" not in st.session_state:
        st.session_state.edit_id = None
    
    if st.session_state.edit_id is not None and st.session_state.edit_id != -1:
        tenant = db.get_tenant_by_id(st.session_state.edit_id)
        if not tenant:
            st.error("租客不存在")
            if st.button("返回"):
                st.session_state.edit_id = None
                st.rerun()
            return
        
        st.subheader(f"編輯 {tenant['room_number']} - {tenant['tenant_name']}")
        
        with st.form("edit_form"):
            name = st.text_input("姓名", value=tenant['tenant_name'])
            phone = st.text_input("電話", value=tenant['phone'] or "")
            deposit = st.number_input("押金", value=tenant['deposit'])
            base_rent = st.number_input("基本房租", value=tenant['base_rent'])
            elec_fee = st.number_input("電費", value=tenant['electricity_fee'])
            
            start_date = datetime.strptime(tenant['lease_start'], "%Y-%m-%d").date()
            end_date = datetime.strptime(tenant['lease_end'], "%Y-%m-%d").date()
            
            start = st.date_input("租約開始", value=start_date)
            end = st.date_input("租約結束", value=end_date)
            
            method = st.selectbox("繳款方式", ["月繳", "半年繳", "年繳"], index=["月繳", "半年繳", "年繳"].index(tenant['payment_method']))
            discount = st.number_input("年折扣月數", value=tenant['annual_discount_months'], min_value=0, max_value=12)
            water = st.checkbox("水費折扣", value=bool(tenant['has_water_discount']))
            prepaid = st.number_input("預繳電費", value=tenant['prepaid_electricity'])
            notes = st.text_area("備註", value=tenant['notes'] or "")
            
            col1, col2 = st.columns(2)
            if col1.form_submit_button("✅ 更新", type="primary"):
                ok, msg = db.upsert_tenant(tenant['room_number'], name, phone, deposit, base_rent, elec_fee, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), method, discount, int(water), prepaid, notes, st.session_state.edit_id)
                if ok:
                    st.success(msg)
                    st.session_state.edit_id = None
                    st.rerun()
                else:
                    st.error(msg)
            
            if col2.form_submit_button("取消"):
                st.session_state.edit_id = None
                st.rerun()
    
    elif st.session_state.edit_id == -1:
        st.subheader("新增租客")
        tenants_df = db.get_tenants()
        existing = tenants_df['room_number'].tolist() if not tenants_df.empty else []
        available = [r for r in ALL_ROOMS if r not in existing]
        
        if not available:
            st.error("沒有可用房間")
            if st.button("返回"):
                st.session_state.edit_id = None
                st.rerun()
            return
        
        with st.form("add_form"):
            room = st.selectbox("房號", available)
            name = st.text_input("姓名")
            phone = st.text_input("電話")
            deposit = st.number_input("押金", value=10000)
            base_rent = st.number_input("房租", value=6000)
            elec_fee = st.number_input("電費", value=0)
            start = st.date_input("租約開始")
            end = st.date_input("租約結束", value=date.today() + timedelta(days=365))
            method = st.selectbox("繳款方式", ["月繳", "半年繳", "年繳"])
            discount = st.number_input("年折扣月數", value=0, min_value=0, max_value=12)
            water = st.checkbox("水費折扣", value=False)
            notes = st.text_area("備註")
            
            if st.form_submit_button("✅ 新增", type="primary"):
                if not name:
                    st.error("請輸入姓名")
                else:
                    ok, msg = db.upsert_tenant(room, name, phone, deposit, base_rent, elec_fee, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), method, discount, int(water), 0, notes)
                    if ok:
                        st.success(msg)
                        st.session_state.edit_id = None
                        st.rerun()
                    else:
                        st.error(msg)
    
    else:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader("租客列表")
        with col2:
            if st.button("➕ 新增租客", type="primary"):
                st.session_state.edit_id = -1
                st.rerun()
        
        tenants_df = db.get_tenants()
        if not tenants_df.empty:
            for idx, (_, row) in enumerate(tenants_df.iterrows()):
                with st.expander(f"{row['room_number']} - {row['tenant_name']} (${row['monthly_rent']:,.0f})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"電話: {row['phone']}")
                        st.write(f"房租: ${row['base_rent']:,.0f}")
                        st.write(f"電費: ${row['electricity_fee']:,.0f}")
                    with col2:
                        st.write(f"租約: {row['lease_start']} 至 {row['lease_end']}")
                        st.write(f"繳款: {row['payment_method']}")
                    
                    col1, col2 = st.columns(2)
                    if col1.button("✏️ 編輯", key=f"edit_{idx}"):
                        st.session_state.edit_id = row['id']
                        st.rerun()
                    if col2.button("🗑️ 刪除", key=f"del_{idx}"):
                        ok, msg = db.delete_tenant(row['id'])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        else:
            st.info("暫無租客")

def page_electricity(db: RentalDB):
    """電費管理頁面 - v7.0 台電單位價格版"""
    st.header("💡 電費管理 (v7.0 台電單位價格版)")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None

    tab1, tab2 = st.tabs(["① 新增期間", "② 輸入度數並計算"])

    with tab1:
        st.subheader("新增計費期間")
        with st.form("period_form"):
            col1, col2, col3 = st.columns(3)
            year = col1.number_input("年份", value=datetime.now().year, min_value=2020)
            month_start = col2.number_input("開始月份", value=1, min_value=1, max_value=12)
            month_end = col3.number_input("結束月份", value=2, min_value=1, max_value=12)
            
            if st.form_submit_button("✅ 新增期間", type="primary", use_container_width=True):
                ok, msg, pid = db.add_electricity_period(year, month_start, month_end)
                if ok:
                    st.session_state.current_period_id = pid
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        
        if st.session_state.current_period_id:
            period_info = db.get_period_info(st.session_state.current_period_id)
            if period_info:
                st.success(f"✅ 當前期間: {period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID: {period_info['id']})")

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先在「① 新增期間」分頁建立計費期間")
            st.stop()
            
        period_id = st.session_state.current_period_id
        period_info = db.get_period_info(period_id)
        
        if period_info:
            st.info(f"期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID: {period_id})")

        with st.form(key="electricity_data_form"):
            st.markdown("### 📊 第 1 步：輸入台電總電費單")
            st.warning("❗ 【重要提示】度數和金額都必須輸入！度數不能為 0")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**2F**")
                st.caption("金額 (元) + 度數 (kWh)")
                fee_2f = st.number_input("金額", min_value=0, key="fee_2f", help="台電單據上的金額")
                kwh_2f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_2f", help="台電單據上的度數")
            
            with col2:
                st.markdown("**3F**")
                st.caption("金額 (元) + 度數 (kWh)")
                fee_3f = st.number_input("金額", min_value=0, key="fee_3f")
                kwh_3f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_3f")
            
            with col3:
                st.markdown("**4F**")
                st.caption("金額 (元) + 度數 (kWh)")
                fee_4f = st.number_input("金額", min_value=0, key="fee_4f")
                kwh_4f = st.number_input("度數", min_value=0.0, format="%.1f", key="kwh_4f")
            
            st.divider()
            
            st.markdown("### 📟 第 2 步：輸入各房間電錶度數")
            st.info("📍 輸入『累計度數』（即電錶上顯示的數字），不是『使用度數』")
            
            for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                        ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                st.markdown(f"**{floor_label}**")
                for room in rooms:
                    c1, c2, c3 = st.columns([0.8, 2, 2])
                    with c1:
                        st.write(f"**{room}**")
                    with c2:
                        st.number_input("上期度數", min_value=0.0, format="%.1f", key=f"start_{room}", help="上個月月底時電錶的讀數")
                    with c3:
                        st.number_input("本期度數", min_value=0.0, format="%.1f", key=f"end_{room}", help="這個月月底時電錶的讀數")
                st.divider()

            submitted = st.form_submit_button("🚀 提交數據並檢查", type="primary", use_container_width=True)

        if submitted:
            logging.info("="*60)
            logging.info("v7.0: Form submitted - Deep Diagnostics with Unit Price")
            
            # 【v7.0 核心】超級深度診斷
            diag = DeepElectricityDiagnosticsV7()
            
            # 收集數據
            tdy_data = {
                "2F": (st.session_state.get("fee_2f", 0), st.session_state.get("kwh_2f", 0.0)),
                "3F": (st.session_state.get("fee_3f", 0), st.session_state.get("kwh_3f", 0.0)),
                "4F": (st.session_state.get("fee_4f", 0), st.session_state.get("kwh_4f", 0.0))
            }
            
            meter_data = {}
            for room in ALL_ROOMS:
                start = st.session_state.get(f"start_{room}", 0.0)
                end = st.session_state.get(f"end_{room}", 0.0)
                meter_data[room] = (start, end)
            
            # 執行診斷
            tdy_valid, tdy_total_kwh, tdy_total_fee = diag.check_tdy_bills(tdy_data)
            st.divider()
            
            meter_valid, meter_total = diag.check_meter_readings(meter_data)
            st.divider()
            
            diag.compare_totals()
            st.divider()
            
            can_proceed, diagnostic_msg = diag.diagnose()
            
            if not can_proceed:
                st.error(diagnostic_msg)
            else:
                st.success(diagnostic_msg)
                
                # 【v7.0】顯示台電單位價格
                if diag.unit_price > 0:
                    st.info(f"✅ 數據驗證通過")
                    st.success(f"📊 【台電單位價格】${diag.unit_price:.4f}/度")
                    st.info(f"這個價格會用來計算每個房間的應繳電費")
                
                # 寫入數據庫
                st.info("✅ 正在寫入數據庫...")
                
                tdy_written = []
                for floor, (fee, kwh) in tdy_data.items():
                    if fee > 0 and kwh > 0:
                        if db.add_tdy_bill(period_id, floor, kwh, fee, diag.unit_price):
                            tdy_written.append(floor)
                
                meter_written = []
                for room, (start, end) in meter_data.items():
                    if end > start:
                        if db.add_meter_reading(period_id, room, start, end):
                            meter_written.append(room)
                
                st.success(f"✅ 數據已寫入：{len(tdy_written)} 筆台電單據，{len(meter_written)} 筆房間度數")
                
                # 計算電費
                with st.spinner("⏳ 正在計算電費..."):
                    time.sleep(0.5)
                    ok, msg, df = db.calculate_electricity_fee(period_id, diag.unit_price)
                
                if ok:
                    st.balloons()
                    st.success(msg)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.error(msg)

def page_expenses(db: RentalDB):
    """支出管理頁面"""
    st.header("💸 支出管理")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("新增支出")
        with st.form("expense_form"):
            d = st.date_input("日期")
            cat = st.selectbox("類別", ["維修", "清潔", "水電瓦斯", "其他"])
            amt = st.number_input("金額", min_value=0)
            room = st.selectbox("房間", ["共用"] + ALL_ROOMS)
            desc = st.text_input("說明")
            
            if st.form_submit_button("➕ 新增", type="primary", use_container_width=True):
                room_val = "" if room == "共用" else room
                if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc, room_val):
                    st.success("已記錄")
                    st.rerun()
    
    with col2:
        st.subheader("最近支出")
        expenses = db.get_expenses(15)
        if not expenses.empty:
            st.dataframe(expenses[['expense_date', 'category', 'amount', 'description', 'room_number']], use_container_width=True, hide_index=True)
        else:
            st.info("暫無支出")

def page_settings(db: RentalDB):
    """設定頁面"""
    st.header("⚙️ 設定")
    
    st.subheader("系統信息")
    display_card("版本", "v7.0 完整版", "blue")
    display_card("數據庫", "rental_system_12rooms.db", "green")
    display_card("日誌", "logs/rental_system.log", "orange")
    
    st.divider()
    st.markdown("✅ **v7.0 新功能**")
    st.markdown("- 計算台電單位價格（當期1度/元）")
    st.markdown("- 用單位價格計算每個房間的應繳電費")
    st.markdown("- 完整保留所有頁面功能")
    st.markdown("- 深度診斷檢查")

# ============================================================================
# 主程式
# ============================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v7.0",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v7.0 - 完整版 + 台電單位價格")
        st.markdown("---")
        menu = st.radio("導航", ["📊 儀表板", "👥 房客管理", "💡 電費管理", "💸 支出管理", "⚙️ 設定"])
        st.markdown("---")
        st.markdown("✅ v7.0 完整版")
        st.markdown("📊 台電單位價格計算")
    
    db = RentalDB()
    
    if menu == "📊 儀表板":
        page_dashboard(db)
    elif menu == "👥 房客管理":
        page_tenants(db)
    elif menu == "💡 電費管理":
        page_electricity(db)
    elif menu == "💸 支出管理":
        page_expenses(db)
    else:
        page_settings(db)

if __name__ == "__main__":
    main()

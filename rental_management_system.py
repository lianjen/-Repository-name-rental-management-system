"""
幸福之家管理系統 Pro v6.1 - 診斷版
加入完整的數據驗證和診斷邏輯

【核心改進】:
1. 在提交表單前，先進行詳細的數據驗證
2. 告訴用戶具體缺少什麼數據，為什麼無法計算
3. 實時反饋每個輸入的狀態
4. 提交前清單檢查
5. 提交後詳細的診斷報告

【特點】:
- 不再出現籠統的「❌ 尚未輸入電錶度數」
- 清晰指出每個步驟的問題
- 用戶能快速定位問題所在
- 完全的診斷日誌
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
import time
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List, Any

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
# 診斷類 (v6.1 新增)
# ============================================================================
class ElectricityDiagnostics:
    """電費數據診斷類"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
    
    def check_tdy_bills(self, tdy_data: Dict[str, Tuple[float, float]]) -> int:
        """檢查台電單據"""
        valid_count = 0
        for floor, (fee, kwh) in tdy_data.items():
            if fee == 0 and kwh == 0:
                self.warnings.append(f"❌ {floor}: 未輸入任何數據")
            elif fee == 0:
                self.errors.append(f"❌ {floor}: 未輸入金額")
            elif kwh == 0:
                self.errors.append(f"❌ {floor}: 未輸入度數")
            elif kwh < 0 or fee < 0:
                self.errors.append(f"❌ {floor}: 數值不能為負數")
            else:
                self.info.append(f"✅ {floor}: {kwh:.1f}度, ${fee:,.0f}")
                valid_count += 1
        
        if valid_count == 0:
            self.errors.append("🚨 臺電單據: 需要至少輸入一個樓層的數據")
        else:
            self.info.append(f"臺電單據: 已輸入 {valid_count}/3 個樓層")
        
        return valid_count
    
    def check_meter_readings(self, meter_data: Dict[str, Tuple[float, float]]) -> int:
        """檢查房間度數"""
        valid_count = 0
        warnings_count = 0
        
        for room, (start, end) in meter_data.items():
            if start == 0 and end == 0:
                # 沒有輸入，跳過
                continue
            elif end == 0:
                self.warnings.append(f"⚠️ {room}: 未輸入本期度數")
                warnings_count += 1
            elif start == 0 and end > 0:
                self.info.append(f"✅ {room}: {end:.1f}度 (無上期數據)")
                valid_count += 1
            elif end > start:
                self.info.append(f"✅ {room}: {start:.1f} → {end:.1f} ({end-start:.1f}度)")
                valid_count += 1
            elif end < start:
                self.errors.append(f"❌ {room}: 本期({end:.1f}) 不能小於上期({start:.1f})")
            elif end == start:
                self.warnings.append(f"⚠️ {room}: 上期和本期相同，度數為 0")
        
        if valid_count == 0:
            self.errors.append("🚨 房間度數: 需要至少輸入一個房間的本期度數")
        else:
            self.info.append(f"房間度數: 已輸入 {valid_count}/{len(ALL_ROOMS)} 個房間")
        
        return valid_count
    
    def diagnose(self) -> Tuple[bool, str]:
        """進行完整診斷"""
        if self.errors:
            error_msg = "🔴 **檢測到以下問題，無法進行計算：**\n\n"
            for error in self.errors:
                error_msg += f"• {error}\n"
            error_msg += "\n**請修正上述問題後重試。**"
            return False, error_msg
        
        if self.warnings:
            warning_msg = "🟡 **警告信息（不影響計算）：**\n\n"
            for warning in self.warnings:
                warning_msg += f"• {warning}\n"
            return True, warning_msg
        
        return True, "✅ 數據驗證通過！"
    
    def get_summary(self) -> str:
        """獲取診斷摘要"""
        summary = "📋 **數據檢查摘要：**\n\n"
        
        if self.info:
            for info in self.info:
                summary += f"• {info}\n"
        
        if self.warnings:
            summary += "\n🟡 **警告：**\n"
            for warning in self.warnings:
                summary += f"• {warning}\n"
        
        if self.errors:
            summary += "\n❌ **錯誤：**\n"
            for error in self.errors:
                summary += f"• {error}\n"
        
        return summary

# ============================================================================
# 數據庫類 (與 v6.0 相同)
# ============================================================================
class RentalDB:
    """數據庫操作類"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        """獲取數據庫連接"""
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
        """初始化數據庫表"""
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
                    avg_price REAL NOT NULL,
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_period ON electricity_period(period_year, period_month_start)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_bill_period ON electricity_tdy_bill(period_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_meter_room ON electricity_meter(room_number)")
            
            logging.info("Database initialized")

    # ============================================================================
    # 租客管理方法 (簡化版，不影響核心)
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
                    logging.info(f"Created tenant {room}")
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
            logging.info(f"Deleted tenant ID {tid}")
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
                    return {"id": row[0], "year": row[1], "month_start": row[2], "month_end": row[3], "notes": row[4]}
        except Exception as e:
            logging.error(f"get_period_info error: {e}")
        return None

    def add_electricity_period(self, year: int, month_start: int, month_end: int, notes: str = "") -> Tuple[bool, str, int]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO electricity_period(period_year, period_month_start, period_month_end, notes)
                    VALUES(?, ?, ?, ?)
                """, (year, month_start, month_end, notes))
                period_id = cursor.lastrowid
                logging.info(f"Created period ID {period_id}")
                return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            logging.error(f"add_electricity_period error: {e}")
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee)
                    VALUES(?, ?, ?, ?)
                """, (period_id, floor_name, tdy_kwh, tdy_fee))
                logging.info(f"Added TDY bill for {floor_name}: {tdy_kwh}kwh, ${tdy_fee}")
                return True
        except Exception as e:
            logging.error(f"add_tdy_bill error: {e}")
            return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage)
                    VALUES(?, ?, ?, ?, ?)
                """, (period_id, room, start, end, kwh_usage))
                logging.info(f"Added meter for {room}: {start}->{end} ({kwh_usage}kwh)")
                return True
        except Exception as e:
            logging.error(f"add_meter_reading error: {e}")
            return False

    def get_sharing_config(self, period_id: int, room_number: str) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""SELECT is_sharing FROM electricity_sharing_config WHERE period_id=? AND room_number=?""", (period_id, room_number))
                row = cursor.fetchone()
                return row[0] if row else 1
        except:
            return 1

    def set_sharing_config(self, period_id: int, room_number: str, is_sharing: int) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_sharing_config(period_id, room_number, is_sharing) VALUES(?, ?, ?)""", (period_id, room_number, is_sharing))
            return True
        except Exception as e:
            logging.error(f"set_sharing_config error: {e}")
            return False

    def calculate_electricity_fee(self, period_id: int) -> Tuple[bool, str, pd.DataFrame]:
        """計算電費"""
        logging.info("="*60)
        logging.info(f"CALC: Starting calculation for period_id={period_id}")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""SELECT floor_name, tdy_total_kwh, tdy_total_fee FROM electricity_tdy_bill WHERE period_id=?""", (period_id,))
                tdy_bills = cursor.fetchall()
                logging.info(f"CALC: Found {len(tdy_bills)} TDY bills")
                
                if not tdy_bills:
                    return False, "❌ 尚未輸入台電單據", pd.DataFrame()

                cursor.execute("""SELECT room_number, meter_kwh_usage FROM electricity_meter WHERE period_id=?""", (period_id,))
                meters = cursor.fetchall()
                logging.info(f"CALC: Found {len(meters)} meter readings")
                
                if not meters:
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()

                results = []
                
                for floor_name, tdy_kwh, tdy_fee in tdy_bills:
                    floor_rooms = [(room, kwh) for room, kwh in meters if ROOM_FLOOR_MAP.get(room) == floor_name]
                    if not floor_rooms:
                        continue
                    
                    private_kwh_sum = sum(kwh for _, kwh in floor_rooms)
                    public_kwh = tdy_kwh - private_kwh_sum
                    sharing_count = len(floor_rooms)
                    kwh_per_room = public_kwh / sharing_count if sharing_count > 0 else 0
                    avg_price = tdy_fee / tdy_kwh if tdy_kwh > 0 else 0
                    
                    for room, private_kwh in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        allocated_kwh = kwh_per_room if is_sharing == 1 else 0
                        total_kwh = private_kwh + allocated_kwh
                        calculated_fee = total_kwh * avg_price
                        
                        cursor.execute("""SELECT balance FROM electricity_prepaid WHERE room_number=? ORDER BY created_at DESC LIMIT 1""", (room,))
                        prepaid_row = cursor.fetchone()
                        prepaid_balance = prepaid_row[0] if prepaid_row else 0
                        actual_payment = max(0, calculated_fee - prepaid_balance)
                        
                        cursor.execute("""INSERT OR REPLACE INTO electricity_calculation(period_id, room_number, floor_name, private_kwh, allocated_kwh, total_kwh, avg_price, calculated_fee, prepaid_balance, actual_payment) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (period_id, room, floor_name, private_kwh, allocated_kwh, total_kwh, avg_price, calculated_fee, prepaid_balance, actual_payment))
                        
                        results.append({
                            '房號': room, '樓層': floor_name, '私錶': f"{private_kwh:.0f}",
                            '分攤': f"{allocated_kwh:.0f}", '合計': f"{total_kwh:.0f}",
                            '電價': f"${avg_price:.2f}", '應繳': f"${calculated_fee:.0f}",
                            '預繳': f"${prepaid_balance:.0f}", '實收': f"${actual_payment:.0f}"
                        })

                logging.info(f"CALC: Success - {len(results)} records")
                logging.info("="*60)
                return True, "✅ 電費計算完成", pd.DataFrame(results)

        except Exception as e:
            logging.error(f"CALC: Error: {e}", exc_info=True)
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

    def add_expense(self, expense_date: str, category: str, amount: float, description: str, room_number: str = "") -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO expenses(expense_date, category, amount, description, room_number) VALUES(?, ?, ?, ?, ?)""", (expense_date, category, amount, description, room_number))
                logging.info(f"Added expense: {category} ${amount}")
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
    col1, col2 = st.columns([2, 1])
    
    with col1:
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
    """電費管理頁面 - v6.1 診斷版"""
    st.header("💡 電費管理 (v6.1 診斷版)")
    
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
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**2F**")
                fee_2f = st.number_input("金額 (元)", min_value=0, key="fee_2f")
                kwh_2f = st.number_input("度數 (kWh)", min_value=0.0, format="%.1f", key="kwh_2f")
            
            with col2:
                st.markdown("**3F**")
                fee_3f = st.number_input("金額 (元)", min_value=0, key="fee_3f")
                kwh_3f = st.number_input("度數 (kWh)", min_value=0.0, format="%.1f", key="kwh_3f")
            
            with col3:
                st.markdown("**4F**")
                fee_4f = st.number_input("金額 (元)", min_value=0, key="fee_4f")
                kwh_4f = st.number_input("度數 (kWh)", min_value=0.0, format="%.1f", key="kwh_4f")
            
            st.divider()
            
            st.markdown("### 📟 第 2 步：輸入各房間電錶度數")
            
            for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                        ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                st.markdown(f"**{floor_label}**")
                for room in rooms:
                    c1, c2, c3 = st.columns([0.8, 2, 2])
                    with c1:
                        st.write(f"**{room}**")
                    with c2:
                        st.number_input("上期度數", min_value=0.0, format="%.1f", key=f"start_{room}")
                    with c3:
                        st.number_input("本期度數", min_value=0.0, format="%.1f", key=f"end_{room}")
                st.divider()

            submitted = st.form_submit_button("🚀 提交數據並計算電費", type="primary", use_container_width=True)

        if submitted:
            logging.info("="*60)
            logging.info("UI: Form submitted - v6.1 Diagnostic")
            
            # 【v6.1 核心】執行診斷
            diagnostics = ElectricityDiagnostics()
            
            # 收集台電數據
            tdy_data = {
                "2F": (st.session_state.get("fee_2f", 0), st.session_state.get("kwh_2f", 0.0)),
                "3F": (st.session_state.get("fee_3f", 0), st.session_state.get("kwh_3f", 0.0)),
                "4F": (st.session_state.get("fee_4f", 0), st.session_state.get("kwh_4f", 0.0))
            }
            
            # 收集房間度數數據
            meter_data = {}
            for room in ALL_ROOMS:
                start = st.session_state.get(f"start_{room}", 0.0)
                end = st.session_state.get(f"end_{room}", 0.0)
                meter_data[room] = (start, end)
            
            # 執行診斷檢查
            tdy_valid = diagnostics.check_tdy_bills(tdy_data)
            meter_valid = diagnostics.check_meter_readings(meter_data)
            
            # 顯示診斷摘要
            st.markdown("### 📋 數據檢查摘要")
            with st.expander("展開詳細檢查結果", expanded=True):
                st.markdown(diagnostics.get_summary())
            
            # 執行診斷判斷
            can_proceed, diagnostic_msg = diagnostics.diagnose()
            
            if not can_proceed:
                st.error(diagnostic_msg)
                st.info("💡 請根據上述提示修正數據，然後重新提交。")
                logging.info(f"Diagnostics: Failed - {len(diagnostics.errors)} errors")
            else:
                if diagnostics.warnings:
                    st.warning(diagnostic_msg)
                else:
                    st.success(diagnostic_msg)
                
                # 資料驗證通過，寫入數據庫並計算
                st.info("✅ 數據驗證通過，正在寫入數據庫...")
                
                # 寫入台電數據
                tdy_written = []
                for floor, (fee, kwh) in tdy_data.items():
                    if fee > 0 and kwh > 0:
                        if db.add_tdy_bill(period_id, floor, kwh, fee):
                            tdy_written.append(floor)
                
                # 寫入房間度數
                meter_written = []
                for room, (start, end) in meter_data.items():
                    if end > start:
                        if db.add_meter_reading(period_id, room, start, end):
                            meter_written.append(room)
                
                st.success(f"✅ 數據已寫入：{len(tdy_written)} 筆台電單據，{len(meter_written)} 筆房間度數")
                
                # 執行計算
                with st.spinner("⏳ 正在計算電費..."):
                    time.sleep(0.5)
                    ok, msg, df = db.calculate_electricity_fee(period_id)
                
                if ok:
                    st.balloons()
                    st.success(msg)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    logging.info("CALC: Successfully completed")
                else:
                    st.error(msg)
                    st.error("💥 計算失敗！請檢查日誌文件。")
                    logging.error(f"CALC: Failed - {msg}")

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
    display_card("版本", "v6.1 診斷版", "blue")
    display_card("數據庫", "rental_system_12rooms.db", "green")
    display_card("日誌", "logs/rental_system.log", "orange")
    
    st.divider()
    st.markdown("✅ **v6.1 新功能**")
    st.markdown("- 提交前詳細診斷數據")
    st.markdown("- 清晰指出問題所在")
    st.markdown("- 不再出現籠統的錯誤提示")
    st.markdown("- 完整的檢查清單")

# ============================================================================
# 主程式
# ============================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v6.1",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v6.1 - 診斷版")
        st.markdown("---")
        menu = st.radio("導航", ["📊 儀表板", "👥 房客管理", "💡 電費管理", "💸 支出管理", "⚙️ 設定"])
        st.markdown("---")
        st.markdown("✅ v6.1 診斷版")
        st.markdown("提交前詳細檢查")
    
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

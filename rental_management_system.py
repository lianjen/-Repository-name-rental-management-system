"""
幸福之家管理系統 Pro v9.0 - 完整版（完全修正）
修復 bug：1A、1B 獨立繳費，不參與分攤
修復 db：electricity_calculation 表移除 floor_name
修復格式：度數到小數點後 2 位，分攤度數為整數

【v9.0 完全正確邏輯】

1F（1A、1B）：獨立繳費，不參與分攤 ❌
2F（2A、2B）：參與分攤
3F（3A、3B、3C、3D）：參與分攤
4F（4A、4B、4C、4D）：參與分攤
分攤房間數 = 10 間

第 1 步：計算當期電度單價 = 台電總金額 ÷ 台電總度數
第 2 步：計算公用電度數 = 台電總度數 - 所有房間私表度數
第 3 步：計算分攤度數 = 公用電度數 ÷ 10 間（四捨五入成整數）
第 4 步：計算應繳
   - 1A、1B：度數 × 單價
   - 其他房間：(度數 + 分攤度數) × 單價
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
TOTAL_ROOMS = len(ALL_ROOMS)  # 12間房間
SHARING_ROOMS = ["2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]  # 10間參與分攤
NON_SHARING_ROOMS = ["1A", "1B"]  # 2間獨立繳費
ROOM_FLOOR_MAP = {
    "1A": "1F", "1B": "1F",
    "2A": "2F", "2B": "2F",
    "3A": "3F", "3B": "3F", "3C": "3F", "3D": "3F",
    "4A": "4F", "4B": "4F", "4C": "4F", "4D": "4F"
}

# ============================================================================
# 電費計算類 (v9.0 - 完全修正)
# ============================================================================
class ElectricityCalculatorV9:
    """電費計算類 - v9.0 完全修正版"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.unit_price = 0  # 當期電度單價（元/度）
        self.tdy_total_kwh = 0  # 台電總度數
        self.tdy_total_fee = 0  # 台電總金額
        self.meter_total_kwh = 0  # 所有房間私表度數總和
        self.public_kwh = 0  # 公用電度數
        self.public_per_room = 0  # 每戶分攤公用度數（整數）
    
    def check_tdy_bills(self, tdy_data: Dict[str, Tuple[float, float]]) -> bool:
        """【第 1 步】檢查台電單據並計算當期電度單價"""
        st.markdown("### 📊 【第 1 步】台電單據檢查 - 計算當期電度單價")
        
        valid_count = 0
        total_kwh = 0
        total_fee = 0
        
        for floor, (fee, kwh) in tdy_data.items():
            if kwh == 0 or fee == 0:
                if fee == 0 and kwh == 0:
                    self.errors.append(f"🚨 【{floor}】完全沒有輸入")
                    st.error(f"❌ {floor}: 完全沒有輸入（金額: $0, 度數: 0度）")
                elif kwh == 0:
                    self.errors.append(f"🚨 【{floor}】度數為 0")
                    st.error(f"❌ {floor}: 度數為 0（金額: ${fee}）")
                elif fee == 0:
                    self.errors.append(f"🚨 【{floor}】金額為 0")
                    st.error(f"❌ {floor}: 金額為 0（度數: {kwh:.1f}）")
            else:
                # ✅ 有效
                unit_price = fee / kwh
                st.success(f"✅ {floor}: {kwh:.1f}度 × ${unit_price:.4f}/度 = ${fee:,.0f}")
                valid_count += 1
                total_kwh += kwh
                total_fee += fee
        
        if valid_count == 0:
            self.errors.append("🚨 沒有任何有效的台電單據")
            st.error("🚨 沒有任何有效的台電單據")
            return False
        
        # 計算當期電度單價
        self.unit_price = total_fee / total_kwh if total_kwh > 0 else 0
        self.tdy_total_kwh = total_kwh
        self.tdy_total_fee = total_fee
        
        st.success(f"✅ 台電單據驗證通過: {valid_count} 個樓層")
        st.info(f"   台電總度數: {total_kwh:.2f}度")
        st.info(f"   台電總金額: ${total_fee:,.0f}")
        st.success(f"📊 【當期電度單價】${self.unit_price:.4f}/度")
        
        return True
    
    def check_meter_readings(self, meter_data: Dict[str, Tuple[float, float]]) -> bool:
        """【第 2 步】檢查房間度數並計算私表總度數"""
        st.markdown("### 📟 【第 2 步】房間度數檢查 - 計算私表總度數")
        
        valid_count = 0
        total_kwh = 0
        
        for room, (start, end) in meter_data.items():
            if start == 0 and end == 0:
                continue
            elif end <= start and not (start == 0 and end == 0):
                if end < start:
                    st.error(f"❌ {room}: 本期({end:.2f}) < 上期({start:.2f}) - 不合理")
                elif end == start:
                    st.warning(f"⚠️ {room}: 本期 = 上期 = {start:.2f}度（度數為 0）")
            else:
                usage = round(end - start, 2)  # 四捨五入到小數點後 2 位
                st.success(f"✅ {room}: {start:.2f} → {end:.2f} （度數: {usage:.2f}）")
                valid_count += 1
                total_kwh += usage
        
        if valid_count == 0:
            self.errors.append("🚨 沒有任何有效的房間度數")
            st.error("🚨 沒有任何有效的房間度數")
            return False
        
        self.meter_total_kwh = round(total_kwh, 2)
        
        st.success(f"✅ 房間度數驗證通過: {valid_count} 間房間")
        st.info(f"   房間私表總度數: {self.meter_total_kwh:.2f}度")
        
        return True
    
    def calculate_public_electricity(self) -> bool:
        """【第 2-3 步】計算公用電度數和分攤度數"""
        st.markdown("### ⚖️ 【第 2-3 步】公用電計算")
        
        # 計算公用電度數
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)
        
        st.info(f"公用電度數 = 台電總度數 - 私表總度數")
        st.info(f"           = {self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.success(f"           = {self.public_kwh:.2f}度")
        
        # 檢查公用電是否合理
        if self.public_kwh < 0:
            self.errors.append(f"🚨 公用電度數為負數 - 房間度數超過台電度數")
            st.error(f"❌ 房間度數總和超過台電度數！")
            return False
        
        # 計算每戶分攤度數（四捨五入成整數）
        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        
        st.info(f"每戶分攤公用度數 = 公用電度數 ÷ {len(SHARING_ROOMS)}間")
        st.info(f"                = {self.public_kwh:.2f}度 ÷ {len(SHARING_ROOMS)}")
        st.success(f"                = {self.public_per_room}度/戶（四捨五入成整數）")
        
        return True
    
    def diagnose(self) -> Tuple[bool, str]:
        """最終診斷"""
        st.markdown("---")
        st.markdown("### 📋 診斷結果")
        
        if self.errors:
            error_msg = "🔴 **檢測到以下錯誤：**\n\n"
            for i, error in enumerate(self.errors, 1):
                error_msg += f"{i}. {error}\n"
            return False, error_msg
        
        if self.warnings:
            warning_msg = "🟡 **警告信息：**\n\n"
            for i, warning in enumerate(self.warnings, 1):
                warning_msg += f"{i}. {warning}\n"
            st.warning(warning_msg)
        
        return True, "✅ 所有檢查都通過了！"

# ============================================================================
# 數據庫類 (v9.0 修正)
# ============================================================================
class RentalDB:
    """數據庫操作類 - v9.0 修正版"""
    
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
                    tdy_total_kwh REAL DEFAULT 0,
                    tdy_total_fee REAL DEFAULT 0,
                    unit_price REAL DEFAULT 0,
                    meter_total_kwh REAL DEFAULT 0,
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
            
            # 【v9.0 修正】移除 floor_name，簡化表結構
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_calculation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_id INTEGER NOT NULL,
                    room_number TEXT NOT NULL,
                    private_kwh REAL NOT NULL,
                    public_allocated_kwh INTEGER NOT NULL,
                    total_kwh REAL NOT NULL,
                    unit_price REAL NOT NULL,
                    calculated_fee REAL NOT NULL,
                    payment_date TEXT,
                    status TEXT DEFAULT '未收',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id),
                    UNIQUE(period_id, room_number)
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
            
            logging.info("Database initialized - v9.0")

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
                if tenant_id:
                    conn.execute("""
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
                    conn.execute("""
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

    def get_period_info(self, period_id: int) -> Optional[Dict]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period WHERE id=?", (period_id,))
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    return dict(zip(cols, row))
        except:
            pass
        return None

    def add_electricity_period(self, year: int, month_start: int, month_end: int) -> Tuple[bool, str, int]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""INSERT INTO electricity_period(period_year, period_month_start, period_month_end) 
                    VALUES(?, ?, ?)""", (year, month_start, month_end))
                period_id = cursor.lastrowid
                return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee) 
                    VALUES(?, ?, ?, ?)""", (period_id, floor_name, tdy_kwh, tdy_fee))
                return True
        except:
            return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        try:
            kwh_usage = round(end - start, 2)
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) 
                    VALUES(?, ?, ?, ?, ?)""", (period_id, room, start, end, kwh_usage))
                return True
        except:
            return False

    def update_period_calculations(self, period_id: int, unit_price: float, meter_total: float, 
                                  public_kwh: float, public_per_room: int, tdy_total_kwh: float, tdy_total_fee: float):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE electricity_period SET unit_price=?, meter_total_kwh=?, public_kwh=?, 
                    public_per_room=?, tdy_total_kwh=?, tdy_total_fee=? WHERE id=?""",
                    (unit_price, meter_total, public_kwh, public_per_room, tdy_total_kwh, tdy_total_fee, period_id))
            return True
        except Exception as e:
            logging.error(f"update_period_calculations error: {e}")
            return False

    def calculate_electricity_fee(self, period_id: int, calc: ElectricityCalculatorV9, meter_data: Dict[str, Tuple[float, float]]) -> Tuple[bool, str, pd.DataFrame]:
        """【第 4 步】計算每間房間應繳電費 - v9.0 修正版"""
        
        try:
            results = []
            
            with self._get_connection() as conn:
                for room, (start, end) in meter_data.items():
                    if end <= start:
                        continue
                    
                    private_kwh = round(end - start, 2)
                    
                    # 【v9.0 修正】判斷是否參與分攤
                    if room in NON_SHARING_ROOMS:  # 1A、1B 獨立繳費
                        public_kwh = 0
                        total_kwh = private_kwh
                    else:  # 其他房間參與分攤
                        public_kwh = calc.public_per_room
                        total_kwh = round(private_kwh + public_kwh, 2)
                    
                    calculated_fee = round(total_kwh * calc.unit_price, 0)
                    
                    results.append({
                        '房號': room,
                        '私表度數': f"{private_kwh:.2f}",
                        '分攤度數': f"{public_kwh}" if public_kwh > 0 else "無",
                        '合計度數': f"{total_kwh:.2f}",
                        '電度單價': f"${calc.unit_price:.4f}/度",
                        '應繳電費': f"${int(calculated_fee)}"
                    })
                    
                    # 寫入數據庫
                    conn.execute("""INSERT OR REPLACE INTO electricity_calculation(
                        period_id, room_number, private_kwh, public_allocated_kwh, total_kwh,
                        unit_price, calculated_fee)
                        VALUES(?, ?, ?, ?, ?, ?, ?)""",
                        (period_id, room, private_kwh, public_kwh, total_kwh, calc.unit_price, calculated_fee))
            
            # 更新 period 計算結果
            self.update_period_calculations(period_id, calc.unit_price, calc.meter_total_kwh, 
                                           calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee)
            
            return True, "✅ 電費計算完成", pd.DataFrame(results)
        
        except Exception as e:
            logging.error(f"CALC Error: {e}", exc_info=True)
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

    def add_expense(self, expense_date: str, category: str, amount: float, description: str) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO expenses(expense_date, category, amount, description) 
                    VALUES(?, ?, ?, ?)""", (expense_date, category, amount, description))
                return True
        except:
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
        rate = (occupancy / TOTAL_ROOMS * 100) if occupancy > 0 else 0
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
            
            start_date = datetime.strptime(tenant['lease_start'], "%Y-%m-%d").date()
            end_date = datetime.strptime(tenant['lease_end'], "%Y-%m-%d").date()
            
            start = st.date_input("租約開始", value=start_date)
            end = st.date_input("租約結束", value=end_date)
            
            col1, col2 = st.columns(2)
            if col1.form_submit_button("✅ 更新", type="primary"):
                ok, msg = db.upsert_tenant(tenant['room_number'], name, phone, deposit, base_rent, 0, 
                                          start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), 
                                          "月繳", 0, 0, 0, "", st.session_state.edit_id)
                if ok:
                    st.success(msg)
                    st.session_state.edit_id = None
                    st.rerun()
            
            if col2.form_submit_button("取消"):
                st.session_state.edit_id = None
                st.rerun()
    
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
                with st.expander(f"{row['room_number']} - {row['tenant_name']}"):
                    st.write(f"電話: {row['phone']}")
                    st.write(f"房租: ${row['base_rent']:,.0f}")
                    st.write(f"租約: {row['lease_start']} 至 {row['lease_end']}")
                    
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
            st.info("暫無租客")

def page_electricity(db: RentalDB):
    """電費管理頁面 - v9.0 修正版"""
    st.header("💡 電費管理 (v9.0 修正版)")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None

    tab1, tab2 = st.tabs(["① 新增期間", "② 輸入數據並計算"])

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
                st.success(f"✅ 當前期間: {period_info['period_year']}年 {period_info['period_month_start']}-{period_info['period_month_end']}月")

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先在「① 新增期間」分頁建立計費期間")
            st.stop()
            
        period_id = st.session_state.current_period_id
        period_info = db.get_period_info(period_id)
        
        if period_info:
            st.info(f"期間：{period_info['period_year']}年 {period_info['period_month_start']}-{period_info['period_month_end']}月")

        with st.form(key="electricity_data_form"):
            st.markdown("### 📊 台電單據")
            st.warning("❗ 度數和金額都必須輸入！")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**2F**")
                fee_2f = st.number_input("金額(元)", min_value=0, key="fee_2f")
                kwh_2f = st.number_input("度數(度)", min_value=0.0, format="%.1f", key="kwh_2f")
            
            with col2:
                st.markdown("**3F**")
                fee_3f = st.number_input("金額(元)", min_value=0, key="fee_3f")
                kwh_3f = st.number_input("度數(度)", min_value=0.0, format="%.1f", key="kwh_3f")
            
            with col3:
                st.markdown("**4F**")
                fee_4f = st.number_input("金額(元)", min_value=0, key="fee_4f")
                kwh_4f = st.number_input("度數(度)", min_value=0.0, format="%.1f", key="kwh_4f")
            
            st.divider()
            
            st.markdown("### 📟 房間電錶度數")
            st.info("輸入『累計度數』（電錶上的數字）")
            
            for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                        ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                st.markdown(f"**{floor_label}**")
                for room in rooms:
                    c1, c2, c3 = st.columns([0.8, 2, 2])
                    with c1:
                        st.write(f"**{room}**")
                    with c2:
                        st.number_input("上期度數", min_value=0.0, format="%.2f", key=f"start_{room}")
                    with c3:
                        st.number_input("本期度數", min_value=0.0, format="%.2f", key=f"end_{room}")
                st.divider()

            submitted = st.form_submit_button("🚀 計算電費", type="primary", use_container_width=True)

        if submitted:
            # 初始化計算器
            calc = ElectricityCalculatorV9()
            
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
            
            # 執行計算步驟
            st.markdown("---")
            st.markdown("## 📝 計算流程")
            
            # 第 1 步
            if not calc.check_tdy_bills(tdy_data):
                st.error("❌ 台電單據驗證失敗")
                st.stop()
            
            st.divider()
            
            # 第 2 步
            if not calc.check_meter_readings(meter_data):
                st.error("❌ 房間度數驗證失敗")
                st.stop()
            
            st.divider()
            
            # 寫入度數數據
            for room, (start, end) in meter_data.items():
                if end > start:
                    db.add_meter_reading(period_id, room, start, end)
            
            for floor, (fee, kwh) in tdy_data.items():
                if fee > 0 and kwh > 0:
                    db.add_tdy_bill(period_id, floor, kwh, fee)
            
            # 第 2-3 步
            if not calc.calculate_public_electricity():
                st.error("❌ 公用電計算失敗")
                st.stop()
            
            st.divider()
            
            # 最終診斷
            can_proceed, msg = calc.diagnose()
            if not can_proceed:
                st.error(msg)
                st.stop()
            
            st.success(msg)
            
            # 第 4 步：計算應繳
            st.markdown("### 💰 【第 4 步】計算每間房間應繳電費")
            
            with st.spinner("正在計算..."):
                time.sleep(0.5)
                ok, msg, df = db.calculate_electricity_fee(period_id, calc, meter_data)
            
            if ok:
                st.balloons()
                st.success(msg)
                
                # 顯示計算總結
                st.markdown("---")
                st.markdown("## 📊 計算總結")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    display_card("電度單價", f"${calc.unit_price:.4f}/度", "blue")
                with col2:
                    display_card("公用電度", f"{calc.public_kwh:.2f}度", "orange")
                with col3:
                    display_card("每戶分攤", f"{calc.public_per_room}度", "green")
                with col4:
                    display_card("分攤房間", f"{len(SHARING_ROOMS)}間", "blue")
                
                st.divider()
                st.markdown("## 💡 電費明細")
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
            desc = st.text_input("說明")
            
            if st.form_submit_button("➕ 新增", type="primary", use_container_width=True):
                if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc):
                    st.success("已記錄")
                    st.rerun()
    
    with col2:
        st.subheader("最近支出")
        expenses = db.get_expenses(15)
        if not expenses.empty:
            st.dataframe(expenses, use_container_width=True, hide_index=True)
        else:
            st.info("暫無支出")

def page_settings(db: RentalDB):
    """設定頁面"""
    st.header("⚙️ 設定")
    
    st.subheader("系統信息")
    display_card("版本", "v9.0 修正版", "blue")
    display_card("房間數", f"{TOTAL_ROOMS}間", "green")
    display_card("分攤房間", f"{len(SHARING_ROOMS)}間", "orange")
    
    st.divider()
    
    st.markdown("✅ **v9.0 修正邏輯**")
    st.markdown("• 1F（1A、1B）：獨立繳費，不參與分攤")
    st.markdown("• 2-4F（10間）：參與分攤公用電")
    st.markdown("• 度數：保留小數點後 2 位")
    st.markdown("• 分攤度數：四捨五入成整數")
    st.markdown("• 應繳電費：四捨五入成整數（元）")

# ============================================================================
# 主程式
# ============================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v9.0",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v9.0 - 修正版")
        st.markdown("---")
        menu = st.radio("導航", ["📊 儀表板", "👥 房客管理", "💡 電費管理", "💸 支出管理", "⚙️ 設定"])
        st.markdown("---")
        st.markdown("✅ v9.0 修正版")
    
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

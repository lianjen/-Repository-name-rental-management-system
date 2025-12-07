"""
幸福之家管理系統 Pro v10.0 - 完整版（最終版本）
1A、1B 只在說明欄記錄，不參與任何計算

【v10.0 完全正確邏輯】

第 1 步：計算當期電度單價
    = 台電總金額 ÷ 台電總度數
    = $7964 ÷ 2965度 = $2.6870/度

第 2 步：計算公用電度數
    = 台電總度數 - (只有 2A~4D 的私表度數)
    = 2965度 - 1500度 = 1465度
    ❌ 1A、1B 完全不算！只在說明裡記錄

第 3 步：計算分攤房間的公用電分攤度數
    = 公用電度數 ÷ 10間（2A~4D）
    = 1465度 ÷ 10 = 146.5度 → 四捨五入 147度

第 4 步：計算應繳電費
    只有 2A~4D（10間房間）出現在計費清單
    1A、1B 只在說明欄記錄「本期記錄：1A房50.00度、1B房40.00度」
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
TOTAL_ROOMS = len(ALL_ROOMS)
SHARING_ROOMS = ["2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]  # 10間
NON_SHARING_ROOMS = ["1A", "1B"]  # 2間，只記錄，不計算
ROOM_FLOOR_MAP = {
    "1A": "1F", "1B": "1F",
    "2A": "2F", "2B": "2F",
    "3A": "3F", "3B": "3F", "3C": "3F", "3D": "3F",
    "4A": "4F", "4B": "4F", "4C": "4F", "4D": "4F"
}

# ============================================================================
# 電費計算類 (v10.0 - 最終版本)
# ============================================================================
class ElectricityCalculatorV10:
    """電費計算類 - v10.0 最終版本"""
    
    def __init__(self):
        self.errors = []
        self.unit_price = 0
        self.tdy_total_kwh = 0
        self.tdy_total_fee = 0
        self.meter_total_kwh = 0
        self.public_kwh = 0
        self.public_per_room = 0
        self.non_sharing_records = {}  # 記錄 1A、1B 的度數
    
    def check_tdy_bills(self, tdy_data: Dict[str, Tuple[float, float]]) -> bool:
        """【第 1 步】檢查台電單據"""
        st.markdown("### 📊 【第 1 步】台電單據檢查")
        
        valid_count = 0
        total_kwh = 0
        total_fee = 0
        
        for floor, (fee, kwh) in tdy_data.items():
            if kwh == 0 or fee == 0:
                if fee == 0 and kwh == 0:
                    self.errors.append(f"🚨 {floor}: 完全沒有輸入")
                    st.error(f"❌ {floor}: 完全沒有輸入")
                elif kwh == 0:
                    self.errors.append(f"🚨 {floor}: 度數為 0")
                    st.error(f"❌ {floor}: 度數為 0")
                elif fee == 0:
                    self.errors.append(f"🚨 {floor}: 金額為 0")
                    st.error(f"❌ {floor}: 金額為 0")
            else:
                unit_price = fee / kwh
                st.success(f"✅ {floor}: {kwh:.1f}度 × ${unit_price:.4f}/度 = ${fee:,.0f}")
                valid_count += 1
                total_kwh += kwh
                total_fee += fee
        
        if valid_count == 0:
            self.errors.append("🚨 沒有任何有效的台電單據")
            st.error("🚨 沒有任何有效的台電單據")
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
        """【第 2 步】檢查房間度數（只檢查 2A~4D，1A~1B 只記錄）"""
        st.markdown("### 📟 【第 2 步】房間度數檢查")
        
        valid_count = 0
        total_kwh = 0
        
        # 先記錄 1A、1B
        for room in NON_SHARING_ROOMS:
            start, end = meter_data[room]
            if end > start:
                usage = round(end - start, 2)
                self.non_sharing_records[room] = usage
                st.info(f"📝 {room}: {start:.2f} → {end:.2f} (記錄: {usage:.2f}度，不計算)")
            elif end > 0:
                st.warning(f"⚠️ {room}: {start:.2f} → {end:.2f}")
        
        st.divider()
        
        # 檢查 2A~4D（參與分攤的房間）
        for room in SHARING_ROOMS:
            start, end = meter_data[room]
            
            if start == 0 and end == 0:
                continue
            elif end <= start and not (start == 0 and end == 0):
                if end < start:
                    self.errors.append(f"🚨 {room}: 本期 < 上期")
                    st.error(f"❌ {room}: 本期({end:.2f}) < 上期({start:.2f})")
            else:
                usage = round(end - start, 2)
                st.success(f"✅ {room}: {start:.2f} → {end:.2f} (度數: {usage:.2f})")
                valid_count += 1
                total_kwh += usage
        
        if valid_count == 0:
            self.errors.append("🚨 沒有分攤房間的度數")
            st.error("🚨 沒有分攤房間的度數")
            return False
        
        self.meter_total_kwh = round(total_kwh, 2)
        
        st.success(f"✅ 房間度數驗證通過: {valid_count} 間房間")
        st.info(f"   分攤房間私表總度數: {self.meter_total_kwh:.2f}度")
        
        return True
    
    def calculate_public_electricity(self) -> bool:
        """【第 2-3 步】計算公用電度數和分攤度數"""
        st.markdown("### ⚖️ 【第 2-3 步】公用電計算")
        
        # 計算公用電（只用 2A~4D 的度數）
        self.public_kwh = round(self.tdy_total_kwh - self.meter_total_kwh, 2)
        
        st.info(f"公用電度數 = 台電總度數 - 分攤房間私表總度數")
        st.info(f"           = {self.tdy_total_kwh:.2f} - {self.meter_total_kwh:.2f}")
        st.success(f"           = {self.public_kwh:.2f}度")
        
        if self.public_kwh < 0:
            self.errors.append(f"🚨 公用電度數為負數")
            st.error(f"❌ 房間度數總和超過台電度數")
            return False
        
        # 計算每戶分攤度數（只除以 10 間）
        self.public_per_room = round(self.public_kwh / len(SHARING_ROOMS))
        
        st.info(f"每戶分攤度數 = 公用電度數 ÷ {len(SHARING_ROOMS)}間")
        st.info(f"            = {self.public_kwh:.2f} ÷ {len(SHARING_ROOMS)}")
        st.success(f"            = {self.public_per_room}度/戶（四捨五入）")
        
        return True
    
    def diagnose(self) -> Tuple[bool, str]:
        """最終診斷"""
        st.markdown("---")
        
        if self.errors:
            error_msg = "🔴 **檢測到以下錯誤：**\n\n"
            for error in self.errors:
                error_msg += f"• {error}\n"
            return False, error_msg
        
        return True, "✅ 所有檢查都通過了！"

# ============================================================================
# 數據庫類 (v10.0)
# ============================================================================
class RentalDB:
    """數據庫操作類 - v10.0"""
    
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
                    lease_start TEXT NOT NULL,
                    lease_end TEXT NOT NULL,
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
                    public_kwh REAL DEFAULT 0,
                    public_per_room INTEGER DEFAULT 0,
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
                    private_kwh REAL NOT NULL,
                    public_allocated_kwh INTEGER NOT NULL,
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
            
            logging.info("Database initialized - v10.0")

    def room_exists(self, room: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,))
                return cursor.fetchone() is not None
        except:
            return False

    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float, base_rent: float, 
                     start: str, end: str, tenant_id: Optional[int] = None) -> Tuple[bool, str]:
        try:
            with self._get_connection() as conn:
                if tenant_id:
                    conn.execute("""
                        UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?,
                        lease_start=?, lease_end=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """, (name, phone, deposit, base_rent, start, end, tenant_id))
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"
                    conn.execute("""
                        INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, lease_start, lease_end)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, start, end))
                    return True, f"✅ 房號 {room} 已新增"
        except Exception as e:
            logging.error(f"upsert_tenant error: {e}")
            return False, f"❌ 失敗: {str(e)}"

    def get_tenants(self) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)
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
        except:
            return False, "❌ 刪除失敗"

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
                return True, f"✅ 計費期間已新增", cursor.lastrowid
        except:
            return False, "❌ 新增失敗", 0

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

    def update_period_calculations(self, period_id: int, unit_price: float, public_kwh: float, public_per_room: int, tdy_total_kwh: float, tdy_total_fee: float):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=? WHERE id=?""",
                    (unit_price, public_kwh, public_per_room, tdy_total_kwh, tdy_total_fee, period_id))
            return True
        except:
            return False

    def calculate_electricity_fee(self, period_id: int, calc: ElectricityCalculatorV10, meter_data: Dict) -> Tuple[bool, str, pd.DataFrame]:
        """【第 4 步】計算應繳電費 - 只有 2A~4D"""
        
        try:
            results = []
            
            with self._get_connection() as conn:
                for room in SHARING_ROOMS:  # 只計算 2A~4D
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
                    
                    conn.execute("""INSERT OR REPLACE INTO electricity_calculation(
                        period_id, room_number, private_kwh, public_allocated_kwh, total_kwh,
                        unit_price, calculated_fee)
                        VALUES(?, ?, ?, ?, ?, ?, ?)""",
                        (period_id, room, private_kwh, public_kwh, total_kwh, calc.unit_price, calculated_fee))
            
            # 建立說明欄
            non_sharing_note = "本期記錄："
            for room, kwh in calc.non_sharing_records.items():
                non_sharing_note += f"{room}房{kwh:.2f}度、"
            non_sharing_note = non_sharing_note.rstrip("、")
            
            self.update_period_calculations(period_id, calc.unit_price, calc.public_kwh, calc.public_per_room, calc.tdy_total_kwh, calc.tdy_total_fee)
            
            # 加入說明
            results_df = pd.DataFrame(results)
            if len(results_df) > 0:
                results_df.loc[len(results_df)-1, '應繳電費'] = f"{results_df.loc[len(results_df)-1, '應繳電費']}\n\n{non_sharing_note}"
            
            return True, "✅ 電費計算完成", results_df
        
        except Exception as e:
            logging.error(f"CALC Error: {e}")
            return False, f"❌ 失敗: {str(e)}", pd.DataFrame()

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
# UI 工具
# ============================================================================
def display_card(title: str, value: str, color: str = "blue"):
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color)}; border-radius: 8px; padding: 15px; margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================================
# 頁面層
# ============================================================================
def page_dashboard(db: RentalDB):
    st.header("📊 儀表板")
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
    st.subheader("🏠 房間狀態")
    active_rooms = tenants['room_number'].tolist() if not tenants.empty else []
    cols = st.columns(6)
    for i, room in enumerate(ALL_ROOMS):
        with cols[i % 6]:
            if room in active_rooms:
                st.success(f"{room}")
            else:
                st.error(f"{room}\n空房")

def page_tenants(db: RentalDB):
    st.header("👥 房客管理")
    
    if "edit_id" not in st.session_state:
        st.session_state.edit_id = None
    
    if st.session_state.edit_id == -1:
        st.subheader("新增租客")
        tenants_df = db.get_tenants()
        existing = tenants_df['room_number'].tolist() if not tenants_df.empty else []
        available = [r for r in ALL_ROOMS if r not in existing]
        
        if available:
            with st.form("add_form"):
                room = st.selectbox("房號", available)
                name = st.text_input("姓名")
                phone = st.text_input("電話")
                deposit = st.number_input("押金", value=10000)
                base_rent = st.number_input("房租", value=6000)
                start = st.date_input("租約開始")
                end = st.date_input("租約結束", value=date.today() + timedelta(days=365))
                
                if st.form_submit_button("✅ 新增", type="primary"):
                    ok, msg = db.upsert_tenant(room, name, phone, deposit, base_rent, 
                                              start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                    if ok:
                        st.success(msg)
                        st.session_state.edit_id = None
                        st.rerun()
    else:
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("➕ 新增", type="primary"):
                st.session_state.edit_id = -1
                st.rerun()
        
        tenants_df = db.get_tenants()
        if not tenants_df.empty:
            for idx, (_, row) in enumerate(tenants_df.iterrows()):
                with st.expander(f"{row['room_number']} - {row['tenant_name']}"):
                    st.write(f"電話: {row['phone']}")
                    st.write(f"房租: ${row['base_rent']}")
        else:
            st.info("暫無租客")

def page_electricity(db: RentalDB):
    st.header("💡 電費管理 (v10.0)")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None

    tab1, tab2 = st.tabs(["① 新增期間", "② 計算電費"])

    with tab1:
        with st.form("period_form"):
            col1, col2, col3 = st.columns(3)
            year = col1.number_input("年份", value=datetime.now().year)
            month_start = col2.number_input("開始月", value=1, min_value=1, max_value=12)
            month_end = col3.number_input("結束月", value=2, min_value=1, max_value=12)
            
            if st.form_submit_button("✅ 新增期間", type="primary", use_container_width=True):
                ok, msg, pid = db.add_electricity_period(year, month_start, month_end)
                if ok:
                    st.session_state.current_period_id = pid
                    st.success(msg)
                    st.rerun()

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先新增計費期間")
            st.stop()

        with st.form("electricity_form"):
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
            
            for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                        ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                st.markdown(f"**{floor_label}**")
                for room in rooms:
                    c1, c2, c3 = st.columns([0.8, 2, 2])
                    with c1:
                        st.write(f"**{room}**")
                    with c2:
                        st.number_input("上期", min_value=0.0, format="%.2f", key=f"start_{room}")
                    with c3:
                        st.number_input("本期", min_value=0.0, format="%.2f", key=f"end_{room}")

            if st.form_submit_button("🚀 計算", type="primary", use_container_width=True):
                calc = ElectricityCalculatorV10()
                
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
                
                st.markdown("---")
                
                if not calc.check_tdy_bills(tdy_data):
                    st.error("❌ 台電單據驗證失敗")
                    st.stop()
                
                st.divider()
                
                if not calc.check_meter_readings(meter_data):
                    st.error("❌ 度數驗證失敗")
                    st.stop()
                
                st.divider()
                
                for room, (start, end) in meter_data.items():
                    if end > start:
                        db.add_meter_reading(st.session_state.current_period_id, room, start, end)
                
                for floor, (fee, kwh) in tdy_data.items():
                    if fee > 0 and kwh > 0:
                        db.add_tdy_bill(st.session_state.current_period_id, floor, kwh, fee)
                
                if not calc.calculate_public_electricity():
                    st.error("❌ 公用電計算失敗")
                    st.stop()
                
                st.divider()
                
                can_proceed, msg = calc.diagnose()
                if can_proceed:
                    st.success(msg)
                    
                    st.markdown("### 💰 【第 4 步】計費清單")
                    ok, msg, df = db.calculate_electricity_fee(st.session_state.current_period_id, calc, meter_data)
                    
                    if ok:
                        st.balloons()
                        st.success(msg)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                    else:
                        st.error(msg)
                else:
                    st.error(msg)

def page_expenses(db: RentalDB):
    st.header("💸 支出")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        with st.form("expense_form"):
            d = st.date_input("日期")
            cat = st.selectbox("類別", ["維修", "清潔", "其他"])
            amt = st.number_input("金額", min_value=0)
            desc = st.text_input("說明")
            
            if st.form_submit_button("➕ 新增", type="primary", use_container_width=True):
                if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc):
                    st.success("已記錄")
    
    with col2:
        expenses = db.get_expenses(10)
        if not expenses.empty:
            st.dataframe(expenses, use_container_width=True, hide_index=True)

def page_settings(db: RentalDB):
    st.header("⚙️ 設定")
    st.markdown("✅ **v10.0 - 最終版本**")
    st.markdown("• 1A、1B 只在說明欄記錄，不參與計算")
    st.markdown("• 2A~4D（10間）參與分攤")
    st.markdown("• 完整的電費計算系統")

# ============================================================================
# 主程式
# ============================================================================
def main():
    st.set_page_config(page_title="幸福之家 v10.0", page_icon="🏠", layout="wide")
    
    with st.sidebar:
        st.title("🏠 幸福之家 v10.0")
        menu = st.radio("", ["📊 儀表板", "👥 房客", "💡 電費", "💸 支出", "⚙️ 設定"])
    
    db = RentalDB()
    
    if menu == "📊 儀表板":
        page_dashboard(db)
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

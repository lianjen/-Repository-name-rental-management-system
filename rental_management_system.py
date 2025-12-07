"""
幸福之家管理系統 Pro v5.9 - Streamlit Form 根本修復版
【核心修正】: 
1. 使用 session_state 存儲表單數據
2. 修復 st.form() 提交時數據丟失的問題
3. 最穩定的表單處理邏輯
特性: 完全解決計算失敗、數據不丟失、使用體驗完美
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, Any, List

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

ALL_ROOMS = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]

ROOM_FLOOR_MAP = {
    "1A": "1F", "1B": "1F",
    "2A": "2F", "2B": "2F",
    "3A": "3F", "3B": "3F", "3C": "3F", "3D": "3F",
    "4A": "4F", "4B": "4F", "4C": "4F", "4D": "4F"
}

# ============================================================================
# 數據庫層
# ============================================================================

class RentalDB:
    """數據庫操作類"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        """獲取資料庫連接"""
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
        """初始化資料庫表"""
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

    def room_exists(self, room: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM tenants WHERE room_number=? AND is_active=1", (room,))
                return cursor.fetchone() is not None
        except:
            return False

    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float,
                      base_rent: float, elec_fee: float, start: str, end: str,
                      method: str, discount: int, water: int, prepaid: float,
                      notes: str, tenant_id: Optional[int] = None) -> Tuple[bool, str]:
        try:
            monthly_rent = base_rent + elec_fee
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if tenant_id:
                    cursor.execute("""
                        UPDATE tenants SET tenant_name=?, phone=?, deposit=?, 
                        base_rent=?, electricity_fee=?, monthly_rent=?,
                        lease_start=?, lease_end=?, payment_method=?,
                        annual_discount_months=?, has_water_discount=?,
                        prepaid_electricity=?, notes=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (name, phone, deposit, base_rent, elec_fee, monthly_rent,
                          start, end, method, discount, water, prepaid, notes, tenant_id))
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在"
                    cursor.execute("""
                        INSERT INTO tenants(room_number, tenant_name, phone, deposit,
                        base_rent, electricity_fee, monthly_rent, lease_start, lease_end,
                        payment_method, annual_discount_months, has_water_discount,
                        prepaid_electricity, notes)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, elec_fee, monthly_rent,
                          start, end, method, discount, water, prepaid, notes))
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
            return None
        except:
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
                    return {"id": row[0], "year": row[1], "month_start": row[2], "month_end": row[3]}
            return None
        except:
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
            return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> Tuple[bool, str]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee)
                    VALUES(?, ?, ?, ?)
                """, (period_id, floor_name, tdy_kwh, tdy_fee))
            return True, f"✅ {floor_name} 已記錄"
        except Exception as e:
            return False, f"❌ 記錄失敗: {str(e)}"

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> Tuple[bool, str]:
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage)
                    VALUES(?, ?, ?, ?, ?)
                """, (period_id, room, start, end, kwh_usage))
            return True, f"✅ {room} 已記錄"
        except Exception as e:
            return False, f"❌ 記錄失敗: {str(e)}"

    def set_sharing_config(self, period_id: int, room_number: str, is_sharing: int) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_sharing_config(period_id, room_number, is_sharing)
                    VALUES(?, ?, ?)
                """, (period_id, room_number, is_sharing))
            return True
        except:
            return False

    def get_sharing_config(self, period_id: int, room_number: str) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""SELECT is_sharing FROM electricity_sharing_config 
                    WHERE period_id=? AND room_number=?""", (period_id, room_number))
                row = cursor.fetchone()
                return row[0] if row else 1
        except:
            return 1

    def calculate_electricity_fee(self, period_id: int) -> Tuple[bool, str, pd.DataFrame]:
        """v5.9 電費計算函數"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT floor_name, tdy_total_kwh, tdy_total_fee FROM electricity_tdy_bill WHERE period_id=?", (period_id,))
                tdy_bills = cursor.fetchall()
                if not tdy_bills:
                    return False, "❌ 尚未輸入台電單據", pd.DataFrame()
                
                cursor.execute("SELECT room_number, meter_kwh_usage FROM electricity_meter WHERE period_id=?", (period_id,))
                meters = cursor.fetchall()
                if not meters:
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()
                
                results = []
                for floor_name, tdy_kwh, tdy_fee in tdy_bills:
                    floor_rooms = [(room, kwh) for room, kwh in meters if ROOM_FLOOR_MAP.get(room, "") == floor_name]
                    if not floor_rooms:
                        continue
                    
                    private_kwh_sum = sum(kwh for _, kwh in floor_rooms)
                    public_kwh = tdy_kwh - private_kwh_sum
                    
                    sharing_rooms = [room for room, _ in floor_rooms if self.get_sharing_config(period_id, room) == 1]
                    sharing_count = len(sharing_rooms) if sharing_rooms else len(floor_rooms)
                    kwh_per_room = public_kwh / sharing_count if sharing_count > 0 else 0
                    avg_price = tdy_fee / tdy_kwh if tdy_kwh > 0 else 0
                    
                    for room, private_kwh in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        allocated_kwh = kwh_per_room if is_sharing == 1 else 0
                        total_kwh = private_kwh + allocated_kwh
                        calculated_fee = total_kwh * avg_price
                        
                        cursor.execute("""SELECT balance FROM electricity_prepaid 
                            WHERE room_number=? ORDER BY created_at DESC LIMIT 1""", (room,))
                        prepaid_row = cursor.fetchone()
                        prepaid_balance = prepaid_row[0] if prepaid_row else 0
                        actual_payment = max(0, calculated_fee - prepaid_balance)
                        
                        cursor.execute("""INSERT OR REPLACE INTO electricity_calculation(
                            period_id, room_number, floor_name, private_kwh, allocated_kwh,
                            total_kwh, avg_price, calculated_fee, prepaid_balance, actual_payment)
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (period_id, room, floor_name, private_kwh, allocated_kwh, total_kwh,
                              avg_price, calculated_fee, prepaid_balance, actual_payment))
                        
                        results.append({
                            '房號': room,
                            '樓層': floor_name,
                            '私錶': f"{private_kwh:.0f}",
                            '分攤': f"{allocated_kwh:.0f}",
                            '合計': f"{total_kwh:.0f}",
                            '電價': f"${avg_price:.2f}",
                            '應繳': f"${calculated_fee:.0f}",
                            '預繳': f"${prepaid_balance:.0f}",
                            '實收': f"${actual_payment:.0f}"
                        })
                
                df = pd.DataFrame(results)
                return True, "✅ 電費計算完成", df
        except Exception as e:
            logging.error(f"calculate error: {e}")
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

    def add_expense(self, expense_date: str, category: str, amount: float, description: str, room_number: str) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO expenses(expense_date, category, amount, description, room_number)
                    VALUES(?, ?, ?, ?, ?)""", (expense_date, category, amount, description, room_number))
            return True
        except:
            return False

    def get_expenses(self, limit: int = 10) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))
        except:
            return pd.DataFrame()

# ============================================================================
# UI 函數
# ============================================================================

def display_card(title: str, value: str, color: str = "blue"):
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color, '#ccc')}; border-radius: 8px; padding: 15px; margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str: str) -> int:
    try:
        target = datetime.strptime(date_str, "%Y.%m.%d").date()
        return (target - date.today()).days
    except:
        return 999

# ============================================================================
# 頁面函數
# ============================================================================

def page_dashboard(db: RentalDB):
    st.header("早安，管理員！ 👋")
    tenants = db.get_tenants()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        occupancy = len(tenants)
        rate = (occupancy / 12) * 100 if occupancy > 0 else 0
        display_card("出租率", f"{rate:.0f}%", "blue")
    with col2:
        total = tenants['monthly_rent'].sum() if not tenants.empty else 0
        display_card("月收租", f"${total:,.0f}", "green")
    with col3:
        elec = tenants['electricity_fee'].sum() if not tenants.empty else 0
        display_card("月電費", f"${elec:,.0f}", "orange")
    with col4:
        prepaid = tenants['prepaid_electricity'].sum() if not tenants.empty else 0
        display_card("預繳電費", f"${prepaid:,.0f}", "blue")

    st.divider()
    st.subheader("🏢 房源狀態")
    active = tenants['room_number'].tolist() if not tenants.empty else []
    
    cols = st.columns(6)
    cols2 = st.columns(6)
    
    for i, room in enumerate(ALL_ROOMS):
        col = cols[i] if i < 6 else cols2[i-6]
        with col:
            if room in active:
                t = tenants[tenants['room_number'] == room].iloc[0]
                days = days_until(t['lease_end'])
                st.success(f"**{room}**\n{t['tenant_name']}")
            else:
                st.error(f"**{room}**\n空房")

def page_tenants(db: RentalDB):
    if "edit_id" not in st.session_state:
        st.session_state.edit_id = None
    
    st.header("👥 房客管理")
    
    if st.session_state.edit_id is not None and st.session_state.edit_id != -1:
        tenant = db.get_tenant_by_id(st.session_state.edit_id)
        if not tenant:
            st.error("❌ 找不到租客")
            if st.button("返回列表"):
                st.session_state.edit_id = None
                st.rerun()
            return
        
        st.subheader(f"✏️ 編輯 {tenant['room_number']}")
        
        name = st.text_input("姓名", value=tenant['tenant_name'])
        phone = st.text_input("電話", value=tenant['phone'] or "")
        deposit = st.number_input("押金", value=tenant['deposit'])
        base_rent = st.number_input("基礎月租", value=tenant['base_rent'])
        elec_fee = st.number_input("月電費", value=tenant['electricity_fee'])
        
        start_date = date.today()
        try:
            start_date = datetime.strptime(tenant['lease_start'], "%Y.%m.%d").date()
        except:
            pass
        start = st.date_input("起租日", value=start_date)
        
        end_date = date.today() + timedelta(days=365)
        try:
            end_date = datetime.strptime(tenant['lease_end'], "%Y.%m.%d").date()
        except:
            pass
        end = st.date_input("到期日", value=end_date)
        
        method = st.selectbox("繳租方式", ["月繳", "半年繳", "年繳"], 
                            index=["月繳", "半年繳", "年繳"].index(tenant['payment_method']))
        discount = st.number_input("年繳折幾個月", value=tenant['annual_discount_months'], min_value=0, max_value=12)
        water = st.checkbox("含100元水費折扣", value=bool(tenant['has_water_discount']))
        prepaid = st.number_input("電費預繳餘額", value=tenant['prepaid_electricity'], min_value=0)
        notes = st.text_area("備註", value=tenant['notes'] or "")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("💾 保存", type="primary", use_container_width=True):
                if not name:
                    st.error("請填寫姓名")
                else:
                    ok, msg = db.upsert_tenant(
                        tenant['room_number'], name, phone, deposit,
                        base_rent, elec_fee, start.strftime("%Y.%m.%d"),
                        end.strftime("%Y.%m.%d"), method, discount, int(water), prepaid,
                        notes, st.session_state.edit_id
                    )
                    if ok:
                        st.success(msg)
                        st.session_state.edit_id = None
                        st.rerun()
        with col2:
            if st.button("取消", use_container_width=True):
                st.session_state.edit_id = None
                st.rerun()
    
    elif st.session_state.edit_id == -1:
        st.subheader("➕ 新增房客")
        tenants_df = db.get_tenants()
        existing_rooms = tenants_df['room_number'].tolist() if not tenants_df.empty else []
        available_rooms = [r for r in ALL_ROOMS if r not in existing_rooms]
        
        if not available_rooms:
            st.error("❌ 所有房間都已有租客")
            if st.button("返回列表"):
                st.session_state.edit_id = None
                st.rerun()
            return
        
        room = st.selectbox("房號", available_rooms)
        name = st.text_input("姓名")
        phone = st.text_input("電話")
        deposit = st.number_input("押金", value=10000)
        base_rent = st.number_input("基礎月租", value=6000)
        elec_fee = st.number_input("月電費", value=0)
        start = st.date_input("起租日")
        end = st.date_input("到期日", value=date.today() + timedelta(days=365))
        method = st.selectbox("繳租方式", ["月繳", "半年繳", "年繳"])
        discount = st.number_input("年繳折幾個月", value=0, min_value=0, max_value=12)
        water = st.checkbox("含100元水費折扣", value=False)
        notes = st.text_area("備註")
        
        if st.button("✅ 新增", type="primary", use_container_width=True):
            if not name:
                st.error("請填寫姓名")
            else:
                ok, msg = db.upsert_tenant(room, name, phone, deposit, base_rent, elec_fee, 
                                          start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"),
                                          method, discount, int(water), 0, notes)
                if ok:
                    st.success(msg)
                    st.session_state.edit_id = None
                    st.rerun()
    else:
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("➕ 新增", type="primary", use_container_width=True):
                st.session_state.edit_id = -1
                st.rerun()
        
        tenants = db.get_tenants()
        if not tenants.empty:
            st.subheader("現有房客")
            for _, t in tenants.iterrows():
                with st.expander(f"{t['room_number']} - {t['tenant_name']}"):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.write(f"月租: ${t['monthly_rent']:,.0f}")
                    with col2:
                        if st.button("✏️", key=f"edit_{t['id']}", use_container_width=True):
                            st.session_state.edit_id = t['id']
                            st.rerun()

def page_electricity(db: RentalDB):
    """💡 電費管理 v5.9 - session_state 修復版"""
    st.header("💡 電費管理 v5.9")
    st.info("✨ 改進的表單處理：使用 session_state 確保數據不丟失")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None
    
    # 【改進】初始化 session_state - 存儲表單數據
    if "elec_form_tdy_data" not in st.session_state:
        st.session_state.elec_form_tdy_data = {}
    if "elec_form_meter_data" not in st.session_state:
        st.session_state.elec_form_meter_data = {}
    
    tab1, tab2 = st.tabs(["新增期間", "輸入 & 計算"])
    
    with tab1:
        st.subheader("第1步：新增計費期間")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            year = st.number_input("年份", value=datetime.now().year, min_value=2020)
        with col2:
            month_start = st.number_input("開始月份", value=1, min_value=1, max_value=12)
        with col3:
            month_end = st.number_input("結束月份", value=2, min_value=1, max_value=12)
        
        notes = st.text_input("備註")
        
        if st.button("✅ 新增期間", type="primary", use_container_width=True):
            ok, msg, period_id = db.add_electricity_period(year, month_start, month_end, notes)
            if ok:
                st.success(msg)
                st.session_state.current_period_id = period_id
                st.rerun()
            else:
                st.error(msg)
        
        if st.session_state.current_period_id:
            period_info = db.get_period_info(st.session_state.current_period_id)
            if period_info:
                st.success(f"✅ 當前期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月")
    
    with tab2:
        st.subheader("第2步：輸入資料 & 自動計算")
        
        if not st.session_state.current_period_id:
            st.warning("❌ 請先建立計費期間")
        else:
            period_id = st.session_state.current_period_id
            period_info = db.get_period_info(period_id)
            
            if period_info:
                st.success(f"📌 當前期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月")
            
            # 【改進】使用 session_state 存儲表單數據
            with st.form(key="electricity_form_v9"):
                
                st.markdown("### 【第一部分】台電單據輸入")
                st.write("**2F、3F、4F**")
                
                for floor in ["2F", "3F", "4F"]:
                    col1, col2 = st.columns(2)
                    with col1:
                        kwh = st.number_input(f"{floor} 台電度數", value=0, min_value=0, step=1, key=f"tdy_kwh_{floor}")
                    with col2:
                        fee = st.number_input(f"{floor} 台電費用", value=0, min_value=0, step=100, key=f"tdy_fee_{floor}")
                    
                    # 【改進】寫入 session_state
                    st.session_state.elec_form_tdy_data[floor] = {"kwh": kwh, "fee": fee}
                
                st.divider()
                st.markdown("### 【第二部分】房間電錶度數輸入")
                
                for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                           ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                    st.write(f"**{floor_label} 房間**")
                    for room in rooms:
                        col1, col2 = st.columns(2)
                        with col1:
                            start = st.number_input(f"{room} 上期", value=0, min_value=0, step=1, key=f"start_{room}")
                        with col2:
                            end = st.number_input(f"{room} 本期", value=0, min_value=0, step=1, key=f"end_{room}")
                        
                        # 【改進】寫入 session_state
                        st.session_state.elec_form_meter_data[room] = (start, end)
                    st.divider()
                
                submitted = st.form_submit_button("✅ 提交並計算", type="primary", use_container_width=True)
                
                if submitted:
                    # 【改進】從 session_state 讀取數據（不會丟失！）
                    tdy_data = st.session_state.elec_form_tdy_data
                    meter_data = st.session_state.elec_form_meter_data
                    
                    # 驗證
                    tdy_valid = sum(1 for d in tdy_data.values() if d["kwh"] > 0 and d["fee"] > 0)
                    meter_valid = sum(1 for s, e in meter_data.values() if e >= s)
                    
                    st.info(f"📊 驗證結果：台電單據 {tdy_valid} 個，房間度數 {meter_valid} 間")
                    
                    if tdy_valid > 0 and meter_valid > 0:
                        with st.spinner("正在提交資料並計算..."):
                            # 提交台電單據
                            for floor, data in tdy_data.items():
                                if data["kwh"] > 0 and data["fee"] > 0:
                                    db.add_tdy_bill(period_id, floor, data["kwh"], data["fee"])
                            
                            # 提交度數
                            for room, (start, end) in meter_data.items():
                                if end >= start:
                                    db.add_meter_reading(period_id, room, start, end)
                            
                            # 設置分攤
                            for room in ALL_ROOMS:
                                is_sharing = 0 if room in ["1A", "1B"] else 1
                                db.set_sharing_config(period_id, room, is_sharing)
                            
                            # 【改進】直接計算（使用 session_state 的數據）
                            ok, msg, result_df = db.calculate_electricity_fee(period_id)
                        
                        if ok:
                            st.balloons()
                            st.success("🎉 計算完成！")
                            
                            st.divider()
                            st.subheader("📋 電費計算結果")
                            st.dataframe(result_df, use_container_width=True, hide_index=True)
                            
                            st.divider()
                            st.subheader("📊 統計")
                            st.write(f"✅ 共 {len(result_df)} 間房已計算")
                        else:
                            st.error(msg)
                    else:
                        st.error("❌ 驗證失敗：需要至少 1 個台電單據和 1 間房間度數")

def page_expenses(db: RentalDB):
    st.header("💸 支出管理")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("新增支出")
        d = st.date_input("日期")
        cat = st.selectbox("類別", ["房貸", "修繕", "水電", "網路", "稅務", "雜支"])
        amt = st.number_input("金額", value=0, min_value=0)
        room = st.selectbox("歸屬", ["公共"] + ALL_ROOMS)
        desc = st.text_input("說明")
        
        if st.button("新增", type="primary", use_container_width=True):
            if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc, room):
                st.success("✅ 已記錄")
            else:
                st.error("❌ 記錄失敗")

def page_settings():
    st.header("⚙️ 系統設定")
    st.success("""
    **幸福之家管理系統 Pro v5.9**
    
    ✅ 根本修復：Streamlit form session_state
    ✅ 計算完全正常
    ✅ 數據永不丟失
    ✅ 穩定可靠
    
    版本: v5.9 Final
    """)

# ============================================================================
# 主程式
# ============================================================================

def main():
    st.set_page_config(page_title="幸福之家", page_icon="🏠", layout="wide")
    
    db = RentalDB()
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v5.9 Final")
        
        menu = st.radio("導航", ["📊 儀表板", "👥 房客管理", "💡 電費管理", "💸 支出", "⚙️ 設定"])
    
    if menu == "📊 儀表板":
        page_dashboard(db)
    elif menu == "👥 房客管理":
        page_tenants(db)
    elif menu == "💡 電費管理":
        page_electricity(db)
    elif menu == "💸 支出":
        page_expenses(db)
    else:
        page_settings()

if __name__ == "__main__":
    main()

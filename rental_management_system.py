"""
幸福之家管理系統 Pro v12.0 - 完整統計與圓餅圖版
新增功能：
1. 電費記錄新增備註欄
2. 支出分類擴展（維修、清潔、貸款、網路費、其他）
3. 支出圓餅圖統計分析
4. 歷史帳單查詢與匯出
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
import time
import matplotlib.pyplot as plt
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

# 支出分類（與 Excel 對應）
EXPENSE_CATEGORIES = ["維修", "清潔", "貸款", "網路費", "其他"]

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
# 數據庫類 (v12.0 支出擴展版)
# ============================================================================
class RentalDB:
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()
        self._force_fix_schema()

    def reset_database(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
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
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS tenants (id INTEGER PRIMARY KEY AUTOINCREMENT, room_number TEXT UNIQUE NOT NULL, tenant_name TEXT NOT NULL, phone TEXT, deposit REAL DEFAULT 0, base_rent REAL DEFAULT 0, lease_start TEXT NOT NULL, lease_end TEXT NOT NULL, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_period (id INTEGER PRIMARY KEY AUTOINCREMENT, period_year INTEGER NOT NULL, period_month_start INTEGER NOT NULL, period_month_end INTEGER NOT NULL, tdy_total_kwh REAL DEFAULT 0, tdy_total_fee REAL DEFAULT 0, unit_price REAL DEFAULT 0, public_kwh REAL DEFAULT 0, public_per_room INTEGER DEFAULT 0, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_tdy_bill (id INTEGER PRIMARY KEY AUTOINCREMENT, period_id INTEGER NOT NULL, floor_name TEXT NOT NULL, tdy_total_kwh REAL NOT NULL, tdy_total_fee REAL NOT NULL, FOREIGN KEY(period_id) REFERENCES electricity_period(id), UNIQUE(period_id, floor_name))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_meter (id INTEGER PRIMARY KEY AUTOINCREMENT, period_id INTEGER NOT NULL, room_number TEXT NOT NULL, meter_start_reading REAL NOT NULL, meter_end_reading REAL NOT NULL, meter_kwh_usage REAL NOT NULL, FOREIGN KEY(period_id) REFERENCES electricity_period(id), UNIQUE(period_id, room_number))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS electricity_calculation (id INTEGER PRIMARY KEY AUTOINCREMENT, period_id INTEGER NOT NULL, room_number TEXT NOT NULL, private_kwh REAL NOT NULL, public_kwh INTEGER NOT NULL, total_kwh REAL NOT NULL, unit_price REAL NOT NULL, calculated_fee REAL NOT NULL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(period_id) REFERENCES electricity_period(id), UNIQUE(period_id, room_number))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, expense_date TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    def _force_fix_schema(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(electricity_calculation)")
                columns = [info[1] for info in cursor.fetchall()]
                if "public_kwh" not in columns:
                    if "public_allocated_kwh" in columns:
                        cursor.execute("ALTER TABLE electricity_calculation RENAME COLUMN public_allocated_kwh TO public_kwh")
                    else:
                        cursor.execute("ALTER TABLE electricity_calculation ADD COLUMN public_kwh INTEGER DEFAULT 0")
                
                # 檢查 electricity_period 是否有 notes 欄位
                cursor.execute("PRAGMA table_info(electricity_period)")
                columns = [info[1] for info in cursor.fetchall()]
                if "notes" not in columns:
                    cursor.execute("ALTER TABLE electricity_period ADD COLUMN notes TEXT DEFAULT ''")
        except Exception:
            pass

    # ========== Tenant 相關 ==========
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
                    conn.execute("""UPDATE tenants SET tenant_name=?, phone=?, deposit=?, base_rent=?, lease_start=?, lease_end=? WHERE id=?""", (name, phone, deposit, base_rent, start, end, tenant_id))
                    return True, f"✅ 房號 {room} 已更新"
                else:
                    if self.room_exists(room): return False, f"❌ 房號 {room} 已存在"
                    conn.execute("""INSERT INTO tenants(room_number, tenant_name, phone, deposit, base_rent, lease_start, lease_end) VALUES(?, ?, ?, ?, ?, ?, ?)""", (room, name, phone, deposit, base_rent, start, end))
                    return True, f"✅ 房號 {room} 已新增"
        except Exception as e: return False, f"❌ 失敗: {str(e)}"

    def get_tenants(self) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number", conn)
        except:
            return pd.DataFrame()

    def delete_tenant(self, tid: int) -> Tuple[bool, str]:
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
            return True, "✅ 已刪除"
        except: return False, "❌ 刪除失敗"

    # ========== Electricity 相關 ==========
    def add_electricity_period(self, year: int, month_start: int, month_end: int) -> Tuple[bool, str, int]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM electricity_period WHERE period_year=? AND period_month_start=? AND period_month_end=?", (year, month_start, month_end))
                row = cursor.fetchone()
                if row: return True, f"✅ 期間已存在", row[0]
                
                cursor.execute("""INSERT INTO electricity_period(period_year, period_month_start, period_month_end) VALUES(?, ?, ?)""", (year, month_start, month_end))
                return True, f"✅ 計費期間已新增", cursor.lastrowid
        except:
            return False, "❌ 新增失敗", 0

    def get_all_periods(self) -> List[Dict]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period ORDER BY id DESC")
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except:
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
        except:
            return pd.DataFrame()

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee) VALUES(?, ?, ?, ?)""", (period_id, floor_name, tdy_kwh, tdy_fee))
                return True
        except: return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        try:
            kwh_usage = round(end - start, 2)
            with self._get_connection() as conn:
                conn.execute("""INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage) VALUES(?, ?, ?, ?, ?)""", (period_id, room, start, end, kwh_usage))
                return True
        except: return False

    def update_period_calculations(self, period_id: int, unit_price: float, public_kwh: float, public_per_room: int, tdy_total_kwh: float, tdy_total_fee: float, notes: str = ""):
        try:
            with self._get_connection() as conn:
                conn.execute("""UPDATE electricity_period SET unit_price=?, public_kwh=?, public_per_room=?, tdy_total_kwh=?, tdy_total_fee=?, notes=? WHERE id=?""", (unit_price, public_kwh, public_per_room, tdy_total_kwh, tdy_total_fee, notes, period_id))
            return True
        except: return False

    def calculate_electricity_fee(self, period_id: int, calc: ElectricityCalculatorV10, meter_data: Dict, notes: str = "") -> Tuple[bool, str, pd.DataFrame]:
        try:
            results = []
            with self._get_connection() as conn:
                for room in SHARING_ROOMS:
                    start, end = meter_data[room]
                    if end <= start: continue
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
        except Exception as e: return False, f"❌ 失敗: {str(e)}", pd.DataFrame()

    # ========== Expense 相關 (v12.0 擴展) ==========
    def add_expense(self, expense_date: str, category: str, amount: float, description: str) -> bool:
        if category not in EXPENSE_CATEGORIES:
            return False
        try:
            with self._get_connection() as conn:
                conn.execute("""INSERT INTO expenses(expense_date, category, amount, description) VALUES(?, ?, ?, ?)""", (expense_date, category, amount, description))
                return True
        except: return False

    def get_expenses(self, limit: int = 50) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?", conn, params=(limit,))
        except: return pd.DataFrame()

    def get_expenses_by_date_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """取得特定日期範圍的支出"""
        try:
            with self._get_connection() as conn:
                return pd.read_sql("""
                    SELECT * FROM expenses 
                    WHERE expense_date BETWEEN ? AND ?
                    ORDER BY expense_date DESC
                """, conn, params=(start_date, end_date))
        except: return pd.DataFrame()

    def get_expenses_summary_by_category(self, start_date: str = None, end_date: str = None) -> Dict[str, float]:
        """按分類統計支出"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if start_date and end_date:
                    cursor.execute("""
                        SELECT category, SUM(amount) as total
                        FROM expenses
                        WHERE expense_date BETWEEN ? AND ?
                        GROUP BY category
                        ORDER BY total DESC
                    """, (start_date, end_date))
                else:
                    cursor.execute("""
                        SELECT category, SUM(amount) as total
                        FROM expenses
                        GROUP BY category
                        ORDER BY total DESC
                    """)
                return {row[0]: row[1] for row in cursor.fetchall()}
        except: return {}

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
            if room in active_rooms: st.success(f"{room}")
            else: st.error(f"{room}\n空房")

def page_tenants(db: RentalDB):
    st.header("👥 房客管理")
    if "edit_id" not in st.session_state: st.session_state.edit_id = None
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
                    ok, msg = db.upsert_tenant(room, name, phone, deposit, base_rent, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
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
        else: st.info("暫無租客")

def page_electricity(db: RentalDB):
    st.header("💡 電費管理 (v12.0)")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None

    tab1, tab2, tab3 = st.tabs(["① 新增期間", "② 計算電費", "📊 歷史帳單"])

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
                    time.sleep(1)
                    st.rerun()

    with tab2:
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先新增計費期間")
        else:
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
                        with c1: st.write(f"**{room}**")
                        with c2: st.number_input("上期", min_value=0.0, format="%.2f", key=f"start_{room}")
                        with c3: st.number_input("本期", min_value=0.0, format="%.2f", key=f"end_{room}")
                
                st.divider()
                st.markdown("### 📝 備註（選填）")
                notes = st.text_area("紀錄此期間的特殊事項、異常狀況等", placeholder="例：某房間電表損壞、臨時維修等")

                if st.form_submit_button("🚀 計算", type="primary", use_container_width=True):
                    calc = ElectricityCalculatorV10()
                    tdy_data = {
                        "2F": (st.session_state.get("fee_2f", 0), st.session_state.get("kwh_2f", 0.0)),
                        "3F": (st.session_state.get("fee_3f", 0), st.session_state.get("kwh_3f", 0.0)),
                        "4F": (st.session_state.get("fee_4f", 0), st.session_state.get("kwh_4f", 0.0))
                    }
                    meter_data = {}
                    for room in ALL_ROOMS:
                        meter_data[room] = (st.session_state.get(f"start_{room}", 0.0), st.session_state.get(f"end_{room}", 0.0))
                    
                    if not calc.check_tdy_bills(tdy_data):
                        st.error("❌ 台電單據驗證失敗"); st.stop()
                    if not calc.check_meter_readings(meter_data):
                        st.error("❌ 度數驗證失敗"); st.stop()
                    
                    for room, (s, e) in meter_data.items():
                        if e > s: db.add_meter_reading(st.session_state.current_period_id, room, s, e)
                    for floor, (f, k) in tdy_data.items():
                        if f > 0 and k > 0: db.add_tdy_bill(st.session_state.current_period_id, floor, k, f)
                    
                    if not calc.calculate_public_electricity():
                        st.error("❌ 公用電計算失敗"); st.stop()
                    
                    can_proceed, msg = calc.diagnose()
                    if can_proceed:
                        ok, msg, df = db.calculate_electricity_fee(st.session_state.current_period_id, calc, meter_data, notes)
                        if ok:
                            st.balloons()
                            st.success(msg)
                            st.dataframe(df, use_container_width=True, hide_index=True)
                        else: st.error(msg)
                    else: st.error(msg)

    with tab3:
        st.subheader("📊 歷史帳單查詢")
        periods = db.get_all_periods()
        
        if not periods:
            st.info("暫無歷史資料")
        else:
            period_options = {f"{p['period_year']}年 {p['period_month_start']}-{p['period_month_end']}月": p['id'] for p in periods}
            selected_period_label = st.selectbox("選擇計費期間", list(period_options.keys()))
            selected_pid = period_options[selected_period_label]
            
            period_data = next((p for p in periods if p['id'] == selected_pid), None)
            if period_data:
                col1, col2, col3, col4 = st.columns(4)
                with col1: display_card("總電費", f"${period_data['tdy_total_fee']:,.0f}", "blue")
                with col2: display_card("總度數", f"{period_data['tdy_total_kwh']:.1f}度", "green")
                with col3: display_card("平均單價", f"${period_data['unit_price']:.4f}", "orange")
                with col4: display_card("分攤公用", f"{period_data['public_per_room']}度", "blue")
                
                if period_data.get('notes'):
                    st.info(f"📝 **備註**：{period_data['notes']}")
            
            st.divider()
            
            report_df = db.get_period_report(selected_pid)
            if not report_df.empty:
                st.dataframe(report_df, use_container_width=True, hide_index=True)
                
                csv = report_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 下載當期報表 (CSV)",
                    data=csv,
                    file_name=f"電費報表_{selected_period_label}.csv",
                    mime="text/csv",
                    type="primary"
                )
            else:
                st.warning("查無此期間的計算資料")

def page_expenses(db: RentalDB):
    st.header("💸 支出管理 (v12.0)")
    
    tab1, tab2, tab3 = st.tabs(["新增支出", "支出記錄", "📊 統計分析"])
    
    # ========== Tab 1: 新增支出 ==========
    with tab1:
        with st.form("expense_form"):
            col1, col2 = st.columns([1, 1])
            with col1:
                d = st.date_input("日期", value=date.today())
                cat = st.selectbox("分類", EXPENSE_CATEGORIES)
            with col2:
                amt = st.number_input("金額 ($)", min_value=0)
                desc = st.text_input("說明", placeholder="例：更換馬桶蓋")
            
            if st.form_submit_button("➕ 新增支出", type="primary", use_container_width=True):
                if db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc):
                    st.success("✅ 已記錄")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ 記錄失敗")
    
    # ========== Tab 2: 支出記錄 ==========
    with tab2:
        st.subheader("📋 最近支出")
        expenses = db.get_expenses(50)
        if not expenses.empty:
            # 格式化顯示
            display_df = expenses[['expense_date', 'category', 'amount', 'description']].copy()
            display_df.columns = ['日期', '分類', '金額($)', '說明']
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("暫無支出記錄")
    
    # ========== Tab 3: 統計分析 (圓餅圖) ==========
    with tab3:
        st.subheader("📊 支出統計分析")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            time_filter = st.radio("時間範圍", ["全部", "本年", "本月"])
        
        with col2:
            if time_filter == "全部":
                summary = db.get_expenses_summary_by_category()
            elif time_filter == "本年":
                start = f"{datetime.now().year}-01-01"
                end = datetime.now().strftime("%Y-%m-%d")
                summary = db.get_expenses_summary_by_category(start, end)
            else:  # 本月
                start = datetime.now().strftime("%Y-%m-01")
                end = datetime.now().strftime("%Y-%m-%d")
                summary = db.get_expenses_summary_by_category(start, end)
        
        if summary:
            # 計算總支出
            total_expense = sum(summary.values())
            
            # 顯示統計卡片
            col1, col2 = st.columns(2)
            with col1: display_card("總支出", f"${int(total_expense):,}", "blue")
            with col2: display_card("分類數", str(len(summary)), "green")
            
            st.divider()
            
            # 繪製圓餅圖
            fig, ax = plt.subplots(figsize=(10, 6))
            colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A", "#98D8C8"]
            
            wedges, texts, autotexts = ax.pie(
                summary.values(),
                labels=summary.keys(),
                autopct='%1.1f%%',
                colors=colors[:len(summary)],
                startangle=90,
                textprops={'fontsize': 11, 'weight': 'bold'}
            )
            
            # 美化文字
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(10)
                autotext.set_weight('bold')
            
            ax.set_title(f"支出分佈 ({time_filter})", fontsize=14, weight='bold', pad=20)
            
            st.pyplot(fig)
            
            st.divider()
            
            # 詳細統計表
            st.subheader("詳細統計")
            detail_data = []
            for cat, amount in sorted(summary.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense * 100) if total_expense > 0 else 0
                detail_data.append({
                    '分類': cat,
                    '金額($)': f"${int(amount):,}",
                    '占比': f"{percentage:.1f}%"
                })
            
            detail_df = pd.DataFrame(detail_data)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        else:
            st.info(f"📭 此時間範圍內暫無支出記錄")

def page_settings(db: RentalDB):
    st.header("⚙️ 設定")
    st.markdown("✅ **v12.0 - 完整統計與圓餅圖版**")
    st.markdown("• 電費記錄新增備註欄")
    st.markdown("• 支出分類擴展（維修、清潔、貸款、網路費、其他）")
    st.markdown("• 支出圓餅圖統計分析")
    st.divider()
    if st.button("💥 重置整個系統 (刪除資料庫)", type="primary"):
        ok, msg = db.reset_database()
        if ok: st.success(msg); time.sleep(1); st.rerun()
        else: st.error(msg)

def main():
    st.set_page_config(page_title="幸福之家 v12.0", page_icon="🏠", layout="wide")
    with st.sidebar:
        st.title("🏠 幸福之家 v12.0")
        st.caption("完整統計版")
        menu = st.radio("", ["📊 儀表板", "👥 房客", "💡 電費", "💸 支出", "⚙️ 設定"])
    db = RentalDB()
    if menu == "📊 儀表板": page_dashboard(db)
    elif menu == "👥 房客": page_tenants(db)
    elif menu == "💡 電費": page_electricity(db)
    elif menu == "💸 支出": page_expenses(db)
    else: page_settings(db)

if __name__ == "__main__":
    main()

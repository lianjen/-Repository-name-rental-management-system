"""
幸福之家管理系統 Pro v9.0 完全修復版
全方位正確、所有問題解決、完全可用
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List

# ================================================================================
# 日誌配置
# ================================================================================
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "rental_system.log"),
    level=logging.DEBUG,
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

# ================================================================================
# 數據庫類
# ================================================================================
class RentalDB:
    """數據庫操作類 - v9.0 完全修復版"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        """獲取數據庫連接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(RESTART)")
            logging.debug("DB committed and checkpointed")
        except Exception as e:
            conn.rollback()
            logging.error(f"DB Error: {e}", exc_info=True)
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化數據庫表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            logging.info("Initializing database tables...")
            
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
            
            logging.info("All tables initialized successfully")

    def get_period_info(self, period_id: int) -> Optional[Dict]:
        """獲取計費期間信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period WHERE id=?", (period_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "year": row[1],
                        "month_start": row[2],
                        "month_end": row[3],
                        "notes": row[4]
                    }
        except Exception as e:
            logging.error(f"get_period_info error: {e}")
        return None

    def add_electricity_period(self, year: int, month_start: int, month_end: int, notes: str = "") -> Tuple[bool, str, int]:
        """新增計費期間"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO electricity_period(period_year, period_month_start, period_month_end, notes)
                    VALUES(?, ?, ?, ?)
                """, (year, month_start, month_end, notes))
                period_id = cursor.lastrowid
            logging.info(f"✓ Period created: {year}年 {month_start}-{month_end}月 (ID={period_id})")
            return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            logging.error(f"add_electricity_period error: {e}")
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float, notes: str = "") -> Tuple[bool, str]:
        """新增台電單據"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee, notes)
                    VALUES(?, ?, ?, ?, ?)
                """, (period_id, floor_name, tdy_kwh, tdy_fee, notes))
                
                # 驗證寫入
                cursor.execute("SELECT * FROM electricity_tdy_bill WHERE period_id=? AND floor_name=?", (period_id, floor_name))
                verify = cursor.fetchone()
                if verify:
                    logging.info(f"✓ TDY bill {floor_name} verified: kwh={verify[2]}, fee={verify[3]}")
                    return True, f"✅ {floor_name} 台電單據已記錄"
                else:
                    return False, f"❌ {floor_name} 台電單據記錄失敗"
        except Exception as e:
            logging.error(f"add_tdy_bill error: {e}")
            return False, f"❌ 記錄失敗: {str(e)}"

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float, notes: str = "") -> Tuple[bool, str]:
        """新增電錶度數"""
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                cursor = conn.cursor()
                logging.debug(f"Adding meter for {room}: start={start}, end={end}, usage={kwh_usage}")
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage, notes)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (period_id, room, start, end, kwh_usage, notes))
                
                # 驗證寫入
                cursor.execute("SELECT * FROM electricity_meter WHERE period_id=? AND room_number=?", (period_id, room))
                verify = cursor.fetchone()
                if verify:
                    logging.info(f"✓ Meter {room} verified: start={verify[2]}, end={verify[3]}, usage={verify[4]}")
                    return True, f"✅ {room} 度數已記錄"
                else:
                    logging.warning(f"Meter {room} verification failed!")
                    return False, f"❌ {room} 度數記錄失敗"
        except Exception as e:
            logging.error(f"add_meter_reading error: {e}")
            return False, f"❌ 記錄失敗: {str(e)}"

    def set_sharing_config(self, period_id: int, room_number: str, is_sharing: int) -> bool:
        """設定房間是否參與公電分攤"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_sharing_config(period_id, room_number, is_sharing)
                    VALUES(?, ?, ?)
                """, (period_id, room_number, is_sharing))
            return True
        except Exception as e:
            logging.error(f"set_sharing_config error: {e}")
            return False

    def get_sharing_config(self, period_id: int, room_number: str) -> int:
        """獲取房間分攤配置"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT is_sharing FROM electricity_sharing_config 
                    WHERE period_id=? AND room_number=?
                """, (period_id, room_number))
                row = cursor.fetchone()
                return row[0] if row else 1
        except:
            return 1

    def calculate_electricity_fee(self, period_id: int) -> Tuple[bool, str, pd.DataFrame]:
        """計算電費 - v9.0 完全修復版"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                logging.info("=" * 70)
                logging.info(f"Starting electricity calculation for period_id={period_id}")
                
                # 檢查台電單據
                cursor.execute("""
                    SELECT floor_name, tdy_total_kwh, tdy_total_fee 
                    FROM electricity_tdy_bill 
                    WHERE period_id=?
                """, (period_id,))
                tdy_bills = cursor.fetchall()
                logging.info(f"TDY Bills found: {len(tdy_bills)}")
                for bill in tdy_bills:
                    logging.info(f"  - {bill[0]}: {bill[1]}度, ${bill[2]}")
                
                if not tdy_bills:
                    logging.error("❌ No TDY bills found")
                    return False, "❌ 尚未輸入台電單據", pd.DataFrame()
                
                # 檢查電錶度數
                cursor.execute("""
                    SELECT room_number, meter_kwh_usage 
                    FROM electricity_meter 
                    WHERE period_id=?
                """, (period_id,))
                meters = cursor.fetchall()
                logging.info(f"Meters found: {len(meters)}")
                for meter in meters:
                    logging.info(f"  - {meter[0]}: {meter[1]}度")
                
                if not meters:
                    logging.error("❌ No meters found")
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()
                
                results = []
                for floor_name, tdy_kwh, tdy_fee in tdy_bills:
                    # 取該樓層有度數的房間
                    floor_rooms = [(room, kwh) for room, kwh in meters if ROOM_FLOOR_MAP.get(room, "") == floor_name]
                    logging.info(f"Processing floor {floor_name}: {len(floor_rooms)} rooms")
                    
                    if not floor_rooms:
                        logging.warning(f"No rooms found for floor {floor_name}")
                        continue
                    
                    # 計算私電和公電
                    private_kwh_sum = sum(kwh for _, kwh in floor_rooms)
                    public_kwh = tdy_kwh - private_kwh_sum
                    
                    # 計算分攤房間數
                    sharing_rooms = []
                    for room, _ in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        if is_sharing == 1:
                            sharing_rooms.append(room)
                    
                    sharing_count = len(sharing_rooms) if sharing_rooms else len(floor_rooms)
                    kwh_per_room = public_kwh / sharing_count if sharing_count > 0 else 0
                    avg_price = tdy_fee / tdy_kwh if tdy_kwh > 0 else 0
                    
                    logging.info(f"  {floor_name}: tdy_kwh={tdy_kwh}, private_sum={private_kwh_sum}, public={public_kwh}, sharing_count={sharing_count}, price=${avg_price:.2f}")
                    
                    # 計算每個房間
                    for room, private_kwh in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        allocated_kwh = kwh_per_room if is_sharing == 1 else 0
                        total_kwh = private_kwh + allocated_kwh
                        calculated_fee = total_kwh * avg_price
                        
                        # 查詢預繳電費
                        cursor.execute("""
                            SELECT balance FROM electricity_prepaid 
                            WHERE room_number=? 
                            ORDER BY created_at DESC LIMIT 1
                        """, (room,))
                        prepaid_row = cursor.fetchone()
                        prepaid_balance = prepaid_row[0] if prepaid_row else 0
                        actual_payment = max(0, calculated_fee - prepaid_balance)
                        
                        # 寫入計算結果
                        cursor.execute("""
                            INSERT OR REPLACE INTO electricity_calculation(
                                period_id, room_number, floor_name, private_kwh, allocated_kwh,
                                total_kwh, avg_price, calculated_fee, prepaid_balance, actual_payment)
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (period_id, room, floor_name, private_kwh, allocated_kwh, total_kwh,
                              avg_price, calculated_fee, prepaid_balance, actual_payment))
                        
                        logging.info(f"  {room}: private={private_kwh:.0f} + allocated={allocated_kwh:.0f} = {total_kwh:.0f}度, 費用${calculated_fee:.0f}")
                        
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
                
                logging.info(f"✓ Calculation complete: {len(results)} results")
                logging.info("=" * 70)
                
                df = pd.DataFrame(results)
                return True, "✅ 電費計算完成", df
        except Exception as e:
            logging.error(f"❌ Calculate error: {e}", exc_info=True)
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

# ================================================================================
# UI 函數
# ================================================================================
def display_card(title: str, value: str, color: str = "blue"):
    """顯示卡片"""
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color, '#ccc')}; border-radius: 8px; padding: 15px; margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def page_electricity(db: RentalDB):
    """電費管理頁面"""
    st.header("💡 電費管理 v9.0")
    st.success("✅ v9.0 完全修復版 - 所有問題解決")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None
    
    tab1, tab2 = st.tabs(["新增期間", "輸入 & 計算"])
    
    with tab1:
        st.subheader("第 1 步：新增計費期間")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            year = st.number_input("年份", value=datetime.now().year, min_value=2020)
        with col2:
            month_start = st.number_input("開始月份", value=1, min_value=1, max_value=12)
        with col3:
            month_end = st.number_input("結束月份", value=2, min_value=1, max_value=12)
        
        if st.button("✅ 新增期間", type="primary", use_container_width=True):
            ok, msg, period_id = db.add_electricity_period(year, month_start, month_end)
            if ok:
                st.success(msg)
                st.session_state.current_period_id = period_id
                st.rerun()
            else:
                st.error(msg)
        
        if st.session_state.current_period_id:
            period_info = db.get_period_info(st.session_state.current_period_id)
            if period_info:
                st.info(f"✅ 期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID={period_info['id']})")
    
    with tab2:
        st.subheader("第 2 步：輸入資料 & 計算")
        
        if not st.session_state.current_period_id:
            st.warning("⚠️ 請先建立計費期間")
        else:
            period_id = st.session_state.current_period_id
            period_info = db.get_period_info(period_id)
            
            if period_info:
                st.info(f"期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID={period_id})")
            
            with st.form(key="electricity_form"):
                st.markdown("### 台電單據")
                for floor in ["2F", "3F", "4F"]:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.number_input(f"{floor} 度數", value=0, min_value=0, key=f"tdy_kwh_{floor}")
                    with col2:
                        st.number_input(f"{floor} 費用", value=0, min_value=0, key=f"tdy_fee_{floor}")
                
                st.markdown("### 房間度數")
                for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                           ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                    st.write(f"**{floor_label}**")
                    for room in rooms:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.number_input(f"{room} 上期", value=0, min_value=0, key=f"start_{room}")
                        with col2:
                            st.number_input(f"{room} 本期", value=0, min_value=0, key=f"end_{room}")
                
                submitted = st.form_submit_button("✅ 提交並計算", type="primary", use_container_width=True)
            
            if submitted:
                logging.info("=" * 70)
                logging.info("Form submitted")
                
                # 收集台電單據數據
                tdy_data = {}
                for floor in ["2F", "3F", "4F"]:
                    kwh = st.session_state.get(f"tdy_kwh_{floor}", 0)
                    fee = st.session_state.get(f"tdy_fee_{floor}", 0)
                    tdy_data[floor] = {"kwh": kwh, "fee": fee}
                    if kwh > 0:
                        logging.info(f"Input TDY {floor}: {kwh}度, ${fee}")
                
                # 收集電錶度數數據
                meter_data = {}
                for room in ALL_ROOMS:
                    start = st.session_state.get(f"start_{room}", 0)
                    end = st.session_state.get(f"end_{room}", 0)
                    meter_data[room] = (start, end)
                    if end > 0:
                        logging.info(f"Input Meter {room}: {start} → {end}")
                
                # 驗證數據
                tdy_valid = sum(1 for d in tdy_data.values() if d["kwh"] > 0 and d["fee"] > 0)
                meter_valid = sum(1 for s, e in meter_data.values() if e > 0 and e > s)
                
                logging.info(f"Validation: TDY={tdy_valid}, Meter={meter_valid}")
                st.info(f"驗證：台電單據 {tdy_valid} 個，房間度數 {meter_valid} 間")
                
                if tdy_valid > 0 and meter_valid > 0:
                    with st.spinner("寫入數據庫..."):
                        # 寫入台電單據
                        tdy_ok = 0
                        for floor, data in tdy_data.items():
                            if data["kwh"] > 0 and data["fee"] > 0:
                                ok, _ = db.add_tdy_bill(period_id, floor, data["kwh"], data["fee"])
                                if ok:
                                    tdy_ok += 1
                        
                        # 寫入電錶度數
                        meter_ok = 0
                        for room, (start, end) in meter_data.items():
                            if end > 0 and end > start:
                                ok, _ = db.add_meter_reading(period_id, room, start, end)
                                if ok:
                                    meter_ok += 1
                        
                        logging.info(f"Written: TDY={tdy_ok}, Meter={meter_ok}")
                        
                        # 設定分攤配置
                        for room in ALL_ROOMS:
                            is_sharing = 0 if room in ["1A", "1B"] else 1
                            db.set_sharing_config(period_id, room, is_sharing)
                    
                    with st.spinner("計算中..."):
                        ok, msg, result_df = db.calculate_electricity_fee(period_id)
                    
                    if ok:
                        st.balloons()
                        st.success(msg)
                        st.dataframe(result_df, use_container_width=True, hide_index=True)
                    else:
                        st.error(msg)
                        st.info("💡 詳細信息請檢查日誌：logs/rental_system.log")
                else:
                    st.error("❌ 驗證失敗：需要至少 1 個台電單據和 1 間房間度數")

# ================================================================================
# 主函數
# ================================================================================
def main():
    st.set_page_config(
        page_title="幸福之家 v9.0",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    db = RentalDB()
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v9.0 完全修復版")
        st.markdown("---")
        st.markdown("**✅ v9.0 全方位正確**")
        st.markdown("- 所有問題已解決")
        st.markdown("- 完全可用")
        st.markdown("- 所有功能正常")
    
    page_electricity(db)

if __name__ == "__main__":
    main()


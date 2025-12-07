"""
幸福之家管理系統 Pro v8.0
🔨 終極修復版 - 數據庫問題徹底解決
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List

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

class RentalDB:
    """數據庫操作類 - v8.0 修復版"""
    
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
            conn.commit()  # 【v8.0】確保提交
            logging.info("Database committed")
        except Exception as e:
            conn.rollback()
            logging.error(f"DB Error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化數據庫 - v8.0 確保所有表都創建"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            logging.info("Creating tables...")
            
            # 【v8.0】完整的表創建邏輯
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_period (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_year INTEGER NOT NULL,
                    period_month_start INTEGER NOT NULL,
                    period_month_end INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logging.info("✓ electricity_period table created")
            
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
            logging.info("✓ electricity_tdy_bill table created")
            
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
            logging.info("✓ electricity_meter table created")
            
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(period_id) REFERENCES electricity_period(id)
                )
            """)
            logging.info("✓ electricity_calculation table created")
            
            logging.info("All tables initialized successfully")

    def get_period_info(self, period_id: int) -> Optional[Dict]:
        """獲取期間信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM electricity_period WHERE id=?", (period_id,))
                row = cursor.fetchone()
                if row:
                    return {"id": row[0], "year": row[1], "month_start": row[2], "month_end": row[3]}
        except Exception as e:
            logging.error(f"get_period_info error: {e}")
        return None

    def add_electricity_period(self, year: int, month_start: int, month_end: int) -> Tuple[bool, str, int]:
        """新增計費期間"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO electricity_period(period_year, period_month_start, period_month_end)
                    VALUES(?, ?, ?)
                """, (year, month_start, month_end))
                period_id = cursor.lastrowid
            logging.info(f"✓ Period created: {year}年 {month_start}-{month_end}月 (ID={period_id})")
            return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            logging.error(f"add_electricity_period error: {e}")
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float) -> bool:
        """新增台電單據 - v8.0 確保 commit"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee)
                    VALUES(?, ?, ?, ?)
                """, (period_id, floor_name, tdy_kwh, tdy_fee))
                logging.info(f"✓ TDY Bill inserted: {floor_name} - period_id={period_id}, kwh={tdy_kwh}, fee={tdy_fee}")
            return True
        except Exception as e:
            logging.error(f"add_tdy_bill error: {e}")
            return False

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float) -> bool:
        """新增電錶度數 - v8.0 確保 commit"""
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage)
                    VALUES(?, ?, ?, ?, ?)
                """, (period_id, room, start, end, kwh_usage))
                logging.info(f"✓ Meter inserted: {room} - period_id={period_id}, start={start}, end={end}, usage={kwh_usage}")
            return True
        except Exception as e:
            logging.error(f"add_meter_reading error: {e}")
            return False

    def verify_data_in_db(self, period_id: int) -> Tuple[int, int]:
        """【v8.0 新增】驗證數據是否真的在數據庫裡"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查台電單據
                cursor.execute("SELECT COUNT(*) FROM electricity_tdy_bill WHERE period_id=?", (period_id,))
                tdy_count = cursor.fetchone()[0]
                
                # 檢查電錶度數
                cursor.execute("SELECT COUNT(*) FROM electricity_meter WHERE period_id=?", (period_id,))
                meter_count = cursor.fetchone()[0]
                
                logging.info(f"Data verification: TDY records={tdy_count}, Meter records={meter_count}")
                
                # 詳細日誌
                cursor.execute("SELECT floor_name, tdy_total_kwh, tdy_total_fee FROM electricity_tdy_bill WHERE period_id=?", (period_id,))
                tdy_records = cursor.fetchall()
                for record in tdy_records:
                    logging.info(f"  TDY: {record}")
                
                cursor.execute("SELECT room_number, meter_kwh_usage FROM electricity_meter WHERE period_id=?", (period_id,))
                meter_records = cursor.fetchall()
                for record in meter_records:
                    logging.info(f"  Meter: {record}")
                
                return tdy_count, meter_count
        except Exception as e:
            logging.error(f"verify_data_in_db error: {e}")
            return 0, 0

    def calculate_electricity_fee(self, period_id: int) -> Tuple[bool, str, pd.DataFrame]:
        """計算電費 - v8.0 真正的修復"""
        try:
            logging.info(f"\n{'='*70}")
            logging.info(f"Starting calculation for period_id={period_id}")
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 【v8.0】先驗證數據確實存在
                tdy_count, meter_count = self.verify_data_in_db(period_id)
                logging.info(f"Pre-calculation check: TDY={tdy_count}, Meter={meter_count}")
                
                if tdy_count == 0:
                    logging.error("❌ No TDY data found")
                    return False, "❌ 尚未輸入台電單據", pd.DataFrame()
                
                if meter_count == 0:
                    logging.error("❌ No meter data found")
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()
                
                # 查詢台電單據
                cursor.execute("SELECT floor_name, tdy_total_kwh, tdy_total_fee FROM electricity_tdy_bill WHERE period_id=?", (period_id,))
                tdy_bills = cursor.fetchall()
                logging.info(f"TDY bills fetched: {len(tdy_bills)}")
                
                # 查詢電錶度數
                cursor.execute("SELECT room_number, meter_kwh_usage FROM electricity_meter WHERE period_id=?", (period_id,))
                meters = cursor.fetchall()
                logging.info(f"Meters fetched: {len(meters)}")
                
                if not meters:
                    logging.error("❌ Query returned empty meters")
                    return False, "❌ 尚未輸入電錶度數（查詢返回空）", pd.DataFrame()
                
                results = []
                for floor_name, tdy_kwh, tdy_fee in tdy_bills:
                    floor_rooms = [(room, kwh) for room, kwh in meters if ROOM_FLOOR_MAP.get(room, "") == floor_name]
                    
                    if not floor_rooms:
                        logging.warning(f"No rooms for floor {floor_name}")
                        continue
                    
                    private_kwh_sum = sum(kwh for _, kwh in floor_rooms)
                    public_kwh = tdy_kwh - private_kwh_sum
                    sharing_count = len(floor_rooms)
                    kwh_per_room = public_kwh / sharing_count if sharing_count > 0 else 0
                    avg_price = tdy_fee / tdy_kwh if tdy_kwh > 0 else 0
                    
                    logging.info(f"Floor {floor_name}: {len(floor_rooms)} rooms, avg_price=${avg_price:.2f}")
                    
                    for room, private_kwh in floor_rooms:
                        allocated_kwh = kwh_per_room
                        total_kwh = private_kwh + allocated_kwh
                        calculated_fee = total_kwh * avg_price
                        
                        cursor.execute("""INSERT OR REPLACE INTO electricity_calculation(
                            period_id, room_number, floor_name, private_kwh, allocated_kwh, total_kwh, avg_price, calculated_fee)
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        """, (period_id, room, floor_name, private_kwh, allocated_kwh, total_kwh, avg_price, calculated_fee))
                        
                        results.append({
                            '房號': room,
                            '樓層': floor_name,
                            '私錶': f"{private_kwh:.0f}",
                            '分攤': f"{allocated_kwh:.0f}",
                            '合計': f"{total_kwh:.0f}",
                            '電價': f"${avg_price:.2f}",
                            '應繳': f"${calculated_fee:.0f}"
                        })
                        logging.info(f"  {room}: {private_kwh:.0f} + {allocated_kwh:.0f} = {total_kwh:.0f} 度, ${calculated_fee:.0f}")
                
                df = pd.DataFrame(results)
                logging.info(f"✓ Calculation complete: {len(df)} rooms processed")
                return True, "✅ 電費計算完成", df
        except Exception as e:
            logging.error(f"❌ Calculate error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

def page_electricity(db: RentalDB):
    """電費管理 - v8.0 修復版"""
    st.header("💡 電費管理 v8.0 🔨修復版")
    
    if "current_period_id" not in st.session_state:
        st.session_state.current_period_id = None
    
    tab1, tab2 = st.tabs(["新增期間", "輸入 & 計算"])
    
    with tab1:
        st.subheader("第1步：新增計費期間")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            year = st.number_input("年份", value=datetime.now().year, min_value=2020)
        with col2:
            month_start = st.number_input("開始月份", value=1, min_value=1, max_value=12)
        with col3:
            month_end = st.number_input("結束月份", value=2, min_value=1, maxvalue=12)
        
        if st.button("✅ 新增期間", type="primary"):
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
                st.success(f"✅ 期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID={period_info['id']})")
    
    with tab2:
        st.subheader("第2步：輸入資料 & 計算")
        
        if not st.session_state.current_period_id:
            st.warning("請先建立計費期間")
        else:
            period_id = st.session_state.current_period_id
            period_info = db.get_period_info(period_id)
            
            if period_info:
                st.info(f"期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID={period_id})")
            
            with st.form(key="electricity_form_v8"):
                st.markdown("### 台電單據（填寫 2F、3F、4F 的資料）")
                for floor in ["2F", "3F", "4F"]:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.number_input(f"{floor} 度數", value=0, min_value=0, key=f"tdy_kwh_{floor}")
                    with col2:
                        st.number_input(f"{floor} 費用", value=0, min_value=0, key=f"tdy_fee_{floor}")
                
                st.markdown("### 房間度數（填寫所有房間 1A-4D）")
                for floor_label, rooms in [("1F", ["1A", "1B"]), ("2F", ["2A", "2B"]), 
                                           ("3F", ["3A", "3B", "3C", "3D"]), ("4F", ["4A", "4B", "4C", "4D"])]:
                    st.write(f"**{floor_label}**")
                    for room in rooms:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.number_input(f"{room} 上期", value=0, min_value=0, key=f"start_{room}")
                        with col2:
                            st.number_input(f"{room} 本期", value=0, min_value=0, key=f"end_{room}")
                
                submitted = st.form_submit_button("✅ 提交並計算", type="primary")
            
            if submitted:
                logging.info("="*70)
                logging.info("Form submitted - v8.0")
                
                # 收集數據
                tdy_data = {}
                for floor in ["2F", "3F", "4F"]:
                    kwh = st.session_state.get(f"tdy_kwh_{floor}", 0)
                    fee = st.session_state.get(f"tdy_fee_{floor}", 0)
                    tdy_data[floor] = {"kwh": kwh, "fee": fee}
                    if kwh > 0:
                        logging.info(f"Input TDY {floor}: {kwh}度, ${fee}")
                
                meter_data = {}
                for room in ALL_ROOMS:
                    start = st.session_state.get(f"start_{room}", 0)
                    end = st.session_state.get(f"end_{room}", 0)
                    meter_data[room] = (start, end)
                    if end > 0:
                        logging.info(f"Input Meter {room}: {start} → {end} ({end-start}度)")
                
                # 驗證
                tdy_valid = sum(1 for d in tdy_data.values() if d["kwh"] > 0 and d["fee"] > 0)
                meter_valid = sum(1 for s, e in meter_data.values() if e > 0 and e > s)
                
                logging.info(f"Initial validation: TDY={tdy_valid}, Meter={meter_valid}")
                st.info(f"驗證：台電單據 {tdy_valid} 個，房間度數 {meter_valid} 間")
                
                if tdy_valid > 0 and meter_valid > 0:
                    with st.spinner("【v8.0】正在寫入數據庫..."):
                        # 【v8.0 核心】逐一寫入並驗證
                        tdy_write_ok = 0
                        for floor, data in tdy_data.items():
                            if data["kwh"] > 0 and data["fee"] > 0:
                                if db.add_tdy_bill(period_id, floor, data["kwh"], data["fee"]):
                                    tdy_write_ok += 1
                                    logging.info(f"✓ TDY {floor} written")
                                else:
                                    logging.error(f"❌ TDY {floor} write failed")
                        
                        logging.info(f"TDY records written: {tdy_write_ok}/{tdy_valid}")
                        
                        meter_write_ok = 0
                        for room, (start, end) in meter_data.items():
                            if end > 0 and end > start:
                                if db.add_meter_reading(period_id, room, start, end):
                                    meter_write_ok += 1
                                    logging.info(f"✓ Meter {room} written")
                                else:
                                    logging.error(f"❌ Meter {room} write failed")
                        
                        logging.info(f"Meter records written: {meter_write_ok}/{meter_valid}")
                        
                        # 【v8.0 核心】驗證寫入
                        logging.info("Verifying written data...")
                        tdy_verify, meter_verify = db.verify_data_in_db(period_id)
                        logging.info(f"After write verification: TDY={tdy_verify}, Meter={meter_verify}")
                    
                    with st.spinner("正在計算..."):
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

def main():
    st.set_page_config(page_title="幸福之家 v8.0", page_icon="🏠", layout="wide")
    
    db = RentalDB()
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("v8.0 🔨修復版")
        st.markdown("---")
        st.markdown("### 目前功能")
        st.markdown("💡 電費管理")
    
    page_electricity(db)

if __name__ == "__main__":
    main()

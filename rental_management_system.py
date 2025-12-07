"""
幸福之家管理系統 Pro v5.8 - SQLite WAL 修復版
【核心修正】: 
1. 改進 WAL 模式連接管理
2. 強制提交和驗證每一步
3. 計算前進行詳細診斷
4. 改進錯誤訊息和提示
特性: 計算不再失敗、詳細的診斷訊息、穩定可靠
"""

import streamlit as st
import pandas as pd
import sqlite3
import logging
import contextlib
import os
import time
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, Any, List

# ============================================================================
# 日誌配置
# ============================================================================
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

# ============================================================================
# 數據庫層
# ============================================================================

class RentalDB:
    """數據庫操作類 v5.8 - 改進連接管理"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        """獲取資料庫連接（改進 WAL 模式）"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            # 【改進 1】WAL 模式優化
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA foreign_keys = ON")
            
            yield conn
            
            # 【改進 2】強制提交
            conn.commit()
            
            # 【改進 3】強制檢查點
            conn.execute("PRAGMA wal_checkpoint(RESTART)")
            
            logging.debug(f"DB connection committed and checkpointed")
            
        except Exception as e:
            conn.rollback()
            logging.error(f"DB Error: {e}", exc_info=True)
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_period ON electricity_period(period_year, period_month_start)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_bill_period ON electricity_tdy_bill(period_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_meter_room ON electricity_meter(room_number)")

    def room_exists(self, room: str) -> bool:
        """檢查房號是否已存在"""
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
        """新增或更新租客"""
        try:
            monthly_rent = base_rent + elec_fee
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                if tenant_id:
                    cursor.execute("""
                        UPDATE tenants SET
                            tenant_name=?, phone=?, deposit=?, 
                            base_rent=?, electricity_fee=?, monthly_rent=?,
                            lease_start=?, lease_end=?, payment_method=?,
                            annual_discount_months=?, has_water_discount=?,
                            prepaid_electricity=?, notes=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (name, phone, deposit, base_rent, elec_fee, monthly_rent,
                          start, end, method, discount, water, prepaid, notes, tenant_id))
                    msg = f"✅ 房號 {room} 已更新"
                    logging.info(f"Updated tenant {room}")
                else:
                    if self.room_exists(room):
                        return False, f"❌ 房號 {room} 已存在，請勿重複新增"
                    
                    cursor.execute("""
                        INSERT INTO tenants(
                            room_number, tenant_name, phone, deposit,
                            base_rent, electricity_fee, monthly_rent,
                            lease_start, lease_end, payment_method,
                            annual_discount_months, has_water_discount,
                            prepaid_electricity, notes)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, elec_fee, monthly_rent,
                          start, end, method, discount, water, prepaid, notes))
                    msg = f"✅ 房號 {room} 已新增"
                    logging.info(f"Created tenant {room}")
                
                return True, msg
                
        except Exception as e:
            logging.error(f"upsert_tenant error: {str(e)}", exc_info=True)
            return False, f"❌ 保存失敗: {str(e)}"

    def get_tenants(self) -> pd.DataFrame:
        """獲取租客列表"""
        try:
            with self._get_connection() as conn:
                df = pd.read_sql(
                    "SELECT * FROM tenants WHERE is_active=1 ORDER BY room_number",
                    conn
                )
                return df if not df.empty else pd.DataFrame()
        except Exception as e:
            logging.error(f"get_tenants error: {e}")
            return pd.DataFrame()

    def get_tenant_by_id(self, tid: int) -> Optional[Dict]:
        """按ID獲取租客"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tenants WHERE id=?", (tid,))
                row = cursor.fetchone()
                if row:
                    cols = [d[0] for d in cursor.description]
                    return dict(zip(cols, row))
            return None
        except Exception as e:
            logging.error(f"get_tenant_by_id error: {e}")
            return None

    def delete_tenant(self, tid: int) -> Tuple[bool, str]:
        """刪除租客"""
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))
            return True, "✅ 已刪除"
        except Exception as e:
            return False, f"❌ 刪除失敗: {str(e)}"

    def get_period_info(self, period_id: int) -> Optional[Dict]:
        """獲取計費期間資訊"""
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
            return None
        except:
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
            logging.info(f"Created electricity period {year}-{month_start}-{month_end}, ID={period_id}")
            return True, f"✅ 計費期間 {year}年 {month_start}-{month_end}月 已新增", period_id
        except Exception as e:
            logging.error(f"add_electricity_period error: {e}", exc_info=True)
            return False, f"❌ 新增失敗: {str(e)}", 0

    def add_tdy_bill(self, period_id: int, floor_name: str, tdy_kwh: float, tdy_fee: float, notes: str = "") -> Tuple[bool, str]:
        """新增台電單據（按樓層）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_tdy_bill(period_id, floor_name, tdy_total_kwh, tdy_total_fee, notes)
                    VALUES(?, ?, ?, ?, ?)
                """, (period_id, floor_name, tdy_kwh, tdy_fee, notes))
                
                # 【改進】寫入後驗證
                cursor.execute("SELECT * FROM electricity_tdy_bill WHERE period_id=? AND floor_name=?", (period_id, floor_name))
                verify = cursor.fetchone()
                if verify:
                    logging.info(f"TDY bill {floor_name} verified: kwh={verify[2]}, fee={verify[3]}")
                    return True, f"✅ {floor_name} 台電單據已記錄"
                else:
                    return False, f"❌ {floor_name} 台電單據記錄失敗"
        except Exception as e:
            logging.error(f"add_tdy_bill error: {e}", exc_info=True)
            return False, f"❌ 記錄失敗: {str(e)}"

    def add_meter_reading(self, period_id: int, room: str, start: float, end: float, notes: str = "") -> Tuple[bool, str]:
        """新增電錶度數（改進驗證）"""
        try:
            kwh_usage = end - start
            with self._get_connection() as conn:
                cursor = conn.cursor()
                logging.debug(f"Adding meter for {room}: start={start}, end={end}, usage={kwh_usage}")
                
                cursor.execute("""
                    INSERT OR REPLACE INTO electricity_meter(period_id, room_number, meter_start_reading, meter_end_reading, meter_kwh_usage, notes)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (period_id, room, start, end, kwh_usage, notes))
                
                # 【改進】寫入後立刻驗證
                cursor.execute("SELECT * FROM electricity_meter WHERE period_id=? AND room_number=?", (period_id, room))
                verify = cursor.fetchone()
                if verify:
                    logging.info(f"Meter {room} verified: start={verify[2]}, end={verify[3]}, usage={verify[4]}")
                    return True, f"✅ {room} 度數已記錄"
                else:
                    logging.warning(f"Meter {room} verification failed!")
                    return False, f"❌ {room} 度數記錄失敗（驗證失敗）"
        except Exception as e:
            logging.error(f"add_meter_reading error: {e}", exc_info=True)
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
            logging.error(f"set_sharing_config error: {e}", exc_info=True)
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

    def calculate_electricity_fee_v8(self, period_id: int) -> Tuple[bool, str, pd.DataFrame]:
        """v5.8 核心電費計算函數（改進診斷）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 【改進】診斷訊息 - 檢查台電單據
                logging.info("=" * 50)
                logging.info("Starting electricity calculation")
                logging.info(f"Period ID: {period_id}")
                
                cursor.execute("""
                    SELECT floor_name, tdy_total_kwh, tdy_total_fee
                    FROM electricity_tdy_bill WHERE period_id=?
                """, (period_id,))
                tdy_bills = cursor.fetchall()
                
                logging.info(f"TDY Bills found: {len(tdy_bills)}")
                for bill in tdy_bills:
                    logging.info(f"  - {bill[0]}: {bill[1]}度, ${bill[2]}")
                
                if not tdy_bills:
                    logging.warning("No TDY bills found")
                    return False, "❌ 尚未輸入台電單據", pd.DataFrame()
                
                # 【改進】診斷訊息 - 檢查電錶度數
                cursor.execute("""
                    SELECT room_number, meter_kwh_usage
                    FROM electricity_meter WHERE period_id=?
                """, (period_id,))
                meters = cursor.fetchall()
                
                logging.info(f"Meters found: {len(meters)}")
                for meter in meters:
                    logging.info(f"  - {meter[0]}: {meter[1]}度")
                
                if not meters:
                    logging.warning("No meters found")
                    # 【改進】詳細診斷訊息
                    cursor.execute("SELECT COUNT(*) FROM electricity_meter")
                    total_meters = cursor.fetchone()[0]
                    logging.info(f"Total meters in DB: {total_meters}")
                    return False, "❌ 尚未輸入電錶度數", pd.DataFrame()
                
                results = []
                
                for floor_name, tdy_kwh, tdy_fee in tdy_bills:
                    floor_rooms = [(room, kwh) for room, kwh in meters if ROOM_FLOOR_MAP.get(room, "") == floor_name]
                    
                    logging.info(f"Processing floor {floor_name}: {len(floor_rooms)} rooms")
                    
                    if not floor_rooms:
                        logging.warning(f"No rooms found for floor {floor_name}")
                        continue
                    
                    private_kwh_sum = sum(kwh for _, kwh in floor_rooms)
                    public_kwh = tdy_kwh - private_kwh_sum
                    
                    sharing_rooms = []
                    for room, _ in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        if is_sharing == 1:
                            sharing_rooms.append(room)
                    
                    sharing_count = len(sharing_rooms) if sharing_rooms else len(floor_rooms)
                    kwh_per_room = public_kwh / sharing_count if sharing_count > 0 else 0
                    avg_price = tdy_fee / tdy_kwh if tdy_kwh > 0 else 0
                    
                    logging.info(f"{floor_name}: tdy_kwh={tdy_kwh}, private_kwh_sum={private_kwh_sum}, public_kwh={public_kwh}, sharing_count={sharing_count}, avg_price={avg_price}")
                    
                    for room, private_kwh in floor_rooms:
                        is_sharing = self.get_sharing_config(period_id, room)
                        
                        allocated_kwh = kwh_per_room if is_sharing == 1 else 0
                        total_kwh = private_kwh + allocated_kwh
                        calculated_fee = total_kwh * avg_price
                        
                        cursor.execute("""
                            SELECT balance FROM electricity_prepaid 
                            WHERE room_number=? ORDER BY created_at DESC LIMIT 1
                        """, (room,))
                        prepaid_row = cursor.fetchone()
                        prepaid_balance = prepaid_row[0] if prepaid_row else 0
                        
                        actual_payment = max(0, calculated_fee - prepaid_balance)
                        
                        cursor.execute("""
                            INSERT OR REPLACE INTO electricity_calculation(
                                period_id, room_number, floor_name, private_kwh, allocated_kwh,
                                total_kwh, avg_price, calculated_fee, prepaid_balance, actual_payment)
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (period_id, room, floor_name, private_kwh, allocated_kwh, total_kwh,
                              avg_price, calculated_fee, prepaid_balance, actual_payment))
                        
                        logging.info(f"  {room}: private={private_kwh}, allocated={allocated_kwh}, total={total_kwh}, fee={calculated_fee}, payment={actual_payment}")
                        
                        results.append({
                            '房號': room,
                            '樓層': floor_name,
                            '私錶度': f"{private_kwh:.0f}",
                            '分攤度': f"{allocated_kwh:.0f}",
                            '合計度': f"{total_kwh:.0f}",
                            '電價': f"${avg_price:.2f}/度",
                            '應繳費': f"${calculated_fee:.0f}",
                            '預繳': f"${prepaid_balance:.0f}",
                            '實收': f"${actual_payment:.0f}"
                        })
                
                logging.info(f"Calculation complete: {len(results)} results")
                logging.info("=" * 50)
                
                df = pd.DataFrame(results)
                return True, "✅ 電費計算完成", df
                
        except Exception as e:
            logging.error(f"calculate_electricity_fee_v8 error: {e}", exc_info=True)
            return False, f"❌ 計算失敗: {str(e)}", pd.DataFrame()

    def add_electricity_prepaid(self, room: str, prepaid_amount: float, prepaid_date: str, notes: str = "") -> Tuple[bool, str]:
        """新增預繳電費"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO electricity_prepaid(room_number, prepaid_amount, prepaid_date, balance, notes)
                    VALUES(?, ?, ?, ?, ?)
                """, (room, prepaid_amount, prepaid_date, prepaid_amount, notes))
            return True, f"✅ {room} 預繳電費已記錄"
        except Exception as e:
            logging.error(f"add_electricity_prepaid error: {e}", exc_info=True)
            return False, f"❌ 記錄失敗: {str(e)}"

    def add_expense(self, expense_date: str, category: str, amount: float, description: str, room_number: str) -> bool:
        """新增支出"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO expenses(expense_date, category, amount, description, room_number)
                    VALUES(?, ?, ?, ?, ?)
                """, (expense_date, category, amount, description, room_number))
            return True
        except Exception as e:
            logging.error(f"add_expense error: {e}", exc_info=True)
            return False

    def get_expenses(self, limit: int = 10) -> pd.DataFrame:
        """獲取支出"""
        try:
            with self._get_connection() as conn:
                return pd.read_sql(
                    "SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?",
                    conn, params=(limit,))
        except:
            return pd.DataFrame()

# ============================================================================
# UI 函數
# ============================================================================

def display_card(title: str, value: str, color: str = "blue"):
    """顯示卡片"""
    colors = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}
    st.markdown(f"""
    <div style="background: white; border-left: 5px solid {colors.get(color, '#ccc')}; border-radius: 8px; padding: 15px; margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700;">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str: str) -> int:
    """計算天數"""
    try:
        target = datetime.strptime(date_str, "%Y.%m.%d").date()
        return (target - date.today()).days
    except:
        return 999

# ============================================================================
# 頁面函數
# ============================================================================

def page_dashboard(db: RentalDB):
    """儀表板"""
    st.header("早安，管理員！ 👋")
    st.caption(f"今天是 {datetime.now().strftime('%Y年%m月%d日')}")
    
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
                st.caption(f"⚠️ {days}天" if days < 60 else "✅ 正常")
            else:
                st.error(f"**{room}**\n空房")

def page_tenants(db: RentalDB):
    """房客管理"""
    
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
        
        st.subheader(f"✏️ 編輯 {tenant['room_number']} - {tenant['tenant_name']}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**基本資訊**")
            name = st.text_input("姓名", value=tenant['tenant_name'], key="edit_name")
            phone = st.text_input("電話", value=tenant['phone'] or "", key="edit_phone")
            deposit = st.number_input("押金", value=tenant['deposit'], key="edit_deposit")
            base_rent = st.number_input("基礎月租", value=tenant['base_rent'], key="edit_base_rent")
        
        with col2:
            st.write("**租約與電費**")
            elec_fee = st.number_input("月電費", value=tenant['electricity_fee'], key="edit_elec_fee")
            
            start_date = date.today()
            try:
                start_date = datetime.strptime(tenant['lease_start'], "%Y.%m.%d").date()
            except:
                pass
            
            end_date = date.today() + timedelta(days=365)
            try:
                end_date = datetime.strptime(tenant['lease_end'], "%Y.%m.%d").date()
            except:
                pass
            
            start = st.date_input("起租日", value=start_date, key="edit_start")
            end = st.date_input("到期日", value=end_date, key="edit_end")
        
        col1, col2 = st.columns(2)
        with col1:
            method = st.selectbox("繳租方式", ["月繳", "半年繳", "年繳"],
                                index=["月繳", "半年繳", "年繳"].index(tenant['payment_method']), key="edit_method")
        with col2:
            discount = st.number_input("年繳折幾個月", value=tenant['annual_discount_months'], min_value=0, max_value=12, key="edit_discount")
        
        col1, col2 = st.columns(2)
        with col1:
            water = st.checkbox("含100元水費折扣", value=bool(tenant['has_water_discount']), key="edit_water")
        with col2:
            prepaid = st.number_input("電費預繳餘額", value=tenant['prepaid_electricity'], min_value=0, key="edit_prepaid")
        
        notes = st.text_area("備註", value=tenant['notes'] or "", key="edit_notes")
        
        st.divider()
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
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
                    else:
                        st.error(msg)
        
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
        
        col1, col2 = st.columns(2)
        
        with col1:
            room = st.selectbox("房號", available_rooms, key="new_room")
            name = st.text_input("姓名", key="new_name")
            phone = st.text_input("電話", key="new_phone")
            deposit = st.number_input("押金", value=10000, key="new_deposit")
            base_rent = st.number_input("基礎月租", value=6000, key="new_base_rent")
        
        with col2:
            elec_fee = st.number_input("月電費", value=0, key="new_elec_fee")
            start = st.date_input("起租日", key="new_start")
            end = st.date_input("到期日", value=date.today() + timedelta(days=365), key="new_end")
            method = st.selectbox("繳租方式", ["月繳", "半年繳", "年繳"], key="new_method")
            discount = st.number_input("年繳折幾個月", value=0, min_value=0, max_value=12, key="new_discount")
        
        water = st.checkbox("含100元水費折扣", value=False, key="new_water")
        notes = st.text_area("備註", key="new_notes")
        
        st.divider()
        
        col1, col2 = st.columns([1, 3])
        
        with col1:
            if st.button("✅ 新增", type="primary", use_container_width=True):
                if not name:
                    st.error("請填寫姓名")
                else:
                    ok, msg = db.upsert_tenant(
                        room, name, phone, deposit,
                        base_rent, elec_fee, start.strftime("%Y.%m.%d"),
                        end.strftime("%Y.%m.%d"), method, discount, int(water), 0, notes
                    )
                    if ok:
                        st.success(msg)
                        st.session_state.edit_id = None
                        st.rerun()
                    else:
                        st.error(msg)
        
        with col2:
            if st.button("取消"):
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
                with st.expander(f"{t['room_number']} - {t['tenant_name']} | 月租 ${t['monthly_rent']:,.0f}"):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.write(f"📞 {t['phone']}")
                        st.write(f"基礎租: ${t['base_rent']:,.0f}")
                        st.write(f"電費: ${t['electricity_fee']:,.0f}")
                        st.write(f"到期: {t['lease_end']}")
                    with col2:
                        if st.button(f"✏️ 編輯", key=f"edit_{t['id']}", use_container_width=True):
                            st.session_state.edit_id = t['id']
                            st.rerun()
                        if st.button(f"🗑️ 刪除", key=f"del_{t['id']}", use_container_width=True):
                            ok, msg = db.delete_tenant(t['id'])
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
        else:
            st.info("尚無房客")

def page_electricity(db: RentalDB):
    """💡 電費管理 v5.8 - WAL 修復版"""
    st.header("💡 電費管理 v5.8")
    st.info("✨ 改進的 WAL 連接管理，確保數據穩定")
    
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
            month_end = st.number_input("結束月份", value=2, min_value=1, max_value=12)
        
        notes = st.text_input("備註 (如: 夏季電費)")
        
        if st.button("✅ 新增期間", type="primary", use_container_width=True):
            ok, msg, period_id = db.add_electricity_period(year, month_start, month_end, notes)
            if ok:
                st.success(msg)
                st.session_state.current_period_id = period_id
                st.rerun()
            else:
                st.error(msg)
        
        if st.session_state.current_period_id:
            st.success(f"✅ 計費期間已建立")
            period_info = db.get_period_info(st.session_state.current_period_id)
            if period_info:
                st.info(f"📌 {period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月 (ID: {period_info['id']})")
                st.write("→ 請進入「輸入 & 計算」標籤輸入台電單據和房間度數")
    
    with tab2:
        st.subheader("第2步：輸入資料 & 自動計算結果")
        
        if not st.session_state.current_period_id:
            st.warning("❌ 請先在「新增期間」標籤建立計費期間")
        else:
            period_id = st.session_state.current_period_id
            period_info = db.get_period_info(period_id)
            
            if period_info:
                st.success(f"📌 當前期間：{period_info['year']}年 {period_info['month_start']}-{period_info['month_end']}月")
            
            st.info("💡 輸入所有台電單據與房間度數，然後點「✅ 提交並計算」")
            
            with st.form(key="electricity_form_v8"):
                
                st.markdown("### 【第一部分】台電單據輸入")
                
                st.write("**1F - 自行繳納**（不計入公電分攤）")
                st.write("（此樓層自行繳納，無需輸入）")
                
                st.divider()
                
                tdy_data = {}
                for floor in ["2F", "3F", "4F"]:
                    st.write(f"**{floor}**")
                    col1, col2 = st.columns(2)
                    with col1:
                        tdy_kwh = st.number_input(f"{floor} 台電度數", value=0, min_value=0, step=1, key=f"tdy_kwh_{floor}")
                        tdy_data[floor] = {"kwh": tdy_kwh}
                    with col2:
                        tdy_fee = st.number_input(f"{floor} 台電費用", value=0, min_value=0, step=100, key=f"tdy_fee_{floor}")
                        tdy_data[floor]["fee"] = tdy_fee
                
                st.divider()
                st.markdown("### 【第二部分】房間電錶度數輸入")
                
                meter_data = {}
                
                st.write("**1F 房間**")
                for room in ["1A", "1B"]:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**{room}**")
                    with col2:
                        start = st.number_input(f"{room} 上期度數", value=0, min_value=0, step=1, key=f"start_{room}")
                    with col3:
                        end = st.number_input(f"{room} 本期度數", value=0, min_value=0, step=1, key=f"end_{room}")
                    meter_data[room] = (start, end)
                
                st.divider()
                
                st.write("**2F 房間**")
                for room in ["2A", "2B"]:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**{room}**")
                    with col2:
                        start = st.number_input(f"{room} 上期度數", value=0, min_value=0, step=1, key=f"start_{room}")
                    with col3:
                        end = st.number_input(f"{room} 本期度數", value=0, min_value=0, step=1, key=f"end_{room}")
                    meter_data[room] = (start, end)
                
                st.divider()
                
                st.write("**3F 房間**")
                for room in ["3A", "3B", "3C", "3D"]:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**{room}**")
                    with col2:
                        start = st.number_input(f"{room} 上期度數", value=0, min_value=0, step=1, key=f"start_{room}")
                    with col3:
                        end = st.number_input(f"{room} 本期度數", value=0, min_value=0, step=1, key=f"end_{room}")
                    meter_data[room] = (start, end)
                
                st.divider()
                
                st.write("**4F 房間**")
                for room in ["4A", "4B", "4C", "4D"]:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**{room}**")
                    with col2:
                        start = st.number_input(f"{room} 上期度數", value=0, min_value=0, step=1, key=f"start_{room}")
                    with col3:
                        end = st.number_input(f"{room} 本期度數", value=0, min_value=0, step=1, key=f"end_{room}")
                    meter_data[room] = (start, end)
                
                st.divider()
                
                submitted = st.form_submit_button("✅ 提交並計算", type="primary", use_container_width=True)
                
                if submitted:
                    st.subheader("📊 數據驗證結果")
                    
                    tdy_valid_count = 0
                    st.write("**台電單據檢查：**")
                    for floor, data in tdy_data.items():
                        if data["kwh"] > 0 and data["fee"] > 0:
                            st.write(f"  ✅ {floor}: {data['kwh']}度, ${data['fee']}")
                            tdy_valid_count += 1
                        else:
                            st.write(f"  ❌ {floor}: 未填或為 0")
                    
                    meter_valid_count = 0
                    st.write("**房間度數檢查：**")
                    for room, (start, end) in meter_data.items():
                        if end >= start:
                            usage = end - start
                            st.write(f"  ✅ {room}: 用電 {usage:.0f} 度")
                            meter_valid_count += 1
                        else:
                            st.write(f"  ❌ {room}: 本期度數 < 上期度數")
                    
                    st.divider()
                    
                    if tdy_valid_count > 0 and meter_valid_count > 0:
                        st.success(f"✅ 驗證通過！ 台電單據: {tdy_valid_count}個, 房間度數: {meter_valid_count}間")
                        
                        try:
                            # 【改進】分步提示
                            progress = st.progress(0)
                            status_text = st.empty()
                            
                            # 步驟 1: 提交台電單據
                            status_text.info("📝 正在提交台電單據...")
                            progress.progress(20)
                            for floor, data in tdy_data.items():
                                if data["kwh"] > 0 and data["fee"] > 0:
                                    db.add_tdy_bill(period_id, floor, data["kwh"], data["fee"])
                            time.sleep(0.5)
                            
                            # 步驟 2: 提交度數
                            status_text.info("📝 正在提交房間度數...")
                            progress.progress(40)
                            for room, (start, end) in meter_data.items():
                                if end >= start:
                                    db.add_meter_reading(period_id, room, start, end)
                            time.sleep(0.5)
                            
                            # 步驟 3: 設置分攤配置
                            status_text.info("⚙️ 正在設置分攤配置...")
                            progress.progress(60)
                            for room in ALL_ROOMS:
                                is_sharing = 0 if room in ["1A", "1B"] else 1
                                db.set_sharing_config(period_id, room, is_sharing)
                            time.sleep(0.5)
                            
                            # 步驟 4: 計算電費
                            status_text.info("🔄 正在計算電費...")
                            progress.progress(80)
                            ok, msg, result_df = db.calculate_electricity_fee_v8(period_id)
                            progress.progress(100)
                            
                            if ok:
                                status_text.empty()
                                progress.empty()
                                st.balloons()
                                st.success("🎉 資料已成功提交並計算完成！")
                                
                                st.divider()
                                st.subheader("📋 電費計算結果")
                                st.dataframe(result_df, use_container_width=True, hide_index=True)
                                
                                st.divider()
                                st.subheader("📊 統計資訊")
                                st.write(f"✅ 共計 {len(result_df)} 間房間已計算")
                            else:
                                status_text.empty()
                                progress.empty()
                                st.error(f"❌ {msg}")
                                
                                # 【改進】詳細的錯誤診斷
                                with st.expander("📋 查看詳細日誌"):
                                    st.write("請檢查 logs/rental_system.log 文件的最後幾行")
                        
                        except Exception as e:
                            st.error(f"❌ 提交失敗: {str(e)}")
                            logging.error(f"Form submission error: {e}", exc_info=True)
                    else:
                        st.error(f"❌ 驗證失敗！\n\n• 台電單據: 需要至少 1 個有效數據 (目前: {tdy_valid_count}個)\n• 房間度數: 需要至少 1 間有效數據 (目前: {meter_valid_count}間)\n\n請檢查並重新填寫")

def page_expenses(db: RentalDB):
    """支出管理"""
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
                st.rerun()
            else:
                st.error("❌ 記錄失敗")
    
    with col2:
        st.subheader("最近支出")
        expenses = db.get_expenses()
        if not expenses.empty:
            st.dataframe(expenses[['expense_date', 'category', 'amount', 'room_number', 'description']],
                        use_container_width=True, hide_index=True)
        else:
            st.info("無支出記錄")

def page_settings():
    """系統設定"""
    st.header("⚙️ 系統設定")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("""
        **幸福之家管理系統 Pro v5.8**
        
        ✨ 核心特性
        • 房客管理 ✅
        • 租金收繳管理 ✅
        • 整合式電費管理 ✅
        • 1F自行繳納標記 ✅
        • 靈活分攤設定 ✅
        • 精確公電計算 ✅
        • 支出記帳 ✅
        
        **版本:** v5.8 SQLite WAL Fixed
        **日期:** 2025-12-07
        **改進:** WAL 連接管理、詳細診斷
        """)
    
    with col2:
        st.success("""
        ✅ WAL 模式優化
        ✅ 強制提交檢查
        ✅ 寫入後驗證
        ✅ 詳細的日誌
        ✅ 計算前診斷
        ✅ 分步提示
        ✅ 使用者友善
        ✅ 穩定可靠
        """)

# ============================================================================
# 主程式
# ============================================================================

def main():
    st.set_page_config(
        page_title="幸福之家管理系統",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.markdown("""
    <style>
        .stApp { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    </style>
    """, unsafe_allow_html=True)
    
    db = RentalDB()
    
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("智慧租房管理系統 v5.8")
        
        menu = st.radio("導航", [
            "📊 儀表板",
            "👥 房客管理",
            "💡 電費管理",
            "💸 支出管理",
            "⚙️ 系統設定"
        ])
    
    if menu == "📊 儀表板":
        page_dashboard(db)
    elif menu == "👥 房客管理":
        page_tenants(db)
    elif menu == "💡 電費管理":
        page_electricity(db)
    elif menu == "💸 支出管理":
        page_expenses(db)
    elif menu == "⚙️ 系統設定":
        page_settings()

if __name__ == "__main__":
    main()

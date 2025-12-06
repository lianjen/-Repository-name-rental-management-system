"""
幸福之家管理系統 Pro v5.0 - 完整電費管理版
架構: 模組化設計 (DB層 + 業務邏輯層 + UI層)
功能: 租客管理、租金收繳、電費管理、支出記帳、智能預測
特性: 電費預繳追蹤、防重複收款、性能優化、完整錯誤處理
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
# 配置日誌
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

# ============================================================================
# 1. 數據庫層 (DB)
# ============================================================================

class RentalDB:
    """數據庫操作類 - 負責所有資料讀寫"""
    
    def __init__(self, db_path: str = "rental_system_12rooms.db"):
        self.db_path = db_path
        self._init_db()
        self._create_indexes()
        self._auto_migrate()

    @contextlib.contextmanager
    def _get_connection(self):
        """獲取數據庫連接 (上下文管理器)"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化數據庫表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 租客表 (新增 base_rent 和 electricity_fee 分離)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT UNIQUE,
                    tenant_name TEXT NOT NULL,
                    phone TEXT,
                    deposit REAL,
                    base_rent REAL NOT NULL,
                    electricity_fee REAL DEFAULT 0,
                    monthly_rent REAL NOT NULL,
                    lease_start TEXT NOT NULL,
                    lease_end TEXT NOT NULL,
                    payment_method TEXT DEFAULT '月繳',
                    annual_discount_months INTEGER DEFAULT 0,
                    has_water_discount BOOLEAN DEFAULT 0,
                    prepaid_electricity REAL DEFAULT 0,
                    notes TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 繳費表 (已加唯一索引防重複)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT NOT NULL,
                    payment_schedule TEXT NOT NULL,
                    base_rent REAL DEFAULT 0,
                    electricity_fee REAL DEFAULT 0,
                    payment_amount REAL NOT NULL,
                    due_date TEXT NOT NULL,
                    payment_date TEXT NOT NULL,
                    status TEXT DEFAULT '已收',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(room_number) REFERENCES tenants(room_number)
                )
            """)
            
            # 電費預繳記錄表 (新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_prepaid (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT NOT NULL,
                    prepaid_amount REAL NOT NULL,
                    prepaid_date TEXT NOT NULL,
                    remaining_balance REAL NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(room_number) REFERENCES tenants(room_number)
                )
            """)
            
            # 電費調整記錄表 (新增)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS electricity_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT NOT NULL,
                    adjustment_month TEXT NOT NULL,
                    old_fee REAL,
                    new_fee REAL,
                    reason TEXT,
                    applied_date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(room_number) REFERENCES tenants(room_number)
                )
            """)
            
            # 支出表
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

    def _auto_migrate(self):
        """自動遷移舊版本資料庫"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # 檢查 tenants 是否有 base_rent 欄位
                cursor.execute("PRAGMA table_info(tenants)")
                cols = {row[1] for row in cursor.fetchall()}
                
                if 'base_rent' not in cols:
                    logging.info("Auto-migrating: Adding base_rent to tenants")
                    cursor.execute("ALTER TABLE tenants ADD COLUMN base_rent REAL DEFAULT 0")
                
                if 'electricity_fee' not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN electricity_fee REAL DEFAULT 0")
                
                if 'prepaid_electricity' not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN prepaid_electricity REAL DEFAULT 0")
                
                if 'updated_at' not in cols:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                
                # 遷移現有租金數據（monthly_rent → base_rent + electricity_fee）
                cursor.execute("SELECT id, monthly_rent FROM tenants WHERE base_rent = 0 AND monthly_rent > 0")
                rows = cursor.fetchall()
                for tenant_id, monthly_rent in rows:
                    # 簡單策略：電費取 monthly_rent 的 1-5%（視情況調整）
                    base_rent = monthly_rent * 0.98
                    electricity = monthly_rent - base_rent
                    cursor.execute(
                        "UPDATE tenants SET base_rent=?, electricity_fee=? WHERE id=?",
                        (base_rent, electricity, tenant_id)
                    )
                    logging.info(f"Migrated tenant {tenant_id}: base={base_rent}, elec={electricity}")
                
                # 檢查 payments 表是否有分離欄位
                cursor.execute("PRAGMA table_info(payments)")
                cols = {row[1] for row in cursor.fetchall()}
                
                if 'base_rent' not in cols:
                    cursor.execute("ALTER TABLE payments ADD COLUMN base_rent REAL DEFAULT 0")
                    cursor.execute("ALTER TABLE payments ADD COLUMN electricity_fee REAL DEFAULT 0")
                
                logging.info("Database auto-migration completed")
            except Exception as e:
                logging.warning(f"Auto-migration note: {e}")

    def _create_indexes(self):
        """建立索引提升查詢效能"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 租客索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_room ON tenants(room_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")
            
            # 繳費索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_room ON payments(room_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_due ON payments(due_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
            
            # 唯一索引：防止同房間同期間重複入帳
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_paid_unique
                ON payments(room_number, payment_schedule)
                WHERE status = '已收'
            """)
            
            # 電費索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_prepaid_room ON electricity_prepaid(room_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_elec_adjust_room ON electricity_adjustments(room_number)")
            
            # 支出索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_room ON expenses(room_number)")

    # ===== 租客操作 =====
    
    def upsert_tenant(self, room: str, name: str, phone: str, deposit: float, 
                      base_rent: float, electricity_fee: float,
                      start: str, end: str, pay_method: str, 
                      discount_months: int, has_water_discount: bool, 
                      prepaid_electricity: float, notes: str, 
                      tenant_id: Optional[int] = None) -> Tuple[bool, str]:
        """新增或更新租客 (分離基礎租金 + 電費)"""
        try:
            monthly_rent = base_rent + electricity_fee
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                if tenant_id:
                    cursor.execute("""
                        UPDATE tenants SET 
                            tenant_name=?, phone=?, deposit=?, base_rent=?, electricity_fee=?,
                            monthly_rent=?, lease_start=?, lease_end=?, payment_method=?, 
                            annual_discount_months=?, has_water_discount=?, 
                            prepaid_electricity=?, notes=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (name, phone, deposit, base_rent, electricity_fee, monthly_rent,
                          start, end, pay_method, int(discount_months), 
                          bool(has_water_discount), prepaid_electricity, notes, tenant_id))
                else:
                    cursor.execute("""
                        INSERT INTO tenants 
                        (room_number, tenant_name, phone, deposit, base_rent, electricity_fee,
                         monthly_rent, lease_start, lease_end, payment_method, 
                         annual_discount_months, has_water_discount, prepaid_electricity, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (room, name, phone, deposit, base_rent, electricity_fee, monthly_rent,
                          start, end, pay_method, int(discount_months), 
                          bool(has_water_discount), prepaid_electricity, notes))
                
                logging.info(f"{'Update' if tenant_id else 'Create'} tenant: {room} (base={base_rent}, elec={electricity_fee})")
                return True, "成功保存"
                
        except sqlite3.IntegrityError as e:
            logging.warning(f"Integrity error: {e}")
            return False, f"錯誤 (房號可能重複): {str(e)}"
        except Exception as e:
            logging.error(f"upsert_tenant error: {e}")
            return False, f"保存失敗: {str(e)}"

    def get_tenants(self, active_only: bool = True) -> pd.DataFrame:
        """獲取租客列表"""
        try:
            with self._get_connection() as conn:
                sql = "SELECT * FROM tenants"
                if active_only:
                    sql += " WHERE is_active = 1"
                sql += " ORDER BY room_number"
                
                df = pd.read_sql(sql, conn)
                
                if not df.empty:
                    df['payment_method'] = df['payment_method'].fillna('月繳')
                    df['annual_discount_months'] = df['annual_discount_months'].fillna(0).astype(int)
                    df['has_water_discount'] = df['has_water_discount'].fillna(0).astype(bool)
                    df['phone'] = df['phone'].fillna('')
                    df['notes'] = df['notes'].fillna('')
                    df['base_rent'] = df['base_rent'].fillna(0)
                    df['electricity_fee'] = df['electricity_fee'].fillna(0)
                    df['prepaid_electricity'] = df['prepaid_electricity'].fillna(0)
                
                return df
        except Exception as e:
            logging.error(f"get_tenants error: {e}")
            st.error(f"讀取租客失敗: {str(e)}")
            return pd.DataFrame()

    def get_tenant_by_id(self, tenant_id: int) -> pd.DataFrame:
        """按 ID 獲取單個租客"""
        try:
            with self._get_connection() as conn:
                return pd.read_sql("SELECT * FROM tenants WHERE id=?", conn, params=(tenant_id,))
        except Exception as e:
            logging.error(f"get_tenant_by_id error: {e}")
            return pd.DataFrame()

    def delete_tenant(self, tenant_id: int) -> Tuple[bool, str]:
        """軟刪除租客"""
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tenant_id,))
            logging.info(f"Delete tenant id: {tenant_id}")
            return True, "已刪除"
        except Exception as e:
            logging.error(f"delete_tenant error: {e}")
            return False, f"刪除失敗: {str(e)}"

    # ===== 繳費操作 =====
    
    def record_payment(self, room: str, payment_schedule: str, base_rent: float,
                      electricity_fee: float, due_date: str, status: str, 
                      notes: str) -> Tuple[bool, str]:
        """記錄租金支付 (分離基礎租金 + 電費)"""
        try:
            amount = base_rent + electricity_fee
            today = datetime.now().strftime("%Y-%m-%d")
            
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO payments 
                    (room_number, payment_schedule, base_rent, electricity_fee, 
                     payment_amount, due_date, payment_date, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (room, payment_schedule, base_rent, electricity_fee, amount, 
                      due_date, today, status, notes))
            
            logging.info(f"Record payment: {room} / {payment_schedule} / base={base_rent}, elec={electricity_fee}")
            return True, "成功記錄"
            
        except sqlite3.IntegrityError:
            logging.warning(f"Duplicate payment record: {room} / {payment_schedule}")
            return False, f"❌ 重複入帳：房{room} / {payment_schedule} 已有收款記錄"
        except Exception as e:
            logging.error(f"record_payment error: {e}")
            return False, f"記錄失敗: {str(e)}"

    def get_payment_history(self, room: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        """獲取繳費歷史"""
        try:
            with self._get_connection() as conn:
                if room:
                    sql = "SELECT * FROM payments WHERE room_number=? ORDER BY due_date DESC LIMIT ?"
                    return pd.read_sql(sql, conn, params=(room, limit))
                else:
                    sql = "SELECT * FROM payments ORDER BY due_date DESC LIMIT ?"
                    return pd.read_sql(sql, conn, params=(limit,))
        except Exception as e:
            logging.error(f"get_payment_history error: {e}")
            return pd.DataFrame()

    # ===== 電費操作 =====
    
    def add_electricity_prepaid(self, room: str, prepaid_amount: float,
                               remaining_balance: float, notes: str) -> Tuple[bool, str]:
        """記錄電費預繳"""
        try:
            prepaid_date = datetime.now().strftime("%Y-%m-%d")
            
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO electricity_prepaid 
                    (room_number, prepaid_amount, prepaid_date, remaining_balance, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (room, prepaid_amount, prepaid_date, remaining_balance, notes))
                
                # 更新租客表的預繳金額
                conn.execute("""
                    UPDATE tenants SET prepaid_electricity = ?
                    WHERE room_number = ?
                """, (remaining_balance, room))
            
            logging.info(f"Prepaid electricity: {room} / amount={prepaid_amount}")
            return True, f"成功記錄 ${prepaid_amount:,.0f} 預繳電費"
        except Exception as e:
            logging.error(f"add_electricity_prepaid error: {e}")
            return False, f"預繳失敗: {str(e)}"

    def adjust_electricity_fee(self, room: str, adjustment_month: str, old_fee: float,
                              new_fee: float, reason: str) -> Tuple[bool, str]:
        """調整電費"""
        try:
            applied_date = datetime.now().strftime("%Y-%m-%d")
            
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO electricity_adjustments 
                    (room_number, adjustment_month, old_fee, new_fee, reason, applied_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (room, adjustment_month, old_fee, new_fee, reason, applied_date))
            
            logging.info(f"Adjust electricity: {room} / {old_fee} → {new_fee} ({reason})")
            return True, f"成功調整電費: ${old_fee:,.0f} → ${new_fee:,.0f}"
        except Exception as e:
            logging.error(f"adjust_electricity_fee error: {e}")
            return False, f"調整失敗: {str(e)}"

    def get_electricity_prepaid_history(self, room: Optional[str] = None) -> pd.DataFrame:
        """獲取電費預繳歷史"""
        try:
            with self._get_connection() as conn:
                if room:
                    sql = "SELECT * FROM electricity_prepaid WHERE room_number=? ORDER BY prepaid_date DESC"
                    return pd.read_sql(sql, conn, params=(room,))
                else:
                    sql = "SELECT * FROM electricity_prepaid ORDER BY prepaid_date DESC"
                    return pd.read_sql(sql, conn)
        except Exception as e:
            logging.error(f"get_electricity_prepaid_history error: {e}")
            return pd.DataFrame()

    # ===== 支出操作 =====
    
    def add_expense(self, date_str: str, category: str, amount: float,
                   desc: str, room: str) -> Tuple[bool, str]:
        """添加支出"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO expenses (expense_date, category, amount, description, room_number)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, category, amount, desc, room))
            logging.info(f"Add expense: {category} / ${amount}")
            return True, "已記錄"
        except Exception as e:
            logging.error(f"add_expense error: {e}")
            return False, f"新增支出失敗: {str(e)}"

    def get_expenses(self, limit: int = 100) -> pd.DataFrame:
        """獲取支出列表"""
        try:
            with self._get_connection() as conn:
                return pd.read_sql(
                    "SELECT * FROM expenses ORDER BY expense_date DESC LIMIT ?",
                    conn, params=(limit,)
                )
        except Exception as e:
            logging.error(f"get_expenses error: {e}")
            return pd.DataFrame()

# ============================================================================
# 2. 業務邏輯層 (Services)
# ============================================================================

class BillingService:
    """租金計算和預測服務"""
    
    @staticmethod
    def calculate_payment_amount(base_rent: float, electricity_fee: float, 
                                payment_method: str, discount_months: int) -> float:
        """計算應繳金額 (基礎租 + 電費)"""
        monthly_total = base_rent + electricity_fee
        
        if payment_method == "月繳":
            return monthly_total
        elif payment_method == "半年繳":
            return monthly_total * 6
        elif payment_method == "年繳":
            # 年繳折扣只計算在基礎租金
            discounted_base = (base_rent * (12 - discount_months)) / 12
            return (discounted_base + electricity_fee) * 12
        
        return monthly_total

    @staticmethod
    def should_collect_this_month(lease_start: str, method: str, today: datetime) -> bool:
        """判斷本月是否應該收租"""
        try:
            start = datetime.strptime(lease_start, "%Y.%m.%d")
        except Exception:
            return False
        
        if method == "月繳":
            return True
        elif method == "半年繳":
            months_since_start = (today.year - start.year) * 12 + (today.month - start.month)
            return months_since_start >= 0 and months_since_start % 6 == 0
        elif method == "年繳":
            return today.strftime("%Y-%m") == start.strftime("%Y-%m")
        
        return False

    @staticmethod
    def build_monthly_forecast(tenants_df: pd.DataFrame, history_df: pd.DataFrame,
                              today: datetime) -> List[Dict[str, Any]]:
        """生成本月預測清單"""
        forecast = []
        month_tag = today.strftime("%Y-%m")
        
        for _, row in tenants_df.iterrows():
            method = str(row.get("payment_method", "月繳")).strip()
            discount = int(row.get("annual_discount_months", 0))
            base_rent = float(row.get("base_rent", 0))
            elec_fee = float(row.get("electricity_fee", 0))
            amount = BillingService.calculate_payment_amount(base_rent, elec_fee, method, discount)
            should_collect = BillingService.should_collect_this_month(row["lease_start"], method, today)
            
            # 檢查是否已收
            paid = False
            if history_df is not None and not history_df.empty:
                paid_records = history_df[
                    (history_df["room_number"] == row["room_number"]) &
                    (history_df["payment_schedule"].astype(str).str.contains(month_tag.split("-")[1], na=False)) &
                    (history_df["status"] == "已收")
                ]
                paid = len(paid_records) > 0
            
            timing_map = {
                "月繳": "📅 每月",
                "半年繳": "📆 簽約月/滿6月",
                "年繳": "📅 簽約月"
            }
            
            forecast.append({
                "room": row["room_number"],
                "name": row["tenant_name"],
                "method": method,
                "water": bool(row.get("has_water_discount", False)),
                "base_rent": float(base_rent),
                "electricity_fee": float(elec_fee),
                "amount": float(amount),
                "should_collect": bool(should_collect),
                "paid": bool(paid),
                "timing": timing_map.get(method, ""),
                "prepaid": float(row.get("prepaid_electricity", 0))
            })
        
        return forecast

# ============================================================================
# 3. UI 輔助函數
# ============================================================================

def display_card(title: str, value: str, delta: Optional[str] = None, 
                color: str = "blue") -> None:
    """顯示指標卡片"""
    delta_html = f"<span style='color: {'green' if delta and '+' in str(delta) else 'red'}'>{delta}</span>" if delta else ""
    border_color = {
        "blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"
    }.get(color, "#ccc")
    
    st.markdown(f"""
    <div style="background-color: white; border-left: 5px solid {border_color}; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700; margin: 5px 0;">{value}</div>
        <div style="font-size: 0.8rem;">{delta_html}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str: str) -> int:
    """計算距今天數"""
    try:
        target_date = datetime.strptime(date_str, "%Y.%m.%d").date()
        return (target_date - date.today()).days
    except Exception:
        return 999

# ============================================================================
# 4. 頁面函數
# ============================================================================

def page_dashboard(db: RentalDB) -> None:
    """儀表板頁面"""
    st.header(f"早安，管理員！ 👋")
    st.caption(f"今天是 {datetime.now().strftime('%Y年%m月%d日')}")
    
    tenants = db.get_tenants()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        occupancy = len(tenants)
        rate = (occupancy / 12) * 100
        display_card("出租率", f"{rate:.0f}%", f"{occupancy}/12 間", "blue")
    
    with col2:
        total_rent = tenants['monthly_rent'].sum() if not tenants.empty else 0
        display_card("月收租", f"${total_rent:,.0f}", f"({occupancy}間)", "green")
    
    with col3:
        total_elec = tenants['electricity_fee'].sum() if not tenants.empty else 0
        display_card("月電費預估", f"${total_elec:,.0f}", f"({occupancy}間)", "orange")
    
    with col4:
        total_prepaid = tenants['prepaid_electricity'].sum() if not tenants.empty else 0
        display_card("電費預繳餘額", f"${total_prepaid:,.0f}", "待扣除", "blue")

    st.divider()
    
    st.subheader("🏢 房源狀態監控")
    active_rooms = tenants['room_number'].tolist() if not tenants.empty else []
    
    cols = st.columns(6)
    cols2 = st.columns(6)
    
    for i, room in enumerate(ALL_ROOMS):
        target_col = cols[i] if i < 6 else cols2[i-6]
        with target_col:
            if room in active_rooms:
                t_info = tenants[tenants['room_number'] == room].iloc[0]
                days = days_until(t_info['lease_end'])
                water_tag = "💧折" if t_info['has_water_discount'] else ""
                elec_tag = f"⚡${t_info['electricity_fee']:.0f}" if t_info['electricity_fee'] > 0 else ""
                pay_method_tag = {'月繳': '📅', '半年繳': '📅📅', '年繳': '📅📅📅'}.get(t_info['payment_method'], '')
                
                st.success(f"**{room}**\n\n{t_info['tenant_name']}\n{pay_method_tag}{water_tag}{elec_tag}")
                if days < 60:
                    st.caption(f"⚠️ 剩 {days} 天")
                else:
                    st.caption("✅ 租約正常")
            else:
                st.error(f"**{room}**\n\n(空房)")

def page_tenants(db: RentalDB) -> None:
    """房客管理頁面"""
    col1, col2 = st.columns([4, 1])
    with col1:
        st.header("房客資料庫")
    with col2:
        if st.button("➕ 新增房客", type="primary", use_container_width=True):
            st.session_state.edit_mode = False
            st.session_state.edit_tenant_id = None
            st.rerun()

    tenants = db.get_tenants()
    
    if not tenants.empty:
        for idx, (_, row) in enumerate(tenants.iterrows()):
            water_badge = " 💧 含100元水費折扣" if row['has_water_discount'] else ""
            discount_badge = f" 💰 年繳折{row['annual_discount_months']}個月" if row['annual_discount_months'] > 0 else ""
            prepaid_badge = f" 📌 預繳 ${row['prepaid_electricity']:,.0f}" if row['prepaid_electricity'] > 0 else ""
            
            pay_method_badge = {
                '月繳': '📅 月繳',
                '半年繳': '📅📅 半年繳',
                '年繳': '📅📅📅 年繳'
            }.get(row['payment_method'], row['payment_method'])
            
            with st.expander(f"**{row['room_number']} - {row['tenant_name']}** ({pay_method_badge} ${row['monthly_rent']:,.0f}){water_badge}{discount_badge}{prepaid_badge}"):
                c1, c2, c3 = st.columns(3)
                
                c1.write(f"📞 {row['phone']}")
                c2.write(f"📅 到期: {row['lease_end']}")
                c1.write(f"**基礎月租:** ${row['base_rent']:,.0f}")
                c1.write(f"**月電費:** ${row['electricity_fee']:,.0f}")
                
                c2.write(f"**繳租方式:** {row['payment_method']}")
                c2.write(f"**月度應繳:** ${row['monthly_rent']:,.0f}")
                
                if row['has_water_discount']:
                    c1.write("**水費:** 已含100元折扣")
                
                if row['prepaid_electricity'] > 0:
                    c3.write(f"**預繳餘額:** ${row['prepaid_electricity']:,.0f}")
                
                b1, b2 = c3.columns(2)
                if b1.button("✏️ 編輯", key=f"edit_btn_{row['id']}"):
                    st.session_state.edit_mode = True
                    st.session_state.edit_tenant_id = row['id']
                    st.rerun()
                
                if b2.button("🗑️ 刪除", key=f"del_btn_{row['id']}"):
                    ok, msg = db.delete_tenant(row['id'])
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
    else:
        st.info("尚無租客，請點擊右上方新增。")

    st.divider()
    
    if st.session_state.edit_mode and st.session_state.edit_tenant_id:
        curr_df = db.get_tenant_by_id(st.session_state.edit_tenant_id)
        
        if curr_df.empty:
            st.error("❌ 找不到該租客資料")
        else:
            curr = curr_df.iloc[0].to_dict()
            st.subheader(f"✏️ 編輯房客 - {curr['room_number']} {curr['tenant_name']}")
            
            with st.form("edit_tenant_form"):
                c1, c2 = st.columns(2)
                
                with c1:
                    st.text_input("房號 (不可修改)", value=curr['room_number'], disabled=True)
                    name = st.text_input("姓名", value=curr['tenant_name'], key="edit_name")
                    phone = st.text_input("電話", value=str(curr['phone']) if curr['phone'] else "", key="edit_phone")
                    deposit = st.number_input("押金", value=float(curr['deposit']), key="edit_deposit")
                
                with c2:
                    base_rent = st.number_input("基礎月租金", value=float(curr['base_rent']), key="edit_base_rent")
                    electricity_fee = st.number_input("月電費估價", value=float(curr['electricity_fee']), key="edit_elec_fee")
                    
                    default_start = date.today()
                    try:
                        default_start = datetime.strptime(curr['lease_start'], "%Y.%m.%d").date()
                    except:
                        pass
                    
                    default_end = date.today() + timedelta(days=365)
                    try:
                        default_end = datetime.strptime(curr['lease_end'], "%Y.%m.%d").date()
                    except:
                        pass

                    start = st.date_input("起租日", value=default_start, key="edit_start")
                    end = st.date_input("到期日", value=default_end, key="edit_end")
                    
                    pay_method_idx = 0
                    if curr['payment_method'] in ["月繳", "半年繳", "年繳"]:
                        pay_method_idx = ["月繳", "半年繳", "年繳"].index(curr['payment_method'])
                    
                    pay_method = st.selectbox("繳費方式", ["月繳", "半年繳", "年繳"], 
                                            index=pay_method_idx, key="edit_paymethod")

                col_discount = st.columns([2, 2])
                with col_discount[0]:
                    discount_months = st.number_input(
                        "年繳折幾個月", 
                        value=int(curr['annual_discount_months']) if curr['annual_discount_months'] else 0, 
                        min_value=0, max_value=12, key="edit_discount"
                    )
                
                with col_discount[1]:
                    has_water_discount = st.checkbox(
                        "☑️ 含100元水費折扣",
                        value=bool(curr['has_water_discount']),
                        key="edit_water_discount"
                    )

                prepaid_elec = st.number_input(
                    "電費預繳餘額", 
                    value=float(curr['prepaid_electricity']) if curr['prepaid_electricity'] else 0, 
                    key="edit_prepaid_elec"
                )

                notes = st.text_area("備註", value=str(curr['notes']) if curr['notes'] else "", key="edit_notes")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    submitted = st.form_submit_button("💾 保存修改", type="primary")
                with col_btn2:
                    cancel = st.form_submit_button("❌ 取消編輯")
                
                if submitted:
                    if not name:
                        st.error("請填寫姓名")
                    else:
                        ok, msg = db.upsert_tenant(
                            curr['room_number'], name, phone, deposit, base_rent, electricity_fee,
                            start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"), 
                            pay_method, discount_months, has_water_discount, prepaid_elec, notes, 
                            st.session_state.edit_tenant_id
                        )
                        if ok:
                            st.success("✅ " + msg)
                            st.session_state.edit_mode = False
                            st.session_state.edit_tenant_id = None
                            st.rerun()
                        else:
                            st.error("❌ " + msg)
                
                if cancel:
                    st.session_state.edit_mode = False
                    st.session_state.edit_tenant_id = None
                    st.rerun()
    
    elif not st.session_state.edit_mode:
        st.subheader("➕ 新增房客")
        
        with st.form("add_tenant_form"):
            c1, c2 = st.columns(2)
            
            with c1:
                room = st.selectbox("房號", ALL_ROOMS, key="add_room")
                name = st.text_input("姓名", key="add_name")
                phone = st.text_input("電話", key="add_phone")
                deposit = st.number_input("押金", value=10000, key="add_deposit")
            
            with c2:
                base_rent = st.number_input("基礎月租金", value=6000, key="add_base_rent")
                electricity_fee = st.number_input("月電費估價", value=0, key="add_elec_fee")
                start = st.date_input("起租日", key="add_start")
                end = st.date_input("到期日", value=date.today() + timedelta(days=365), key="add_end")
                pay_method = st.selectbox("繳費方式", ["月繳", "半年繳", "年繳"], key="add_paymethod")

            col_discount = st.columns([2, 2])
            with col_discount[0]:
                discount_months = st.number_input(
                    "年繳折幾個月", value=0, min_value=0, max_value=12, key="add_discount"
                )
            
            with col_discount[1]:
                has_water_discount = st.checkbox(
                    "☑️ 含100元水費折扣", value=False, key="add_water_discount"
                )

            notes = st.text_area("備註", key="add_notes")
            
            if st.form_submit_button("✅ 新增租客", type="primary"):
                if not name:
                    st.error("請填寫姓名")
                else:
                    ok, msg = db.upsert_tenant(
                        room, name, phone, deposit, base_rent, electricity_fee,
                        start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"), 
                        pay_method, discount_months, has_water_discount, 0, notes
                    )
                    if ok:
                        st.success("✅ " + msg)
                        st.rerun()
                    else:
                        st.error("❌ " + msg)

def page_payments(db: RentalDB) -> None:
    """租金收繳頁面"""
    st.header("💰 租金收繳管理系統")
    
    tenants = db.get_tenants()
    history = db.get_payment_history(limit=200)
    
    if tenants.empty:
        st.error("❌ 請先在房客管理中新增租客")
        return

    today = datetime.now()
    forecast = BillingService.build_monthly_forecast(tenants, history, today)

    should_collect_list = [f for f in forecast if f["should_collect"]]
    paid_list = [f for f in should_collect_list if f["paid"]]
    
    total_expected = sum(f["amount"] for f in should_collect_list)
    total_base_rent = sum(f["base_rent"] for f in should_collect_list)
    total_elec = sum(f["electricity_fee"] for f in should_collect_list)
    total_collected = sum(f["amount"] for f in paid_list)
    total_unpaid = total_expected - total_collected
    rate = (total_collected / total_expected * 100) if total_expected > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("本月應收", f"${total_expected:,.0f}", f"{len(should_collect_list)} 間")
    col2.metric("本月已收", f"${total_collected:,.0f}", f"{len(paid_list)} 間")
    col3.metric("未繳金額", f"${total_unpaid:,.0f}", f"{len(should_collect_list)-len(paid_list)} 間")
    col4.metric("收繳率", f"{rate:.1f}%")

    st.divider()
    
    col_info1, col_info2 = st.columns(2)
    col_info1.info(f"📊 基礎租金: ${total_base_rent:,.0f}")
    col_info2.info(f"⚡ 月電費: ${total_elec:,.0f}")

    st.divider()
    st.subheader("📋 本月繳費狀態")

    unpaid = [f for f in should_collect_list if not f["paid"]]
    if unpaid:
        st.warning(f"🔴 待繳（{len(unpaid)} 間）")
        cols = st.columns(3)
        for i, f in enumerate(unpaid):
            with cols[i % 3]:
                water_badge = "💧" if f['water'] else ""
                st.markdown(f"""
                <div style="background-color: #ffe6e6; border-left: 4px solid #ff4444; border-radius: 8px; padding: 12px;">
                    <div style="font-weight: bold;">{f['room']} {f['name']}</div>
                    <div style="font-size: 0.85rem; color: #666;">租{f['base_rent']:.0f} + 電{f['electricity_fee']:.0f}</div>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #d32f2f;">應繳 ${f['amount']:,.0f}</div>
                </div>
                """, unsafe_allow_html=True)
        st.divider()

    if paid_list:
        st.success(f"🟢 已繳（{len(paid_list)} 間）")
        cols = st.columns(3)
        for i, f in enumerate(paid_list):
            with cols[i % 3]:
                water_badge = "💧" if f['water'] else ""
                st.markdown(f"""
                <div style="background-color: #e6ffe6; border-left: 4px solid #44ff44; border-radius: 8px; padding: 12px;">
                    <div style="font-weight: bold;">{f['room']} {f['name']}</div>
                    <div style="font-size: 0.85rem; color: #666;">租{f['base_rent']:.0f} + 電{f['electricity_fee']:.0f}</div>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #2e7d32;">✅ ${f['amount']:,.0f}</div>
                </div>
                """, unsafe_allow_html=True)
        st.divider()

    st.subheader("📝 快速記錄收租")
    
    collectible_rooms = [f["room"] for f in unpaid]
    if collectible_rooms:
        with st.form("quick_payment_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                room = st.selectbox("房號", collectible_rooms, key="quick_room")
                target = next(x for x in forecast if x["room"] == room)
            
            with col2:
                st.write(f"**基礎租:** ${target['base_rent']:,.0f}")
                st.write(f"**電費:** ${target['electricity_fee']:,.0f}")
                st.write(f"**合計:** ${target['amount']:,.0f}")
            
            with col3:
                st.write("")
                if st.form_submit_button("🎯 快速記錄", type="primary", use_container_width=True):
                    ok, msg = db.record_payment(
                        room, today.strftime("%Y-%m"), target["base_rent"], target["electricity_fee"],
                        today.strftime("%Y-%m-%d"), "已收", "快速記錄"
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
    else:
        st.info("✅ 本月無待繳房間")

    st.divider()
    
    tab1, tab2, tab3 = st.tabs(["📊 本月詳細", "⚡ 電費分析", "📜 繳費歷史"])
    
    with tab1:
        detail_data = []
        for f in forecast:
            if f['should_collect']:
                water_label = "✅ 有折" if f['water'] else "❌"
                status = "✅ 已收" if f['paid'] else "🔴 未繳"
                detail_data.append({
                    '房號': f['room'], '租客': f['name'], '繳租方式': f['method'],
                    '基礎租': f"${f['base_rent']:,.0f}", '電費': f"${f['electricity_fee']:,.0f}",
                    '合計': f"${f['amount']:,.0f}", '狀態': status
                })
        
        if detail_data:
            st.dataframe(pd.DataFrame(detail_data), width='stretch', hide_index=True)
        else:
            st.info("本月無應繳記錄")
    
    with tab2:
        st.subheader("⚡ 電費預估統計")
        elec_data = []
        for f in forecast:
            if f["electricity_fee"] > 0:
                elec_data.append({
                    '房號': f['room'],
                    '房客': f['name'],
                    '月電費': f"${f['electricity_fee']:,.0f}",
                    '預繳餘額': f"${f['prepaid']:,.0f}" if f['prepaid'] > 0 else "無"
                })
        
        if elec_data:
            st.dataframe(pd.DataFrame(elec_data), width='stretch', hide_index=True)
        else:
            st.info("無電費記錄")
    
    with tab3:
        if not history.empty:
            h_display = history.head(30).copy()
            h_display['base_rent'] = h_display['base_rent'].apply(lambda x: f"${x:,.0f}")
            h_display['electricity_fee'] = h_display['electricity_fee'].apply(lambda x: f"${x:,.0f}")
            h_display['payment_amount'] = h_display['payment_amount'].apply(lambda x: f"${x:,.0f}")
            st.dataframe(
                h_display[['room_number', 'payment_schedule', 'base_rent', 'electricity_fee', 'payment_amount', 'payment_date', 'status']],
                width='stretch', hide_index=True
            )
        else:
            st.info("尚無繳費記錄")

def page_electricity(db: RentalDB) -> None:
    """電費管理頁面"""
    st.header("⚡ 電費管理系統")
    
    tenants = db.get_tenants()
    
    if tenants.empty:
        st.error("❌ 請先在房客管理中新增租客")
        return

    tab1, tab2, tab3 = st.tabs(["📌 電費預繳", "🔄 電費調整", "📊 電費記錄"])
    
    with tab1:
        st.subheader("📌 電費預繳記錄")
        
        with st.form("prepaid_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                room = st.selectbox("房號", tenants['room_number'].tolist(), key="prepaid_room")
            
            with col2:
                prepaid_amount = st.number_input("預繳金額", value=0, min_value=0, key="prepaid_amount")
            
            with col3:
                st.write("")
                if st.form_submit_button("💾 記錄預繳", type="primary", use_container_width=True):
                    tenant = tenants[tenants['room_number'] == room].iloc[0]
                    old_prepaid = float(tenant['prepaid_electricity'])
                    new_balance = old_prepaid + prepaid_amount
                    
                    ok, msg = db.add_electricity_prepaid(
                        room, prepaid_amount, new_balance, 
                        f"預繳 ${prepaid_amount:,.0f} (新餘額: ${new_balance:,.0f})"
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        
        st.subheader("預繳歷史")
        prepaid_hist = db.get_electricity_prepaid_history()
        if not prepaid_hist.empty:
            prepaid_hist['prepaid_amount'] = prepaid_hist['prepaid_amount'].apply(lambda x: f"${x:,.0f}")
            prepaid_hist['remaining_balance'] = prepaid_hist['remaining_balance'].apply(lambda x: f"${x:,.0f}")
            st.dataframe(
                prepaid_hist[['room_number', 'prepaid_amount', 'prepaid_date', 'remaining_balance', 'notes']],
                width='stretch', hide_index=True
            )
        else:
            st.info("尚無預繳記錄")
    
    with tab2:
        st.subheader("🔄 調整房間電費")
        
        with st.form("adjust_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                room = st.selectbox("房號", tenants['room_number'].tolist(), key="adjust_room")
                tenant = tenants[tenants['room_number'] == room].iloc[0]
                old_fee = float(tenant['electricity_fee'])
            
            with col2:
                new_fee = st.number_input("新電費額度", value=old_fee, key="adjust_new_fee")
                reason = st.selectbox(
                    "調整原因",
                    ["季節變化", "冷氣清潔", "房客異動", "用電習慣", "其他"],
                    key="adjust_reason"
                )
            
            with col3:
                st.write("")
                st.write(f"**原電費:** ${old_fee:,.0f}")
                st.write(f"**新電費:** ${new_fee:,.0f}")
                st.write(f"**差異:** {'+' if new_fee > old_fee else ''}{new_fee - old_fee:,.0f}")
                
                if st.form_submit_button("✅ 確認調整", type="primary", use_container_width=True):
                    month_tag = datetime.now().strftime("%Y-%m")
                    ok, msg = db.adjust_electricity_fee(room, month_tag, old_fee, new_fee, reason)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
    
    with tab3:
        st.subheader("📊 電費統計")
        
        elec_summary = tenants[tenants['electricity_fee'] > 0][['room_number', 'tenant_name', 'electricity_fee', 'prepaid_electricity']]
        if not elec_summary.empty:
            elec_summary = elec_summary.rename(columns={
                'room_number': '房號',
                'tenant_name': '房客',
                'electricity_fee': '月電費',
                'prepaid_electricity': '預繳餘額'
            })
            elec_summary['月電費'] = elec_summary['月電費'].apply(lambda x: f"${x:,.0f}")
            elec_summary['預繳餘額'] = elec_summary['預繳餘額'].apply(lambda x: f"${x:,.0f}")
            
            st.dataframe(elec_summary, width='stretch', hide_index=True)
            
            col1, col2, col3 = st.columns(3)
            total_monthly_elec = tenants[tenants['electricity_fee'] > 0]['electricity_fee'].sum()
            total_prepaid = tenants[tenants['prepaid_electricity'] > 0]['prepaid_electricity'].sum()
            
            col1.metric("總月電費", f"${total_monthly_elec:,.0f}")
            col2.metric("總預繳餘額", f"${total_prepaid:,.0f}")
            col3.metric("電費房間數", len(elec_summary))
        else:
            st.info("尚無電費記錄")

def page_expenses(db: RentalDB) -> None:
    """支出記帳頁面"""
    st.header("💸 支出管理")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        with st.form("expense_form"):
            d = st.date_input("日期", key="exp_date")
            cat = st.selectbox("類別", ["房貸", "修繕", "水電", "網路", "稅務", "雜支"], key="exp_cat")
            amt = st.number_input("金額", min_value=0, key="exp_amt")
            room = st.selectbox("歸屬", ["公共"] + ALL_ROOMS, key="exp_room")
            desc = st.text_input("說明", key="exp_desc")
            
            if st.form_submit_button("新增支出", type="primary"):
                ok, msg = db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc, room)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    
    with col2:
        st.subheader("最近 10 筆支出")
        expenses = db.get_expenses(limit=10)
        if not expenses.empty:
            st.dataframe(expenses[['expense_date', 'category', 'amount', 'room_number', 'description']], 
                        width='stretch', hide_index=True)
        else:
            st.info("尚無支出記錄")

def page_settings() -> None:
    """系統設定頁面"""
    st.header("⚙️ 系統設定")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("系統信息")
        st.info("""
        **幸福之家管理系統 Pro v5.0**
        
        ✨ **全新電費管理**
        • 電費分離計算
        • 電費預繳追蹤
        • 電費動態調整
        • 電費統計分析
        
        🏠 **租金管理**
        • 基礎租金 + 電費分離
        • 月繳/半年繳/年繳支援
        • 年繳折扣計算
        • 智能預測清單
        
        💡 **性能優化**
        • 自動資料庫遷移
        • 防重複收款
        • SQLite WAL 模式
        • 完整日誌系統
        
        **上次更新:** 2025-12-06
        """)
    
    with col2:
        st.subheader("功能特性")
        st.success("""
        ✅ 租金與電費分離
        ✅ 電費預繳管理
        ✅ 電費調整追蹤
        ✅ 防重複入帳
        ✅ 自動資料庫遷移
        ✅ 完整錯誤處理
        ✅ 歷史記錄完整
        ✅ 性能索引優化
        """)

# ============================================================================
# 5. 主程式
# ============================================================================

def main():
    st.set_page_config(
        page_title="幸福之家管理系統 Pro",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.markdown("""
    <style>
        .stApp { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
        div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #eee; }
        .stButton button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)
    
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False
    if 'edit_tenant_id' not in st.session_state:
        st.session_state.edit_tenant_id = None

    db = RentalDB()

    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("智慧租房管理系統 Pro v5.0")
        menu = st.radio("功能導航", 
                       ["📊 總覽儀表板", "👥 房客管理", "💰 租金收繳", "⚡ 電費管理", "💸 支出記帳", "⚙️ 系統設定"], 
                       index=0)

    if menu == "📊 總覽儀表板":
        page_dashboard(db)
    elif menu == "👥 房客管理":
        page_tenants(db)
    elif menu == "💰 租金收繳":
        page_payments(db)
    elif menu == "⚡ 電費管理":
        page_electricity(db)
    elif menu == "💸 支出記帳":
        page_expenses(db)
    elif menu == "⚙️ 系統設定":
        page_settings()

if __name__ == "__main__":
    main()



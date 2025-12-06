
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date

# ============================================================================
# 1. 頁面配置與 CSS
# ============================================================================

st.set_page_config(
    page_title="幸福之家管理系統 Pro",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    
    .metric-card {
        background-color: #ffffff;
        border-left: 5px solid #ff4b4b;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }
    
    div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #eee; }
    .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)

ALL_ROOMS = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]

# ============================================================================
# 2. 數據庫邏輯
# ============================================================================

class RentalDB:
    def __init__(self, db_path="rental_system_12rooms.db"):
        self.db_path = db_path
        self.init_db()
        self.migrate_db()

    def get_connection(self):
        """獲取數據庫連接"""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        """初始化數據庫表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 租客表 (租金已包含水費)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT UNIQUE,
                    tenant_name TEXT,
                    phone TEXT,
                    deposit REAL,
                    monthly_rent REAL,
                    lease_start TEXT,
                    lease_end TEXT,
                    payment_method TEXT DEFAULT '月繳',
                    annual_discount_months INTEGER DEFAULT 0,
                    has_water_discount BOOLEAN DEFAULT 0,
                    prepaid_electricity INTEGER DEFAULT 0,
                    notes TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 繳費表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT,
                    period_year INTEGER,
                    period_month INTEGER,
                    amount_due REAL,
                    amount_paid REAL,
                    payment_date TEXT,
                    category TEXT DEFAULT '租金',
                    status TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 支出表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_date TEXT,
                    category TEXT,
                    amount REAL,
                    description TEXT,
                    room_number TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
        except Exception as e:
            pass
        finally:
            conn.close()

    def migrate_db(self):
        """確保資料庫欄位完整"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tenants'")
            if not cursor.fetchone():
                conn.close()
                return
            
            cursor.execute("PRAGMA table_info(tenants)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            
            required_cols = {
                'prepaid_electricity': 'INTEGER DEFAULT 0',
                'payment_method': "TEXT DEFAULT '月繳'",
                'annual_discount_months': 'INTEGER DEFAULT 0',
                'has_water_discount': 'BOOLEAN DEFAULT 0'
            }
            
            for col_name, col_type in required_cols.items():
                if col_name not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE tenants ADD COLUMN {col_name} {col_type}")
                    except:
                        pass
            
            conn.commit()
        except Exception as e:
            pass
        finally:
            conn.close()

    def calculate_effective_monthly_rent(self, monthly_rent, payment_method, discount_months=0):
        """計算實際月均租金 (考慮年繳折扣)"""
        if payment_method == '年繳' and discount_months > 0:
            return (monthly_rent * (12 - discount_months)) / 12
        return monthly_rent

    def upsert_tenant(self, room, name, phone, deposit, rent, start, end, pay_method, discount_months, has_water_discount, prepaid, notes, tenant_id=None):
        """新增或更新租客"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            if tenant_id:
                cursor.execute("""
                    UPDATE tenants SET room_number=?, tenant_name=?, phone=?, deposit=?, monthly_rent=?,
                    lease_start=?, lease_end=?, payment_method=?, annual_discount_months=?, has_water_discount=?, prepaid_electricity=?, notes=?
                    WHERE id=?
                """, (room, name, phone, deposit, rent, start, end, pay_method, int(discount_months), bool(has_water_discount), int(prepaid), notes, tenant_id))
            else:
                cursor.execute("""
                    INSERT INTO tenants (room_number, tenant_name, phone, deposit, monthly_rent,
                    lease_start, lease_end, payment_method, annual_discount_months, has_water_discount, prepaid_electricity, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (room, name, phone, deposit, rent, start, end, pay_method, int(discount_months), bool(has_water_discount), int(prepaid), notes))
            
            conn.commit()
            return True, "成功保存"
        except Exception as e:
            return False, f"錯誤 (可能房號重複): {str(e)}"
        finally:
            conn.close()

    def get_tenants(self, active_only=True):
        """獲取租客列表"""
        conn = self.get_connection()
        try:
            sql = "SELECT * FROM tenants"
            if active_only:
                sql += " WHERE is_active = 1"
            sql += " ORDER BY room_number"
            
            df = pd.read_sql(sql, conn)
            
            if not df.empty:
                df['payment_method'] = df['payment_method'].fillna('月繳')
                df['annual_discount_months'] = df['annual_discount_months'].fillna(0).astype(int)
                df['has_water_discount'] = df['has_water_discount'].fillna(0).astype(bool)
                df['prepaid_electricity'] = df['prepaid_electricity'].fillna(0)
                df['phone'] = df['phone'].fillna('')
                df['notes'] = df['notes'].fillna('')
            
            return df
        except Exception as e:
            st.error(f"讀取租客失敗: {str(e)}")
            return pd.DataFrame()
        finally:
            conn.close()
        
    def delete_tenant(self, tenant_id):
        """標記租客為非活躍（軟刪除）"""
        conn = self.get_connection()
        try:
            conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tenant_id,))
            conn.commit()
        except Exception as e:
            st.error(f"刪除失敗: {str(e)}")
        finally:
            conn.close()

    def record_payment(self, room, year, month, due, paid, status, notes):
        """記錄租金支付"""
        conn = self.get_connection()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            conn.execute("""
                INSERT INTO payments (room_number, period_year, period_month, amount_due, amount_paid, payment_date, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (room, year, month, due, paid, today, status, notes))
            conn.commit()
        except Exception as e:
            st.error(f"記錄支付失敗: {str(e)}")
        finally:
            conn.close()

    def get_monthly_status(self, year, month):
        """獲取月度繳費狀態"""
        tenants = self.get_tenants()
        
        if tenants.empty:
            return pd.DataFrame()
        
        conn = self.get_connection()
        try:
            payments = pd.read_sql(
                "SELECT room_number, amount_paid, status FROM payments WHERE period_year=? AND period_month=?",
                conn, params=(year, month)
            )
        except:
            payments = pd.DataFrame()
        finally:
            conn.close()
        
        merged = pd.merge(tenants, payments, on='room_number', how='left')
        merged['status'] = merged['status'].fillna('未繳')
        merged['amount_paid'] = merged['amount_paid'].fillna(0)
        
        return merged

    def add_expense(self, date_str, category, amount, desc, room):
        """添加支出"""
        conn = self.get_connection()
        try:
            conn.execute(
                "INSERT INTO expenses (expense_date, category, amount, description, room_number) VALUES (?,?,?,?,?)",
                (date_str, category, amount, desc, room)
            )
            conn.commit()
        except Exception as e:
            st.error(f"新增支出失敗: {str(e)}")
        finally:
            conn.close()

# ============================================================================
# 3. UI 輔助函數
# ============================================================================

def display_card(title, value, delta=None, color="blue"):
    """顯示指標卡片"""
    delta_html = f"<span style='color: {'green' if delta and '+' in str(delta) else 'red'}'>{delta}</span>" if delta else ""
    border_color = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}.get(color, "#ccc")
    
    st.markdown(f"""
    <div style="background-color: white; border-left: 5px solid {border_color}; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700; margin: 5px 0;">{value}</div>
        <div style="font-size: 0.8rem;">{delta_html}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str):
    """計算距今天數"""
    try:
        target_date = datetime.strptime(date_str, "%Y.%m.%d").date()
        return (target_date - date.today()).days
    except:
        return 999

# ============================================================================
# 4. 主程式
# ============================================================================

def main():
    db = RentalDB()
    
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False
    
    if 'edit_tenant_id' not in st.session_state:
        st.session_state.edit_tenant_id = None

    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("智慧租房管理系統 Pro v3.4")
        menu = st.radio("功能導航", 
                       ["📊 總覽儀表板", "👥 房客管理", "💰 租金收繳", "💸 支出記帳", "⚙️ 系統設定"], 
                       index=0)

    # --- 1. 儀表板 ---
    if menu == "📊 總覽儀表板":
        st.header(f"早安，管理員！ 👋")
        st.caption(f"今天是 {datetime.now().strftime('%Y年%m月%d日')}")
        
        tenants = db.get_tenants()
        
        # 關鍵指標
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            occupancy = len(tenants)
            rate = (occupancy / 12) * 100
            display_card("出租率", f"{rate:.0f}%", f"{occupancy}/12 間", "blue")
        
        with col2:
            total_rent = tenants['monthly_rent'].sum() if not tenants.empty else 0
            display_card("月收租", f"${total_rent:,.0f}", f"({occupancy}間)", "green")
        
        with col3:
            dep = tenants['deposit'].sum() if not tenants.empty else 0
            display_card("押金總管", f"${dep:,.0f}", "帳戶保管", "orange")
        
        with col4:
            water_discount_count = len(tenants[tenants['has_water_discount'] == True]) if not tenants.empty else 0
            display_card("折水費房間", f"{water_discount_count} 間", "含100元水費", "blue")

        st.divider()
        
        # 房間狀態網格
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
                    
                    st.success(f"**{room}**\n\n{t_info['tenant_name']}\n{water_tag}")
                    if days < 60:
                        st.caption(f"⚠️ 剩 {days} 天")
                    else:
                        st.caption("✅ 租約正常")
                else:
                    st.error(f"**{room}**\n\n(空房)")

    # --- 2. 房客管理 ---
    elif menu == "👥 房客管理":
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
                effective_rent = db.calculate_effective_monthly_rent(
                    row['monthly_rent'], 
                    row['payment_method'],
                    row['annual_discount_months']
                )
                
                water_badge = " 💧 含100元水費折扣" if row['has_water_discount'] else ""
                discount_badge = f" 💰 年繳折{row['annual_discount_months']}個月" if row['annual_discount_months'] > 0 else ""
                
                with st.expander(f"**{row['room_number']} - {row['tenant_name']}** (${effective_rent:,.0f}){water_badge}{discount_badge}"):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"📞 {row['phone']}")
                    c2.write(f"📅 到期: {row['lease_end']}")
                    c1.write(f"**月租金:** ${row['monthly_rent']:,.0f}")
                    
                    if row['has_water_discount']:
                        c2.write("**水費:** 已含100元折扣")
                    
                    b1, b2 = c3.columns(2)
                    
                    if b1.button("✏️ 編輯", key=f"edit_btn_{row['id']}"):
                        st.session_state.edit_mode = True
                        st.session_state.edit_tenant_id = row['id']
                        st.rerun()
                    
                    if b2.button("🗑️ 刪除", key=f"del_btn_{row['id']}"):
                        db.delete_tenant(row['id'])
                        st.success("已刪除")
                        st.rerun()
        else:
            st.info("尚無租客，請點擊右上方新增。")

        # 表單區域
        st.divider()
        
        if st.session_state.edit_mode:
            if st.session_state.edit_tenant_id:
                conn = db.get_connection()
                curr_df = pd.read_sql(
                    "SELECT * FROM tenants WHERE id=?",
                    conn, 
                    params=(st.session_state.edit_tenant_id,)
                )
                conn.close()
                
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
                            rent = st.number_input("月租金", value=float(curr['monthly_rent']), key="edit_rent")
                            
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

                        # 年繳折扣 + 水費折扣
                        col_discount = st.columns([2, 2])
                        with col_discount[0]:
                            discount_months = st.number_input(
                                "年繳折幾個月", 
                                value=int(curr['annual_discount_months']) if curr['annual_discount_months'] else 0, 
                                min_value=0, 
                                max_value=12,
                                key="edit_discount",
                                help="例如：年繳折1個月"
                            )
                        
                        with col_discount[1]:
                            has_water_discount = st.checkbox(
                                "☑️ 含100元水費折扣",
                                value=bool(curr['has_water_discount']),
                                key="edit_water_discount",
                                help="勾選表示租金已包含100元水費折扣優待"
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
                                success, msg = db.upsert_tenant(
                                    curr['room_number'], name, phone, deposit, rent, 
                                    start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"), 
                                    pay_method, discount_months, has_water_discount, 0, notes, 
                                    st.session_state.edit_tenant_id
                                )
                                if success:
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
        else:
            # 新增模式
            st.subheader("➕ 新增房客")
            
            with st.expander("📖 水費折扣說明", expanded=False):
                st.markdown("""
                ### 💧 水費計價方式
                
                **基礎價格 (含100元水費)：**
                - **折水費房間** → 月租 **4,000 元** (包含100元水費折扣)
                - **不折水費房間** → 月租 **4,100 元** (包含100元水費正常價)
                
                **實例：**
                - 房 2B (王程)：月租 4,000 元 (已折100元水費)
                - 房 3A (焦嵒)：月租 4,100 元 (未折水費)
                - 房 3B (林庭義)：月租 4,000 元 (已折水費，年繳)
                
                **勾選說明：**
                ☑️ 表示該房間租金中已包含100元水費的優待折扣
                """)
            
            with st.form("add_tenant_form"):
                c1, c2 = st.columns(2)
                
                with c1:
                    room = st.selectbox("房號", ALL_ROOMS, key="add_room")
                    name = st.text_input("姓名", key="add_name")
                    phone = st.text_input("電話", key="add_phone")
                    deposit = st.number_input("押金", value=10000, key="add_deposit")
                
                with c2:
                    rent = st.number_input("月租金", value=6000, key="add_rent")
                    start = st.date_input("起租日", key="add_start")
                    end = st.date_input("到期日", value=date.today() + timedelta(days=365), key="add_end")
                    pay_method = st.selectbox("繳費方式", ["月繳", "半年繳", "年繳"], key="add_paymethod")

                # 年繳折扣 + 水費折扣
                col_discount = st.columns([2, 2])
                with col_discount[0]:
                    discount_months = st.number_input(
                        "年繳折幾個月", 
                        value=0, 
                        min_value=0, 
                        max_value=12,
                        key="add_discount",
                        help="例如：年繳折1個月"
                    )
                
                with col_discount[1]:
                    has_water_discount = st.checkbox(
                        "☑️ 含100元水費折扣",
                        value=False,
                        key="add_water_discount",
                        help="勾選表示租金已包含100元水費折扣優待"
                    )

                notes = st.text_area("備註", key="add_notes")
                
                if st.form_submit_button("✅ 新增租客", type="primary"):
                    if not name:
                        st.error("請填寫姓名")
                    else:
                        success, msg = db.upsert_tenant(
                            room, name, phone, deposit, rent, 
                            start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"), 
                            pay_method, discount_months, has_water_discount, 0, notes
                        )
                        if success:
                            st.success("✅ " + msg)
                            st.rerun()
                        else:
                            st.error("❌ " + msg)

    # --- 3. 租金收繳 ---
    elif menu == "💰 租金收繳":
        st.header("租金收繳中心")
        c1, c2 = st.columns(2)
        
        with c1:
            y = st.number_input("年份", value=datetime.now().year, key="pay_year")
        with c2:
            m = st.number_input("月份", value=datetime.now().month, min_value=1, max_value=12, key="pay_month")
        
        status_df = db.get_monthly_status(y, m)
        
        tab1, tab2 = st.tabs(["🔴 待收帳款", "🟢 已收帳款"])
        
        with tab1:
            if not status_df.empty:
                unpaid = status_df[status_df['status'] != '已收']
                
                if unpaid.empty:
                    st.balloons()
                    st.success("本月租金已全數收齊！")
                else:
                    st.write(f"尚有 {len(unpaid)} 筆未入帳")
                    
                    for idx, (_, row) in enumerate(unpaid.iterrows()):
                        with st.container():
                            cols = st.columns([1, 2, 2, 2])
                            cols[0].markdown(f"### {row['room_number']}")
                            cols[1].write(f"**{row['tenant_name']}**")
                            
                            base_rent = row['monthly_rent']
                            if row['annual_discount_months'] > 0:
                                base_rent = (row['monthly_rent'] * (12 - row['annual_discount_months'])) / 12
                            
                            expected = base_rent
                            if row['payment_method'] == '半年繳':
                                expected *= 6
                            elif row['payment_method'] == '年繳':
                                expected *= 12
                            
                            water_note = "(含水費折扣)" if row['has_water_discount'] else ""
                            cols[2].write(f"應收: **${expected:,.0f}** {water_note}")
                            
                            if cols[3].button("💰 收款", key=f"pay_{row['room_number']}_{idx}"):
                                db.record_payment(row['room_number'], y, m, expected, expected, "已收", "快速入帳")
                                st.success("已記錄")
                                st.rerun()
                            
                            st.divider()
            else:
                st.warning("請先建立租客資料")

        with tab2:
            if not status_df.empty:
                paid = status_df[status_df['status'] == '已收']
                if not paid.empty:
                    st.dataframe(paid[['room_number', 'tenant_name', 'amount_paid']], width='stretch')
                else:
                    st.info("本月暫無已收帳款")

    # --- 4. 支出記帳 ---
    elif menu == "💸 支出記帳":
        st.header("支出管理")
        col1, col2 = st.columns([1, 2])
        
        with col1:
            with st.form("expense_form"):
                d = st.date_input("日期", key="exp_date")
                cat = st.selectbox("類別", ["房貸", "修繕", "水電", "網路", "稅務", "雜支"], key="exp_cat")
                amt = st.number_input("金額", min_value=0, key="exp_amt")
                room = st.selectbox("歸屬", ["公共"] + ALL_ROOMS, key="exp_room")
                desc = st.text_input("說明", key="exp_desc")
                
                if st.form_submit_button("新增支出", type="primary"):
                    db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc, room)
                    st.success("已記錄")
                    st.rerun()
        
        with col2:
            st.subheader("最近 10 筆支出")
            conn = db.get_connection()
            try:
                df = pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT 10", conn)
                if not df.empty:
                    st.dataframe(df[['expense_date', 'category', 'amount', 'room_number', 'description']], width='stretch')
                else:
                    st.info("尚無支出記錄")
            except:
                st.info("查詢支出記錄失敗")
            finally:
                conn.close()

    # --- 5. 系統設定 ---
    elif menu == "⚙️ 系統設定":
        st.header("系統設定")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("系統信息")
            st.info("""
            **幸福之家管理系統 Pro v3.4**
            
            • 12房間管理模式
            • ✨ 支持年繳折扣計算
            • 💧 水費已包含在租金中
            • SQLite3 本地數據庫
            
            **上次更新:** 2025-12-06
            """)
        
        with col2:
            st.subheader("功能特性")
            st.success("""
            ✅ 完整的資料庫遷移機制
            ✅ Null 值防護
            ✅ 年繳折扣自動計算
            ✅ 水費折扣标記
            ✅ Session State 狀態管理
            ✅ 異常處理完整
            """)
        
        with st.expander("💧 水費計價說明"):
            st.markdown("""
            ### 水費包含在租金裡面
            
            本系統中，水費已經包含在月租金中。您只需要在新增或編輯房客時，勾選「☑️ 含100元水費折扣」即可。
            
            **示例：**
            
            | 房號 | 租客 | 是否折水費 | 月租金 | 說明 |
            |------|------|----------|--------|------|
            | 2B | 王程 | ✅ 有折扣 | 4,000 | 租金4000包含100元水費折扣 |
            | 3A | 焦嵒 | ❌ 無折扣 | 4,100 | 租金4100包含100元水費正常價 |
            | 3B | 林庭義 | ✅ 有折扣 | 4,000 | 租金4000，年繳優待 |
            
            ### 收租時
            
            - 直接按該房間的月租金收，**不需另外計算水費**
            - 系統會自動在「本月預測」顯示折扣標記
            """)

if __name__ == "__main__":
    main()


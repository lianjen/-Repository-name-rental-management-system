
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date
import calendar

# ============================================================================
# 1. 核心配置與 CSS 美化
# ============================================================================

st.set_page_config(
    page_title="幸福之家管理系統 Pro",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 定義 12 間房間
ALL_ROOMS = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]

st.markdown("""
<style>
    /* 全局字體與背景 */
    .stApp { font-family: 'Microsoft JhengHei', 'Segoe UI', sans-serif; background-color: #f8f9fa; }
    
    /* 指標卡片 */
    .metric-card {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        border-left: 5px solid #ccc;
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    
    /* 狀態標籤 */
    .status-badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }
    .status-due { background-color: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }
    .status-ok { background-color: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
    
    /* 表格優化 */
    div[data-testid="stDataFrame"] { border-radius: 8px; border: 1px solid #e0e0e0; background: white; }
    
    /* 按鈕樣式 */
    .stButton button { font-weight: bold; border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# 2. 數據庫邏輯 (增強版)
# ============================================================================

class RentalDB:
    def __init__(self, db_path="rental_system_v4.db"):
        self.db_path = db_path
        self.init_db()
        self.migrate_db()

    def get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()
        
        # 租客表 (新增 next_payment_date 用於智能追蹤)
        c.execute("""
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
                next_payment_date TEXT, 
                annual_discount_months INTEGER DEFAULT 0,
                has_water_discount BOOLEAN DEFAULT 0,
                notes TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 繳費紀錄
        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT,
                amount REAL,
                period_start TEXT,
                period_end TEXT,
                payment_date TEXT,
                status TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 支出紀錄
        c.execute("""
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
        conn.close()

    def migrate_db(self):
        """資料庫結構升級，確保舊資料兼容"""
        conn = self.get_conn()
        c = conn.cursor()
        try:
            # 檢查並新增 next_payment_date
            c.execute("PRAGMA table_info(tenants)")
            cols = [row[1] for row in c.fetchall()]
            
            if 'next_payment_date' not in cols:
                c.execute("ALTER TABLE tenants ADD COLUMN next_payment_date TEXT")
            if 'payment_method' not in cols:
                c.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
            if 'annual_discount_months' not in cols:
                c.execute("ALTER TABLE tenants ADD COLUMN annual_discount_months INTEGER DEFAULT 0")
            if 'has_water_discount' not in cols:
                c.execute("ALTER TABLE tenants ADD COLUMN has_water_discount BOOLEAN DEFAULT 0")
                
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    # --- 租客管理 ---
    def upsert_tenant(self, data, t_id=None):
        conn = self.get_conn()
        try:
            # 如果是新增，且沒有指定 next_payment_date，預設為起租日
            if not data.get('next_payment_date'):
                data['next_payment_date'] = data['lease_start']

            if t_id:
                conn.execute("""
                    UPDATE tenants SET room_number=?, tenant_name=?, phone=?, deposit=?, monthly_rent=?,
                    lease_start=?, lease_end=?, payment_method=?, next_payment_date=?, 
                    annual_discount_months=?, has_water_discount=?, notes=?
                    WHERE id=?
                """, (data['room'], data['name'], data['phone'], data['deposit'], data['rent'],
                      data['start'], data['end'], data['method'], data['next_pay'], 
                      data['discount'], data['water'], data['notes'], t_id))
            else:
                conn.execute("""
                    INSERT INTO tenants (room_number, tenant_name, phone, deposit, monthly_rent,
                    lease_start, lease_end, payment_method, next_payment_date, 
                    annual_discount_months, has_water_discount, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (data['room'], data['name'], data['phone'], data['deposit'], data['rent'],
                      data['start'], data['end'], data['method'], data['next_pay'], 
                      data['discount'], data['water'], data['notes']))
            conn.commit()
            return True, "保存成功"
        except Exception as e:
            return False, f"保存失敗: {str(e)}"
        finally:
            conn.close()

    def get_tenants(self, active_only=True):
        conn = self.get_conn()
        sql = "SELECT * FROM tenants"
        if active_only: sql += " WHERE is_active = 1"
        sql += " ORDER BY room_number"
        df = pd.read_sql(sql, conn)
        conn.close()
        return df

    def delete_tenant(self, t_id):
        conn = self.get_conn()
        conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (t_id,))
        conn.commit()
        conn.close()

    # --- 核心邏輯: 繳費與日期推算 ---
    def calculate_due_amount(self, rent, method, discount_months):
        """計算應繳金額"""
        rent = float(rent)
        if method == '月繳': return rent
        if method == '半年繳': return rent * 6
        if method == '年繳': 
            months_to_pay = 12 - int(discount_months)
            return rent * months_to_pay
        return rent

    def record_payment(self, t_id, amount, current_next_date, method):
        """記錄繳費並推算下一次繳費日"""
        conn = self.get_conn()
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            
            # 1. 計算新的下次繳費日
            curr_date = datetime.strptime(current_next_date, "%Y-%m-%d")
            next_date = curr_date
            
            if method == '月繳':
                # 加一個月
                month = curr_date.month - 1 + 1
                year = curr_date.year + month // 12
                month = month % 12 + 1
                try:
                    next_date = curr_date.replace(year=year, month=month)
                except ValueError:
                    # 處理 1/31 加一個月變 2/28 的情況
                    next_date = curr_date.replace(year=year, month=month, day=1) + timedelta(days=-1)
                    
            elif method == '半年繳':
                next_date = curr_date + timedelta(days=182) # 近似半年
            elif method == '年繳':
                next_date = curr_date.replace(year=curr_date.year + 1)

            next_date_str = next_date.strftime("%Y-%m-%d")

            # 2. 寫入繳費紀錄
            conn.execute("""
                INSERT INTO payments (room_number, amount, period_start, period_end, payment_date, status, notes)
                VALUES ((SELECT room_number FROM tenants WHERE id=?), ?, ?, ?, ?, '已收', '系統自動入帳')
            """, (t_id, amount, current_next_date, next_date_str, today_str))

            # 3. 更新租客的 next_payment_date
            conn.execute("UPDATE tenants SET next_payment_date=? WHERE id=?", (next_date_str, t_id))
            
            conn.commit()
            return True, f"入帳成功！下期繳費日更新為: {next_date_str}"
        except Exception as e:
            return False, f"錯誤: {str(e)}"
        finally:
            conn.close()

    # --- 財務與支出 ---
    def add_expense(self, date_str, cat, amt, desc, room):
        conn = self.get_conn()
        conn.execute("INSERT INTO expenses (expense_date, category, amount, description, room_number) VALUES (?,?,?,?,?)",
                     (date_str, cat, amt, desc, room))
        conn.commit()
        conn.close()

    def get_monthly_summary(self, year, month):
        conn = self.get_conn()
        # 收入
        month_str = f"{year}-{month:02d}"
        income = pd.read_sql("SELECT SUM(amount) as total FROM payments WHERE strftime('%Y-%m', payment_date)=?", conn, params=(month_str,))
        # 支出
        expense = pd.read_sql("SELECT SUM(amount) as total FROM expenses WHERE strftime('%Y-%m', expense_date)=?", conn, params=(month_str,))
        conn.close()
        return (income.iloc[0]['total'] or 0), (expense.iloc[0]['total'] or 0)

# ============================================================================
# 3. UI 輔助元件
# ============================================================================

def card_component(title, value, subtext="", color="#4c6ef5"):
    st.markdown(f"""
    <div class="metric-card" style="border-left-color: {color};">
        <div style="color: #6c757d; font-size: 0.9rem; font-weight: 600;">{title}</div>
        <div style="color: #212529; font-size: 1.8rem; font-weight: 700; margin: 5px 0;">{value}</div>
        <div style="color: {color}; font-size: 0.8rem;">{subtext}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str):
    if not date_str: return 999
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d - date.today()).days
    except:
        # 嘗試處理另一種格式
        try:
            d = datetime.strptime(date_str, "%Y.%m.%d").date()
            return (d - date.today()).days
        except:
            return 999

# ============================================================================
# 4. 主程式邏輯
# ============================================================================

def main():
    db = RentalDB()
    
    # 初始化 Session State
    if 'edit_id' not in st.session_state: st.session_state.edit_id = None
    if 'page_mode' not in st.session_state: st.session_state.page_mode = 'view'

    # --- 側邊欄 ---
    with st.sidebar:
        st.title("🏠 幸福之家 Pro")
        st.write(f"📅 今天: {date.today().strftime('%Y-%m-%d')}")
        st.divider()
        menu = st.radio("功能選單", ["📊 儀表板", "💰 租金收繳", "👥 房客管理", "💸 支出記帳", "⚙️ 設定"], index=0)
        st.divider()
        st.info("💡 系統提示\n\n繳費日期會根據租客設定自動推算，不再需要手動檢查月份。")

    # --- 1. 儀表板 Dashboard ---
    if menu == "📊 儀表板":
        st.header("營運總覽")
        
        tenants = db.get_tenants()
        now = datetime.now()
        inc, exp = db.get_monthly_summary(now.year, now.month)
        
        # 指標區
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            occupancy = len(tenants)
            card_component("出租率", f"{occupancy}/12 間", f"{int(occupancy/12*100)}%", "#4c6ef5")
        with c2:
            card_component("本月實收", f"${inc:,.0f}", "現金流", "#40c057")
        with c3:
            card_component("本月支出", f"${exp:,.0f}", f"淨利: ${inc-exp:,.0f}", "#fa5252")
        with c4:
            # 計算欠費/即將到期
            overdue = 0
            for _, t in tenants.iterrows():
                if days_until(t['next_payment_date']) <= 0:
                    overdue += 1
            card_component("待繳/逾期", f"{overdue} 戶", "請留意催款", "#fab005" if overdue>0 else "#40c057")

        st.subheader("🏢 房間狀態矩陣")
        
        # 繪製 12 宮格
        cols = st.columns(6)
        cols2 = st.columns(6)
        
        active_map = {row['room_number']: row for _, row in tenants.iterrows()}
        
        for i, room in enumerate(ALL_ROOMS):
            target_col = cols[i] if i < 6 else cols2[i-6]
            with target_col:
                if room in active_map:
                    t = active_map[room]
                    # 判斷狀態
                    lease_days = days_until(t['lease_end'])
                    pay_days = days_until(t['next_payment_date'])
                    
                    bg_color = "#e8f5e9" # Green (Safe)
                    status_icon = "🟢"
                    msg = "正常"
                    
                    if pay_days < 0:
                        bg_color = "#ffebee" # Red (Overdue)
                        status_icon = "🔴"
                        msg = "逾期"
                    elif pay_days <= 7:
                        bg_color = "#fff3e0" # Orange (Due soon)
                        status_icon = "🟠"
                        msg = "繳費"
                    
                    if lease_days < 30:
                        msg = "租約到期"
                        status_icon = "⚠️"

                    st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #ddd; margin-bottom: 10px;">
                        <div style="font-weight: bold; font-size: 1.1em;">{room}</div>
                        <div style="font-size: 0.8em; color: #555;">{t['tenant_name']}</div>
                        <div style="font-size: 0.9em; margin-top: 5px;">{status_icon} {msg}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="background-color: #f1f3f5; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #ddd; margin-bottom: 10px; opacity: 0.7;">
                        <div style="font-weight: bold; font-size: 1.1em; color: #adb5bd;">{room}</div>
                        <div style="font-size: 0.8em; color: #adb5bd;">(空房)</div>
                        <div style="font-size: 0.9em; margin-top: 5px;">⚪ 待租</div>
                    </div>
                    """, unsafe_allow_html=True)

    # --- 2. 租金收繳 (核心功能) ---
    elif menu == "💰 租金收繳":
        st.header("租金收繳中心")
        
        tenants = db.get_tenants()
        if tenants.empty:
            st.info("尚無租客資料")
        else:
            # 分類租客狀態
            due_list = [] # 應繳
            future_list = [] # 未來
            
            for _, t in tenants.iterrows():
                days = days_until(t['next_payment_date'])
                amount = db.calculate_due_amount(t['monthly_rent'], t['payment_method'], t['annual_discount_months'])
                
                info = {
                    'id': t['id'],
                    'room': t['room_number'],
                    'name': t['tenant_name'],
                    'date': t['next_payment_date'],
                    'days': days,
                    'amount': amount,
                    'method': t['payment_method'],
                    'water': t['has_water_discount']
                }
                
                if days <= 7: # 7天內到期或已逾期
                    due_list.append(info)
                else:
                    future_list.append(info)

            # 顯示應繳清單
            st.subheader(f"🔴 待處理款項 ({len(due_list)})")
            if due_list:
                for item in due_list:
                    with st.container():
                        # 使用 HTML 製作卡片
                        bg = "#ffebee" if item['days'] < 0 else "#fff3e0"
                        status_text = f"逾期 {abs(item['days'])} 天" if item['days'] < 0 else f"剩 {item['days']} 天"
                        water_tag = "💧含水費" if item['water'] else ""
                        
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 1.5])
                        with c1:
                            st.markdown(f"### {item['room']}")
                        with c2:
                            st.write(f"**{item['name']}**")
                            st.caption(f"{item['method']} {water_tag}")
                        with c3:
                            st.markdown(f"<span style='color:red; font-weight:bold; font-size:1.1em'>${item['amount']:,.0f}</span>", unsafe_allow_html=True)
                            st.caption(f"期限: {item['date']} ({status_text})")
                        with c4:
                            if st.button("💰 收款入帳", key=f"pay_{item['id']}", type="primary"):
                                success, msg = db.record_payment(item['id'], item['amount'], item['date'], item['method'])
                                if success:
                                    st.toast(f"✅ {item['room']} {msg}")
                                    st.rerun()
                                else:
                                    st.error(msg)
                        st.divider()
            else:
                st.success("🎉 目前沒有急需處理的款項！")

            # 顯示未來清單
            with st.expander(f"🟢 未來待繳清單 ({len(future_list)})"):
                if future_list:
                    f_df = pd.DataFrame(future_list)
                    f_df['amount'] = f_df['amount'].apply(lambda x: f"${x:,.0f}")
                    st.dataframe(
                        f_df[['room', 'name', 'date', 'amount', 'method']],
                        column_config={
                            "room": "房號", "name": "姓名", "date": "下次繳費日",
                            "amount": "應繳金額", "method": "方式"
                        },
                        use_container_width=True,
                        hide_index=True
                    )

    # --- 3. 房客管理 ---
    elif menu == "👥 房客管理":
        col1, col2 = st.columns([4, 1])
        with col1: st.header("房客資料庫")
        with col2: 
            if st.button("➕ 新增房客", type="primary", use_container_width=True):
                st.session_state.edit_id = None
                st.session_state.page_mode = 'edit'
                st.rerun()

        # 編輯/新增模式
        if st.session_state.page_mode == 'edit':
            st.markdown("### 📝 編輯/新增資料")
            
            # 獲取預設值
            default_data = {}
            if st.session_state.edit_id:
                raw = db.get_tenants()
                default_data = raw[raw['id'] == st.session_state.edit_id].iloc[0].to_dict()
            
            with st.form("tenant_form"):
                c1, c2 = st.columns(2)
                with c1:
                    # 房號處理
                    idx = 0
                    if default_data.get('room_number') in ALL_ROOMS:
                        idx = ALL_ROOMS.index(default_data.get('room_number'))
                    room = st.selectbox("房號", ALL_ROOMS, index=idx)
                    
                    name = st.text_input("姓名", value=default_data.get('tenant_name', ''))
                    phone = st.text_input("電話", value=default_data.get('phone', ''))
                    deposit = st.number_input("押金", value=float(default_data.get('deposit', 10000)), step=1000.0)
                
                with c2:
                    rent = st.number_input("月租金", value=float(default_data.get('monthly_rent', 6000)), step=100.0)
                    # 日期處理
                    d_start = datetime.strptime(default_data['lease_start'], "%Y-%m-%d").date() if default_data.get('lease_start') else date.today()
                    try:
                        d_end = datetime.strptime(default_data['lease_end'], "%Y-%m-%d").date() if default_data.get('lease_end') else date.today() + timedelta(days=365)
                    except:
                        d_end = date.today() + timedelta(days=365)

                    start = st.date_input("起租日", value=d_start)
                    end = st.date_input("到期日", value=d_end)
                    
                    m_idx = ["月繳", "半年繳", "年繳"].index(default_data.get('payment_method', '月繳'))
                    method = st.selectbox("繳費方式", ["月繳", "半年繳", "年繳"], index=m_idx)
                
                # 進階選項
                with st.expander("進階設定 (折扣/水費/下次繳費日)", expanded=True):
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        discount = st.number_input("年繳折扣月數", value=int(default_data.get('annual_discount_months', 0)))
                    with ec2:
                        water = st.checkbox("含水費優惠", value=bool(default_data.get('has_water_discount', False)))
                    with ec3:
                        # 允許手動調整下次繳費日
                        try:
                            d_next = datetime.strptime(default_data.get('next_payment_date', start.strftime("%Y-%m-%d")), "%Y-%m-%d").date()
                        except:
                            d_next = start
                        next_pay = st.date_input("下次繳費日 (重要)", value=d_next, help="系統會依此日期判斷是否逾期")

                notes = st.text_area("備註", value=default_data.get('notes', ''))
                
                col_b1, col_b2 = st.columns([1, 1])
                with col_b1:
                    if st.form_submit_button("💾 保存", type="primary", use_container_width=True):
                        # 整理數據
                        save_data = {
                            'room': room, 'name': name, 'phone': phone, 'deposit': deposit,
                            'rent': rent, 'start': start.strftime("%Y-%m-%d"), 'end': end.strftime("%Y-%m-%d"),
                            'method': method, 'discount': discount, 'water': water, 'notes': notes,
                            'next_pay': next_pay.strftime("%Y-%m-%d")
                        }
                        success, msg = db.upsert_tenant(save_data, st.session_state.edit_id)
                        if success:
                            st.success(msg)
                            st.session_state.page_mode = 'view'
                            st.session_state.edit_id = None
                            st.rerun()
                        else:
                            st.error(msg)
                with col_b2:
                    if st.form_submit_button("❌ 取消", use_container_width=True):
                        st.session_state.page_mode = 'view'
                        st.session_state.edit_id = None
                        st.rerun()
            st.divider()

        # 列表模式
        tenants = db.get_tenants()
        if not tenants.empty:
            for _, row in tenants.iterrows():
                # 計算應繳顯示
                amt = db.calculate_due_amount(row['monthly_rent'], row['payment_method'], row['annual_discount_months'])
                
                with st.expander(f"**{row['room_number']} {row['tenant_name']}** - {row['payment_method']} ${amt:,.0f}"):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"📞 {row['phone']}")
                    c1.write(f"📅 租期: {row['lease_end']}")
                    
                    c2.write(f"💰 押金: ${row['deposit']:,.0f}")
                    c2.write(f"⏰ 下次繳費: **{row['next_payment_date']}**")
                    
                    c3.write(f"📝 {row['notes']}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("✏️ 編輯", key=f"e_{row['id']}"):
                        st.session_state.edit_id = row['id']
                        st.session_state.page_mode = 'edit'
                        st.rerun()
                    
                    if b2.button("🗑️ 退租", key=f"d_{row['id']}"):
                        db.delete_tenant(row['id'])
                        st.success("已退租")
                        st.rerun()

    # --- 4. 支出記帳 ---
    elif menu == "💸 支出記帳":
        st.header("支出管理")
        
        with st.form("exp_form"):
            c1, c2, c3 = st.columns(3)
            with c1: d = st.date_input("日期")
            with c2: cat = st.selectbox("類別", ["房貸", "維修", "水電", "網路", "稅務", "雜支"])
            with c3: r = st.selectbox("歸屬", ["公共"] + ALL_ROOMS)
            
            c4, c5 = st.columns([1, 2])
            with c4: amt = st.number_input("金額", min_value=0, step=100)
            with c5: desc = st.text_input("說明")
            
            if st.form_submit_button("➕ 記錄支出", type="primary"):
                db.add_expense(d.strftime("%Y-%m-%d"), cat, amt, desc, r)
                st.success("已儲存")
                st.rerun()
        
        st.subheader("近期支出明細")
        conn = db.get_conn()
        df = pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT 20", conn)
        conn.close()
        
        if not df.empty:
            st.dataframe(
                df[['expense_date', 'category', 'room_number', 'amount', 'description']],
                column_config={
                    "expense_date": "日期", "category": "類別", "room_number": "房號",
                    "amount": st.column_config.NumberColumn("金額", format="$%d"),
                    "description": "說明"
                },
                use_container_width=True, hide_index=True
            )

    # --- 5. 設定 ---
    elif menu == "⚙️ 設定":
        st.header("系統設定")
        st.info("資料庫路徑: rental_system_v4.db")
        
        with st.expander("功能說明"):
            st.markdown("""
            **關於繳費邏輯**
            1. 系統依據 `next_payment_date` (下次繳費日) 來判斷是否逾期。
            2. 當您點擊「收款入帳」時，系統會自動：
               - 產生一筆收入紀錄
               - 自動將 `next_payment_date` 往後推算 (月繳+1月, 半年繳+6月, 年繳+1年)
            """)

if __name__ == "__main__":
    main()


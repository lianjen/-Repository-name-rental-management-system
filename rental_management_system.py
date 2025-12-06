
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date
import calendar

# ============================================================================
# 1. 頁面配置與 CSS 樣式優化
# ============================================================================

st.set_page_config(
    page_title="幸福之家管理系統 Pro",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定義 CSS 以美化介面
st.markdown("""
<style>
    /* 全局字體優化 */
    .stApp {
        font-family: 'Microsoft JhengHei', sans-serif;
    }
    
    /* 資訊卡片樣式 */
    .metric-card {
        background-color: #ffffff;
        border-left: 5px solid #ff4b4b;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }
    .metric-title {
        color: #666;
        font-size: 0.9em;
        font-weight: bold;
    }
    .metric-value {
        color: #333;
        font-size: 1.8em;
        font-weight: bold;
        margin: 5px 0;
    }
    .metric-delta {
        font-size: 0.8em;
    }
    
    /* 狀態標籤 */
    .status-badge {
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: bold;
    }
    .status-ok { background-color: #d4edda; color: #155724; }
    .status-warning { background-color: #fff3cd; color: #856404; }
    .status-danger { background-color: #f8d7da; color: #721c24; }
    
    /* 表格優化 */
    div[data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
        border: 1px solid #eee;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# 2. 數據庫核心邏輯 (保持穩定性，增強查詢功能)
# ============================================================================

class RentalDB:
    def __init__(self, db_path="rental_system_pro.db"):
        self.db_path = db_path
        self.init_db()
        self.migrate_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 租客表
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
                prepaid_electricity INTEGER DEFAULT 0,
                notes TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 繳費記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT,
                period_year INTEGER,
                period_month INTEGER,
                amount_due REAL,
                amount_paid REAL,
                payment_date TEXT,
                category TEXT DEFAULT '租金', -- 租金, 電費, 押金
                status TEXT, -- 已繳, 未繳, 部分
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
        conn.close()

    def migrate_db(self):
        """簡單的遷移邏輯，確保欄位存在"""
        conn = self.get_connection()
        try:
            # 嘗試查詢新欄位，若失敗則添加
            conn.execute("SELECT payment_method FROM tenants LIMIT 1")
        except:
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN payment_method TEXT DEFAULT '月繳'")
                conn.execute("ALTER TABLE tenants ADD COLUMN prepaid_electricity INTEGER DEFAULT 0")
            except:
                pass
        conn.close()

    # --- 租客相關 ---
    def upsert_tenant(self, room, name, phone, deposit, rent, start, end, pay_method, prepaid, notes, tenant_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if tenant_id: # Update
                cursor.execute("""
                    UPDATE tenants SET room_number=?, tenant_name=?, phone=?, deposit=?, monthly_rent=?,
                    lease_start=?, lease_end=?, payment_method=?, prepaid_electricity=?, notes=?
                    WHERE id=?
                """, (room, name, phone, deposit, rent, start, end, pay_method, prepaid, notes, tenant_id))
            else: # Insert
                cursor.execute("""
                    INSERT INTO tenants (room_number, tenant_name, phone, deposit, monthly_rent,
                    lease_start, lease_end, payment_method, prepaid_electricity, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (room, name, phone, deposit, rent, start, end, pay_method, prepaid, notes))
            conn.commit()
            return True, "成功保存"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_tenants(self, active_only=True):
        conn = self.get_connection()
        sql = "SELECT * FROM tenants"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY room_number"
        df = pd.read_sql(sql, conn)
        conn.close()
        return df
        
    def delete_tenant(self, tenant_id):
        conn = self.get_connection()
        conn.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tenant_id,))
        conn.commit()
        conn.close()

    # --- 財務相關 ---
    def record_payment(self, room, year, month, due, paid, status, notes):
        conn = self.get_connection()
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO payments (room_number, period_year, period_month, amount_due, amount_paid, payment_date, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (room, year, month, due, paid, today, status, notes))
        conn.commit()
        conn.close()

    def get_monthly_status(self, year, month):
        """獲取某月的收租狀態，並結合租客表"""
        tenants = self.get_tenants()
        conn = self.get_connection()
        payments = pd.read_sql("""
            SELECT room_number, amount_paid, status 
            FROM payments 
            WHERE period_year=? AND period_month=?
        """, conn, params=(year, month))
        conn.close()
        
        if tenants.empty:
            return pd.DataFrame()

        # 合併數據
        merged = pd.merge(tenants, payments, on='room_number', how='left')
        merged['status'] = merged['status'].fillna('未繳')
        merged['amount_paid'] = merged['amount_paid'].fillna(0)
        return merged

    def add_expense(self, date_str, category, amount, desc, room):
        conn = self.get_connection()
        conn.execute("INSERT INTO expenses (expense_date, category, amount, description, room_number) VALUES (?,?,?,?,?)",
                     (date_str, category, amount, desc, room))
        conn.commit()
        conn.close()
        
    def get_financial_summary(self, year):
        conn = self.get_connection()
        # 收租總計
        income = pd.read_sql("""
            SELECT period_month, SUM(amount_paid) as income 
            FROM payments WHERE period_year=? GROUP BY period_month
        """, conn, params=(year,))
        
        # 支出總計
        expense = pd.read_sql("""
            SELECT strftime('%m', expense_date) as month, SUM(amount) as expense
            FROM expenses WHERE strftime('%Y', expense_date)=? GROUP BY month
        """, conn, params=(str(year),))
        conn.close()
        
        # 整理成 1-12 月的 DataFrame
        df = pd.DataFrame({'month': range(1, 13)})
        
        # 合併收入
        if not income.empty:
            df = df.merge(income, left_on='month', right_on='period_month', how='left')
        else:
            df['income'] = 0
            
        # 合併支出 (處理字串月份轉數字)
        if not expense.empty:
            expense['month'] = expense['month'].astype(int)
            df = df.merge(expense, on='month', how='left')
        else:
            df['expense'] = 0
            
        df = df.fillna(0)
        df['net'] = df['income'] - df['expense']
        return df

# ============================================================================
# 3. UI 組件與輔助函數
# ============================================================================

def display_card(title, value, delta=None, color="blue"):
    """顯示美化的數據卡片"""
    delta_html = f"<span style='color: {'green' if delta and '+' in delta else 'red'}'>{delta}</span>" if delta else ""
    border_color = {"blue": "#4c6ef5", "green": "#40c057", "orange": "#fab005", "red": "#fa5252"}.get(color, "#ccc")
    
    st.markdown(f"""
    <div style="background-color: white; border-left: 5px solid {border_color}; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px;">
        <div style="color: #888; font-size: 0.85rem; font-weight: 600;">{title}</div>
        <div style="color: #333; font-size: 1.5rem; font-weight: 700; margin: 5px 0;">{value}</div>
        <div style="font-size: 0.8rem;">{delta_html}</div>
    </div>
    """, unsafe_allow_html=True)

def days_until(date_str):
    try:
        target = datetime.strptime(date_str, "%Y.%m.%d").date()
        delta = (target - date.today()).days
        return delta
    except:
        return 999

# ============================================================================
# 4. 主程式邏輯
# ============================================================================

def main():
    db = RentalDB()
    
    # 側邊欄設計
    with st.sidebar:
        st.title("🏠 幸福之家")
        st.caption("智慧租房管理系統 Pro")
        st.write("---")
        
        menu = st.radio(
            "功能導航",
            ["📊 總覽儀表板", "👥 房客管理", "💰 租金收繳", "💸 支出記帳", "⚙️ 系統設定"],
            index=0
        )
        
        st.write("---")
        # 快速操作區
        st.markdown("**快速跳轉**")
        current_year = datetime.now().year
        current_month = datetime.now().month
        st.info(f"📅 目前月份: {current_year}年 {current_month}月")

    # --- 頁面 1: 儀表板 ---
    if menu == "📊 總覽儀表板":
        st.header(f"早安，管理員！ 👋")
        st.write(f"今天是 {datetime.now().strftime('%Y年%m月%d日')}")
        
        tenants = db.get_tenants()
        financials = db.get_financial_summary(datetime.now().year)
        
        # 1. 關鍵指標
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            occupancy = len(tenants)
            total_rooms = 10  # 假設總共10間
            rate = (occupancy / total_rooms) * 100
            display_card("出租率", f"{rate:.0f}%", f"{occupancy}/{total_rooms} 間", "blue")
            
        with col2:
            current_month_income = financials[financials['month'] == datetime.now().month]['income'].sum()
            display_card("本月已收租", f"${current_month_income:,.0f}", "vs 上月", "green")
            
        with col3:
            total_deposit = tenants['deposit'].sum() if not tenants.empty else 0
            display_card("押金總管", f"${total_deposit:,.0f}", "由帳戶保管", "orange")
            
        with col4:
            # 簡單計算本月未收
            status_df = db.get_monthly_status(datetime.now().year, datetime.now().month)
            if not status_df.empty:
                unpaid = len(status_df[status_df['status'] == '未繳'])
            else:
                unpaid = 0
            display_card("本月待收", f"{unpaid} 戶", "請留意催繳", "red" if unpaid > 0 else "green")

        # 2. 視覺化圖表與提醒
        col_chart, col_alert = st.columns([2, 1])
        
        with col_chart:
            st.subheader("📈 年度財務趨勢")
            if not financials.empty:
                chart_data = financials[['month', 'income', 'expense', 'net']].set_index('month')
                st.bar_chart(chart_data, color=["#40c057", "#fa5252", "#4c6ef5"])
                st.caption("綠色: 收入 | 紅色: 支出 | 藍色: 淨利")
            else:
                st.info("尚無財務數據")

        with col_alert:
            st.subheader("⚠️ 重要提醒")
            
            # 租約到期檢查
            expiring_soon = []
            if not tenants.empty:
                for _, row in tenants.iterrows():
                    days = days_until(row['lease_end'])
                    if 0 <= days <= 60:
                        expiring_soon.append((row['room_number'], row['tenant_name'], days))
            
            if expiring_soon:
                for room, name, days in expiring_soon:
                    st.warning(f"**{room} {name}** 租約剩 {days} 天到期")
            else:
                st.success("目前無即將到期租約")
                
            st.write("---")
            st.write("**最近空房**")
            active_rooms = tenants['room_number'].tolist()
            all_rooms = ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"]
            empty_rooms = [r for r in all_rooms if r not in active_rooms]
            
            if empty_rooms:
                st.write(" ".join([f"`{r}`" for r in empty_rooms]))
            else:
                st.write("🎉 滿租中！")

    # --- 頁面 2: 房客管理 ---
    elif menu == "👥 房客管理":
        col1, col2 = st.columns([4, 1])
        with col1:
            st.header("房客資料庫")
        with col2:
            add_btn = st.button("➕ 新增房客", type="primary", use_container_width=True)
        
        # 新增/編輯 模態框邏輯
        if add_btn:
            st.session_state['edit_mode'] = False
            st.session_state['current_tenant'] = None
        
        # 顯示租客列表
        tenants = db.get_tenants()
        
        if not tenants.empty:
            # 準備顯示用的數據
            display_df = tenants.copy()
            display_df['剩餘天數'] = display_df['lease_end'].apply(days_until)
            
            # 使用 container 顯示卡片式列表 (比表格更人性化)
            st.markdown("### 🏘️ 租客名單")
            
            # 搜索欄
            search = st.text_input("🔍 搜尋房號或姓名...", placeholder="例如: 2A 或 王小明")
            if search:
                display_df = display_df[display_df['room_number'].str.contains(search, case=False) | 
                                      display_df['tenant_name'].str.contains(search, case=False)]

            for i, row in display_df.iterrows():
                with st.expander(f"**{row['room_number']} - {row['tenant_name']}** (租金: ${row['monthly_rent']:,.0f})"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.write(f"📞 電話: **{row['phone']}**")
                        st.write(f"💰 押金: ${row['deposit']:,.0f}")
                    with c2:
                        st.write(f"📅 租期: {row['lease_start']} ~ {row['lease_end']}")
                        days = row['剩餘天數']
                        if days < 30:
                            st.error(f"⚠️ 剩餘 {days} 天")
                        else:
                            st.success(f"✅ 剩餘 {days} 天")
                    with c3:
                        st.write(f"📝 備註: {row['notes']}")
                        
                    # 操作按鈕
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("✏️ 編輯資料", key=f"edit_{row['id']}"):
                            st.session_state['edit_mode'] = True
                            st.session_state['current_tenant'] = row.to_dict()
                            st.rerun()
                    with b2:
                        if st.button("🗑️ 退租/刪除", key=f"del_{row['id']}", type="secondary"):
                            if st.warning("確定要移除此租客嗎？"): # 簡單模擬，實際應有確認彈窗
                                db.delete_tenant(row['id'])
                                st.success("已移除")
                                st.rerun()

        else:
            st.info("目前沒有租客資料，請點擊右上方新增。")

        # 編輯/新增 表單區塊 (如果被觸發)
        if 'edit_mode' in st.session_state or add_btn:
            st.write("---")
            is_edit = st.session_state.get('edit_mode', False)
            curr = st.session_state.get('current_tenant', {})
            
            st.subheader("✏️ 編輯房客" if is_edit else "➕ 新增房客")
            
            with st.form("tenant_form"):
                c1, c2 = st.columns(2)
                with c1:
                    room = st.selectbox("房號", ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"], 
                                      index=["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"].index(curr.get('room_number', '1A')) if is_edit else 0)
                    name = st.text_input("姓名", value=curr.get('tenant_name', ''))
                    phone = st.text_input("電話", value=curr.get('phone', ''))
                    deposit = st.number_input("押金", value=float(curr.get('deposit', 0)), step=100.0)
                
                with c2:
                    rent = st.number_input("月租金", value=float(curr.get('monthly_rent', 5000)), step=100.0)
                    pay_method = st.selectbox("繳款方式", ["月繳", "半年繳", "年繳"], index=["月繳", "半年繳", "年繳"].index(curr.get('payment_method', '月繳')))
                    start = st.date_input("起租日", value=datetime.strptime(curr['lease_start'], "%Y.%m.%d") if is_edit and curr.get('lease_start') else date.today())
                    end = st.date_input("到期日", value=datetime.strptime(curr['lease_end'], "%Y.%m.%d") if is_edit and curr.get('lease_end') else date.today() + timedelta(days=365))
                
                notes = st.text_area("備註", value=curr.get('notes', ''))
                
                submitted = st.form_submit_button("💾 保存資料", type="primary")
                if submitted:
                    success, msg = db.upsert_tenant(
                        room, name, phone, deposit, rent,
                        start.strftime("%Y.%m.%d"), end.strftime("%Y.%m.%d"),
                        pay_method, 0, notes,
                        curr.get('id') if is_edit else None
                    )
                    if success:
                        st.success(msg)
                        # 清除狀態
                        if 'edit_mode' in st.session_state: del st.session_state['edit_mode']
                        if 'current_tenant' in st.session_state: del st.session_state['current_tenant']
                        st.rerun()
                    else:
                        st.error(f"失敗: {msg}")

    # --- 頁面 3: 租金收繳 ---
    elif menu == "💰 租金收繳":
        st.header("租金收繳中心")
        
        # 選擇月份
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            sel_year = st.number_input("年份", value=datetime.now().year, min_value=2023)
        with c2:
            sel_month = st.number_input("月份", value=datetime.now().month, min_value=1, max_value=12)
        
        # 獲取該月狀態
        status_df = db.get_monthly_status(sel_year, sel_month)
        
        if status_df.empty:
            st.warning("請先建立租客資料")
        else:
            # 分頁顯示：未繳款 vs 已繳款
            tab1, tab2 = st.tabs(["🔴 待收帳款", "🟢 已收帳款"])
            
            # --- 待收帳款邏輯 ---
            with tab1:
                unpaid_df = status_df[status_df['status'] != '已收']
                if unpaid_df.empty:
                    st.balloons()
                    st.success("🎉 太棒了！本月租金已全部收齊！")
                else:
                    st.write(f"尚有 {len(unpaid_df)} 筆未入帳")
                    
                    for i, row in unpaid_df.iterrows():
                        with st.container():
                            # 每一行是一個卡片
                            cols = st.columns([1, 2, 2, 2, 2])
                            with cols[0]:
                                st.markdown(f"### {row['room_number']}")
                            with cols[1]:
                                st.write(f"**{row['tenant_name']}**")
                                st.caption(f"{row['payment_method']}")
                            with cols[2]:
                                expected = row['monthly_rent']
                                if row['payment_method'] == '半年繳': expected *= 6
                                elif row['payment_method'] == '年繳': expected *= 12
                                st.write(f"應收: **${expected:,.0f}**")
                            with cols[3]:
                                # 快速入帳按鈕
                                if st.button("💰 確認收款", key=f"pay_{row['room_number']}"):
                                    db.record_payment(row['room_number'], sel_year, sel_month, expected, expected, "已收", "快速入帳")
                                    st.toast(f"✅ {row['room_number']} 入帳成功！")
                                    st.rerun()
                            with cols[4]:
                                with st.popover("更多操作"):
                                    amount_input = st.number_input("實收金額", value=float(expected), key=f"amt_{row['room_number']}")
                                    note_input = st.text_input("備註", key=f"note_{row['room_number']}")
                                    if st.button("部分收款/特殊入帳", key=f"spec_{row['room_number']}"):
                                        db.record_payment(row['room_number'], sel_year, sel_month, expected, amount_input, "已收", note_input)
                                        st.rerun()
                            st.divider()

            # --- 已收帳款邏輯 ---
            with tab2:
                paid_df = status_df[status_df['status'] == '已收']
                st.dataframe(
                    paid_df[['room_number', 'tenant_name', 'amount_paid', 'payment_method']],
                    column_config={
                        "room_number": "房號",
                        "tenant_name": "姓名",
                        "amount_paid": st.column_config.NumberColumn("已收金額", format="$%d"),
                        "payment_method": "方式"
                    },
                    use_container_width=True,
                    hide_index=True
                )
                st.metric("本月已入帳總額", f"${paid_df['amount_paid'].sum():,.0f}")

    # --- 頁面 4: 支出記帳 ---
    elif menu == "💸 支出記帳":
        st.header("支出管理")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("新增支出")
            with st.form("expense_form"):
                e_date = st.date_input("日期")
                e_cat = st.selectbox("類別", ["房貸", "修繕", "水電", "網路", "稅務", "雜支"])
                e_room = st.selectbox("歸屬", ["公共", "1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"])
                e_amt = st.number_input("金額", min_value=0, step=100)
                e_desc = st.text_input("說明 (選填)")
                
                if st.form_submit_button("提交支出", type="primary"):
                    db.add_expense(e_date.strftime("%Y-%m-%d"), e_cat, e_amt, e_desc, e_room)
                    st.success("已記錄！")
                    
        with col2:
            st.subheader("近期支出紀錄")
            conn = db.get_connection()
            df = pd.read_sql("SELECT * FROM expenses ORDER BY expense_date DESC LIMIT 10", conn)
            conn.close()
            
            if not df.empty:
                st.dataframe(
                    df[['expense_date', 'category', 'room_number', 'amount', 'description']],
                    column_config={
                        "expense_date": "日期",
                        "category": "類別",
                        "room_number": "房號",
                        "amount": st.column_config.NumberColumn("金額", format="$%d"),
                        "description": "說明"
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("尚無支出紀錄")

    # --- 頁面 5: 設定 ---
    elif menu == "⚙️ 系統設定":
        st.header("系統設定")
        
        with st.expander("房貸參數設定", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.number_input("每月固定房貸支出", value=39185)
            with col2:
                st.info("此設定將用於計算淨利潤。")
                
        with st.expander("資料庫管理"):
            st.warning("下載備份功能開發中...")
            st.download_button("📥 下載資料庫備份", data=b"demo", file_name="backup.db", disabled=True)

if __name__ == "__main__":
    main()

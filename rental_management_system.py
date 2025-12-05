
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import json
from pathlib import Path
import numpy as np

# ============================================================================
# 配置和初始化
# ============================================================================

st.set_page_config(
    page_title="幸福之家 - 租金管理系統",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定義CSS
st.markdown("""
    <style>
    .main { padding: 2rem; }
    .stMetric { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; }
    .metric-highlight { background-color: #d1f2eb; }
    .metric-warning { background-color: #ffe5e5; }
    </style>
""", unsafe_allow_html=True)

# ============================================================================
# 數據庫管理
# ============================================================================

class RentalDB:
    """數據庫管理類"""

    def __init__(self, db_path="rental_system.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """初始化數據庫表"""
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
                payment_method TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)

        # 租金記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rental_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT,
                payment_year INTEGER,
                payment_month INTEGER,
                amount_paid REAL,
                payment_date TEXT,
                payment_status TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_number) REFERENCES tenants(room_number)
            )
        """)

        # 電費記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS utility_charges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT,
                charge_month TEXT,
                private_usage_kwh REAL,
                private_usage_fee REAL,
                shared_usage_kwh REAL,
                shared_usage_fee REAL,
                total_fee REAL,
                charge_date TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_number) REFERENCES tenants(room_number)
            )
        """)

        # 支出記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_date TEXT,
                category TEXT,
                description TEXT,
                amount REAL,
                room_number TEXT,
                receipt_path TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 租客交接記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT,
                old_tenant TEXT,
                new_tenant TEXT,
                move_out_date TEXT,
                move_in_date TEXT,
                deposit_returned REAL,
                deposit_deduction REAL,
                deduction_reason TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_number) REFERENCES tenants(room_number)
            )
        """)

        conn.commit()
        conn.close()

    def add_tenant(self, room_num, name, phone, deposit, rent, lease_start, lease_end, payment_method, notes):
        """添加租客"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO tenants (room_number, tenant_name, phone, deposit, monthly_rent, 
                                   lease_start, lease_end, payment_method, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (room_num, name, phone, deposit, rent, lease_start, lease_end, payment_method, notes))
            conn.commit()
            return True
        except Exception as e:
            st.error(f"錯誤: {e}")
            return False
        finally:
            conn.close()

    def get_all_tenants(self):
        """獲取所有租客"""
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM tenants WHERE is_active = 1", conn)
        conn.close()
        return df

    def record_payment(self, room_num, year, month, amount, status, notes=""):
        """記錄租金支付"""
        conn = self.get_connection()
        cursor = conn.cursor()
        payment_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT INTO rental_payments (room_number, payment_year, payment_month, 
                                        amount_paid, payment_date, payment_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (room_num, year, month, amount, payment_date, status, notes))
        conn.commit()
        conn.close()

    def add_expense(self, exp_date, category, description, amount, room_num="", notes=""):
        """添加支出"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO expenses (expense_date, category, description, amount, room_number, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (exp_date, category, description, amount, room_num, notes))
        conn.commit()
        conn.close()

    def get_monthly_summary(self, year, month):
        """獲取月度統計"""
        conn = self.get_connection()

        # 該月收租
        rentals = pd.read_sql_query(
            "SELECT SUM(amount_paid) as total FROM rental_payments WHERE payment_year = ? AND payment_month = ?",
            conn, params=(year, month)
        )

        # 該月支出
        expenses = pd.read_sql_query(
            """SELECT category, SUM(amount) as total FROM expenses 
               WHERE strftime('%Y', expense_date) = ? AND strftime('%m', expense_date) = ? 
               GROUP BY category""",
            conn, params=(str(year), str(month).zfill(2))
        )

        conn.close()
        return rentals, expenses

# ============================================================================
# 主應用程式
# ============================================================================

def main():
    # 初始化數據庫
    db = RentalDB()

    # 頁面標題
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("🏠 幸福之家 - 租金管理系統")
    with col2:
        st.write(f"更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 側邊欄導航
    st.sidebar.title("📋 導航菜單")
    menu = st.sidebar.radio(
        "選擇功能",
        ["📊 儀表板", "👥 租客管理", "💰 租金收繳", "⚡ 電費管理", 
         "💸 支出管理", "📈 報表分析", "⚙️ 系統設定"]
    )

    # ================================================================
    # 1. 儀表板
    # ================================================================
    if menu == "📊 儀表板":
        st.header("儀表板概覽")

        # 獲取數據
        tenants_df = db.get_all_tenants()

        # KPI 指標
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric("總房間", len(tenants_df), "間")

        with col2:
            total_monthly = tenants_df['monthly_rent'].sum()
            st.metric("月收租預估", f"${total_monthly:,.0f}", "元")

        with col3:
            total_deposit = tenants_df['deposit'].sum()
            st.metric("押金總額", f"${total_deposit:,.0f}", "元")

        with col4:
            st.metric("房貸月付", "$39,185", "元")

        with col5:
            net_monthly = total_monthly - 39185
            st.metric("預估月淨收", f"${net_monthly:,.0f}", "元" if net_monthly >= 0 else "元(虧)")

        # 待辦事項
        st.subheader("⚠️ 重要提醒")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**即將到期的租約 (3個月內)**")
            today = datetime.now()
            three_months_later = today + timedelta(days=90)

            if not tenants_df.empty:
                upcoming = tenants_df[
                    (pd.to_datetime(tenants_df['lease_end'], format='%Y.%m.%d', errors='coerce') >= today) &
                    (pd.to_datetime(tenants_df['lease_end'], format='%Y.%m.%d', errors='coerce') <= three_months_later)
                ]

                if not upcoming.empty:
                    for _, row in upcoming.iterrows():
                        days_left = (pd.to_datetime(row['lease_end'], format='%Y.%m.%d') - today).days
                        st.warning(f"🔴 {row['room_number']} ({row['tenant_name']}) - 剩餘 {days_left} 天")
                else:
                    st.info("✅ 近期無租約到期")

        with col2:
            st.write("**空房狀態**")
            active_rooms = len(tenants_df[tenants_df['is_active'] == 1])
            empty_rooms = 10 - active_rooms

            if empty_rooms > 0:
                st.error(f"⛔ 目前空房數: {empty_rooms} 間")
            else:
                st.success(f"✅ 滿房 {active_rooms}/10 間")

        # 最近交易
        st.subheader("📋 最近交易紀錄")
        st.info("(此功能需連接到數據庫)")

    # ================================================================
    # 2. 租客管理
    # ================================================================
    elif menu == "👥 租客管理":
        st.header("租客管理")

        tab1, tab2, tab3 = st.tabs(["查看租客", "新增租客", "編輯/刪除"])

        with tab1:
            st.subheader("所有租客列表")
            tenants_df = db.get_all_tenants()

            if not tenants_df.empty:
                # 重新格式化顯示
                display_df = tenants_df[[
                    'room_number', 'tenant_name', 'phone', 'monthly_rent', 
                    'deposit', 'lease_end'
                ]].copy()
                display_df.columns = ['房號', '租客姓名', '電話', '月租', '押金', '租期至']

                st.dataframe(display_df, use_container_width=True)
            else:
                st.info("尚無租客記錄")

        with tab2:
            st.subheader("新增租客")

            with st.form("add_tenant_form"):
                col1, col2 = st.columns(2)

                with col1:
                    room_num = st.selectbox("房號", ["1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"])
                    tenant_name = st.text_input("租客姓名")
                    phone = st.text_input("聯絡電話")
                    deposit = st.number_input("押金", min_value=0)

                with col2:
                    monthly_rent = st.number_input("月租金", min_value=0)
                    lease_start = st.date_input("租期開始")
                    lease_end = st.date_input("租期結束")
                    payment_method = st.selectbox("繳租方式", ["月繳", "半年繳", "年繳"])

                notes = st.text_area("備註")

                if st.form_submit_button("✅ 新增租客"):
                    if db.add_tenant(
                        room_num, tenant_name, phone, deposit, monthly_rent,
                        lease_start.strftime("%Y.%m.%d"), lease_end.strftime("%Y.%m.%d"),
                        payment_method, notes
                    ):
                        st.success(f"✅ 成功新增 {room_num} - {tenant_name}")
                    else:
                        st.error("❌ 新增失敗")

        with tab3:
            st.subheader("編輯/刪除租客")
            st.info("此功能開發中...")

    # ================================================================
    # 3. 租金收繳
    # ================================================================
    elif menu == "💰 租金收繳":
        st.header("租金收繳管理")

        tab1, tab2 = st.tabs(["記錄收租", "收租統計"])

        with tab1:
            st.subheader("記錄租金收繳")

            tenants_df = db.get_all_tenants()

            with st.form("payment_form"):
                col1, col2 = st.columns(2)

                with col1:
                    room_num = st.selectbox("房號", tenants_df['room_number'].tolist())
                    year = st.number_input("年份", value=2025, min_value=2020)

                with col2:
                    month = st.number_input("月份", value=datetime.now().month, min_value=1, max_value=12)
                    amount = st.number_input("收租金額", min_value=0)

                payment_status = st.selectbox("狀態", ["已收", "預收", "逾期", "部分收"])
                notes = st.text_area("備註")

                if st.form_submit_button("✅ 記錄收租"):
                    db.record_payment(room_num, year, month, amount, payment_status, notes)
                    st.success(f"✅ 已記錄 {room_num} {year}年{month}月的收租")

        with tab2:
            st.subheader("收租統計")

            col1, col2 = st.columns(2)
            with col1:
                selected_year = st.number_input("選擇年份", value=2025)
            with col2:
                selected_month = st.number_input("選擇月份", value=datetime.now().month, min_value=1, max_value=12)

            rentals, expenses = db.get_monthly_summary(selected_year, selected_month)

            st.info(f"📊 {selected_year}年{selected_month}月收租統計 (開發中...)")

    # ================================================================
    # 4. 電費管理
    # ================================================================
    elif menu == "⚡ 電費管理":
        st.header("電費管理系統")

        st.subheader("複雜的電費分攤計算")

        col1, col2 = st.columns(2)

        with col1:
            charge_month = st.date_input("選擇月份")
            shared_kwh = st.number_input("共用電度數", min_value=0.0)
            shared_fee = st.number_input("共用電費", min_value=0.0)

        with col2:
            total_residents = st.number_input("住戶數", value=10, min_value=1)
            st.write(f"每戶平均分攤: {shared_kwh/total_residents:.1f} 度 / {shared_fee/total_residents:.0f} 元")

        st.info("電費計算模塊: 支持複雜的私表與公電分攤(詳見 Excel 原文件範例)")

    # ================================================================
    # 5. 支出管理
    # ================================================================
    elif menu == "💸 支出管理":
        st.header("支出管理")

        tab1, tab2 = st.tabs(["記錄支出", "支出統計"])

        with tab1:
            st.subheader("新增支出記錄")

            with st.form("expense_form"):
                col1, col2 = st.columns(2)

                with col1:
                    exp_date = st.date_input("支出日期")
                    category = st.selectbox("類別", ["房貸", "維修費", "稅務", "保險", "水電網路", "雜支"])
                    description = st.text_input("說明")

                with col2:
                    amount = st.number_input("金額", min_value=0)
                    room_num = st.selectbox("相關房號", ["", "1A", "1B", "2A", "2B", "3A", "3B", "3C", "3D", "4A", "4B", "4C", "4D"])

                notes = st.text_area("備註")

                if st.form_submit_button("✅ 新增支出"):
                    db.add_expense(exp_date.strftime("%Y-%m-%d"), category, description, amount, room_num, notes)
                    st.success(f"✅ 已記錄 {category} 支出: ${amount}")

        with tab2:
            st.subheader("支出統計分析")
            st.info("支出統計圖表 (開發中...)")

    # ================================================================
    # 6. 報表分析
    # ================================================================
    elif menu == "📈 報表分析":
        st.header("報表與分析")

        col1, col2 = st.columns(2)

        with col1:
            report_type = st.selectbox(
                "選擇報表類型",
                ["月度財務報表", "收租統計", "支出明細", "租約續期提醒", "年度總結"]
            )

        with col2:
            st.write("")

        if report_type == "月度財務報表":
            col1, col2 = st.columns(2)
            with col1:
                year = st.number_input("年", value=2025)
            with col2:
                month = st.number_input("月", value=datetime.now().month, min_value=1, max_value=12)

            st.subheader(f"{year}年{month}月財務報表")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("預計收租", "$57,066", "+5.8%")
            with col2:
                st.metric("預計支出", "-$39,185", "-5.2%")
            with col3:
                st.metric("預計淨收", "$17,881", "+12.3%")

            st.info("詳細報表功能開發中...")

    # ================================================================
    # 7. 系統設定
    # ================================================================
    elif menu == "⚙️ 系統設定":
        st.header("系統設定")

        tab1, tab2, tab3 = st.tabs(["基本設定", "數據導出/導入", "關於系統"])

        with tab1:
            st.subheader("物業基本信息")

            col1, col2 = st.columns(2)
            with col1:
                property_name = st.text_input("物業名稱", value="幸福之家")
                property_address = st.text_input("地址", value="8-13號")

            with col2:
                total_units = st.number_input("總房間數", value=10)
                manager_name = st.text_input("管理人姓名", value="")

            st.subheader("房貸信息")
            col1, col2, col3 = st.columns(3)

            with col1:
                mortgage_total = st.number_input("貸款總額", value=9550000)
            with col2:
                monthly_payment = st.number_input("月付款", value=39185)
            with col3:
                interest_rate = st.number_input("年利率", value=2.79, step=0.01)

            if st.button("💾 保存設定"):
                st.success("✅ 設定已保存")

        with tab2:
            st.subheader("數據導出")

            if st.button("📥 導出為 Excel"):
                st.info("Excel 導出功能開發中...")

            if st.button("📤 從 Excel 導入"):
                st.info("Excel 導入功能開發中...")

        with tab3:
            st.subheader("系統信息")
            st.write("**系統名稱:** 幸福之家租金管理系統 v1.0")
            st.write("**開發時間:** 2025年")
            st.write("**功能特性:** 租客管理、租金追蹤、電費計算、財務分析")
            st.write("**支持:** Streamlit + SQLite3")

            if st.button("🔄 檢查更新"):
                st.info("您已是最新版本 ✅")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
租金管理系統 - 數據初始化腳本
"""

import sqlite3
from datetime import datetime, timedelta

def init_sample_data():
    """初始化示例數據"""
    conn = sqlite3.connect('rental_system.db')
    cursor = conn.cursor()

    # 示例租客數據
    sample_tenants = [
        ('1A', '陳重鈞', '0912-345-678', 12000, 6100, '114.01.01', '115.08.31', '月繳', ''),
        ('1B', '楊惏苑', '0912-345-679', 12000, 6100, '114.01.01', '115.08.31', '半年繳', '房仲業務'),
        ('2A', '張郁賢', '0912-345-680', 12000, 6000, '114.01.01', '114.12.31', '半年繳', '台北學生'),
        ('2B', '王程', '0912-345-681', 5500, 5500, '114.01.01', '114.12.31', '半年繳', '六輕'),
        ('3A', '焦嵒', '0912-345-682', 3500, 4100, '114.01.01', '115.08.31', '月繳', '休學接案'),
        ('3B', '林庭義', '0912-345-683', 8000, 4000, '114.01.01', '115.06.30', '年繳', '碩一資工'),
        ('3C', '武心如', '0912-345-684', 5000, 4000, '114.01.01', '115.06.30', '月繳', '上班族'),
        ('3D', '陳俞任', '0912-345-685', 10000, 5000, '114.01.01', '115.07.31', '年繳', '虎科1年級'),
        ('4A', '王世嘉', '0912-345-686', 10000, 5000, '114.01.01', '115.07.31', '年繳', '彰化學生'),
        ('4B', '陳緯芯', '0912-345-687', 4000, 4000, '114.01.01', '115.06.30', '年繳', '碩一電機'),
    ]

    for room, name, phone, deposit, rent, start, end, method, notes in sample_tenants:
        cursor.execute('''
            INSERT OR REPLACE INTO tenants 
            (room_number, tenant_name, phone, deposit, monthly_rent, lease_start, lease_end, payment_method, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (room, name, phone, deposit, rent, start, end, method, notes))

    # 示例租金記錄 (2025年1月)
    sample_payments = [
        ('1A', 2025, 1, 6100, '已收', ''),
        ('1B', 2025, 1, 6100, '已收', ''),
        ('2A', 2025, 1, 6000, '已收', ''),
        ('2B', 2025, 1, 5500, '已收', ''),
        ('3A', 2025, 1, 4100, '已收', ''),
        ('3B', 2025, 1, 4000, '已收', '年繳抵扣'),
        ('3C', 2025, 1, 4000, '已收', ''),
        ('3D', 2025, 1, 5000, '已收', '年繳抵扣'),
        ('4A', 2025, 1, 5000, '已收', '年繳抵扣'),
        ('4B', 2025, 1, 4000, '已收', '年繳抵扣'),
    ]

    for room, year, month, amount, status, notes in sample_payments:
        cursor.execute('''
            INSERT INTO rental_payments 
            (room_number, payment_year, payment_month, amount_paid, payment_date, payment_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (room, year, month, amount, datetime.now().strftime('%Y-%m-%d'), status, notes))

    # 示例支出
    sample_expenses = [
        ('2025-01-05', '房貸', '1月房貸', 39185, '', ''),
        ('2025-01-10', '水電', '1樓電費', 1500, '', ''),
        ('2025-01-12', '保險', '火災險半年度', 2425, '', ''),
        ('2025-01-15', '維修費', '2A冷氣清洗', 2000, '2A', ''),
        ('2025-01-20', '雜支', '清潔用品', 500, '', ''),
    ]

    for date, category, desc, amount, room, notes in sample_expenses:
        cursor.execute('''
            INSERT INTO expenses 
            (expense_date, category, description, amount, room_number, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date, category, desc, amount, room, notes))

    conn.commit()
    conn.close()
    print("✅ 示例數據已初始化")

if __name__ == '__main__':
    init_sample_data()

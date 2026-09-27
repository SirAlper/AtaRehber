"""Demo SQLite database (fictitious products, sales, and support tickets) for trying the database agent."""

import os
import sqlite3
from typing import Optional

from src.core.config import SAMPLE_DB_PATH


def create_sample_sqlite_db(db_path: Optional[str] = None) -> str:
    """Generate sample enterprise SQLite database for instant zero-config testing."""
    target_path = db_path or SAMPLE_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    conn = sqlite3.connect(target_path)
    cursor = conn.cursor()

    # 1. Products Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS urunler (
        urun_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        urun_adi TEXT NOT NULL,
        kategori TEXT NOT NULL,
        birim_fiyat REAL NOT NULL,
        stok_adedi INTEGER NOT NULL
    );
    """)

    # 2. Sales Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS satislar (
        satis_id INTEGER PRIMARY KEY AUTOINCREMENT,
        siparis_no TEXT NOT NULL,
        musteri_adi TEXT NOT NULL,
        urun_id INTEGER,
        adet INTEGER NOT NULL,
        toplam_tutar REAL NOT NULL,
        bolge TEXT NOT NULL,
        tarih TEXT NOT NULL,
        FOREIGN KEY (urun_id) REFERENCES urunler(urun_id)
    );
    """)

    # 3. Support Requests Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS destek_talepleri (
        talep_id INTEGER PRIMARY KEY AUTOINCREMENT,
        talep_kodu TEXT NOT NULL,
        musteri_adi TEXT NOT NULL,
        konu TEXT NOT NULL,
        detay TEXT NOT NULL,
        cozum TEXT NOT NULL,
        durum TEXT NOT NULL
    );
    """)

    # Populate initial sample records if empty
    cursor.execute("SELECT COUNT(*) FROM urunler;")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            """
        INSERT INTO urunler (sku, urun_adi, kategori, birim_fiyat, stok_adedi) VALUES (?, ?, ?, ?, ?);
        """,
            [
                ("NT-SRV-01", "NovaTech Enterprise Server X1", "Hardware", 85000.0, 14),
                ("NT-LPT-02", "NovaTech ProBook 15 G3", "Computer", 38500.0, 45),
                ("NT-SEC-03", "NovaShield Enterprise Firewall", "Security", 62000.0, 8),
                (
                    "NT-SFT-04",
                    "NovaERP Cloud License (Annual)",
                    "Software",
                    120000.0,
                    100,
                ),
                ("NT-MON-05", "NovaView 27-inch 4K Monitor", "Accessory", 9400.0, 60),
            ],
        )

        cursor.executemany(
            """
        INSERT INTO satislar (siparis_no, musteri_adi, urun_id, adet, toplam_tutar, bolge, tarih) VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
            [
                (
                    "ORD-2026-001",
                    "Anadolu Logistics Corp.",
                    1,
                    2,
                    170000.0,
                    "Marmara",
                    "2026-01-15",
                ),
                (
                    "ORD-2026-002",
                    "Capital Health Group",
                    2,
                    5,
                    192500.0,
                    "Central",
                    "2026-01-18",
                ),
                (
                    "ORD-2026-003",
                    "Aegean IT Systems",
                    3,
                    1,
                    62000.0,
                    "Aegean",
                    "2026-02-02",
                ),
                (
                    "ORD-2026-004",
                    "Mediterranean Retail Ltd.",
                    4,
                    1,
                    120000.0,
                    "Mediterranean",
                    "2026-02-14",
                ),
                (
                    "ORD-2026-005",
                    "Anadolu Logistics Corp.",
                    5,
                    4,
                    37600.0,
                    "Marmara",
                    "2026-03-01",
                ),
            ],
        )

        cursor.executemany(
            """
        INSERT INTO destek_talepleri (talep_kodu, musteri_adi, konu, detay, cozum, durum) VALUES (?, ?, ?, ?, ?, ?);
        """,
            [
                (
                    "SR-2026-101",
                    "Anadolu Logistics Corp.",
                    "Server BIOS Update",
                    "IPMI disconnected after Enterprise Server X1 reboot.",
                    "Applied IPMI firmware 2.14 patch and reset static IP.",
                    "Resolved",
                ),
                (
                    "SR-2026-102",
                    "Capital Health Group",
                    "ERP License Activation Error",
                    "Users receiving 'License Limit Exceeded' warning.",
                    "Terminated stale sessions on license server and cleaned connection pool.",
                    "Resolved",
                ),
                (
                    "SR-2026-103",
                    "Aegean IT Systems",
                    "Firewall VPN Setup",
                    "IKEv2 key mismatch when establishing IPsec tunnel.",
                    "Synchronized Phase-1 and Phase-2 encryption algorithms to AES-256.",
                    "Resolved",
                ),
            ],
        )

    conn.commit()
    conn.close()
    return target_path

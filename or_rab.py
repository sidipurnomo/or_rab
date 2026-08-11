import streamlit as st
import gspread
import pandas as pd
from datetime import date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import os

# =====================================================================
# 1. KONFIGURASI & KONEKSI GOOGLE API
# =====================================================================
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SPREADSHEET_NAME = "Rincian Tagihan OR PT RAB"
DRIVE_FOLDER_ID = "1Nag7O-ZguGM-smzk1SkMQXVIjaHQXZH2"
CREDENTIALS_FILE = "credentials.json"

@st.cache_resource
def get_services():
    """Inisialisasi koneksi ke Google Sheets dan Google Drive via st.secrets atau file lokal"""
    # Cek apakah konfigurasi ada di Streamlit Secrets (untuk deploy di Streamlit Cloud)
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    # Jika tidak ada, coba baca dari file credentials.json lokal
    elif os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    else:
        st.error("❌ Kredensial Google Service Account tidak ditemukan! Setup 'st.secrets' atau taruh file 'credentials.json' di folder proyek.")
        st.stop()
    
    # Koneksi Google Sheets
    gc = gspread.authorize(creds)
    sheet = gc.open(SPREADSHEET_NAME).sheet1
    
    # Koneksi Google Drive
    drive_service = build('drive', 'v3', credentials=creds)
    
    return sheet, drive_service

sheet, drive_service = get_services()

# =====================================================================
# 2. FUNGSI UPLOAD KE GOOGLE DRIVE
# =====================================================================
def upload_to_drive(file_buffer, file_name, mime_type):
    """Mengunggah file ke Google Drive dan mengembalikan link yang bisa dibuka"""
    file_metadata = {
        'name': file_name,
        'parents': [DRIVE_FOLDER_ID]
    }
    
    media = MediaIoBaseUpload(io.BytesIO(file_buffer.getvalue()), mimetype=mime_type, resumable=True)
    
    uploaded_file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    # Beri izin agar link bisa diakses
    drive_service.permissions().create(
        fileId=uploaded_file.get('id'),
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()
    
    return uploaded_file.get('webViewLink')

# =====================================================================
# 3. TAMPILAN DASHBOARD & RINCIAN ATAS (KPI)
# =====================================================================
st.set_page_config(page_title="Rincian Tagihan OR", layout="wide")

st.title("📋 Input & Rincian Tagihan OR")

# Ambil data dari Spreadsheet
try:
    records = sheet.get_all_records()
    df = pd.DataFrame(records)
except Exception as e:
    st.error(f"Gagal membaca data dari Google Sheets: {e}")
    df = pd.DataFrame()

# Perhitungan KPI (Total Diajukan, Approved, Not Approved)
total_diajukan = 0
total_approved = 0
total_not_approved = 0

if not df.empty and "Total" in df.columns and "Approve by RAB" in df.columns:
    df["Total_Num"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0)
    total_diajukan = df["Total_Num"].sum()
    total_approved = df[df["Approve by RAB"] == "Approved"]["Total_Num"].sum()
    total_not_approved = df[df["Approve by RAB"] == "Not Approved"]["Total_Num"].sum()

# Tampilkan ringkasan tagihan
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Diajukan", f"Rp {total_diajukan:,.0f}".replace(",", "."))
with col2:
    st.metric("Approved", f"Rp {total_approved:,.0f}".replace(",", "."), delta_color="normal")
with col3:
    st.metric("Not Approved", f"Rp {total_not_approved:,.0f}".replace(",", "."), delta_color="inverse")

st.divider()

# =====================================================================
# 4. FORM INPUT DATA
# =====================================================================
st.subheader("➕ Input Data Tagihan Baru")

with st.form("form_tagihan", clear_on_submit=True):
    col_input1, col_input2 = st.columns(2)
    
    with col_input1:
        tanggal_input = st.date_input("Tanggal", value=date.today())
        plat_input = st.text_input("Plat Kendaraan", placeholder="Contoh: B 1234 ABC").upper()
        total_input = st.number_input("Total Tagihan (Rp)", min_value=0, step=10000, format="%d")
    
    with col_input2:
        dokumen_file = st.file_uploader("Dokumen Penunjang (PDF/Foto)", type=["pdf", "png", "jpg", "jpeg"])
        status_rab = st.selectbox("Approve by RAB", options=["Approved", "Not Approved", "Pending"])
        
    submit_btn = st.form_submit_button("Simpan Tagihan", type="primary", use_container_width=True)

    if submit_btn:
        if not plat_input:
            st.warning("⚠️ Nomor Plat Kendaraan wajib diisi!")
        else:
            with st.spinner("Mengunggah dokumen & menyimpan data ke Google Sheets..."):
                try:
                    # 1. Upload dokumen jika ada
                    link_dokumen = ""
                    if dokumen_file is not None:
                        link_dokumen = upload_to_drive(
                            dokumen_file, 
                            f"{plat_input}_{tanggal_input}_{dokumen_file.name}",
                            dokumen_file.type
                        )
                    
                    # 2. Format tanggal (Contoh: 31-May-2026)
                    tanggal_str = tanggal_input.strftime("%d-%b-%Y")
                    
                    # 3. Simpan ke baris baru Google Sheets
                    row_data = [
                        tanggal_str,
                        plat_input,
                        int(total_input),
                        link_dokumen,
                        status_rab
                    ]
                    sheet.append_row(row_data)
                    
                    st.success("✅ Data berhasil disimpan ke Spreadsheet & Google Drive!")
                    st.rerun()  # Refresh halaman agar tabel terupdate
                except Exception as e:
                    st.error(f"Terjadi kesalahan saat menyimpan data: {e}")

st.divider()

# =====================================================================
# 5. TABEL DATA TAGIHAN
# =====================================================================
st.subheader("📊 Daftar Rincian Tagihan OR")

if not df.empty:
    # Ubah format angka rupiah agar nyaman dibaca
    if "Total" in df.columns:
        df["Total_Display"] = df["Total"].apply(
            lambda x: f"Rp {int(x):,.0f}".replace(",", ".") if pd.notnull(x) and str(x).strip() != "" else "Rp 0"
        )
        df["Total"] = df["Total_Display"]
        df.drop(columns=["Total_Display"], inplace=True)
    
    # Hapus kolom bantuan numerik jika ada sebelum ditampilkan ke tabel
    if "Total_Num" in df.columns:
        df.drop(columns=["Total_Num"], inplace=True)
    
    # Tampilkan tabel menggunakan dataframe
    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "Dokumen Penunjang": st.column_config.LinkColumn(
                "Dokumen Penunjang",
                display_text="Lihat Dokumen"
            ),
            "Approve by RAB": st.column_config.TextColumn(
                "Approve by RAB"
            )
        },
        hide_index=True
    )
else:
    st.info("Belum ada data tagihan di Spreadsheet.")

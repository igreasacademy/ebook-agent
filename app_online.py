"""
Title Ebook With IGreasacademy - versi online.
Pembeli masuk dengan kode akses, lalu memakai kunci Gemini MILIK MEREKA SENDIRI.
- Kunci hanya disimpan di memori sesi (tidak ditulis ke file / environment server).
- Tiap sesi punya folder sendiri, tidak bisa melihat ebook orang lain.
- Folder sesi dihapus otomatis setelah 24 jam.
"""
import os
import re
import json
import time
import uuid
import shutil
import hmac
import tempfile

import streamlit as st

import agent  # outline, tulis bab, PDF

NAMA = "Title Ebook With IGreasacademy"
BASE = os.path.join(tempfile.gettempdir(), "ebook_sesi")
UMUR_MAKS = 24 * 3600
MAKS_COBA_KODE = 5

st.set_page_config(page_title=NAMA, page_icon="📘", layout="centered")
ss = st.session_state
ss.setdefault("tahap", "form")
ss.setdefault("gagal_kode", 0)


# ----------------------------------------------------------------- Bantu ----
def daftar_kode():
    """Kode akses dari Streamlit Secrets (kode_akses) atau variabel lingkungan KODE_AKSES."""
    kode = None
    try:
        kode = st.secrets.get("kode_akses")
    except Exception:
        kode = None
    if not kode:
        kode = os.getenv("KODE_AKSES", "")
    if isinstance(kode, str):
        kode = kode.split(",")
    return [str(k).strip() for k in kode if str(k).strip()]


def kode_benar(masuk, valid):
    masuk = masuk.strip().encode()
    ok = False
    for k in valid:  # tidak berhenti di kecocokan pertama
        ok |= hmac.compare_digest(masuk, k.encode())
    return ok


def bersihkan_lama():
    try:
        if not os.path.isdir(BASE):
            return
        now = time.time()
        for d in os.listdir(BASE):
            p = os.path.join(BASE, d)
            if os.path.isdir(p) and now - os.path.getmtime(p) > UMUR_MAKS:
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def slug(t):
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.lower()).strip("-")
    return t[:30] or "ebook"


def folder_proyek():
    return os.path.join(ss.dir, ss.pid)


def simpan_outline():
    os.makedirs(os.path.join(folder_proyek(), "bab"), exist_ok=True)
    with open(os.path.join(folder_proyek(), "outline.json"), "w", encoding="utf-8") as f:
        json.dump(ss.data, f, ensure_ascii=False, indent=2)


def pesan_error(e):
    return str(e.code) if e.code else "Terjadi kesalahan."


def lupa_kunci():
    ss.pop("api_key", None)


def keluar():
    for k in list(ss.keys()):
        del ss[k]


# ----------------------------------------------------------------- Header ----
st.title(f"📘 {NAMA}")

valid = daftar_kode()
if not valid:
    st.error("Aplikasi belum dikonfigurasi oleh pemiliknya (kode akses belum diatur).")
    st.stop()

# -------------------------------------------------------------- Kode akses ----
if not ss.get("akses_ok"):
    st.subheader("Masuk")
    kode = st.text_input("Kode akses pembeli", type="password")
    if st.button("Masuk", type="primary"):
        if ss.gagal_kode >= MAKS_COBA_KODE:
            st.error("Terlalu banyak percobaan. Muat ulang halaman, lalu coba lagi.")
        elif kode_benar(kode, valid):
            ss.akses_ok = True
            st.rerun()
        else:
            ss.gagal_kode += 1
            st.error("Kode akses salah.")
    st.caption("Kode akses dikirim setelah pembelian.")
    st.stop()

# ------------------------------------------------------------- Kunci Gemini ----
if not ss.get("api_key"):
    st.subheader("Sambungkan kunci Gemini")
    st.markdown(
        "1. Buka **aistudio.google.com/apikey** dan masuk dengan akun Google.\n"
        "2. Buat kunci baru (**Create API key**).\n"
        "3. Salin **kunci**-nya (teks panjang tanpa spasi), bukan nama kuncinya, lalu tempel di bawah."
    )
    kunci = st.text_input("Kunci Gemini", type="password")
    if st.button("Sambungkan", type="primary"):
        k = kunci.strip()
        if len(k) < 20 or " " in k:
            st.error("Yang ditempel tampaknya bukan kunci. Salin kolom 'API Key' (teks panjang tanpa spasi).")
        else:
            ss.api_key = k
            st.rerun()
    st.caption(
        "Biaya pemakaian AI memakai kuota akun Google kamu sendiri. Kunci hanya disimpan sementara di "
        "memori selama jendela ini terbuka dan tidak ditulis ke file. Setelah selesai klik 'Keluar'."
    )
    st.stop()

# ----------------------------------------------------------------- Sidebar ----
with st.sidebar:
    st.success("✓ Gemini tersambung")
    if st.button("➕ Ebook baru"):
        ss.tahap = "form"
        st.rerun()
    st.button("Ganti kunci", on_click=lupa_kunci)
    st.button("Keluar & hapus kunci", on_click=keluar)
    st.caption("Unduh PDF segera setelah jadi. File di server dihapus otomatis maksimal 24 jam.")

if "dir" not in ss:
    bersihkan_lama()
    ss.dir = os.path.join(BASE, uuid.uuid4().hex)
    os.makedirs(ss.dir, exist_ok=True)

# -------------------------------------------------------------------- Form ----
if ss.tahap == "form":
    st.subheader("Mau bikin ebook tentang apa hari ini?")
    topik = st.text_area("Topik ebook", max_chars=240,
                         placeholder="Contoh: Cara mengajarkan berhitung pada anak TK")
    merek = st.text_input("Nama merek di cover", placeholder="Boleh dikosongkan")
    n_bab = st.slider("Jumlah bab", 3, 12, 8)
    if st.button("Susun outline dulu →", type="primary"):
        if not topik.strip():
            st.error("Isi topik dulu.")
            st.stop()
        with st.spinner("Menyusun outline... (biasanya 20-60 detik)"):
            try:
                data = agent.buat_outline(agent.get_client(ss.api_key), topik.strip(), n_bab)
            except SystemExit as e:
                st.error(pesan_error(e))
                st.stop()
        data["topik"] = topik.strip()
        data["merek"] = merek.strip()
        ss.data = data
        ss.pid = uuid.uuid4().hex[:8]
        simpan_outline()
        ss.tahap = "outline"
        st.rerun()

# ----------------------------------------------------------------- Outline ----
elif ss.tahap == "outline":
    data, pid = ss.data, ss.pid
    st.subheader("Ini rancangan ebook-mu")
    pil = data["judul_pilihan"]
    idx = st.radio(
        "Pilih judul",
        range(len(pil)),
        format_func=lambda i: f"{pil[i]['judul']} - {pil[i].get('subjudul', '')}",
        key=f"judul_{pid}",
    )
    st.markdown("**Daftar bab** (boleh diubah)")
    for i, b in enumerate(data["bab"]):
        with st.expander(f"{i + 1}. {b['judul']}"):
            st.text_input("Judul bab", b["judul"], key=f"j{pid}_{i}")
            st.text_area("Poin (satu per baris)", "\n".join(b["poin"]), key=f"p{pid}_{i}")
    if st.button("Mulai bikin ebook →", type="primary"):
        for i, b in enumerate(data["bab"]):
            b["judul"] = ss[f"j{pid}_{i}"].strip() or b["judul"]
            poin = [x.strip() for x in ss[f"p{pid}_{i}"].splitlines() if x.strip()]
            b["poin"] = poin or b["poin"]
        data["judul_terpilih"] = pil[idx]
        simpan_outline()
        ss.tahap = "tulis"
        st.rerun()

# ------------------------------------------------------------------- Tulis ----
elif ss.tahap == "tulis":
    data = ss.data
    st.subheader(data["judul_terpilih"]["judul"])
    st.caption("Jangan tutup tab atau mengunci layar sampai selesai. Proses sekitar beberapa menit.")
    bar = st.progress(0.0)
    status = st.empty()
    client = agent.get_client(ss.api_key)
    total = len(data["bab"])
    bab_list, ringkasan = [], ""
    for i in range(total):
        p = os.path.join(folder_proyek(), "bab", f"bab_{i + 1:02d}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                isi = json.load(f)
        else:
            status.info(f"Menulis bab {i + 1} dari {total}: {data['bab'][i]['judul']}")
            try:
                isi = agent.tulis_bab(client, data, i, ringkasan)
            except SystemExit as e:
                st.error(pesan_error(e))
                st.info("Bab yang sudah jadi tersimpan selama jendela ini terbuka. Klik 'Lanjutkan' untuk mencoba lagi.")
                st.button("Lanjutkan")
                st.button("Ganti kunci Gemini", on_click=lupa_kunci, key="ganti_kunci_err")
                st.stop()
            with open(p, "w", encoding="utf-8") as f:
                json.dump(isi, f, ensure_ascii=False, indent=2)
        bab_list.append(isi)
        ringkasan = isi.get("pembuka", "")[:400] + " Bagian: " + "; ".join(
            b.get("subjudul", "") for b in isi.get("bagian", [])
        )
        bar.progress((i + 1) / total)
    status.info("Membuat PDF...")
    pdf = os.path.join(folder_proyek(), "ebook.pdf")
    agent.buat_pdf(data, bab_list, pdf, data.get("merek", ""))
    with open(pdf, "rb") as f:
        ss.pdf_bytes = f.read()
    ss.tahap = "selesai"
    st.rerun()

# ----------------------------------------------------------------- Selesai ----
elif ss.tahap == "selesai":
    data = ss.data
    st.success("Ebook-mu sudah jadi! 🎉")
    st.subheader(data["judul_terpilih"]["judul"])
    st.download_button(
        "⬇️ Unduh PDF",
        ss.pdf_bytes,
        file_name=f"{slug(data['judul_terpilih']['judul'])}.pdf",
        mime="application/pdf",
        type="primary",
    )
    st.caption("Unduh sekarang. Isi ebook dibuat oleh AI, jadi baca dan periksa dulu sebelum dipublikasikan.")

st.divider()
st.caption(f"{NAMA} · IGreasacademy")

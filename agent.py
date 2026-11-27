"""
Ebook Agent - Tahap 1
Alur: topik -> outline (JSON) -> kamu pilih judul & edit -> tulis bab satu per satu -> PDF

Cara pakai:
    python agent.py "Strategi menjual lebih mahal" --merek "Nama Brand Kamu"
Opsi:
    --bab 10      jumlah bab (default 10)
    --lanjut      pakai hasil/outline.json yang sudah ada (tidak bikin outline baru)
"""
import os
import re
import sys
import json
import time
import argparse
from xml.sax.saxutils import escape

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")  # ganti lewat .env jika perlu
OUT = "hasil"
BAB_DIR = os.path.join(OUT, "bab")
OUTLINE_PATH = os.path.join(OUT, "outline.json")
PDF_PATH = os.path.join(OUT, "ebook.pdf")


# ---------------------------------------------------------------- Gemini ----
class EbookError(SystemExit):
    """Error dengan pesan yang ramah pengguna (turunan SystemExit supaya aplikasi lama tetap jalan)."""


def get_client(key=None):
    from google import genai
    key = key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise EbookError("Kunci Gemini belum diisi.")
    return genai.Client(api_key=key)


def cek_error(e):
    """Hentikan percobaan ulang untuk error yang tidak akan pulih sendiri."""
    t = str(e)
    tl = t.lower()
    if "perday" in tl or "per day" in tl:
        raise EbookError(
            "Kuota harian Gemini habis. Hasil yang sudah jadi tersimpan. "
            "Coba lanjutkan setelah kuota reset (sekitar jam 15.00 WIB), "
            "atau aktifkan billing di Google AI Studio."
        )
    if "api_key_invalid" in tl or "api key not valid" in tl or "permission_denied" in tl:
        raise EbookError(
            "Kunci Gemini tidak valid atau tidak punya izin. "
            "Periksa lagi kunci yang ditempel (salin utuh dari Google AI Studio)."
        )
    if "not_found" in tl and "model" in tl:
        raise EbookError(
            "Model Gemini yang dipakai tidak tersedia. Hubungi pemilik aplikasi untuk memperbarui nama model."
        )


def ask_json(client, prompt, retries=6):
    from google.genai import types
    for n in range(retries):
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.8
                ),
            )
            return json.loads(r.text)
        except Exception as e:
            cek_error(e)
            print(f"  ! percobaan {n + 1} gagal: {str(e)[:300]}")
            time.sleep(10 * (n + 1))
    raise EbookError("Gagal setelah beberapa percobaan (server Gemini sibuk atau koneksi bermasalah). Coba lagi beberapa menit lagi.")


def ask_text(client, prompt, retries=6):
    for n in range(retries):
        try:
            r = client.models.generate_content(model=MODEL, contents=prompt)
            return r.text.strip()
        except Exception as e:
            cek_error(e)
            print(f"  ! percobaan {n + 1} gagal: {str(e)[:300]}")
            time.sleep(10 * (n + 1))
    return ""


# --------------------------------------------------------------- Langkah ----
def buat_outline(client, topik, n_bab):
    prompt = f"""Kamu penerbit e-book berbahasa Indonesia yang ahli membuat ebook laris untuk pemula.
Topik ebook: {topik}

Tugas:
1. Tentukan sudut pandang yang paling menjual.
2. Buat 3 pilihan judul yang menarik beserta subjudul singkat.
3. Rancang tepat {n_bab} bab. Tiap bab punya judul dan 3 poin pembahasan.
4. Buat 1 tokoh contoh (nama Indonesia) yang dipakai sebagai contoh kasus di sepanjang ebook.
5. Tentukan palet warna (hex 6 digit) yang cocok dengan topik: "utama" (gelap, untuk cover), "aksen" (cerah).

Balas HANYA JSON dengan bentuk:
{{
  "sudut": "...",
  "judul_pilihan": [{{"judul": "...", "subjudul": "..."}}, {{"judul": "...", "subjudul": "..."}}, {{"judul": "...", "subjudul": "..."}}],
  "bab": [{{"judul": "...", "poin": ["...", "...", "..."]}}],
  "tokoh": {{"nama": "...", "deskripsi": "..."}},
  "palet": {{"utama": "#1B3A2F", "aksen": "#D4A957"}}
}}"""
    return ask_json(client, prompt)


def tulis_bab(client, data, i, ringkasan_sebelumnya):
    bab = data["bab"][i]
    judul = data["judul_terpilih"]["judul"]
    daftar = "\n".join(f"{k + 1}. {b['judul']}" for k, b in enumerate(data["bab"]))
    poin = "\n".join(f"- {p}" for p in bab["poin"])
    tokoh = data.get("tokoh", {})
    prompt = f"""Kamu penulis e-book berbahasa Indonesia. Gaya: santai, jelas, praktis, seperti ngobrol dengan teman, tanpa bertele-tele.
Judul ebook: {judul}
Topik: {data['topik']}
Daftar semua bab:
{daftar}

Tokoh contoh: {tokoh.get('nama', '')} - {tokoh.get('deskripsi', '')}
Ringkasan bab sebelumnya: {ringkasan_sebelumnya or '(ini bab pertama)'}

Tulis BAB {i + 1}: {bab['judul']}
Poin yang harus dibahas:
{poin}

Aturan: jangan mengulang isi bab lain, beri contoh konkret, jangan mengarang angka/statistik/fakta yang tidak pasti.
Panjang total sekitar 700-900 kata.

Balas HANYA JSON dengan bentuk:
{{
  "pembuka": "satu paragraf pembuka",
  "bagian": [{{"subjudul": "...", "paragraf": ["...", "..."]}}],
  "tips": ["tips praktis 1", "tips praktis 2", "tips praktis 3"]
}}
Buat satu bagian untuk tiap poin."""
    return ask_json(client, prompt)


# ------------------------------------------------------------------- PDF ----
def bersih(t):
    """Buang karakter yang tidak didukung font standar PDF (mis. emoji), lalu escape."""
    t = str(t).replace("\u2011", "-").replace("\u00a0", " ")
    t = t.encode("cp1252", "ignore").decode("cp1252")
    return escape(t)


def hex_ok(h, default):
    if isinstance(h, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", h.strip()):
        return h.strip()
    return default


def buat_pdf(data, bab_list, path, merek=""):
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.platypus import (
        BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
        PageBreak, Table, TableStyle, NextPageTemplate, KeepTogether,
    )

    palet = data.get("palet", {})
    UTAMA = colors.HexColor(hex_ok(palet.get("utama"), "#1B3A2F"))
    AKSEN = colors.HexColor(hex_ok(palet.get("aksen"), "#D4A957"))
    KERTAS = colors.HexColor("#FAF6EE")
    TEKS = colors.HexColor("#25221E")
    luminans = 0.299 * UTAMA.red + 0.587 * UTAMA.green + 0.114 * UTAMA.blue
    TEKS_COVER = colors.HexColor("#FFFFFF") if luminans < 0.6 else colors.HexColor("#1A1A1A")

    judul = data["judul_terpilih"]["judul"]
    subjudul = data["judul_terpilih"].get("subjudul", "")
    W, H = A5
    M = 18 * mm

    def cover(c, doc):
        c.saveState()
        c.setFillColor(UTAMA)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(AKSEN)
        c.rect(0, H * 0.40, W, 2.5 * mm, fill=1, stroke=0)
        c.setFillColor(TEKS_COVER)
        y = H * 0.72
        for baris in simpleSplit(bersih_plain(judul), "Helvetica-Bold", 26, W - 36 * mm):
            c.setFont("Helvetica-Bold", 26)
            c.drawCentredString(W / 2, y, baris)
            y -= 32
        y = H * 0.40 - 12 * mm
        c.setFont("Helvetica", 11)
        for baris in simpleSplit(bersih_plain(subjudul), "Helvetica", 11, W - 40 * mm):
            c.drawCentredString(W / 2, y, baris)
            y -= 15
        if merek:
            c.setFillColor(AKSEN)
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(W / 2, 16 * mm, bersih_plain(merek).upper())
        c.restoreState()

    def bersih_plain(t):
        return str(t).replace("\u2011", "-").encode("cp1252", "ignore").decode("cp1252")

    def halaman(c, doc):
        c.saveState()
        c.setFillColor(KERTAS)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#8A8478"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(W / 2, 9 * mm, str(doc.page - 1))
        c.restoreState()

    doc = BaseDocTemplate(path, pagesize=A5, leftMargin=M, rightMargin=M,
                          topMargin=M, bottomMargin=M + 4 * mm,
                          title=bersih_plain(judul), author=bersih_plain(merek))
    frame = Frame(M, M + 4 * mm, W - 2 * M, H - 2 * M - 4 * mm, id="f")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=cover),
        PageTemplate(id="isi", frames=[frame], onPage=halaman),
    ])

    s_no = ParagraphStyle("no", fontName="Helvetica-Bold", fontSize=40, leading=44, textColor=AKSEN)
    s_h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=UTAMA, spaceAfter=10)
    s_h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=UTAMA, spaceBefore=10, spaceAfter=4)
    s_body = ParagraphStyle("body", fontName="Times-Roman", fontSize=10.8, leading=15.5, textColor=TEKS, alignment=TA_JUSTIFY, spaceAfter=7)
    s_lead = ParagraphStyle("lead", parent=s_body, fontName="Times-Italic", fontSize=11.5, leading=16.5)
    s_tip_h = ParagraphStyle("tiph", fontName="Helvetica-Bold", fontSize=10, textColor=UTAMA, spaceAfter=3)
    s_tip = ParagraphStyle("tip", fontName="Times-Roman", fontSize=10.2, leading=14, textColor=TEKS, leftIndent=8, bulletIndent=0, spaceAfter=2)
    s_toc_h = ParagraphStyle("toch", parent=s_h1, spaceAfter=14)
    s_toc = ParagraphStyle("toc", fontName="Helvetica", fontSize=10.5, leading=17, textColor=TEKS)
    s_center = ParagraphStyle("center", parent=s_body, alignment=TA_CENTER)

    story = [Spacer(1, 1), NextPageTemplate("isi"), PageBreak()]

    # Daftar isi
    story.append(Paragraph("Daftar Isi", s_toc_h))
    for i, b in enumerate(data["bab"]):
        story.append(Paragraph(f"<font color='{AKSEN.hexval().replace('0x', '#')}'><b>{i + 1}.</b></font>&nbsp;&nbsp;{bersih(b['judul'])}", s_toc))
    story.append(PageBreak())

    # Bab
    for i, isi in enumerate(bab_list):
        story.append(Paragraph(str(i + 1).zfill(2), s_no))
        story.append(Paragraph(bersih(data["bab"][i]["judul"]), s_h1))
        if isi.get("pembuka"):
            story.append(Paragraph(bersih(isi["pembuka"]), s_lead))
        for bag in isi.get("bagian", []):
            story.append(Paragraph(bersih(bag.get("subjudul", "")), s_h2))
            for p in bag.get("paragraf", []):
                story.append(Paragraph(bersih(p), s_body))
        tips = isi.get("tips", [])
        if tips:
            isi_tip = [Paragraph("INTI BAB INI", s_tip_h)]
            isi_tip += [Paragraph(bersih(t), s_tip, bulletText="\u2022") for t in tips]
            kotak = Table([[isi_tip]], colWidths=[W - 2 * M])
            kotak.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFE8D8")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, AKSEN),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(Spacer(1, 6))
            story.append(KeepTogether([kotak]))
        story.append(PageBreak())

    # Penutup
    story.append(Spacer(1, 50 * mm))
    story.append(Paragraph("Terima kasih sudah membaca.", ParagraphStyle("t", parent=s_h1, alignment=TA_CENTER)))
    if merek:
        story.append(Paragraph(bersih(merek), s_center))

    doc.build(story)


# ------------------------------------------------------------------ Main ----
def main():
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("topik", nargs="?", help="Topik ebook")
    ap.add_argument("--merek", default="", help="Nama merek di cover")
    ap.add_argument("--bab", type=int, default=10, help="Jumlah bab")
    ap.add_argument("--lanjut", action="store_true", help="Pakai outline.json yang sudah ada")
    a = ap.parse_args()

    os.makedirs(BAB_DIR, exist_ok=True)
    client = get_client()

    # 1) Outline
    if a.lanjut and os.path.exists(OUTLINE_PATH):
        print("Memakai outline yang sudah ada...")
    else:
        if not a.topik:
            sys.exit('Isi topik, contoh: python agent.py "Strategi menjual lebih mahal"')
        print("Menyusun outline...")
        data = buat_outline(client, a.topik, a.bab)
        data["topik"] = a.topik
        print("\nPilih judul:")
        for k, j in enumerate(data["judul_pilihan"], 1):
            print(f"  {k}. {j['judul']}  -  {j.get('subjudul', '')}")
        while True:
            pilih = input("Nomor judul (1-3): ").strip()
            if pilih in ("1", "2", "3"):
                break
        data["judul_terpilih"] = data["judul_pilihan"][int(pilih) - 1]
        with open(OUTLINE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nOutline disimpan di {OUTLINE_PATH}")
        input("Buka file itu kalau mau edit judul/bab/poin. Selesai? Tekan Enter untuk lanjut menulis... ")

    with open(OUTLINE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # 2) Tulis bab (hasil tiap bab disimpan, jadi bisa dilanjut kalau terputus)
    bab_list, ringkasan = [], ""
    total = len(data["bab"])
    for i in range(total):
        p = os.path.join(BAB_DIR, f"bab_{i + 1:02d}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                isi = json.load(f)
            print(f"Bab {i + 1}/{total} sudah ada, dilewati")
        else:
            print(f"Menulis bab {i + 1}/{total}: {data['bab'][i]['judul']} ...")
            isi = tulis_bab(client, data, i, ringkasan)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(isi, f, ensure_ascii=False, indent=2)
        bab_list.append(isi)
        ringkasan = isi.get("pembuka", "")[:400] + " Bagian: " + "; ".join(
            b.get("subjudul", "") for b in isi.get("bagian", [])
        )

    # 3) PDF
    print("Membuat PDF...")
    buat_pdf(data, bab_list, PDF_PATH, a.merek)
    print(f"\nSelesai! Ebook ada di: {PDF_PATH}")


if __name__ == "__main__":
    main()

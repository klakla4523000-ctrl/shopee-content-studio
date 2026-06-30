"""
Shopee Affiliate Content Studio
================================
แอปช่วยงานนายหน้า Shopee: ป้อนข้อมูลสินค้า -> ให้ AI คิด prompt รูป + prompt วิดีโอ + แคปชั่น Facebook
ให้พร้อมก๊อปไปวางใน Google Flow (Veo) และ Facebook

โหมด:
  - เร็ว (Batch) : พิมพ์ชื่อสินค้าทีละบรรทัด 5-10 ตัว กดทีเดียวได้หมด  <- เร็วสุด
  - เดี่ยว        : กรอกแค่ชื่อ (ที่เหลือ AI คิดเอง) + อัปรูปให้ AI อ่านได้
  - Auto (Shopee API) : ดึงสินค้าอัตโนมัติ (เปิดใช้เมื่อมี API key)

รัน:  streamlit run shopee_affiliate_app.py
"""

import json
import sqlite3
import datetime
import tempfile
from pathlib import Path

import streamlit as st

APP_TITLE = "Shopee Affiliate Content Studio"
# เก็บฐานข้อมูลในโฟลเดอร์ที่เขียนได้เสมอ (สำคัญบน Streamlit Cloud ที่โฟลเดอร์โค้ดอ่านอย่างเดียว)
DB_PATH = Path(tempfile.gettempdir()) / "shopee_history.db"

STYLE_GUIDE = """\
You write production-ready prompts for Thai e-commerce affiliate content.
The user may give you only a product NAME (or an image). When details are missing,
INTELLIGENTLY INFER realistic selling points, colors, target audience, and captions
for that product type yourself — do not ask back, just produce great content.

Always follow this proven structure and tone:

VIDEO PROMPT (for Google Flow / Veo, 10 seconds, 6 shots):
- Minimalist product video ad, PRODUCT ONLY (no people, no faces, no full body).
- Off-white clean studio background, soft natural lighting, premium calm cute mood.
- Smooth slow camera movements, "iPhone 17 Pro" look.
- The product MUST stay 100% identical to the reference in every shot (no redesign,
  consistent colors in all frames).
- 6 timed shots: 0.0-1.6 / 1.6-3.3 / 3.3-5.0 / 5.0-6.6 / 6.6-8.3 / 8.3-10.0 s.
- Each shot has a cute rounded Thai on-screen caption (white text, soft shadow).
- Shot ideas tailored to THIS product's real selling points.
- End with a strong Thai CTA caption.
- Include a Negative list (wrong colors, redesigned subject, distorted text,
  people, faces, cluttered background, harsh shadows, shaky camera, watermark).

IMAGE / STORYBOARD PROMPT:
- ONE clean storyboard sheet, white/off-white background, premium minimal e-commerce.
- 2x3 grid of 6 numbered panels matching the 6 video shots.
- Thai header title + sub-row (เวลารวม 10 วินาที · 6 ช็อต · จุดเด่น · จำนวนสี).
- Icon legend row: มุมกล้อง / การเคลื่อนไหว / จุดเด่น / เวลา.
- Match the reference product exactly, product only.
- Footer: ถ่ายด้วย iPhone 17 Pro · เพลง lo-fi + ASMR · โทนมินิมอล · ไม่มีคน เน้นสินค้า.

FACEBOOK CAPTION:
- Thai, punchy. Structure: hook -> 2-3 benefit lines -> CTA -> affiliate link placeholder -> hashtags.
- Friendly, sales-y but not spammy. A few tasteful emojis.

Return STRICT JSON only, keys: "image_prompt", "video_prompt", "facebook_caption".
No markdown, no commentary outside the JSON.
"""


# --------------------------- DB ---------------------------
def init_db():
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT, product_name TEXT, link TEXT,
                image_prompt TEXT, video_prompt TEXT, facebook_caption TEXT)"""
        )
        con.commit()
        con.close()
    except Exception:
        pass  # ฐานข้อมูลไม่พร้อมก็ไม่เป็นไร แอปยังทำงานได้


def save_history(product_name, link, result):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT INTO history (created_at, product_name, link, image_prompt, video_prompt, facebook_caption) VALUES (?,?,?,?,?,?)",
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                product_name, link,
                result.get("image_prompt", ""), result.get("video_prompt", ""),
                result.get("facebook_caption", ""),
            ),
        )
        con.commit()
        con.close()
    except Exception:
        pass


def load_history(limit=30):
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT created_at, product_name, link, image_prompt, video_prompt, facebook_caption "
            "FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
        return rows
    except Exception:
        return []


# --------------------------- Gemini ---------------------------
def _model(api_key, model_name):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name, system_instruction=STYLE_GUIDE)


def _parse_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip("`").replace("json", "", 1).strip()
        return json.loads(cleaned)


def generate(api_key, model_name, product_info, images=None):
    """images: list ของ dict {'mime_type','data'} (ไม่บังคับ) -> ให้ AI อ่านรูปเดารายละเอียด"""
    model = _model(api_key, model_name)
    user_msg = f"""\
สร้างชุดคอนเทนต์สำหรับสินค้านี้ (แคปชั่น/ข้อความบนจอเป็นภาษาไทย):

ชื่อสินค้า: {product_info.get('name') or '(ดูจากรูป)'}
ประเภท/หมวด: {product_info.get('category') or '(ให้ AI เดา)'}
สี/ตัวเลือก: {product_info.get('colors') or '(ให้ AI เดาให้เหมาะ)'}
จุดเด่น/สรรพคุณ: {product_info.get('features') or '(ให้ AI คิดจุดขายที่น่าจะจริง)'}
ราคา: {product_info.get('price') or '-'}
ลิงค์นายหน้า: {product_info.get('link') or '[วางลิงค์นายหน้าที่นี่]'}
กลุ่มเป้าหมาย: {product_info.get('audience') or '(ให้ AI เดา)'}

คิด prompt รูป storyboard, prompt วิดีโอ 10 วิ 6 ช็อต, และแคปชั่น Facebook ให้เหมาะกับสินค้านี้
ตอบเป็น JSON เท่านั้น (image_prompt, video_prompt, facebook_caption)."""

    parts = [user_msg]
    if images:
        parts.extend(images)

    resp = model.generate_content(
        parts,
        generation_config={"response_mime_type": "application/json", "temperature": 0.8},
    )
    return _parse_json(resp.text)


# --------------------------- UI helpers ---------------------------
def copy_block(label, content):
    st.markdown(f"**{label}**")
    st.code(content, language="text")


def render_result(r):
    copy_block("🖼️ Prompt รูป (Storyboard)", r.get("image_prompt", ""))
    copy_block("🎬 Prompt วิดีโอ (Flow / Veo)", r.get("video_prompt", ""))
    copy_block("📝 แคปชั่น Facebook", r.get("facebook_caption", ""))


# --------------------------- App ---------------------------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🛍️", layout="wide")
    init_db()
    st.title("🛍️ " + APP_TITLE)
    st.caption("ป้อนสินค้า → AI คิด prompt รูป + วิดีโอ + แคปชั่น Facebook พร้อมก๊อปไปใช้")

    with st.sidebar:
        st.header("⚙️ ตั้งค่า")
        api_key = st.text_input("Gemini API Key", type="password",
                                help="ขอฟรีที่ aistudio.google.com")
        model_name = st.selectbox("โมเดล",
                                  ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"], index=0)
        st.divider()
        mode = st.radio("โหมดทำงาน",
                        ["⚡ เร็ว (หลายตัวรวด)", "ทีละตัว", "Auto (Shopee API)"])
        if mode.startswith("Auto"):
            st.info("โหมด Auto จะเปิดเมื่อ Shopee Affiliate API อนุมัติ")

    tab_make, tab_history = st.tabs(["✨ สร้างคอนเทนต์", "🕑 ประวัติ"])

    with tab_make:
        # ---------- โหมดเร็ว Batch ----------
        if mode.startswith("⚡"):
            st.subheader("⚡ โหมดเร็ว — พิมพ์ทีละบรรทัด แล้วกดทีเดียว")
            st.caption("พิมพ์แค่ชื่อสินค้าก็พอ (AI คิดที่เหลือเอง) "
                       "ถ้าอยากใส่จุดเด่นด้วย ใช้รูปแบบ: ชื่อสินค้า | จุดเด่น | สี")
            bulk = st.text_area(
                "รายการสินค้า (บรรทัดละ 1 ตัว)",
                height=180,
                placeholder="รองเท้าแตะพื้นนุ่ม ลายการ์ตูน | กดเด้งไม่ปวดเท้า | ขาว/น้ำตาล/ส้ม/เหลือง\n"
                            "กระเป๋าสะพายหนัง 3 ช่อง\nหมอนรองคอเมมโมรี่โฟม\nขวดน้ำเก็บความเย็น 24 ชม.",
            )
            link_note = st.text_input("ลิงค์นายหน้า (ใส่ทีหลังก็ได้ ปล่อยว่างได้)", "")
            if st.button("🚀 สร้างทั้งหมด", type="primary", use_container_width=True):
                if not api_key:
                    st.error("ใส่ Gemini API Key ในแถบซ้ายก่อน")
                else:
                    lines = [l.strip() for l in bulk.splitlines() if l.strip()]
                    if not lines:
                        st.error("ใส่อย่างน้อย 1 บรรทัด")
                    else:
                        prog = st.progress(0.0)
                        for i, line in enumerate(lines, 1):
                            seg = [s.strip() for s in line.split("|")]
                            info = {
                                "name": seg[0],
                                "features": seg[1] if len(seg) > 1 else "",
                                "colors": seg[2] if len(seg) > 2 else "",
                                "link": link_note,
                            }
                            try:
                                r = generate(api_key, model_name, info)
                                save_history(seg[0], link_note, r)
                                with st.expander(f"✅ {seg[0]}", expanded=False):
                                    render_result(r)
                            except Exception as e:
                                st.error(f"'{seg[0]}' ผิดพลาด: {e}")
                            prog.progress(i / len(lines))
                        st.success(f"เสร็จ {len(lines)} ตัว! ดูในแต่ละแถบ หรือแท็บ 'ประวัติ'")

        # ---------- โหมด Auto ----------
        elif mode.startswith("Auto"):
            st.warning("ยังไม่ได้เชื่อม Shopee API — ใช้โหมด ⚡ เร็ว หรือ ทีละตัว ไปก่อน")

        # ---------- โหมดทีละตัว ----------
        else:
            st.subheader("ทีละตัว — กรอกแค่ชื่อก็พอ ที่เหลือ AI คิดให้")
            name = st.text_input("ชื่อสินค้า*", placeholder="รองเท้าแตะแบบสวม ลายการ์ตูน")
            category = colors = price = features = link = audience = ""
            with st.expander("➕ ใส่รายละเอียดเพิ่ม (ไม่บังคับ)"):
                c1, c2 = st.columns(2)
                with c1:
                    category = st.text_input("ประเภท/หมวด")
                    colors = st.text_input("สี/ตัวเลือก")
                    price = st.text_input("ราคา")
                with c2:
                    features = st.text_area("จุดเด่น/สรรพคุณ", height=90)
                    link = st.text_input("ลิงค์นายหน้า")
                    audience = st.text_input("กลุ่มเป้าหมาย")
          
import os
import time
import tempfile
import textwrap
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from instagrapi import Client
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
IG_SESSIONID = unquote(os.getenv("IG_SESSIONID", "").strip())
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip().lower().lstrip("@")


# --- Render.com 24/7 uchun mini veb-server ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Instagram AI Bot is running!")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


threading.Thread(target=run_web_server, daemon=True).start()


# --- 1. Gemini AI sozlash ---
ai_client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = None
for m in ai_client.models.list():
    actions = getattr(m, "supported_actions", []) or []
    if "generateContent" in actions and "gemini" in m.name and "2.5-flash" not in m.name:
        try:
            ai_client.models.generate_content(model=m.name, contents="Salom")
            MODEL_NAME = m.name
            break
        except Exception:
            continue

if not MODEL_NAME:
    raise RuntimeError("API kalit uchun ishlaydigan Gemini modeli topilmadi!")

print(f"Tanlangan Gemini modeli: {MODEL_NAME}")

SYSTEM_PROMPT = (
    "Sen Javlonning Instagram profilida do'stona va tabiiy javob beradigan yordamchisan. "
    "Javlon Samarqandda universitetda o'qiydi. "
    "O'zingni 'men botman' yoki 'haqiqiy inson emasman' deb tanishtirma. "
    "Qisqa (1-2 ta gap), samimiy, tabiiy o'zbek tilida javob yoz. "
    "'Sizga qanday yordam bera olaman?' kabi rasmiy shablon gaplarni ishlatma."
)


# --- 2. Instagram'ga ulanish (sessionid bilan) ---
cl = Client()
cl.delay_range = [1, 3]
cl.login_by_sessionid(IG_SESSIONID)

MY_USER_ID = str(cl.user_id)
print(f"Muvaffaqiyatli ulandi! User ID: {MY_USER_ID}")


# --- 3. Video va matn funksiyalari ---
def resolve_direct_mp4(url: str) -> str | None:
    if "instagram.com/" in url and ("/reel/" in url or "/p/" in url or "/tv/" in url):
        try:
            pk = cl.media_pk_from_url(url)
            info = cl.media_info(pk)
            if getattr(info, "video_url", None):
                return str(info.video_url)
        except Exception as e:
            print(f"Media ma'lumotini olishda xato: {e}")
            return None
    return url


def get_video_url(msg) -> str | None:
    for attr in ("clip", "media", "media_share", "felix_share"):
        obj = getattr(msg, attr, None)
        if obj and getattr(obj, "video_url", None):
            return resolve_direct_mp4(str(obj.video_url))

    xma = getattr(msg, "xma_share", None)
    if xma:
        raw_url = getattr(xma, "video_url", None) or getattr(xma, "target_url", None)
        if raw_url:
            return resolve_direct_mp4(str(raw_url))

    vm = getattr(msg, "visual_media", None)
    if vm and isinstance(vm, dict):
        media = vm.get("media", {})
        versions = media.get("video_versions", [])
        if versions:
            return versions[0].get("url")

    return None


def ask_gemini_text(prompt: str, use_system: bool = True) -> str:
    config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT) if use_system else None
    response = ai_client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=config,
    )
    return response.text.strip()


def ask_gemini_video(video_url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    res = requests.get(video_url, headers=headers, timeout=30)
    res.raise_for_status()

    content_type = res.headers.get("Content-Type", "")
    if "text/html" in content_type or len(res.content) < 10_000:
        raise ValueError(f"Haqiqiy video yuklanmadi (Content-Type: {content_type}).")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(res.content)
        tmp_path = tmp.name

    video_file = None
    try:
        video_file = ai_client.files.upload(
            file=tmp_path,
            config={"mime_type": "video/mp4"},
        )

        for _ in range(30):
            state = getattr(video_file.state, "name", str(video_file.state))
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise RuntimeError("Gemini serveri videoni qayta ishlay olmadi (FAILED).")
            time.sleep(2)
            video_file = ai_client.files.get(name=video_file.name)
        else:
            raise TimeoutError("Video qayta ishlanishi juda uzoq cho'zildi.")

        response = ai_client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                video_file,
                "Bu videoda nima bo'layotganini ko'rib, o'zbek tilida 1-2 ta qisqa, qiziqarli va tabiiy izoh yoz.",
            ],
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        return response.text.strip()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if video_file:
            try:
                ai_client.files.delete(name=video_file.name)
            except Exception:
                pass


# --- 4. SMM-Menejer funksiyalari ---
def analyze_profile() -> str:
    info = cl.user_info(cl.user_id)
    medias = cl.user_medias(cl.user_id, amount=5)
    avg_likes = round(sum(m.like_count for m in medias) / len(medias), 1) if medias else 0

    summary = (
        f"Username: @{info.username}\n"
        f"Ism: {info.full_name}\n"
        f"Bio: {info.biography or 'Bo`sh'}\n"
        f"Obunachilar: {info.follower_count} | Obunalar: {info.following_count}\n"
        f"Postlar soni: {info.media_count} | Oxirgi 5 post o'rtacha layk: {avg_likes}\n"
        f"Profil holati: {'Yopiq (Private)' if info.is_private else 'Ochiq (Public)'}\n"
        f"Biznes/Professional akkount: {'Ha' if info.is_business else 'Yo`q'}"
    )
    prompt = (
        "Sen tajribali SMM-menejersan. Quyidagi Instagram profil ma'lumotlarini tahlil qil "
        "va o'zbek tilida qisqa, aniq 3-4 ta amaliy tavsiya ber (bio, sozlamalar va faollik bo'yicha):\n\n"
        f"{summary}"
    )
    return ask_gemini_text(prompt, use_system=False)


def update_bio(new_bio: str) -> str:
    if new_bio.lower() == "auto":
        info = cl.user_info(cl.user_id)
        prompt = (
            f"Instagram profil (@{info.username}, hozirgi bio: '{info.biography}') uchun "
            "o'zbek tilida zamonaviy, qisqa (maksimal 120 belgi) va chiroyli yangi bio yoz. "
            "Faqat bio matnining o'zini qaytar."
        )
        new_bio = ask_gemini_text(prompt, use_system=False)[:145]

    cl.account_edit(biography=new_bio)
    return f"Bio muvaffaqiyatli yangilandi:\n\n{new_bio}"


def post_text_story(text: str) -> str:
    img = Image.new("RGB", (1080, 1920), color=(18, 22, 34))
    draw = ImageDraw.Draw(img)

    font = None
    for font_name in ("arial.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(font_name, 64)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    wrapped = textwrap.fill(text, width=22)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1080 - text_w) / 2
    y = (1920 - text_h) / 2

    draw.multiline_text((x, y), wrapped, fill=(245, 247, 250), font=font, align="center", spacing=18)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name, "JPEG", quality=95)
        tmp_path = tmp.name

    try:
        cl.photo_upload_to_story(tmp_path)
        return "Story muvaffaqiyatli joylandi!"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def reply_recent_comments() -> str:
    medias = cl.user_medias(cl.user_id, amount=3)
    replied = 0

    for media in medias:
        if replied >= 3:
            break
        comments = cl.media_comments(media.id, amount=10)
        for c in comments:
            if replied >= 3:
                break
            if str(c.user.pk) == MY_USER_ID:
                continue
            reply_text = ask_gemini_text(
                f"Instagram postim ostiga '{c.text}' deb komment yozishdi. "
                "O'zbek tilida juda qisqa (1 ta gap), samimiy javob yoz."
            )
            cl.media_comment(media.id, f"@{c.user.username} {reply_text}", replied_to_comment_id=c.pk)
            replied += 1
            time.sleep(3)

    return f"Kommentlar tekshirildi. Jami {replied} ta kommentga javob yozildi."


def handle_admin_command(thread, text: str) -> bool:
    if not text or not text.startswith("!"):
        return False

    sender_usernames = [u.username.lower() for u in (thread.users or [])]
    if ADMIN_USERNAME and ADMIN_USERNAME not in sender_usernames:
        return False

    cmd = text.strip()
    low = cmd.lower()

    if low == "!yordam":
        msg = (
            "SMM-Menejer buyruqlari:\n"
            "• !tahlil — Profil, bio va sozlamalarni tahlil qilish\n"
            "• !bio auto — Gemini yozgan yangi bioni qo'yish\n"
            "• !bio <matn> — Bioni o'zingiz xohlagan matnga o'zgartirish\n"
            "• !story <matn> — Matnli rasm yasab Story joylash\n"
            "• !komment — Oxirgi postlardagi kommentlarga javob berish"
        )
    elif low == "!tahlil":
        msg = analyze_profile()
    elif low.startswith("!bio "):
        msg = update_bio(cmd[5:].strip())
    elif low.startswith("!story "):
        msg = post_text_story(cmd[7:].strip())
    elif low == "!komment":
        msg = reply_recent_comments()
    else:
        return False

    cl.direct_send(msg, thread_ids=[thread.id])
    print(f"[Admin buyrug'i bajarildi]: {cmd}")
    return True


def build_chat_history(messages) -> str:
    lines = []
    for m in reversed(messages[:6]):
        if m.text:
            sender = "Men" if str(m.user_id) == MY_USER_ID else "Suhbatdosh"
            lines.append(f"{sender}: {m.text}")
    return "\n".join(lines)


# --- 5. Asosiy sikl ---
processed_ids = set()
for thread in cl.direct_threads(amount=10) + cl.direct_pending_inbox(amount=5):
    for m in thread.messages:
        processed_ids.add(m.id)

print("Bot ishga tushdi! Direct, Reels va SMM-menejer faol...")

while True:
    try:
        threads = cl.direct_threads(amount=5) + cl.direct_pending_inbox(amount=5)
        for thread in threads:
            if not thread.messages:
                continue

            last_msg = thread.messages[0]

            if str(last_msg.user_id) == MY_USER_ID or last_msg.id in processed_ids:
                continue

            processed_ids.add(last_msg.id)
            print(f"[Yangi xabar] Turi: {last_msg.item_type} | Matn: {last_msg.text}")

            if last_msg.text and handle_admin_command(thread, last_msg.text):
                continue

            video_url = get_video_url(last_msg)

            if video_url:
                print("[Video/Reels topildi] — Gemini tahlil qilmoqda...")
                reply = ask_gemini_video(video_url)
                cl.direct_send(reply, thread_ids=[thread.id])
                print(f"Videoga javob yuborildi: {reply}")

            elif last_msg.text:
                history = build_chat_history(thread.messages)
                reply = ask_gemini_text(history)
                cl.direct_send(reply, thread_ids=[thread.id])
                print(f"Matnga javob yuborildi: {reply}")

            else:
                print(f"[O'tkazib yuborildi] Video URL topilmadi. Xabar turi: {last_msg.item_type}")

    except Exception as e:
        print(f"Xatolik: {e}")

    time.sleep(20)
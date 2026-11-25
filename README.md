# Instagram AI SMM Manager Bot

Google Gemini va `instagrapi` asosida ishlaydigan aqlli Instagram yordamchi va SMM-menejer boti.

## Imkoniyatlari
- **Direct & Reels javoblari:** Shaxsiy xabarlar (jumladan *Requests*) hamda yuborilgan Reels/videolarni tahlil qilib, tabiiy o'zbek tilida javob yozadi.
- **SMM-Menejer buyruqlari (Admin uchun):**
  - `!yordam` — barcha buyruqlar ro'yxati
  - `!tahlil` — profil, bio, sozlamalar va oxirgi postlar statistikasini tahlil qilish
  - `!bio auto` — Gemini yordamida yangi bio yaratib, avtomatik o'rnatish
  - `!bio <matn>` — bioni qo'lda yangilash
  - `!story <matn>` — matndan rasm yasab, mustaqil Story joylash
  - `!komment` — oxirgi postlardagi kommentlarga avtomatik javob yozish
- **24/7 ishlash:** Render.com kabi platformalar uchun o'rnatilgan mini HTTP-server (`HealthHandler`).

## O'rnatish va ishga tushirish

1. Kutubxonalarni o'rnating:
   ```bash
   pip install -r requirements.txt
   ```

2. Loyiha papkasida `.env` faylini yarating va quyidagi o'zgaruvchilarni kiriting:
   ```env
   GEMINI_API_KEY=sizning_gemini_api_kalitingiz
   IG_SESSIONID=sizning_instagram_sessionid
   ADMIN_USERNAME=admin_akkount_username
   ```

3. Botni ishga tushiring:
   ```bash
   python bot.py
   ```

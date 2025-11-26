# 🚀 Render এ Deploy করার সহজ গাইড

## তথ্য যা লাগবে

✅ **GitHub Repository**: https://github.com/s28626198-sys/rrrincome24-7
✅ **Branch**: main
✅ **Supabase Database**: https://sgnnqvfoajqsfdyulolm.supabase.co

---

## Render Configuration

### Service Settings:
```
Name: whatsapp-otp-bot
Region: Singapore
Branch: main
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: python telegram_bot_deploy.py
Instance Type: Free
```

### Environment Variables:
```
BOT_TOKEN=8419074330:AAGGPd9rZEFPgbfzEadJtsWg4mouVLWKZns
ADMIN_ID=7325836764
SITE_USERNAME=9475595762
SITE_PASSWORD=raja0000
DATABASE_URL=postgresql://postgres:53561106@Tojo@db.sgnnqvfoajqsfdyulolm.supabase.co:5432/postgres
```

---

## ধাপে ধাপে Deployment

### 1️⃣ Supabase Database Setup

1. যান: https://sgnnqvfoajqsfdyulolm.supabase.co
2. SQL Editor খুলুন
3. `supabase_setup.sql` ফাইলের কোড run করুন
4. Success message দেখুন

### 2️⃣ Render এ Deploy

1. যান: https://dashboard.render.com
2. **New +** → **Web Service**
3. GitHub repository connect করুন: `rrrincome24-7`
4. উপরের Settings দিন
5. Environment Variables add করুন
6. **Create Web Service** ক্লিক করুন

### 3️⃣ Deployment Check

Logs এ এগুলো দেখা যাবে:
```
[OK] PostgreSQL connected
[OK] All sites logged in successfully
[OK] Bot started successfully!
```

### 4️⃣ Test Bot

Telegram এ bot খুলে `/start` পাঠান!

---

## 🎉 সম্পন্ন!

Bot এখন **24/7 online** এবং **production ready**!

কোনো সমস্যা হলে `DEPLOYMENT_GUIDE.md` দেখুন।


# نصب ربات مارکتینگ (میلاد)

۱) پوشه robot-marketing را در /root/robot-marketing بگذار.
۲) apt-get install -y python3-venv ffmpeg
۳) python3 -m venv /root/robot-marketing/venv
   /root/robot-marketing/venv/bin/pip install "python-telegram-bot[all]" anthropic openai openpyxl flask
۴) .env را پر کن (OPENAI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN). chmod 600 .env
۵) cp robot-marketing.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now robot-marketing

امکانات:
- متن/ویس → Claude Opus داده را در جدول می‌چیند (ویس: ffmpeg→mp3→OpenAI)
- ویرایش با متن/ویس: «ردیف ۳ تتر را ۲۰ کن» یا «اینو ویرایش کن» (آخرین ردیف خودش)
- داشبورد پورت 8080 (رمز robot1234): ویرایش سلولی + افزودن دستی + حذف + تغییر رمز
- محدودیت ۳ کارمند (MAX_EMPLOYEES)؛ اولین /start مدیر می‌شود
- فیلد دلخواه: /field <اسم> (در ربات+سایت+اکسل می‌آید)
- توکن هر مشتری: TELEGRAM_BOT_TOKEN در .env + systemctl restart robot-marketing
- نکته: credit حساب Anthropic باید شارژ بماند وگرنه parse کار نمی‌کند

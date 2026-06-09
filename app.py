#!/usr/bin/env python3
"""Ilovani ishga tushirish uchun kirish nuqtasi (entrypoint).

`app/` paketi bilan ziddiyat bermaydi: bu fayl skript sifatida
(`python app.py`) ishga tushadi, shu sababli `from app.main import main`
to'g'ri `app/` paketidan import qiladi.
"""
from app.main import main

if __name__ == "__main__":
    main()

FROM python:3.10-slim

# Kerakli tizim kutubxonalarini o'rnatish:
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Ilova katalogiga o'tish
WORKDIR /userbot_for_logistic

# Faqat requirements.txt faylini ko'chirish
COPY requirements.txt .

# Pip, setuptools va wheel'ni yangilash, so'ng kutubxonalarni o'rnatish
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Ilovaning qolgan qismini ko'chirish
COPY . .

# Ilovani ishga tushirish (bu yerda 'uzbek.py' ilovangizning asosiy fayli deb hisoblaymiz)
CMD ["python", "uzbek.py"]

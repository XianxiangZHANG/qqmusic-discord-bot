FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# discord.py 2.7.1 uses the davey 0.1 API.
RUN pip install --no-cache-dir "discord.py[voice]==2.7.1" "davey==0.1.7"
RUN pip install --no-cache-dir "qqmusic-api-python==0.7.3"
WORKDIR /app
COPY bot.py qq_login.py qq_provider.py ./
CMD ["python", "-u", "bot.py"]

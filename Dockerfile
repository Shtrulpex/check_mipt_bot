FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 admissions \
    && useradd --uid 10001 --gid admissions --create-home admissions

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=admissions:admissions main.py ./
COPY --chown=admissions:admissions bot ./bot
COPY --chown=admissions:admissions database ./database
COPY --chown=admissions:admissions parser ./parser

USER admissions

CMD ["python", "main.py"]

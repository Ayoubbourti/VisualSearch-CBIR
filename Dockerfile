# Image unique pour l'API de descripteurs et l'application web (la commande diffère : voir docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 APP_ENV=production

# Utilisateur non privilégié : un exploit dans l'application ne donne pas les droits root du conteneur.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
RUN mkdir -p /data && chown app:app /data
USER app

ENV GALLERY_DB=/data/gallery.db GALLERY_STORAGE=/data/storage
VOLUME /data
EXPOSE 5000 5001

# Par défaut : application web (2 workers). L'API est lancée par docker-compose.
CMD ["gunicorn", "-w", "2", "--threads", "4", "-b", "0.0.0.0:5000", "--access-logfile", "-", "wsgi:app"]

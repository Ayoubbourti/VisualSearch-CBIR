"""Point d'entrée WSGI pour la production :  gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app
(sous Windows : waitress-serve --port=5000 wsgi:app)"""
from webapp import create_app

app = create_app()

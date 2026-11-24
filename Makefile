# Raccourcis (Linux/macOS ; sous Windows, lancer les commandes à la main ou via WSL).
PY ?= python

.PHONY: install dev test cov lint run api web index eval report docker clean

install:        ## dépendances d'exécution
	$(PY) -m pip install -r requirements.txt
dev:            ## dépendances de développement (tests, lint, rapport)
	$(PY) -m pip install -r requirements-dev.txt
test:           ## suite de tests
	$(PY) -m pytest
cov:            ## tests + couverture
	$(PY) -m pytest --cov=api --cov=webapp --cov=scripts --cov-report=term-missing
lint:           ## analyse statique
	$(PY) -m ruff check .
run:            ## API + application web (développement)
	$(PY) run_all.py
api:
	$(PY) -m api.app
web:
	$(PY) -m flask --app wsgi:app run --port 5000
index:          ## make index FOLDER=data/ghim-10k USER=admin
	$(PY) scripts/index_dataset.py --folder $(FOLDER) --username $(or $(USER),admin) --workers 2
eval:           ## évaluation (protocole classique puis strict) + figures
	$(PY) scripts/evaluate.py --output results/eval_classic.csv
	$(PY) scripts/evaluate.py --exclude-judged --output results/eval_strict.csv
	$(PY) scripts/make_figures.py results/eval_classic_summary.csv results/eval_strict_summary.csv
report:         ## rapport Word (+ PDF si LibreOffice est installé)
	$(PY) docs/build_report.py --results results/eval_classic_summary.csv --strict results/eval_strict_summary.csv
docker:
	docker compose up --build
clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

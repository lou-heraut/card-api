# Interface de déploiement — usage : make <cible>
# Prérequis : docker + docker compose, fichier .env (cf. .env.example).

.PHONY: help env up update logs status stats down test
.ONESHELL:

help:            ## liste des cibles
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

env:             ## crée .env depuis l'exemple (à éditer ensuite)
	@test -f .env || (cp .env.example .env \
	  && sed -i "s/changez-moi/$$(openssl rand -hex 16)/" .env \
	  && echo ".env créé (sel généré) — éditer DOMAIN puis: make up")

up: env          ## construit et lance (première fois ou après modif locale)
	docker compose up -d --build

update:          ## met à jour le code et redéploie
	git pull --ff-only
	docker compose up -d --build
	@$(MAKE) --no-print-directory status

logs:            ## suit les logs de l'API
	docker compose logs -f api

status:          ## état des conteneurs + sonde de vie
	@docker compose ps
	@docker compose exec api python -c "import urllib.request; \
	  print(urllib.request.urlopen('http://localhost:8000/v1/health').read().decode())" \
	  || echo "API injoignable"

stats:           ## statistiques d'usage (journal anonymisé)
	@docker compose exec api python - <<-'EOF'
	import json, collections
	try:
	    lines = [json.loads(l) for l in open("/data/usage.jsonl")]
	except FileNotFoundError:
	    print("aucun usage enregistré"); raise SystemExit
	by_ep = collections.Counter(e["endpoint"] for e in lines)
	users = len({e["user"] for e in lines})
	cards = collections.Counter(c for e in lines for c in e.get("cards", []))
	print(f"{len(lines)} requêtes de calcul, {users} utilisateurs distincts")
	print("par endpoint :", dict(by_ep))
	print("fiches les plus demandées :", cards.most_common(10))
	EOF

down:            ## arrête le service
	docker compose down

test:            ## suite de tests (dev, hors Docker)
	.python_env/bin/python -m pytest -q

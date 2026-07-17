# Interface de déploiement. Usage : make <cible>
# Prérequis : docker + docker compose, fichier .env (cf. .env.example).

.PHONY: help env up apache update logs status stats watch key keys key-revoke down test
.ONESHELL:

help:            ## liste des cibles
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

env:             ## crée .env depuis l'exemple (à éditer ensuite)
	@test -f .env || (cp .env.example .env \
	  && sed -i "s/changez-moi/$$(openssl rand -hex 16)/" .env \
	  && echo ".env créé (sel généré), éditer DOMAIN puis: make up")

up: env          ## construit et lance (première fois ou après modif locale)
	docker compose up -d --build

apache:          ## génère et active le vhost Apache (DOMAIN lu dans .env)
	@set -e
	test -f .env || { echo "pas de .env : make env, puis éditer DOMAIN"; exit 1; }
	DOMAIN=$$(sed -n 's/^DOMAIN=//p' .env)
	test -n "$$DOMAIN" || { echo "DOMAIN manquant dans .env"; exit 1; }
	PORT=$$(sed -n 's/^CARD_API_PORT=//p' .env); PORT=$${PORT:-8000}
	printf '%s\n' \
	  "# Généré par « make apache » (card-api) ; DOMAIN vient de .env." \
	  "<VirtualHost *:80>" \
	  "    ServerName $$DOMAIN" \
	  "    ProxyPreserveHost On" \
	  "    ProxyPass        / http://127.0.0.1:$$PORT/" \
	  "    ProxyPassReverse / http://127.0.0.1:$$PORT/" \
	  "</VirtualHost>" \
	  | sudo tee /etc/apache2/sites-available/card-api.conf >/dev/null
	sudo a2enmod -q proxy proxy_http
	sudo a2ensite -q card-api
	sudo apachectl configtest
	sudo systemctl reload apache2
	echo "vhost actif : http://$$DOMAIN/"
	case "$$DOMAIN" in
	  *[a-zA-Z]*) echo "HTTPS : sudo certbot --apache -d $$DOMAIN" ;;
	  *) echo "HTTPS impossible sur une IP nue ; il faudra un nom de domaine." ;;
	esac

update:          ## met à jour le code et redéploie
	git pull --ff-only
	docker compose up -d --build
	@$(MAKE) --no-print-directory status

logs:            ## suit les logs de l'API
	docker compose logs -f api

status:          ## état des conteneurs + sonde de vie
	@docker compose ps
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
	  docker compose exec api python -c "import urllib.request; \
	    print(urllib.request.urlopen('http://localhost:8000/v1/health').read().decode())" \
	    2>/dev/null && exit 0; \
	  sleep 1; \
	done; echo "API injoignable après 10 s"; exit 1

stats:           ## tableau de bord (usage, file de calcul, disque)
	@docker compose exec api python -m card_api.stats

watch:           ## tableau de bord rafraîchi en continu (Ctrl-C pour sortir)
	@docker compose exec api python -m card_api.stats --watch

key:             ## crée une clé de priorité : make key name="Prénom Nom, labo"
	@docker compose exec api python -m card_api.keys add "$(name)"

keys:            ## liste les clés de priorité
	@docker compose exec api python -m card_api.keys list

key-revoke:      ## révoque une clé : make key-revoke key=<jeton, préfixe ou nom>
	@docker compose exec api python -m card_api.keys revoke "$(key)"

down:            ## arrête le service
	docker compose down

test:            ## suite de tests (dev, hors Docker)
	.python_env/bin/python -m pytest -q

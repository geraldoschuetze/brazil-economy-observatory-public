.PHONY: help env up down restart logs ps psql test clean om-up om-down om-logs om-automate om-genkeys tunnel-up tunnel-down tunnel-logs superset-diff superset-apply superset-bootstrap superset-capture

OM_COMPOSE := docker compose -f infra/openmetadata/docker-compose.openmetadata.yml --env-file infra/openmetadata/openmetadata.env
TUNNEL_COMPOSE := docker compose -f infra/cloudflared/docker-compose.cloudflared.yml

help:           ## Show this help
	@grep -E '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

env:            ## Generate .env with random secrets (no-op if it exists)
	@bash scripts/gen_env.sh

up: env         ## Start the full stack (Postgres + Airflow + Superset)
	@mkdir -p dags logs plugins config include
	docker compose up -d

down:           ## Stop the stack (data volumes are kept)
	docker compose down

restart: down up ## Restart the stack

logs:           ## Tail logs from all services
	docker compose logs -f --tail=100

ps:             ## Show container status
	docker compose ps

psql:           ## Open psql on the brazil_economy warehouse
	docker compose exec postgres psql -U brazil_economy -d brazil_economy

test:           ## Run unit tests + doctests (pure helpers, no Docker needed)
	pytest -q

om-up:          ## Start OpenMetadata (needs infra/openmetadata/openmetadata.env)
	$(OM_COMPOSE) up -d

om-down:        ## Stop OpenMetadata (volumes kept)
	$(OM_COMPOSE) down

om-logs:        ## Tail OpenMetadata logs
	$(OM_COMPOSE) logs -f --tail=100

om-automate:    ## Deploy native OM pipelines + bot, register om_ingest token in Airflow
	@bash scripts/om_automation_setup.sh

om-genkeys:     ## Generate OM JWT signing keys into infra/openmetadata/certs (idempotent)
	@bash scripts/om_gen_jwt_keys.sh

tunnel-up:      ## Start the Cloudflare Tunnel (needs infra/cloudflared/creds/tunnel.json)
	$(TUNNEL_COMPOSE) up -d

tunnel-down:    ## Stop the Cloudflare Tunnel
	$(TUNNEL_COMPOSE) down

tunnel-logs:    ## Tail the Cloudflare Tunnel logs
	$(TUNNEL_COMPOSE) logs -f --tail=100

superset-diff:  ## Show DEV chart edits not yet in code, vs a pristine env (make superset-diff ENV=qa|prod)
	@bash scripts/superset_diff.sh $(ENV) || true

superset-apply: ## Patch a UI chart rename from DEV into bootstrap_dashboard.py (make superset-apply ENV=qa|prod)
	@bash scripts/superset_apply.sh $(ENV) || true

superset-bootstrap: ## Rebuild the DEV dashboard from code (preview a code change at localhost:8088 before pushing)
	@set -a; . ./.env; set +a; \
	docker compose exec -T \
	  -e ADMIN_USERNAME="$${SUPERSET_ADMIN_USERNAME:-admin}" \
	  -e BRAZIL_ECONOMY_DB_PASSWORD="$$BRAZIL_ECONOMY_DB_PASSWORD" \
	  superset python - < superset/bootstrap_dashboard.py

superset-capture: ## ONE-SHOT: verify ALL changes, capture what's safe, rebuild DEV, show the diff (stops if a change needs manual code edit)
	@bash scripts/superset_capture.sh $(ENV) || true

clean:          ## Remove containers AND volumes (DELETES ALL DATA)
	docker compose down -v

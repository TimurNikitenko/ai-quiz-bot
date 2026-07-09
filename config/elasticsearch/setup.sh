#!/bin/sh
set -e

ES="http://elasticsearch-quiz:9200"
AUTH="-u elastic:${ELASTIC_QUIZ_PASSWORD}"

echo "Waiting for Elasticsearch-Quiz..."
until curl -sf $AUTH "$ES/_cluster/health" > /dev/null; do
  sleep 3
done
echo "Elasticsearch-Quiz is up."

# ── ILM policy (automatically delete logs after 14 days to save server storage) ─
echo "Creating ILM policy..."
curl -f $AUTH -X PUT "$ES/_ilm/policy/quiz-logs-policy" \
  -H 'Content-Type: application/json' -d '
{
  "policy": {
    "phases": {
      "delete": {
        "min_age": "14d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'

# ── Index template (apply zero replicas and ILM policy to quiz-logs-*) ────────
echo "Creating index template..."
curl -f $AUTH -X PUT "$ES/_index_template/quiz-logs-template" \
  -H 'Content-Type: application/json' -d '
{
  "index_patterns": ["quiz-logs-*"],
  "template": {
    "settings": {
      "number_of_replicas": 0,
      "index.lifecycle.name": "quiz-logs-policy"
    }
  },
  "priority": 500
}'

# ── Set kibana_system password ────────────────────────────────────────────────
echo "Setting kibana_system password..."
curl -f $AUTH -X POST "$ES/_security/user/kibana_system/_password" \
  -H 'Content-Type: application/json' -d "{\"password\":\"${KIBANA_QUIZ_SYSTEM_PASSWORD}\"}"

echo "Elasticsearch setup complete."

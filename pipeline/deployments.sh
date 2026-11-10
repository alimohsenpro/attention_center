#!/usr/bin/env bash
# Operator tool for the two scheduled deployments that drive the pipeline.
#
#   pipeline/deployments.sh credentials store each token in its vault (run once, before create)
#   pipeline/deployments.sh create      create both deployments (needs the three variables below)
#   pipeline/deployments.sh list        show ids, status and next run times
#   pipeline/deployments.sh run builder|reviewer     start one run now
#   pipeline/deployments.sh pause|unpause            both deployments
#
# Required for `credentials` and `create` (export them in your shell; never write them to a file in this repo):
#   AC_REPO_URL              https://github.com/<owner>/<repo>   (no .git suffix)
#   AC_BUILDER_REPO_TOKEN    fine-grained token for the builder  (see docs/SETUP_GUIDE_AR.md)
#   AC_REVIEWER_REPO_TOKEN   fine-grained token for the reviewer
#
# Agent, environment and vault ids are read from ./claude-lock.json, written by `ant apply`.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

LOCK=claude-lock.json
IDS=.pipeline-deployments   # local, git-ignored: "<role> <deployment id>" per line

lock_id() {  # lock_id <path suffix>
  python3 - "$LOCK" "$1" <<'PY'
import json, sys
resources = json.load(open(sys.argv[1]))["resources"]
matches = [v["id"] for k, v in resources.items() if k.endswith(sys.argv[2])]
if len(matches) != 1:
    sys.exit(f"expected exactly one lock entry ending with {sys.argv[2]}, found {len(matches)}")
print(matches[0])
PY
}

dep_id() { awk -v role="$1" '$1 == role {print $2}' "$IDS"; }

create_one() {  # create_one <role> <cron> <budget cents> <token>
  local role=$1 cron=$2 budget=$3 token=$4 id
  id=$(ant beta:deployments create --transform id -r <<YAML
name: ac-${role}-loop
agent: $(lock_id "agents/${role}.md")
environment_id: $(lock_id "environments/bench.yaml")
vault_ids: [$(lock_id "vaults/${role}.yaml")]
resources:
  - type: github_repository
    url: ${AC_REPO_URL}
    mount_path: /workspace/attention_center
    authorization_token: ${token}
    checkout: {type: branch, name: main}
initial_events:
  - type: user.message
    content:
      - type: text
        text: Run one pipeline step now, as your instructions describe. If scripts/pipeline/status.py cannot detect the repository, run `export AC_REPO=${AC_REPO_URL#https://github.com/}` first.
schedule: {type: cron, expression: "${cron}", timezone: UTC}
budget: {type: limit, max_list_cost: {amount: "${budget}", currency: USD}}
YAML
  )
  echo "${role} ${id}" >> "$IDS"
  echo "created ${role}: ${id}"
}

add_credential() {  # add_credential <role> <token>
  ant beta:vaults:credentials create --vault-id "$(lock_id "vaults/$1.yaml")" --transform id -r <<YAML
display_name: GitHub API token for the $1 agent
auth:
  type: environment_variable
  secret_name: AC_GITHUB_TOKEN
  secret_value: $2
  injection_location:
    header: true
  networking:
    type: limited
    allowed_hosts: [api.github.com]
YAML
}

case "${1:-}" in
  credentials)
    : "${AC_BUILDER_REPO_TOKEN:?}" "${AC_REVIEWER_REPO_TOKEN:?}"
    [ -f "$LOCK" ] || { echo "run 'ant apply' first (see docs/SETUP_GUIDE_AR.md)"; exit 1; }
    echo "builder credential:  $(add_credential builder "$AC_BUILDER_REPO_TOKEN")"
    echo "reviewer credential: $(add_credential reviewer "$AC_REVIEWER_REPO_TOKEN")"
    ;;
  create)
    : "${AC_REPO_URL:?}" "${AC_BUILDER_REPO_TOKEN:?}" "${AC_REVIEWER_REPO_TOKEN:?}"
    [ -f "$LOCK" ] || { echo "run 'ant apply' first (see docs/SETUP_GUIDE_AR.md)"; exit 1; }
    [ -s "$IDS" ] && { echo "$IDS already lists deployments; remove it only if they were archived"; exit 1; }
    create_one builder  "5,35 * * * *"  1000 "$AC_BUILDER_REPO_TOKEN"
    create_one reviewer "20,50 * * * *" 300  "$AC_REVIEWER_REPO_TOKEN"
    ;;
  list)
    while read -r role id; do
      echo "== ${role} ${id}"
      ant beta:deployments retrieve --deployment-id "$id" --transform '{status,paused_reason,next:schedule.upcoming_runs_at.0,last:schedule.last_run_at}' --format yaml </dev/null
    done < "$IDS"
    ;;
  run)
    ant beta:deployments run --deployment-id "$(dep_id "${2:?builder or reviewer}")" </dev/null
    ;;
  pause|unpause)
    while read -r role id; do ant beta:deployments "$1" --deployment-id "$id" </dev/null >/dev/null && echo "$1 ${role}"; done < "$IDS"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 1
    ;;
esac

#!/bin/bash
REPO="$HOME/covid"
ENV_FILE="$HOME/env/covid.env"
source $ENV_FILE
cd $REPO
# Activate virtualenv
source env/bin/activate
echo "Checking for updated pip requirements"
pip install -r requirements.txt
echo "Regenerate versioning.json"
python matrix_manager.py
# TODO : Update DB
SENTRY_VERSION=$(sentry-cli releases propose-version)
OLD_VERSION=$(sentry-cli releases list | tail -n +4 | head -n1 | awk -F'|' '{print $3}')
COMMIT_DATA=$(git log --name-status --pretty='format:P { "id" : "%H", "message" : "%f", "timestamp":"%ai", "author_name" : "%aN", "author_email" : "%aE", "repository" : "rrampage/covid-test-py"}' "$OLD_VERSION".."$SENTRY_VERSION" | python scripts/git-log-to-json.py | jq -c)

sed -i -r "s/SENTRY_RELEASE=.+/SENTRY_RELEASE=$SENTRY_VERSION/" $ENV_FILE
sentry-cli releases new "$SENTRY_VERSION"
#sentry-cli releases set-commits --auto "$SENTRY_VERSION"
# TODO : Make request to sentry with commit data
sentry-cli releases finalize "$SENTRY_VERSION"
echo "Sentry version created: $SENTRY_VERSION"
start=$(date +%s)
sudo systemctl restart covid.service
echo "App restarted, sleeping 1 sec"
sleep 1
echo "Generating HTML files for batch sizes"
./scripts/generate_batch_html.sh
now=$(date +%s)
sentry-cli releases deploys $SENTRY_VERSION new -e $SENTRY_ENV -t $((now-start))

#!/usr/bin/env bash
# Render every diagrams/*.dot to diagrams/*.svg, normalizing entity-escaped IDs.
set -e
cd "$(dirname "$0")/diagrams"
for f in *.dot; do
    name=${f%.dot}
    dot -Tsvg "$f" | sed 's/&#45;/-/g' > "$name.svg"
    echo "  built $name.svg"
done

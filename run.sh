#!/bin/bash
# execute in script's directory
OLD_CD=$PWD
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null || exit 1

# activate python virtual env if not already active
if [[ ! -n "$VIRTUAL_ENV" ]]; then
	if [ -f "./.venv/bin/activate" ]; then
		echo "Virtualenv detected but not active, activating it..."
		source ./.venv/bin/activate
	fi
fi

python app.py

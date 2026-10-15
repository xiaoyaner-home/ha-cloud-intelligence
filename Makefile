PYTHON ?= .venv/bin/python
export PYTHONDONTWRITEBYTECODE := 1
export PYTHONHASHSEED := 0
export PYTHONNOUSERSITE := 1

.PHONY: check check-core check-ha lint test mutation links external-links package
check: check-core check-ha
check-core: lint test links mutation

check-ha:
	$(PYTHON) tools/check_ha.py

lint:
	$(PYTHON) tools/check_tools.py
	$(PYTHON) tools/sync_core.py
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

test:
	COVERAGE_FILE=.coverage.core $(PYTHON) -m coverage run -m unittest tests.test_snapshot tests.test_models tests.test_identity tests.test_links -v
	COVERAGE_FILE=.coverage.core $(PYTHON) -m coverage report

links:
	$(PYTHON) tools/check_links.py

mutation:
	$(PYTHON) tools/mutation_check.py

external-links:
	$(PYTHON) tools/check_links.py --external

package:
	$(PYTHON) tools/package.py

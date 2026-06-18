.PHONY: install install-dev run test

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

run:
	streamlit run app.py

test:
	pytest

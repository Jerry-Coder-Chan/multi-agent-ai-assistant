SHELL := /bin/bash

.PHONY: install run deploy

install:
	pip install -r requirements.txt

run:
	STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
		streamlit run app.py --server.address 127.0.0.1 --server.port 8501

deploy:
	./deploy_new_service.sh

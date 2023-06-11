FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8

RUN apt-get update

COPY ./requirements.txt /requirements.txt

RUN pip3 install --upgrade pip &&\
    pip3 install -r /requirements.txt

COPY ./ /app
WORKDIR /app

EXPOSE 8765

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]

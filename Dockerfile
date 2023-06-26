FROM python:3

WORKDIR /home/work
COPY . .

RUN pip install -r requirements.txt

ENTRYPOINT ["python","multiDCswitch.py"]


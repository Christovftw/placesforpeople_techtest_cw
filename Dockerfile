FROM public.ecr.aws/lambda/python:3.14

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY etl/ ${LAMBDA_TASK_ROOT}/etl

CMD ["etl.main.lambda_handler"]

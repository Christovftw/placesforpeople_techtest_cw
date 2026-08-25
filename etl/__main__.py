"""CLI shim so `python -m etl` invokes the Lambda handler locally."""

from etl.main import lambda_handler

if __name__ == "__main__":
    lambda_handler({}, None)

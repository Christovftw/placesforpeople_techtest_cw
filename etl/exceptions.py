"""Pipeline exceptions."""


class ETLError(Exception):
    """Base pipeline error."""


class ExtractionError(ETLError):
    """Error extracting data from the source API."""


class TransformationError(ETLError):
    """Error transforming source data into the target schema."""


class LoadError(ETLError):
    """Error loading data into the target database."""

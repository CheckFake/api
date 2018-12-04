import logging


class APIException(Exception):
    def __init__(self, level: int, message: str):
        """
        :param level: Must be an int that follows logging levels. See logging module
        """
        super().__init__()
        self.level = level
        self.message = message

    @classmethod
    def info(cls, message: str):
        return cls(logging.INFO, message)

    @classmethod
    def warning(cls, message: str):
        return cls(logging.WARNING, message)

    @classmethod
    def error(cls, message: str):
        return cls(logging.ERROR, message)

    @classmethod
    def critical(cls, message: str):
        return cls(logging.CRITICAL, message)


import logging


class APIException(Exception):
    def __init__(self, level: int, message: str, internal_message: str = None):
        """
        :param level: Must be an int that follows logging levels. See logging module
        """
        super().__init__()
        self.level = level
        self.message = message
        self.internal_message = internal_message

    @classmethod
    def info(cls, message: str, internal_message: str = None):
        return cls(logging.INFO, message, internal_message)

    @classmethod
    def warning(cls, message: str, internal_message: str = None):
        return cls(logging.WARNING, message, internal_message)

    @classmethod
    def error(cls, message: str, internal_message: str = None):
        return cls(logging.ERROR, message, internal_message)

    @classmethod
    def critical(cls, message: str, internal_message: str = None):
        return cls(logging.CRITICAL, message, internal_message)


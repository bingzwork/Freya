import logging
from pathlib import Path
from datetime import datetime


class FreyaLogger:

    def __init__(self, name="Freya"):

        self.name = name

        self.log_dir = Path("data/logs")

        self.log_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = (
            datetime.now()
            .strftime("%Y-%m-%d")
            + ".log"
        )

        self.log_file = self.log_dir / filename

        self.logger = logging.getLogger(name)

        self.logger.setLevel(
            logging.DEBUG
        )

        if not self.logger.handlers:

            file_handler = logging.FileHandler(
                self.log_file,
                encoding="utf-8",
            )

            console_handler = logging.StreamHandler()


            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )


            file_handler.setFormatter(
                formatter
            )

            console_handler.setFormatter(
                formatter
            )


            self.logger.addHandler(
                file_handler
            )

            self.logger.addHandler(
                console_handler
            )


    def info(self, message):

        self.logger.info(message)


    def warning(self, message):

        self.logger.warning(message)


    def error(self, message):

        self.logger.error(message)


    def debug(self, message):

        self.logger.debug(message)


logger = FreyaLogger()
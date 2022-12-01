import logging
import os
import sys
import time
from typing import Dict, Tuple

import requests
import telegram
from dotenv import load_dotenv

import exceptions

load_dotenv()

PRACTICUM_TOKEN: str = os.getenv("PRACTICUM_TOKEN")
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID")

RETRY_PERIOD: int = 600
ENDPOINT: str = "https://practicum.yandex.ru/api/user_api/homework_statuses/"
HEADERS: Dict[str, str] = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}

HOMEWORK_VERDICTS: Dict[str, str] = {
    "approved": "Работа проверена: ревьюеру всё понравилось. Ура!",
    "reviewing": "Работа взята на проверку ревьюером.",
    "rejected": "Работа проверена: у ревьюера есть замечания.",
}


def check_tokens() -> bool:
    """Проверка наличия обязательных переменных окружения."""
    flag: bool = True
    env_list: Tuple[str] = ("PRACTICUM_TOKEN",
                            "TELEGRAM_TOKEN",
                            "TELEGRAM_CHAT_ID")

    for env_var in env_list:
        if not os.getenv(env_var):
            log_message: str = f"Переменная окружения {env_var} не объявлена."
            logging.critical(log_message)
            flag = False

    return flag


def send_message(bot, message: str) -> None:
    """Отправка сообщения ботом телеграмма."""
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except telegram.error.TelegramError:
        logging.error(f"Бот не смог отправить сообщение {message}",
                      {"tg_error": True})
    else:
        logging.debug(f"Бот отправил сообщение: {message}",
                      {"tg_error": True})


def get_api_answer(timestamp: int) -> Dict:
    """Получить ответ от практикума."""
    headers: Dict[str, str] = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}
    payload: Dict[str, str] = {"from_date": str(timestamp)}
    logging.debug(f"Запрашиваем домашки за {timestamp}")
    try:
        homework_statuses = requests.get(ENDPOINT,
                                         headers=headers,
                                         params=payload)
    except requests.RequestException as error:
        log_message = f"Ошибка при запросе к практикуму: {error}"
        logging.error(log_message)

    if homework_statuses.status_code != 200:
        log_message: str = (f"Эндпоинт практикума не доступен,"
                            f" код запроса: {homework_statuses.status_code}")
        logging.error(log_message)
        raise exceptions.UnreachablePracticumEndpoint
    else:
        log_message: str = "Ответ от практикума получен"
        logging.debug(log_message)

    return homework_statuses.json()


def check_response(response) -> None:
    """Проверка наличия домашних работ в ответе от практикума."""
    if type(response) is not dict:
        raise TypeError
    if type(response.get("homeworks")) is not list:
        raise TypeError


def parse_status(homework) -> str:
    """Обработка состояния домашней работы."""
    if "status" not in homework:
        raise exceptions.MalformedPracticumReply
    if "homework_name" not in homework:
        raise exceptions.MalformedPracticumReply

    homework_name: str = homework.get("homework_name")
    homework_status: str = homework.get("status")
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError
    verdict: str = HOMEWORK_VERDICTS.get(homework_status)

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""

    class TelegramFilter(logging.Filter):
        """Класс фильтра для отправки ошибок в телеграм."""

        last_message: str = ""

        def filter(self, record):
            if ("tg_error" not in record.args
                    and record.levelno == logging.ERROR
                    and self.last_message != record.msg):
                send_message(bot, record.msg)
                self.last_message = record.msg
            return True

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger_handler = logging.StreamHandler(sys.stdout)
    logger_handler.setLevel(logging.DEBUG)
    log_format: str = "%(asctime)s [%(levelname)s] %(message)s"
    formatter = logging.Formatter(log_format)
    logger_handler.setFormatter(formatter)

    logger.addHandler(logger_handler)
    logger.addFilter(TelegramFilter())

    if not check_tokens():
        logging.critical("Программа принудительно остановлена.")
        os._exit(0)

    bot = telegram.Bot(token=TELEGRAM_TOKEN)

    mainloop_period: int = 0
    logging.debug("Входим в главный цыкл.")
    while True:
        timestamp: int = int(time.time())
        last_timestamp: int = timestamp - RETRY_PERIOD - mainloop_period
        try:
            practicum_response: Dict = get_api_answer(last_timestamp)
            check_response(practicum_response)
            for homework in practicum_response.get("homeworks"):
                log_message: str = parse_status(homework)
                send_message(bot, log_message)
            else:
                log_message: str = "Изменений в статусах домашек нет."
                logger.debug(log_message)
        except Exception as error:
            log_message = f"Сбой в работе программы: {error}"
            logging.error(log_message)

        mainloop_period = int(time.time()) - timestamp

        time.sleep(RETRY_PERIOD)


if __name__ == "__main__":
    main()

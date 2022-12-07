import logging
import os
import sys
import time
from typing import Dict, List, Tuple

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


class TelegramFilter(logging.Filter):
    """Класс фильтра для отправки ошибок в телеграм."""

    last_message: str = ""

    def __init__(self, bot):
        """Инициализация фильтра для логов."""
        self.bot = bot

    def filter(self, record):
        """Правило фильтра."""
        if (record.levelno == logging.ERROR
                and self.last_message != record.msg):
            send_message(self.bot, record.msg)
            self.last_message = record.msg
        return True


def check_tokens() -> bool:
    """Проверка наличия обязательных переменных окружения."""
    env_list: Tuple[str] = (
        "PRACTICUM_TOKEN",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID"
    )
    return all(map(lambda x: os.getenv(x), env_list))


def send_message(bot, message: str) -> None:
    """Отправка сообщения ботом телеграмма."""
    logging.debug(f"Отправляем сообщение в телеграм: {message}.")
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except telegram.error.TelegramError:
        logging.error(f"Бот не смог отправить сообщение {message}")
    else:
        logging.debug(f"Бот отправил сообщение: {message}")


def get_api_answer(timestamp: int) -> Dict:
    """Получить ответ от практикума."""
    requests_params = {
        "headers": {"Authorization": f"OAuth {PRACTICUM_TOKEN}"},
        "params": {"from_date": str(timestamp)},
    }

    logging.debug(f"Запрашиваем домашки за {timestamp}.")
    try:
        homework_statuses = requests.get(ENDPOINT, **requests_params)
    except requests.RequestException:
        raise exceptions.PracticumRequestError(
            "Ошибка при запросе к практикуму."
        )
    except Exception:
        raise exceptions.PracticumRequestError(
            "Ошибка при запросе к практикуму"
        )

    if homework_statuses.status_code != 200:
        log_message: str = (
            f"Эндпоинт практикума не доступен, "
            f"код запроса: {homework_statuses.status_code}, "
            f"заголовки: {homework_statuses.headers}, "
            f"тело ответа: {homework_statuses.text}"
        )
        logging.error(log_message)
        raise exceptions.UnreachablePracticumEndpoint
    else:
        log_message: str = "Ответ от практикума получен."
        logging.debug(log_message)

    return homework_statuses.json()


def check_response(response) -> None:
    """Проверка наличия домашних работ в ответе от практикума."""
    if not isinstance(response, Dict):
        raise TypeError
    if not isinstance(response.get("homeworks"), List):
        raise TypeError
    if "code" in response:
        if response.get("code") == "not_authenticated":
            raise exceptions.PracticumRequestError("Ошибра авторизации.")
        if response.get("code") == "UnknownError":
            raise exceptions.PracticumRequestError("Неизвестная ошибка.")
    if not len(response.get("homeworks")):
        logging.debug("Список домашних работ пуст.")


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
    if not check_tokens():
        logging.critical(
            "Не объявлены необходимые переменные окружения. "
            "Программа принудительно остановлена."
        )
        os._exit(0)

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    logger.addFilter(TelegramFilter(bot))

    last_successful_check: int = int(time.time()) - RETRY_PERIOD
    logging.debug("Входим в главный цыкл.")
    while True:
        try:
            practicum_response: Dict = get_api_answer(last_successful_check)
            check_response(practicum_response)
            homeworks: List = practicum_response.get("homeworks")
            for homework in homeworks:
                log_message: str = parse_status(homework)
                send_message(bot, log_message)
        except Exception as error:
            log_message = f"Сбой в работе программы: {str(error)}"
            logging.error(log_message)
        else:
            last_successful_check = int(time.time())

        time.sleep(RETRY_PERIOD)


if __name__ == "__main__":

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger_handler = logging.StreamHandler(sys.stdout)
    logger_handler.setLevel(logging.DEBUG)

    log_format: str = "%(asctime)s [%(levelname)s] %(message)s"
    formatter = logging.Formatter(log_format)
    logger_handler.setFormatter(formatter)

    logger.addHandler(logger_handler)

    main()

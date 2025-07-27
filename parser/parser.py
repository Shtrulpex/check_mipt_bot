import os
import logging
from typing import Dict

from bs4 import BeautifulSoup
import requests


class Parser:
    def __init__(self, url: str) -> None:
        self.url = url
        self.soup = None
        self._tech2readable = {
            'students': "Номер в списке: ",
            'accepted_students': "Номер среди подавших согласие: ",
            'higher_priority': "Номер среди студентов с неменьшим приоритетом: ",
            'higher_priority_accepted': "Неменьший приоритет и согласие: ",
            'score': "Баллы: "
        }
        self.init_logger()
        self.load_html()

    def init_logger(self) -> None:
        self.logger = logging.getLogger(__name__+self.url)
        self.logger.setLevel(logging.DEBUG)
        
        handler = logging.FileHandler(os.path.join(os.getenv("LOG_DIR"), f'parser_{self.url.replace("https://", "").replace("/", "_")}.log'))
        handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(file_formatter)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | Parser: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        
        self.logger.addHandler(handler)
        self.logger.addHandler(console_handler)

    def load_html(self) -> None:
        """Загружает HTML-контент страницы по указанному URL."""
        self.logger.info(f"Loading HTML content from %s", self.url)
        try:
            response = requests.get(self.url)
            response.raise_for_status()  # Проверка на ошибки HTTP
            self.soup = BeautifulSoup(response.text, 'html.parser')
            self.logger.info("HTML content loaded successfully.")
        except requests.exceptions.RequestException as e:
            self.logger.error("Error loading HTML content: %s", e)
            self.soup = None
    
    def get_student_info(self, person_number: int) -> Dict[str, int]:
        """
        Парсит html файл и выдаёт информацию про студента под номером person_number
        :param person_number: уникальный номер студента
        :returns: словарь с данными о положении студента
        """
        if self.soup is None:
            self.logger.error("Soup is not initialized. Cannot parse HTML.")
            return {}

        self.logger.info(
            "Parsing information for student number: %s from url: %s",
            person_number,
            self.url
        )
        student_info = {
            'students': 0,
            'accepted_students': 0,
            'higher_priority': 0,
            'higher_priority_accepted': 0,
            'score': 0
        }
        priority_counter = {}
        accepted_priority_counter = {}

        try:
            table = self.soup.select('tbody')[0]
            for tr in table.select('tr'):
                row = tr.select('td')
                if int(row[2].text) == person_number:
                    student_priority = int(row[1].text)
                    for priority in range(1, student_priority+1):
                        student_info['higher_priority'] += priority_counter[priority]
                        student_info['higher_priority_accepted'] += accepted_priority_counter[priority]
                    student_info['score'] = int(row[5].text)
                    self.logger.info('Found information about student %d', person_number)
                    return student_info
                else:
                    priority_counter[int(row[1].text)] = priority_counter.get(int(row[1].text), 0) + 1
                    if row[10].text == '✓':
                        accepted_priority_counter[int(row[1].text)] = accepted_priority_counter.get(int(row[1].text), 0) + 1
                        student_info['accepted_students'] += 1
                    student_info['students'] += 1
            else:
                self.logger.warning(f"No information found for student number: {person_number}")
                return {}
        except Exception as e:
            self.logger.error("Error parsing HTML content: %s", e)
            return {}

    def __call__(self, person_number: int) -> str:
        """
        Парсит html файл и выдаёт информацию про студента под номером person_number в виде строки
        :param person_number: уникальный номер студента
        """
        student_info = self.get_student_info(person_number)
        if len(student_info) == 0:
            student_info['Problem: '] = "Информация о студенте не найдена (скорее всего, его нет в данном списке или url некорректный)."
        
        headers = self.soup.select('h6')
        output_text = []

        for head in headers:
            output_text.append(head.text)
        output_text.append('\n')

        for key, value in student_info.items():
            output_text.append(f'{self._tech2readable.get(key, key)}{value}')
        self.logger.info("Formed output text for student %d", person_number)
        return '\n'.join(output_text)

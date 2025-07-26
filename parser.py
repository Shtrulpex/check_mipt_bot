import logging
from typing import Dict

from bs4 import BeautifulSoup
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class Parser:
    def __init__(self, url: str) -> None:
        self._url = url
        self.soup = None
        self.load_html()
        self._tech2readable = {
            'students': "Номер в списке: ",
            'accepted_students': "Номер среди подавших согласие: ",
            'higher_priority': "Номер среди студентов с неменьшим приоритетом: ",
            'higher_priority_accepted': "Неменьший приоритет и согласие: ",
            'score': "Баллы: "
        }

    def load_html(self) -> None:
        """Загружает HTML-контент страницы по указанному URL."""
        logging.info(f"Loading HTML content from %s", self._url)
        '''with open(self._url, 'r') as f:
            text = '\n'.join(f.readlines())
        '''
        try:
            response = requests.get(self._url)
            response.raise_for_status()  # Проверка на ошибки HTTP
            self.soup = BeautifulSoup(response.text, 'html.parser')  #TODO: вернуть на requests
            #self.soup = BeautifulSoup(text, 'html.parser')
            logging.info("HTML content loaded successfully.")
        except requests.exceptions.RequestException as e:
            logging.error("Error loading HTML content: %s", e)
            self.soup = None
    
    def get_student_info(self, person_number: int) -> Dict[str, int]:
        """
        Парсит html файл и выдаёт информацию про студента под номером person_number
        :param person_number: уникальный номер студента
        :returns: словарь с данными о положении студента
        """
        if self.soup is None:
            logging.error("Soup is not initialized. Cannot parse HTML.")
            return {}

        logging.info(
            "Parsing information for student number: %s from url: %s",
            person_number,
            self._url
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
                    logging.info('Found information about student %d', person_number)
                    return student_info
                else:
                    priority_counter[int(row[1].text)] = priority_counter.get(int(row[1].text), 0) + 1
                    if row[10].text == '✓':
                        accepted_priority_counter[int(row[1].text)] = accepted_priority_counter.get(int(row[1].text), 0) + 1
                        student_info['accepted_students'] += 1
                    student_info['students'] += 1
            else:
                logging.warning(f"No information found for student number: {person_number}")
                return {}
        except Exception as e:
            logging.error("Error parsing HTML content: %s", e)
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
        logging.info("Formed output text for student %d", person_number)
        return '\n'.join(output_text)

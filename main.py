from parser import Parser


if __name__ == '__main__':
    url = 'https://priem.mipt.ru/applications_v2/bWFzdGVyL0luZm9ybWF0aWthIGkgdnljaGlzbGl0ZWxuYXlhIHRla2huaWthX0J5dWR6aGV0Lmh0bWw='
    p = Parser(url)
    print(p(3657064))

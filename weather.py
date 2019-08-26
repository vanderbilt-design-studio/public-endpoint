import datetime

import requests

weather = None
weather_last = None
def get_weather() -> str:
    global weather, weather_last
    if weather is None or (datetime.datetime.now() - weather_last) > datetime.timedelta(seconds=60):
        try:
            res = requests.get('https://wttr.in/~Vanderbilt University?format=1')
            if res.status_code == requests.codes.ok:
                weather = res.text
            else:
                weather = ''
        except:
            weather = ''
        finally:
            weather_last = datetime.datetime.now()
    return weather

if __name__ == '__main__':
    print(f'The weather is {get_weather()}')

import datetime
import requests
import os
import logging

WEATHERSTEM_API_KEY = os.environ['WEATHERSTEM_API_KEY']

weather: str = None
weather_last: datetime.datetime = None


def get_weather() -> str:
    """Gets the weather at Vanderbilt University from the Weatherstem API every 60 seconds"""
    global weather, weather_last
    if weather is None or weather_last is None or (datetime.datetime.now() - weather_last) > datetime.timedelta(seconds=60):
        try:
            res = requests.post('https://davidson.weatherstem.com/api', json={'api_key':WEATHERSTEM_API_KEY, 'stations':['vanderbilt'], 'sensors':['Temperature']}).json()
            if len(res) > 0 and 'record' in res[0] and 'readings' in res[0]['record']:
                for reading in res[0]['record']['readings']:
                    if 'sensor_type' in reading and reading['sensor_type'] == 'Thermometer' and 'value' in reading:
                        weather = '{} °F'.format(float(reading['value']))
        except (requests.RequestException, ValueError) as e:
            logging.error(f'Exception while getting weather: {e}')
            weather = ''
        finally:
            weather_last = datetime.datetime.now()
    return weather

if __name__ == '__main__':
    print(f'The weather at Vanderbilt is {get_weather()}')

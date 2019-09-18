import datetime
import requests
import os

WEATHERSTEM_API_KEY = os.environ['WEATHERSTEM_API_KEY']

weather = None
weather_last = None
def get_weather() -> str:
    global weather, weather_last
    if weather is None or (datetime.datetime.now() - weather_last) > datetime.timedelta(seconds=60):
        try:
            res = requests.post('https://davidson.weatherstem.com/api', json={'api_key':WEATHERSTEM_API_KEY, 'stations':['vanderbilt'], 'sensors':['Temperature']}).json()
            if len(res) > 0 and 'record' in res[0] and 'readings' in res[0]['record']:
                for reading in res[0]['record']['readings']:
                    if 'sensor_type' in reading and 'value' in reading and reading['sensor_type'] == 'Thermometer':
                        weather = '{} °F'.format(reading['value'])
        except:
            weather = ''
        finally:
            weather_last = datetime.datetime.now()
    return weather

if __name__ == '__main__':
    print(f'The weather is {get_weather()}')

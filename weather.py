import datetime
import requests
import os
import logging
import warnings

WEATHERSTEM_API_KEY = os.environ.get('WEATHERSTEM_API_KEY','')

weather: str = None
weather_last: datetime.datetime = None


def get_weather() -> str:
    """Gets the weather at Vanderbilt University from the Weatherstem API every 60 seconds"""
    global weather, weather_last
    if weather is not None and weather_last is not None and (datetime.datetime.now() - weather_last) < datetime.timedelta(seconds=60):
        return weather
    try:
        res = requests.post('https://davidson.weatherstem.com/api', json={'api_key':WEATHERSTEM_API_KEY, 'stations':['vanderbilt'], 'sensors':['Thermometer']}).json()
        if type(res) == dict and 'error' in res:
            raise PermissionError(res['error'])
        if len(res) > 0 and 'record' in res[0] and 'readings' in res[0]['record']:
            for reading in res[0]['record']['readings']:
                if 'sensor_type' in reading and reading['sensor_type'] == 'Thermometer' and 'value' in reading:
                    temperature = float(reading['value'])
                    weather = '{} °F'.format(temperature)
                    # Unreasonably weird temperatures
                    # https://en.wikipedia.org/wiki/Lowest_temperature_recorded_on_Earth
                    # https://en.wikipedia.org/wiki/Highest_temperature_recorded_on_Earth (ground temperature)
                    if temperature > 201.0 or temperature < -128.6:
                        warnings.warn(f'Unreasonably weird temperature received: {weather}')
                        weather = ''
    except (requests.RequestException, ValueError) as e:
        logging.error(f'Exception while getting weather: {e}')
        weather = ''
    finally:
        weather_last = datetime.datetime.now()
    return weather

if __name__ == '__main__':
    print(f'The weather at Vanderbilt is {get_weather()}')

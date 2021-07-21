import datetime
import requests
import os
import logging
import warnings
from metar import Metar
import defusedxml.ElementTree as ET

# KBNA = Nashville International Airport
# KJWN = John C Tune Airport (closer to Vandy than BNA)
WEATHER_STATION = 'KJWN'

weather: str = None
weather_last: datetime.datetime = None


def get_weather() -> str:
    """Gets the weather at Vanderbilt University from the Weatherstem API every 60 seconds"""
    global weather, weather_last
    if weather is not None and weather_last is not None and (datetime.datetime.now() - weather_last) < datetime.timedelta(seconds=60):
        return weather
    try:
        res = requests.get(f'https://www.aviationweather.gov/adds/dataserver_current/httpparam?datasource=metars&requesttype=retrieve&format=xml&hoursBeforeNow=1.25&mostRecentForEachStation=constraint&stationString={WEATHER_STATION}')
        xml = ET.fromstring(res.text)
        raw_observation_element = xml.find('data/METAR/raw_text')
        if raw_observation_element is None:
            weather = ''
            warnings.warn(f'XML returned by aviationweather.gov did not contain the expected path to METAR: {res.text}')
            return weather

        observation: Metar.Metar = Metar.Metar(raw_observation_element.text, strict=False)
        temperature = observation.temp.value()

        if observation.temp._units == 'K':
            temperature = temperature + 273.15
        if observation.temp._units in ['C', 'K']:
            temperature = temperature * 1.8 + 32
        temperature = round(temperature, 1)
        weather = f'{temperature} °F'
        # Unreasonably weird temperatures
        # https://en.wikipedia.org/wiki/Lowest_temperature_recorded_on_Earth
        # https://en.wikipedia.org/wiki/Highest_temperature_recorded_on_Earth (ground temperature)
        if temperature > 201.0 or temperature < -128.6:
            warnings.warn(f'Unreasonably weird temperature received: {weather}')
            weather = ''
    except Metar.ParserError as e:
        logging.error(f'Exception while parsing weather METAR: {e}')
        weather = ''
    except requests.RequestException as e:
        logging.error(f'Exception while getting weather from NWS: {e}')
        weather = ''
    finally:
        weather_last = datetime.datetime.now()
    return weather

if __name__ == '__main__':
    print(f'The weather at Vanderbilt is {get_weather()}')

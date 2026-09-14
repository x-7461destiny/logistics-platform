import math
from datetime import datetime
from typing import Optional

import h3
import httpx
from app.config import settings
from app.schemas.pricing import PricingSchema
from app.services.caching.cache import get_redis_client

# Configuration for pricing factors based on vehicle types
BASE_FARE = {"refrigerated_truck": 15.0, "van": 10.0, "truck": 12.5}
COST_PER_KM = {"refrigerated_truck": 3.0, "van": 2.5, "truck": 3.5}
MIN_PRICE = 20.0
MAX_PRICE = 10000.0

# H3 configuration
H3_RESOLUTION = 9

# Configuration for dynamic surge pricing
SURGE_BASE_MULTIPLIER = 1.0
SURGE_INCREMENT = 0.1
SURGE_MAX_MULTIPLIER = 3.0

# Configuration for time of day multiplier
PEAK_HOURS = [(6, 9), (17, 20)]
PEAK_MULTIPLIER = 1.5
OFF_PEAK_MULTIPLIER = 1.0

# Google Maps API Configuration
GOOGLE_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


async def get_real_time_demand(pickup_h3: str) -> float:
    """
    Fetch real-time demand data from Redis or another data source.
    The demand factor influences the surge multiplier.
    """
    redis_client = await get_redis_client()
    demand_key = f"demand:{pickup_h3}"
    demand = await redis_client.get(demand_key)
    if demand:
        try:
            demand = float(demand)
            # Ensure demand is within a reasonable range
            demand = max(1.0, min(demand, SURGE_MAX_MULTIPLIER))
            return demand
        except ValueError:
            pass
    return SURGE_BASE_MULTIPLIER


def get_h3_index(lat: float, lon: float) -> str:
    """
    Convert latitude and longitude to H3 index.
    """
    return h3.latlng_to_cell(lat, lon, H3_RESOLUTION)


def calculate_approx_distance_duration(
    pickup_lat: float, pickup_lng: float, dropoff_lat: float, dropoff_lng: float
) -> dict:
    earth_radius_km = 6371
    lat1 = math.radians(pickup_lat)
    lat2 = math.radians(dropoff_lat)
    delta_lat = math.radians(dropoff_lat - pickup_lat)
    delta_lng = math.radians(dropoff_lng - pickup_lng)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    straight_line_distance_km = earth_radius_km * c
    distance_km = max(straight_line_distance_km * 1.2, 1.0)
    duration_min = (distance_km / 30) * 60
    return {"distance_km": distance_km, "duration_min": duration_min}


async def get_distance_duration(
    pickup_lat: float, pickup_lng: float, dropoff_lat: float, dropoff_lng: float
) -> dict:
    """
    Use Google Maps Distance Matrix API to get distance in kilometers and duration in minutes.
    Fall back to an approximate local calculation when the external API is unavailable.
    """
    params = {
        "origins": f"{pickup_lat},{pickup_lng}",
        "destinations": f"{dropoff_lat},{dropoff_lng}",
        "units": "metric",
        "key": settings.GOOGLE_MAPS_API_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(GOOGLE_DISTANCE_MATRIX_URL, params=params)
        response.raise_for_status()
        data = response.json()
        api_status = data.get("status")
        if api_status != "OK":
            raise ValueError(data.get("error_message") or api_status or "unknown error")

        element = data["rows"][0]["elements"][0]
        element_status = element.get("status")
        if element_status != "OK":
            raise ValueError(element_status)

        distance_km = element["distance"]["value"] / 1000
        duration_min = element["duration"]["value"] / 60
        return {"distance_km": distance_km, "duration_min": duration_min}
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return calculate_approx_distance_duration(
            pickup_lat, pickup_lng, dropoff_lat, dropoff_lng
        )


async def get_surge_multiplier(pickup_h3: str) -> float:
    """
    Calculate the surge multiplier based on real-time demand and time of day.
    """
    demand = await get_real_time_demand(pickup_h3)
    current_hour = datetime.utcnow().hour

    # Determine if current time is in peak hours
    if any(start <= current_hour < end for start, end in PEAK_HOURS):
        time_multiplier = PEAK_MULTIPLIER
    else:
        time_multiplier = OFF_PEAK_MULTIPLIER

    surge = demand * time_multiplier
    return min(surge, SURGE_MAX_MULTIPLIER)


async def calculate_price(pricing_data: dict) -> float:
    """
    Calculate the price based on booking data.
    """
    pricing_schema = PricingSchema(**pricing_data)

    pickup_lat = pricing_schema.pickup_latitude
    pickup_lng = pricing_schema.pickup_longitude
    dropoff_lat = pricing_schema.dropoff_latitude
    dropoff_lng = pricing_schema.dropoff_longitude
    vehicle_type = pricing_schema.vehicle_type
    scheduled_time = pricing_schema.scheduled_time

    # Fetch distance and duration from Google Maps API
    distance_duration = await get_distance_duration(
        pickup_lat, pickup_lng, dropoff_lat, dropoff_lng
    )

    distance = distance_duration["distance_km"]
    duration = distance_duration["duration_min"]

    # Base fare and cost per km based on vehicle type
    if vehicle_type not in BASE_FARE or vehicle_type not in COST_PER_KM:
        raise ValueError("Invalid vehicle type provided.")

    base_fare = BASE_FARE[vehicle_type]
    cost_per_km = COST_PER_KM[vehicle_type]

    total = base_fare + (cost_per_km * distance)

    # Apply surge multiplier based on real-time demand
    pickup_h3 = get_h3_index(pickup_lat, pickup_lng)
    surge = await get_surge_multiplier(pickup_h3)

    total *= surge

    # Enforce min and max price
    total = max(MIN_PRICE, min(total, MAX_PRICE))

    return total

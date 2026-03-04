# backend/routers_discovery.py
import os
import http
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/discovery", tags=["discovery"])
GMAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

def _need_key():
    if not GMAPS_KEY:
        raise HTTPException(500, "Missing GOOGLE_MAPS_API_KEY env var")

@router.get("/nearby")
def nearby(plz: str = Query(..., min_length=3), radius_m: int = 2500):
    """
    Returns real restaurants near a German PLZ that are open now.
    Uses Google Geocoding + Places Nearby Search (type=restaurant&opennow=true).
    """
    _need_key()

    # Geocode PLZ (restrict to DE)
    g = http.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": plz, "components": "country:DE", "key": GMAPS_KEY},
        timeout=10,
    ).json()
    if not g.get("results"):
        raise HTTPException(404, "PLZ not found")
    loc = g["results"][0]["geometry"]["location"]
    lat, lng = loc["lat"], loc["lng"]

    # Nearby open restaurants
    n = http.get(
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
        params={
            "location": f"{lat},{lng}",
            "radius": radius_m,
            "type": "restaurant",
            "opennow": "true",
            "key": GMAPS_KEY,
        },
        timeout=10,
    ).json()

    out = []
    for r in n.get("results", []):
        out.append({
            "place_id": r["place_id"],
            "name": r["name"],
            "address": r.get("vicinity"),
            "rating": r.get("rating"),
            "user_ratings_total": r.get("user_ratings_total"),
            "open_now": True,
            "lat": r["geometry"]["location"]["lat"],
            "lng": r["geometry"]["location"]["lng"],
        })
    return out

@router.get("/place/{place_id}")
def place_details(place_id: str):
    """
    Returns details (website, maps URL, phone, opening_hours).
    """
    _need_key()
    d = http.get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        params={
            "place_id": place_id,
            "fields": "name,website,url,formatted_phone_number,opening_hours",
            "key": GMAPS_KEY,
        },
        timeout=10,
    ).json()
    r = d.get("result")
    if not r:
        raise HTTPException(404, "Place not found")
    return {
        "name": r.get("name"),
        "website": r.get("website"),
        "maps_url": r.get("url"),
        "phone": r.get("formatted_phone_number"),
        "opening_hours": r.get("opening_hours", {}),
    }

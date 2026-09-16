"""
Manual, real-network smoke test for the TomTom provider (ROADMAP.md M1
"done when" criteria). Not run by pytest / CI -- it spends real API quota
and needs a real key.

Usage:
    TM_API_KEY=... python scripts/smoke_tomtom.py "<origin address>" "<destination address>"

Defaults to the addresses used during M1 development if none are given.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.providers.tomtom import TomTomConfig, TomTomProvider  # noqa: E402


async def main() -> None:
    api_key = os.environ.get("TM_API_KEY")
    if not api_key:
        print("Set TM_API_KEY to a real TomTom API key first.", file=sys.stderr)
        raise SystemExit(1)

    origin_addr = sys.argv[1] if len(sys.argv) > 1 else "Decker Farms, Magnolia, TX 77355"
    dest_addr = sys.argv[2] if len(sys.argv) > 2 else "22777 Springwoods Village Pkwy, Spring, TX 77389"

    async with TomTomProvider(TomTomConfig(api_key=api_key)) as provider:
        print(f"Geocoding origin: {origin_addr!r}")
        origin = await provider.geocode(origin_addr)
        print(f"  -> {origin.formatted_address} ({origin.point.lat}, {origin.point.lon})")

        print(f"Geocoding destination: {dest_addr!r}")
        destination = await provider.geocode(dest_addr)
        print(f"  -> {destination.formatted_address} ({destination.point.lat}, {destination.point.lon})")

        print("\nCalculating route (live traffic, tolls allowed)...")
        calc = await provider.calculate_route(origin.point, destination.point, max_alternatives=2)
        for i, route in enumerate(calc.routes):
            s = route.summary
            print(
                f"  route {i}: {s.duration_seconds / 60:.1f} min live "
                f"({s.duration_typical_seconds / 60:.1f} min typical, "
                f"+{s.delay_seconds / 60:.1f} min delay, "
                f"traffic={s.traffic_level.value}), "
                f"{s.length_meters / 1609.34:.1f} mi"
            )


if __name__ == "__main__":
    asyncio.run(main())

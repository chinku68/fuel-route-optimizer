# Fuel Route Optimizer

A Django REST API and browser map for planning fuel purchases between two USA
locations using the supplied fuel-price CSV. The vehicle has a **500-mile range**,
achieves **10 miles per gallon**, and **starts with a full 50-gallon tank**.

The application returns a driving route, fuel-stop markers, planned purchases and
fuel-cost estimates. **Station-location preparation is still in progress, and road
detours to fuel stations are not included yet.**

## Current project status

Implemented:

- `POST /api/route/`: start and finish lookup, driving route and fuel plan.
- Interactive browser map at `/`, with numbered fuel stops and purchase details.
- Fuel carried between stops, partial purchases, tank limits and reachability
  checks within the current fixed-route model.
- Separate totals for fuel purchases during the trip and estimated total fuel cost.
- Local SQLite station filtering; up to three external requests per route attempt.
- CSV import, approximate city coordinates, station geocoding, local OSM matching
  and cached state-by-state OSM preparation.
- **66 automated tests passing**, verified on **7 October 2026**.

Local database snapshot checked on **7 October 2026**:

- **8,151 station records**, matching the supplied CSV row count.
- **7,531 USA records**, including states and Washington, DC.
- **35 USA records with matched station locations** (`venue`).
- **7,481 USA records with approximate city locations** (`city`).
- **15 USA records with unverified locations** (`unverified`).
- **620 non-USA records**, retained in the database and excluded from route planning.

These counts describe the local database at the time of this update. They change
as preparation continues. The database and generated OSM cache are excluded from
Git, so a fresh checkout must rebuild its data; it does not inherit these counts.

Remaining assessment work:

- Improve station-location coverage and verify usable road entrances.
- Calculate driving routes through selected fuel stops, include their extra road
  distance in fuel costs and validate every actual driving leg against the range.
- Preserve the external-request budget while adding that route verification.
- Complete final live checks, commit and push the current changes, and record the
  Loom demonstration of no more than five minutes.

## Technology

Verified locally with Python **3.14.6**. `requirements.txt` pins Django **6.1.2**,
Django REST Framework **3.18.1**, Requests and python-dotenv. Other components:

- SQLite for fuel stations and station-geocoding search results.
- OpenRouteService / HeiGIT for location lookup and driving directions.
- Leaflet **1.9.4** for the browser map.
- OpenStreetMap background tiles and Overpass data for station preparation.
- GeoJSON for route geometry and map markers.

## Setup and run

### 1. Get the project and install dependencies

Access to the repository is required if it is private:

```bash
git clone https://github.com/chinku68/fuel-route-optimizer.git
cd fuel-route-optimizer
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

These commands use macOS/Linux shell syntax. On Windows, create the environment
with `python -m venv venv` and activate it using the command for your shell, such
as `venv\Scripts\activate.bat` in Command Prompt.

Run subsequent commands from the project root with the environment active.
On macOS/Linux, `venv/bin/python -B manage.py ...` also works without activation.

### 2. Configure the API key

Create `.env` in the project root:

```dotenv
ORS_API_KEY="your_api_key_here"
```

Use the key from your HeiGIT / OpenRouteService account. Settings load it using
python-dotenv. Keep the real key out of Git and screenshots. Restart Django after
changing the key. The browser does not receive this key.

### 3. Prepare a new database

The required local inputs are `data/fuel_prices.csv` and `data/us_cities.csv`.
Run migrations, then import prices and prepare initial city locations:

```bash
python manage.py migrate
python manage.py import_fuel_prices
python manage.py add_station_coordinates
```

**Run the price import once on an empty station table.** It appends records with
`bulk_create()` and does not deduplicate or replace existing stations. If prices
are already imported in your local database, skip that command. Coordinate
preparation preserves existing address/station matches and original price fields.

The supplied CSV has these columns and no coordinates:

```text
OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price
```

City preparation uses `CITY`, `STATE_CODE`, `LATITUDE` and `LONGITUDE` from the
local city CSV. It provides approximate locations, not exact station addresses.

### 4. Start Django

```bash
python manage.py runserver
```

Leave this terminal running. Open **http://127.0.0.1:8000/**, enter two USA
locations and select **Plan my trip**. Click a numbered marker or a stop in the
list to view its price, gallons to purchase and cost.

The page displays an accuracy notice and distinguishes **Spent at stops** from
**Estimated total fuel cost**. An unknown total cost is shown as **Unavailable**.
Internet access is needed for routing, the Leaflet CDN and background tiles.

## API usage

### Health check

`GET /api/health/` returns HTTP 200:

```json
{
  "status": "success",
  "message": "Fuel Route Optimizer API is running"
}
```

### Fuel stations

`GET /api/stations/` returns `count` and a `stations` list ordered by retail price.
Optional query parameters are `state`, `city` and `limit` (default 20). Use a
positive integer for `limit`, for example:

```text
http://127.0.0.1:8000/api/stations/?state=VA&limit=5
```

Each record includes the original station fields, coordinates, location quality,
source, geocoder confidence where available, check timestamp and review reason.
This endpoint can list non-USA records; route planning filters those out.

### Route and fuel plan

`POST /api/route/` accepts JSON:

```json
{
  "start": "New York, NY",
  "finish": "Dallas, TX"
}
```

With Django running, open a second terminal and test it:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start":"New York, NY","finish":"Dallas, TX"}' \
  | python3 -m json.tool
```

The full response contains:

- `start` and `finish`: submitted input, resolved label and coordinates.
- `trip`: driving distance in miles and estimated driving duration in hours.
- `vehicle`: range, efficiency, tank capacity and starting fuel.
- `fuel_summary`: consumption, purchases, costs, remaining fuel and assumptions.
- `starting_fuel_reference`: the station used to estimate starting fuel value,
  or `null` if none is available.
- `fuel_stops`: station details, location quality, approximate route position,
  arrival fuel, gallons purchased, fuel after refueling and purchase cost.
- `map`: a GeoJSON `FeatureCollection` containing the route `LineString`, start,
  fuel-stop and destination `Point` features. Coordinates use `[longitude, latitude]`.

The following is an **excerpt from a recorded successful New York → Dallas test
on 7 October 2026**, before later station-location imports. It is not a guaranteed
result for future requests; data and routing changes may alter it:

```json
{
  "trip": {
    "distance_miles": 1553.52,
    "duration_hours": 25.86
  },
  "vehicle": {
    "maximum_range_miles": 500,
    "fuel_efficiency_mpg": 10,
    "tank_capacity_gallons": 50,
    "starting_fuel_gallons": 50.0
  },
  "fuel_summary": {
    "candidate_station_count": 420,
    "number_of_fuel_stops": 8,
    "total_gallons": 155.35,
    "total_gallons_purchased": 105.351827,
    "total_refueling_cost": 301.74,
    "initial_fuel_used_gallons": 50.0,
    "starting_fuel_cost_estimate": 154.95,
    "total_fuel_cost": 456.69,
    "ending_fuel_gallons": 0.0
  }
}
```

### Validation and errors

Both locations are required. This request returns HTTP 400:

```bash
curl -sS -i -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start":"New York, NY"}'
```

```json
{"error": "Both start and finish locations are required."}
```

Other handled cases:

- HTTP **400** when the geocoder cannot find a location or the fuel model cannot
  find a reachable station sequence for a long trip.
- HTTP **502** when an external geocoding/routing request raises a Requests error.
- HTTP **500** for unexpected routing-response structures caught by the view.
- Trips of **up to 500 miles** need no purchases under the full-starting-tank
  assumption. They can return HTTP 200 even without nearby stations; total cost
  is `null` when no starting price can be estimated.

The endpoint is intended for textual USA locations. It sends the geocoder a USA
country filter. More comprehensive input-type checks and independent verification
of resolved endpoint countries remain improvement work.

## Fuel calculation and optimization

Assumptions: 10 MPG, a 50-gallon tank, full starting fuel, and CSV retail prices
interpreted as **USD per gallon**. Prices come from the supplied dataset and are
not refreshed from live fuel-price feeds.

```text
Fuel consumed = driving-route distance / 10
Fuel at destination = 50 + gallons purchased - fuel consumed
Estimated total fuel cost = starting fuel value + fuel purchases during the trip
```

Important response fields:

- `total_gallons`: fuel consumed, rounded to two decimal places.
- `total_gallons_purchased`: fuel bought at the displayed stops.
- `total_refueling_cost`: sum of the displayed stop purchase costs.
- `initial_fuel_used_gallons`: starting fuel attributed to consumption, up to 50 gallons.
- `starting_fuel_cost_estimate`: value of that starting fuel at the reference price.
- `total_fuel_cost`: starting fuel estimate plus route purchases.
- `ending_fuel_gallons`: fuel remaining at the destination.
- `cost_basis`: explanation of the starting-tank and detour assumptions.

The starting price reference is the cheapest usable candidate within **25 sampled
route miles** of the origin. It is an estimate, not a record of an actual purchase.
If that price is unavailable, `starting_fuel_reference`, `starting_fuel_cost_estimate`
and `total_fuel_cost` are `null`, except that a zero-length trip has zero fuel cost.
Known route purchases are still reported, with an explanatory `message`.

Purchase calculations use Decimal arithmetic; each purchase is rounded half-up
to cents. Retail prices are stored to five decimal places, and stop-level fuel
quantities are reported to six decimal places.

The optimizer sorts candidate stations by approximate route mile, keeps the
cheapest station at each shared position and rejects gaps exceeding the vehicle
range. Starting with a full tank, it moves to useful reachable stations. At each
purchase point, it buys enough to reach a cheaper station when available; otherwise
it fills the tank and advances to the cheapest reachable option. Equal prices
favor the furthest station, and the final purchase buys only enough to finish.
Stops requiring no purchase are omitted.

This minimizes continuous fuel-purchase cost for the supplied fixed-route station
positions. It does not jointly optimize route choice, road detours or the number
of stops. Small purchases can occur, and cent rounding can distinguish tied plans.
The optimizer is **O(n log n)** including sorting.

## Routing, station filtering and external calls

A normal successful route request makes:

1. One HeiGIT Pelias request to resolve the start.
2. One HeiGIT Pelias request to resolve the finish.
3. One OpenRouteService directions request for the driving route.

The code uses `https://api.heigit.org/pelias/v1/search` and
`https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson`.
The routing profile is **driving-car**. Geocoding requests have a 10-second timeout;
the directions request has a 30-second timeout. There are no automatic retries.

Stations and prices are read from SQLite, rather than rereading the CSV per trip.
The application samples route geometry at roughly **five-mile intervals**, applies
a geographic bounding box, and keeps USA stations within **20 miles of a sampled
point**, using great-circle distance. `route_mile` is an approximate position based
on the sampled geometry; `distance_from_route_miles` is a geographic offset, not
the extra road distance to visit a station.

Station filtering compares candidates against sampled route points. Its cost
grows with the number of candidates and samples; overall API latency also depends
on the external services. There is no guaranteed response-time target or current
cache for start/finish lookups, directions or complete route responses. Repeating
a route request normally makes the same three external requests again.

The browser separately downloads Leaflet assets and visible map tiles. Those are
additional HTTP requests for displaying the map, not extra route calculations.
Preparation commands described below make their own external requests outside
`/api/route/`.

**The current route line goes from start to finish. Station markers do not make
that route pass through the stations.** The present 500-mile checks use approximate
positions along that line and exclude station road detours and entrance access.
They do not yet establish that every actual station-to-station driving leg is feasible.

## Preparing better station locations

Preparation updates database coordinates and their provenance while preserving
the original CSV and station price fields. It runs separately from route requests.

Location-quality values:

- `city`: approximate city point.
- `unverified`: provenance not established or coordinates missing.
- `address`: accepted geocoder address match.
- `venue`: accepted station name/branch match from geocoding or OSM data.

Matched points and OSM way centers are location estimates. They do not guarantee
a usable road entrance or surveyed accuracy. The API and browser expose quality
rather than silently treating approximate locations as exact.

### Automatic OpenStreetMap preparation

Preview the work without requests or writes:

```bash
python manage.py prepare_osm_coordinates --dry-run
```

Process USA states represented in the station database in small resumable batches:

```bash
python manage.py prepare_osm_coordinates --max-requests 3 --pause-seconds 60
```

To attempt all remaining represented states in one run:

```bash
python manage.py prepare_osm_coordinates --max-requests 51 --pause-seconds 60
```

Downloads are sequential. `--max-requests` limits attempted new downloads, including
failed attempts. The command defaults to three requests and a ten-second minimum
interval between request starts; `--pause-seconds` accepts values from 5 to 60.
A larger interval reduces request frequency but does not guarantee acceptance.

Successful downloads are saved atomically in `data/osm_cache/<STATE>.json` and
reused on later runs. The default cache also reuses `data/osm_virginia.json`,
`data/osm_tennessee.json` and `data/osm_texas.json` when present. Each state imports
up to 10,000 matches, which covers the current dataset. Previously matched records
are skipped. The command needs no ORS key.

Useful options:

- `--states VA TN TX`: process only the listed states.
- `--max-requests 0`: import only already-downloaded files.
- `--dry-run`: preview cached matches and pending downloads without changing files
  or the database.
- `--cache-dir /path/to/cache`: use another directory; legacy-file reuse is disabled.

The summary reports new matches, external calls and remaining USA location coverage.
**Downloading all states does not guarantee that every station matches.** The
current matcher requires matching brand, explicit branch number, city and state,
valid coordinates, consistent candidate positions and proximity within 25 miles
of the existing city location when available. The branch number in a station name
is different from its OPIS CSV ID. Missing or contradictory evidence is skipped.

The sample `data/osm_station_sample.json` contains 46 map objects around three towns
and identified KWIK TRIP #796 in Tomah, Wisconsin. In the tested Texas extract,
11,142 map objects produced zero matches under the current checks. Broad map
coverage and confident CSV matching are separate requirements.

### Rate limits and resuming

Overpass has returned **HTTP 429** during preparation. The command stops on that
response, keeps earlier saved matches and complete downloads, and performs no
automatic retry or provider switching. A later run reuses cached files and retries
the first remaining download.

Wait before rerunning after a rate limit; the required wait depends on server load.
Use a slower request interval, and wait longer if another 429 occurs. Provider
limits and cooldown behavior are described in the
[Overpass resource guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

Partial responses containing an error `remark`, malformed data, downloads exceeding
32 MB and HTTP/network failures also stop preparation. Invalid downloads are not
cached. A corrupt existing file must be replaced with valid data before resuming.

### Import a downloaded JSON file

The single-file importer accepts raw Overpass JSON containing `elements` and node
coordinates or way/relation centers, not GeoJSON. Preview, then apply matches:

```bash
python manage.py import_osm_station_coordinates \
  --input data/osm_virginia.json --state VA --limit 10000 --dry-run

python manage.py import_osm_station_coordinates \
  --input data/osm_virginia.json --state VA --limit 10000
```

Without `--limit`, this single-file command imports at most **25 records per run**.
Repeat imports skip existing address/venue matches. It makes zero external calls.
Input files beyond the supplied sample must first be downloaded or obtained.

### Station geocoding with the existing key

The geocoding command can improve missing, city-based and unverified points:

```bash
python manage.py geocode_missing_stations --dry-run
python manage.py geocode_missing_stations --state TX --limit 5 --max-requests 10
```

It searches station name, then address if needed. Accepted results must pass
confidence, location, branch/address and consistency checks; city/street centroids
and ambiguous highway-exit results are rejected. Rejected searches retain their
previous coordinates and receive a review reason.

`StationGeocodeCache` stores search results, including failures, in SQLite. This
cache applies to station preparation, not endpoint geocoding in `/api/route/`.
Checked failures are skipped unless `--retry` is used; that option refreshes searches
and can consume quota again. `--station-id` selects an OPIS ID.

Defaults are 25 station records and at most 50 external calls, with a minimum
1.1-second interval between request starts. Available quota is printed when supplied
by the provider. Request caps, exhausted quota and request errors stop further calls
while retaining saved progress. A high confidence score alone does not establish
that the returned point is the correct station.

## Tests and verification

```bash
python manage.py test routing
python manage.py check
python manage.py makemigrations --check --dry-run
```

The latest local test run on 7 October 2026 passed **66 tests**. Tests use mocks for
external services and temporary test databases; they do not require a live ORS key.
Coverage includes:

- Short trips without stations, unknown starting prices and unreachable long trips.
- Fuel carryover, partial purchases, 500-mile boundaries, price precision and rounding.
- A comparison with an exhaustive purchase-cost solver on 200 seeded small routes.
- Rejection of wrong branches, addresses, locations and ambiguous coordinate matches.
- Preservation of prices and existing matches, repeat imports and dry runs.
- Cached downloads, request caps, partial/oversized responses and recovery after errors.

For manual checks, use the browser or Postman. In Postman, select **POST**, use
`http://127.0.0.1:8000/api/route/`, select **Body → raw → JSON**, paste the request
shown above and choose **Send**. Django must be running.

Check a long trip, a short trip such as New York → Philadelphia, and a request
missing one location. Compare the summary with the stop purchases and note location
quality. Exact live distances, prices and stop counts are not fixed test assertions.

## Project layout

```text
config/                         Django settings and root URLs
routing/
  models.py                     FuelStation and StationGeocodeCache
  serializers.py                Station-list response fields
  services.py                   Endpoint geocoding and driving directions
  fuel_service.py               USA filtering and sampled route candidates
  fuel_optimizer.py             Fuel purchases and cost calculations
  map_service.py                GeoJSON route and markers
  views.py, urls.py              Browser map and API views
  station_geocoding.py           Station-specific geocoder validation
  osm_station_matching.py        Brand/branch/city/state matching
  osm_coordinate_import.py       Local imports and validated downloads
  management/commands/
    import_fuel_prices.py
    add_station_coordinates.py
    geocode_missing_stations.py
    import_osm_station_coordinates.py
    prepare_osm_coordinates.py
  migrations/                   Database schema changes
  templates/routing/            Browser-map HTML
  static/routing/               Browser-map JavaScript and CSS
  tests.py, test_*.py            API, optimizer and preparation tests
data/
  fuel_prices.csv               Supplied prices
  us_cities.csv                 Approximate city coordinates
  osm_station_sample.json       Small example OSM extract
  osm_cache/                    Generated local downloads, ignored by Git
manage.py
requirements.txt
README.md
```

`.env` and `db.sqlite3` are local runtime files excluded from Git. Larger downloaded
OSM extracts may be present locally and are not required to start with city points.

## Map attribution and development configuration

OSM station data is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
available under the [Open Database License](https://opendatacommons.org/licenses/odbl/).
Extracts retain OSM metadata, and accepted matches store their source object IDs.

The browser displays map attribution and uses normal browser caching for visible
tiles. The map page sets `Referrer-Policy: strict-origin-when-cross-origin`, which
allows the tile service to receive the page origin without start/finish query
parameters. This addresses the restrictive default header that caused blocked
background tiles during local testing. Refresh the page after header changes;
provider availability or other request blocking may still affect tile loading.
See the [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/).

The current Django settings are for development: `DEBUG` is enabled, the Django
secret key is fixed in settings, and application authentication/rate limiting is
not configured. Deployment would require suitable production settings and secret
handling. The fuel plan also does not apply truck-specific road restrictions.

## Submission checklist

- Finish or clearly document the station-accuracy and road-detour limitations.
- Complete final live verification of fuel costs, actual range and request counts.
- Commit and push current source, migrations, templates, static files, tests and
  this README to the repository; keep credentials and generated local files out.
- Provide repository access to the evaluator as required.
- Record and share a **Loom video of no more than five minutes** showing a request
  in Postman or a similar API tool, returned fuel costs/stops, the map and a brief
  overview of the models, routing, filtering and optimizer code.
- Submit within **three days of receiving the exercise**. No submission date or
  Loom link is recorded here yet.

The application is a working assessment implementation with the unfinished items
listed above; this README does not claim nationwide station accuracy or completed
submission.

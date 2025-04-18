from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import json
import requests
from sqlalchemy.types import TypeDecorator, VARCHAR
import logging
import random

# Initialize Flask application
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure SQLite database
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'atm_finder.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)


# Custom JSON type for SQLAlchemy
class JSONField(TypeDecorator):
    impl = VARCHAR

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None


# Define ATM model
class ATM(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(200), nullable=False)
    services = db.Column(JSONField, nullable=False)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'lat': self.lat,
            'lng': self.lng,
            'address': self.address,
            'services': self.services,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None
        }


# Create database tables
with app.app_context():
    db.create_all()

# Default radius in meters
DEFAULT_RADIUS = 1000

# HTML template for the main page - using Leaflet instead of Google Maps
MAIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATM Booth Finder</title>

    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" 
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" 
          crossorigin=""/>

    <style>
        :root {
            --primary-color: #3498db;
            --secondary-color: #2980b9;
            --success-color: #2ecc71;
            --danger-color: #e74c3c;
            --text-color: #333;
            --light-text: #fff;
            --background-color: #f5f5f5;
            --card-bg: #fff;
            --shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }

        body {
            background-color: var(--background-color);
            color: var(--text-color);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        header {
            background: var(--primary-color);
            color: var(--light-text);
            padding: 1rem;
            box-shadow: var(--shadow);
            z-index: 10;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }

        .main-container {
            display: flex;
            flex: 1;
            position: relative;
            overflow: hidden;
        }

        #map {
            flex: 1;
            height: 100%;
            z-index: 1;
        }

        #side-panel {
            position: absolute;
            right: -400px;
            top: 0;
            width: 350px;
            height: 100%;
            background: var(--card-bg);
            box-shadow: -2px 0 10px rgba(0, 0, 0, 0.1);
            padding: 1.5rem;
            transition: right 0.3s ease;
            overflow-y: auto;
            z-index: 5;
        }

        #side-panel.active {
            right: 0;
        }

        .panel-close {
            position: absolute;
            top: 1rem;
            right: 1rem;
            background: none;
            border: none;
            font-size: 1.2rem;
            cursor: pointer;
            color: var(--text-color);
        }

        .atm-details h2 {
            margin-bottom: 1rem;
            color: var(--primary-color);
            padding-right: 2rem;
        }

        .atm-address {
            margin-bottom: 1.5rem;
            line-height: 1.4;
        }

        .atm-services {
            margin-top: 1.5rem;
        }

        .service-badge {
            display: inline-block;
            background: #f0f0f0;
            padding: 0.5rem 0.8rem;
            border-radius: 20px;
            margin: 0.3rem 0.3rem 0.3rem 0;
            font-size: 0.9rem;
        }

        .controls {
            position: absolute;
            bottom: 1.5rem;
            left: 1.5rem;
            z-index: 2;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .btn {
            padding: 0.7rem 1.2rem;
            border: none;
            border-radius: 4px;
            background: var(--primary-color);
            color: white;
            font-weight: 500;
            cursor: pointer;
            box-shadow: var(--shadow);
            transition: all 0.2s ease;
        }

        .btn:hover {
            background: var(--secondary-color);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .btn:active {
            transform: translateY(0);
        }

        .radius-control {
            background: white;
            padding: 0.7rem;
            border-radius: 4px;
            box-shadow: var(--shadow);
        }

        .radius-control label {
            font-size: 0.9rem;
            margin-right: 0.5rem;
        }

        .radius-control select {
            padding: 0.3rem;
            border: 1px solid #ddd;
            border-radius: 3px;
        }

        .loading-spinner {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 100;
            background: rgba(255, 255, 255, 0.8);
            padding: 1rem;
            border-radius: 8px;
            display: none;
            align-items: center;
            gap: 1rem;
        }

        .spinner {
            border: 4px solid rgba(0, 0, 0, 0.1);
            border-left-color: var(--primary-color);
            border-radius: 50%;
            width: 24px;
            height: 24px;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .error-message {
            position: fixed;
            top: 1rem;
            left: 50%;
            transform: translateX(-50%);
            background: var(--danger-color);
            color: white;
            padding: 0.8rem 1.5rem;
            border-radius: 4px;
            box-shadow: var(--shadow);
            display: none;
            z-index: 100;
        }

        @media (max-width: 768px) {
            #side-panel {
                width: 100%;
                right: -100%;
            }

            .controls {
                bottom: 1rem;
                left: 1rem;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>ATM Booth Finder</h1>
    </header>

    <div class="main-container">
        <div id="map"></div>

        <div id="side-panel">
            <button class="panel-close" id="close-panel">&times;</button>
            <div class="atm-details">
                <h2 id="atm-name">ATM Name</h2>
                <p id="atm-address" class="atm-address">Loading address...</p>

                <div class="atm-services">
                    <h3>Available Services</h3>
                    <div id="services-container"></div>
                </div>
            </div>
        </div>

        <div class="controls">
            <div class="radius-control">
                <label for="radius-select">Radius:</label>
                <select id="radius-select">
                    <option value="500">500m</option>
                    <option value="1000" selected>1km</option>
                    <option value="2000">2km</option>
                    <option value="5000">5km</option>
                </select>
            </div>
            <button id="refresh-btn" class="btn">Refresh ATMs</button>
        </div>

        <div class="loading-spinner" id="loading-spinner">
            <div class="spinner"></div>
            <span>Loading ATMs...</span>
        </div>

        <div class="error-message" id="error-message">
            Error loading ATMs. Please try again.
        </div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" 
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" 
            crossorigin=""></script>

    <script>
        // Global variables
        let map;
        let userMarker;
        let atmMarkers = [];
        let userPosition = null;
        let markerLayer = null;

        // Initialize the application when the DOM is fully loaded
        document.addEventListener('DOMContentLoaded', initApp);

        function initApp() {
            // Set up event listeners
            document.getElementById('refresh-btn').addEventListener('click', refreshATMs);
            document.getElementById('close-panel').addEventListener('click', closeSidePanel);
            document.getElementById('radius-select').addEventListener('change', refreshATMs);

            // Get user's geolocation
            getUserLocation();
        }

        function getUserLocation() {
            showLoading(true);

            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    // Success callback
                    position => {
                        userPosition = {
                            lat: position.coords.latitude,
                            lng: position.coords.longitude
                        };

                        // Initialize map once we have the user's location
                        initMap();
                        refreshATMs();
                    },
                    // Error callback
                    error => {
                        console.error("Geolocation error:", error);
                        showError("Unable to get your location. Please allow location access and refresh the page.");
                        showLoading(false);

                        // Use a default location (e.g., city center) as fallback
                        userPosition = { lat: 40.7128, lng: -74.0060 }; // New York City
                        initMap();
                    },
                    // Options
                    {
                        enableHighAccuracy: true,
                        timeout: 5000,
                        maximumAge: 0
                    }
                );
            } else {
                showError("Geolocation is not supported by your browser");
                showLoading(false);

                // Use a default location as fallback
                userPosition = { lat: 40.7128, lng: -74.0060 }; // New York City
                initMap();
            }
        }

        function initMap() {
            // Initialize the Leaflet map centered on user's location
            map = L.map('map').setView([userPosition.lat, userPosition.lng], 15);

            // Add the OpenStreetMap tile layer
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }).addTo(map);

            // Create a layer group for markers
            markerLayer = L.layerGroup().addTo(map);

            // Add a distinctive marker for the user's location
            const userIcon = L.divIcon({
                className: 'user-marker',
                html: `<div style="
                    width: 20px; 
                    height: 20px; 
                    background-color: #3498db; 
                    border: 2px solid #fff; 
                    border-radius: 50%;
                    box-shadow: 0 0 5px rgba(0,0,0,0.3);
                "></div>`,
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            });

            userMarker = L.marker([userPosition.lat, userPosition.lng], {
                icon: userIcon,
                zIndexOffset: 1000
            }).addTo(map);

            // Add tooltip to user marker
            userMarker.bindTooltip("You Are Here", {
                permanent: false,
                direction: 'top',
                opacity: 0.8
            });
        }

        function refreshATMs() {
            if (!userPosition) {
                showError("User location not available");
                return;
            }

            showLoading(true);
            clearATMMarkers();
            closeSidePanel();

            const radius = document.getElementById('radius-select').value;

            // Fetch ATMs from our backend API
            fetch(`/api/atms?lat=${userPosition.lat}&lng=${userPosition.lng}&radius=${radius}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.atms && data.atms.length > 0) {
                        displayATMs(data.atms);
                    } else {
                        showError("No ATMs found in this area. Try increasing the radius.");
                    }
                })
                .catch(error => {
                    console.error("Error fetching ATMs:", error);
                    showError("Failed to fetch ATMs. Please try again.");
                })
                .finally(() => {
                    showLoading(false);
                });
        }

        function displayATMs(atms) {
            // Clear existing markers
            clearATMMarkers();

            // Create ATM icon
            const atmIcon = L.icon({
                iconUrl: 'https://cdn.rawgit.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.3.4/images/marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
            });

            // Add markers for each ATM
            atms.forEach(atm => {
                const marker = L.marker([atm.lat, atm.lng], { icon: atmIcon })
                    .addTo(markerLayer);

                // Add popup with basic info
                marker.bindPopup(`<b>${atm.name}</b><br>${atm.address}`);

                // Add click event listener to show ATM details
                marker.on('click', () => {
                    fetchATMDetails(atm.id);
                });

                // Store marker reference for later cleanup
                atmMarkers.push(marker);
            });
        }

        function fetchATMDetails(atmId) {
            showLoading(true);

            fetch(`/api/atms/${atmId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(atm => {
                    showATMDetails(atm);
                })
                .catch(error => {
                    console.error("Error fetching ATM details:", error);
                    showError("Failed to load ATM details. Please try again.");
                })
                .finally(() => {
                    showLoading(false);
                });
        }

        function showATMDetails(atm) {
            // Update side panel content with ATM details
            document.getElementById('atm-name').textContent = atm.name;
            document.getElementById('atm-address').textContent = atm.address;

            // Clear and populate services
            const servicesContainer = document.getElementById('services-container');
            servicesContainer.innerHTML = '';

            if (atm.services && atm.services.length > 0) {
                atm.services.forEach(service => {
                    const serviceElement = document.createElement('span');
                    serviceElement.className = 'service-badge';

                    // Add appropriate emoji based on service type
                    let emoji = '🏧';
                    if (service.toLowerCase().includes('deposit')) emoji = '💵';
                    if (service.toLowerCase().includes('cardless')) emoji = '📲';
                    if (service.toLowerCase().includes('balance')) emoji = '💰';
                    if (service.toLowerCase().includes('withdraw')) emoji = '💳';

                    serviceElement.textContent = `${emoji} ${service}`;
                    servicesContainer.appendChild(serviceElement);
                });
            } else {
                const noServices = document.createElement('p');
                noServices.textContent = 'No specific services information available.';
                servicesContainer.appendChild(noServices);
            }

            // Open the side panel
            openSidePanel();
        }

        function openSidePanel() {
            document.getElementById('side-panel').classList.add('active');
        }

        function closeSidePanel() {
            document.getElementById('side-panel').classList.remove('active');
        }

        function clearATMMarkers() {
            // Remove all ATM markers from the map
            if (markerLayer) {
                markerLayer.clearLayers();
            }
            atmMarkers = [];
        }

        function showLoading(isLoading) {
            const spinner = document.getElementById('loading-spinner');
            if (isLoading) {
                spinner.style.display = 'flex';
            } else {
                spinner.style.display = 'none';
            }
        }

        function showError(message, duration = 5000) {
            const errorElement = document.getElementById('error-message');
            errorElement.textContent = message;
            errorElement.style.display = 'block';

            // Hide the error message after specified duration
            setTimeout(() => {
                errorElement.style.display = 'none';
            }, duration);
        }
    </script>
</body>
</html>
'''


# Function to generate mock ATMs around a location
def generate_mock_atms(lat, lng, radius, count=10):
    """
    Generate mock ATM data around a location

    Args:
        lat (float): Center latitude
        lng (float): Center longitude
        radius (int): Radius in meters
        count (int): Number of ATMs to generate

    Returns:
        list: List of ATM dictionaries
    """
    atms = []

    # Convert radius from meters to degrees (very approximate)
    # 1 degree of latitude is approximately 111,000 meters
    radius_lat = radius / 111000
    # 1 degree of longitude varies with latitude
    radius_lng = radius / (111000 * abs(math.cos(math.radians(lat))))

    # Bank names for more realistic data
    bank_names = [
        "United Bank", "Citizens Financial", "First National", "Metro Credit Union",
        "Community Bank", "Urban Trust", "Heritage Bank", "Liberty Financial",
        "Capital One", "Chase", "Wells Fargo", "Bank of America"
    ]

    # Street names for address generation
    street_names = [
        "Main St", "Oak Ave", "Maple Rd", "Broadway", "Park Ave",
        "Washington St", "Market St", "State St", "Water St", "Commerce Way"
    ]

    # Available services
    all_services = [
        "Cash Withdrawal", "Cash Deposit", "Cardless Withdrawal",
        "Balance Inquiry", "Check Deposit", "Bill Payment"
    ]

    # Generate random ATMs
    for i in range(count):
        # Random position within radius
        random_lat = lat + (random.random() * 2 - 1) * radius_lat
        random_lng = lng + (random.random() * 2 - 1) * radius_lng

        # Random bank name
        bank = random.choice(bank_names)

        # Random address
        street_number = random.randint(1, 999)
        street = random.choice(street_names)
        address = f"{street_number} {street}"

        # Random services (2-4 services per ATM)
        service_count = random.randint(2, 4)
        services = random.sample(all_services, service_count)

        atm = {
            'name': f"{bank} ATM",
            'lat': random_lat,
            'lng': random_lng,
            'address': address,
            'services': services
        }
        atms.append(atm)

    return atms


# Routes
@app.route('/')
def index():
    """Render the main page with the map"""
    return render_template_string(MAIN_TEMPLATE)


@app.route('/api/atms')
def get_atms():
    """
    API endpoint to get ATMs near a location

    Query Parameters:
        lat (float): Latitude
        lng (float): Longitude
        radius (int): Search radius in meters

    Returns:
        json: ATM data
    """
    try:
        # Get query parameters
        lat = float(request.args.get('lat', 0))
        lng = float(request.args.get('lng', 0))
        radius = int(request.args.get('radius', DEFAULT_RADIUS))

        # Check if we have fresh data
        fifteen_mins_ago = datetime.utcnow() - timedelta(minutes=15)
        fresh_atms = ATM.query.filter(ATM.fetched_at >= fifteen_mins_ago).all()

        # If data is stale or we have no data, generate mock data
        # In a real app, this would fetch from an external API
        if not fresh_atms:
            logger.info("No fresh ATM data available, generating mock data")

            # Generate mock ATM data
            num_atms = random.randint(5, 15)  # Random number of ATMs between 5 and 15
            atm_data = generate_mock_atms(lat, lng, radius, count=num_atms)

            # Clear old data if we have new data
            if atm_data:
                # Delete all existing ATMs - in a production app, you might want a more nuanced approach
                ATM.query.delete()
                db.session.commit()

                # Add new ATMs to the database
                for atm in atm_data:
                    new_atm = ATM(
                        name=atm['name'],
                        lat=atm['lat'],
                        lng=atm['lng'],
                        address=atm['address'],
                        services=atm['services'],
                        fetched_at=datetime.utcnow()
                    )
                    db.session.add(new_atm)

                db.session.commit()

            # Get the newly added ATMs
            atms = ATM.query.all()
        else:
            logger.info("Using cached ATM data")
            atms = fresh_atms

        # Convert ATMs to dictionary format
        atm_list = [atm.to_dict() for atm in atms]

        return jsonify({"atms": atm_list})

    except Exception as e:
        logger.error(f"Error in get_atms: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/atms/<int:atm_id>')
def get_atm(atm_id):
    """
    API endpoint to get detailed info for a single ATM

    Args:
        atm_id (int): ATM ID

    Returns:
        json: Detailed ATM data
    """
    try:
        atm = ATM.query.get(atm_id)
        if not atm:
            return jsonify({"error": "ATM not found"}), 404

        return jsonify(atm.to_dict())

    except Exception as e:
        logger.error(f"Error in get_atm: {e}")
        return jsonify({"error": str(e)}), 500


# Import math module for coordinate calculations
import math

# Run the application
if __name__ == '__main__':
    app.run(debug=True, port=5000)
// Mapbox configuration and utilities

class ExploreEaseMap {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.options = {
            style: 'mapbox://styles/mapbox/outdoors-v12',
            zoom: 10,
            ...options
        };
        this.map = null;
        this.markers = [];
        this.init();
    }

    init() {
        // Set your Mapbox access token
        mapboxgl.accessToken = 'pk.eyJ1IjoiaHJpc2loZCIsImEiOiJjbWV5OHV5aGsxZzJrMnJvYXV2NjIzM2FmIn0.EkiCK9FTrUSSYgISQY41Vg';

        try {
            this.map = new mapboxgl.Map({
                container: this.containerId,
                style: this.options.style,
                center: this.options.center || [88.3639, 22.5726], // Default to Kolkata
                zoom: this.options.zoom,
                interactive: true
            });

            this.map.addControl(new mapboxgl.NavigationControl());
            this.map.addControl(new mapboxgl.FullscreenControl());

            // Add geolocate control
            this.map.addControl(new mapboxgl.GeolocateControl({
                positionOptions: {
                    enableHighAccuracy: true
                },
                trackUserLocation: true,
                showUserLocation: true
            }));

            this.map.on('load', () => {
                console.log('Map loaded successfully');
                if (this.options.onLoad) {
                    this.options.onLoad(this.map);
                }
            });

            this.map.on('error', (e) => {
                console.error('Mapbox error:', e);
                this.showFallbackMap();
            });

        } catch (error) {
            console.error('Error initializing map:', error);
            this.showFallbackMap();
        }
    }

    addMarker(lngLat, properties = {}) {
        if (!this.map) return null;

        const el = document.createElement('div');
        el.className = 'map-marker';
        el.innerHTML = '<i class="fas fa-map-marker-alt"></i>';
        el.style.color = '#e74c3c';
        el.style.fontSize = '24px';
        el.style.cursor = 'pointer';

        const marker = new mapboxgl.Marker(el)
            .setLngLat(lngLat)
            .addTo(this.map);

        if (properties.popup) {
            const popup = new mapboxgl.Popup({ offset: 25 })
                .setHTML(properties.popup);
            marker.setPopup(popup);
        }

        this.markers.push(marker);
        return marker;
    }

    addPackageMarker(packageData) {
        const popupContent = `
            <div class="map-popup">
                <h6 class="fw-bold">${packageData.name}</h6>
                <p class="mb-1"><i class="fas fa-map-marker-alt me-1"></i>${packageData.destination}</p>
                <p class="mb-1"><i class="fas fa-tag me-1"></i>${packageData.category}</p>
                <p class="mb-2"><i class="fas fa-indian-rupee-sign me-1"></i>${packageData.price}/person</p>
                <a href="/package/${packageData.id}" class="btn btn-sm btn-primary">View Details</a>
            </div>
        `;

        return this.addMarker(
            [packageData.longitude, packageData.latitude],
            { popup: popupContent }
        );
    }

    fitBounds(markers) {
        if (!this.map || markers.length === 0) return;

        const bounds = new mapboxgl.LngLatBounds();
        markers.forEach(marker => bounds.extend(marker.getLngLat()));
        
        this.map.fitBounds(bounds, {
            padding: 50,
            duration: 1000
        });
    }

    showFallbackMap() {
        const mapContainer = document.getElementById(this.containerId);
        if (mapContainer) {
            mapContainer.innerHTML = `
                <div class="text-center p-4 bg-light rounded">
                    <i class="fas fa-map fa-3x text-muted mb-3"></i>
                    <h5 class="text-muted">Map Unavailable</h5>
                    <p class="text-muted">We're having trouble loading the map. Please check your connection.</p>
                </div>
            `;
        }
    }

    destroy() {
        if (this.map) {
            this.map.remove();
            this.map = null;
        }
        this.markers = [];
    }
}

// Initialize map on package detail page
function initPackageMap(latitude, longitude, packageName) {
    if (!latitude || !longitude) return;

    try {
        const map = new ExploreEaseMap('map', {
            center: [longitude, latitude],
            zoom: 12
        });

        map.addMarker([longitude, latitude], {
            popup: `<h6>${packageName}</h6><p>Your destination awaits!</p>`
        });

    } catch (error) {
        console.error('Error initializing package map:', error);
    }
}

// Initialize maps on page load
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on a page that needs a map
    const mapContainer = document.getElementById('map');
    if (mapContainer) {
        const latitude = parseFloat(mapContainer.dataset.lat);
        const longitude = parseFloat(mapContainer.dataset.lng);
        const packageName = mapContainer.dataset.packageName;

        if (latitude && longitude) {
            initPackageMap(latitude, longitude, packageName);
        }
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ExploreEaseMap, initPackageMap };
}
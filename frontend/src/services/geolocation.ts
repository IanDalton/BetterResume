/**
 * Geolocation service to detect user's country
 * Uses IP-based geolocation (no browser geolocation permission needed)
 */

export interface GeoLocation {
  country: string;
  countryCode: string;
  isOutsideUS: boolean;
  isArgentina: boolean;
  error?: string;
}

// Cache the geolocation result
let cachedGeo: GeoLocation | null = null;

/**
 * Detect user's country based on IP
 * Uses ipapi.co (free service with no API key required)
 */
export async function detectCountry(): Promise<GeoLocation> {
  // Return cached result if available
  if (cachedGeo) {
    return cachedGeo;
  }

  try {
    const response = await fetch('https://ipapi.co/json/', {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Geolocation API returned ${response.status}`);
    }

    const data = await response.json();
    const countryCode = data.country_code || '';
    const countryName = data.country_name || '';

    const result: GeoLocation = {
      country: countryName,
      countryCode: countryCode,
      isOutsideUS: countryCode !== 'US',
      isArgentina: countryCode === 'AR',
    };

    // Cache the result
    cachedGeo = result;
    return result;
  } catch (error) {
    console.error('Failed to detect country:', error);
    
    // Fallback: assume US if detection fails
    const fallback: GeoLocation = {
      country: 'Unknown',
      countryCode: 'US',
      isOutsideUS: false,
      isArgentina: false,
      error: String(error),
    };
    
    cachedGeo = fallback;
    return fallback;
  }
}

/**
 * Clear the cached geolocation (useful for testing)
 */
export function clearGeoCache(): void {
  cachedGeo = null;
}

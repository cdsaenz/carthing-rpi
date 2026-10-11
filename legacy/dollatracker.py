"""
dollar-tracker.py
Dollar Rate API server for Stream Deck and Infoscreen integration
Fetches MEP dollar rate from DolarAPI and Ambito
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import requests
from functools import wraps
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)

# Security configuration
API_KEY = os.getenv("API_KEY")

# Cache for rates
rate_cache = {
    "dolarapi": {
        "rate": 0,
        "change": 0,
        "changePercent": 0,
        "date": "",
        "lastUpdate": None
    },
    "ambito": {
        "rate": 0,
        "change": 0,
        "changePercent": 0,
        "date": "",
        "lastUpdate": None
    }
}

def require_api_key(f):
    """Decorator to require API key in X-API-Key header"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != API_KEY:
            return jsonify({"error": "Unauthorized - Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

def fetch_dolarapi():
    """Fetch MEP dollar rate from DolarAPI"""
    try:
        response = requests.get(
            'https://dolarapi.com/v1/dolares/bolsa',
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        rate = float(data.get('compra', 0))
        
        # Calculate change from previous
        prev_rate = rate_cache['dolarapi']['rate'] or rate
        change = rate - prev_rate
        change_percent = (change / prev_rate * 100) if prev_rate > 0 else 0
        
        rate_cache['dolarapi'] = {
            "rate": rate,
            "change": change,
            "changePercent": change_percent,
            "date": data.get('fechaActualizacion', ''),
            "lastUpdate": datetime.now().isoformat()
        }
        
        return rate_cache['dolarapi']
        
    except Exception as e:
        print(f"[DolarAPI] Error: {e}")
        return None

def fetch_ambito():
    """Fetch MEP dollar rate from Ambito"""
    try:
        # Get date range (last 7 days)
        from datetime import timedelta
        
        today = datetime.now()
        past_date = today - timedelta(days=7)
        
        def format_date(date):
            return date.strftime("%d-%m-%Y")
        
        start_date = format_date(past_date)
        end_date = format_date(today)
        
        url = f"https://mercados.ambito.com/dolarrava/mep/historico-general/{start_date}/{end_date}"
        
        response = requests.get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/plain, */*'
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if len(data) < 2:
            raise Exception("Not enough data from Ambito")
        
        # Get most recent rate (skip header row)
        recent_data = data[1]
        rate = float(recent_data[1].replace(',', '.'))
        
        # Calculate change from previous
        prev_rate = rate_cache['ambito']['rate'] or rate
        change = rate - prev_rate
        change_percent = (change / prev_rate * 100) if prev_rate > 0 else 0
        
        rate_cache['ambito'] = {
            "rate": rate,
            "change": change,
            "changePercent": change_percent,
            "date": recent_data[0],
            "lastUpdate": datetime.now().isoformat()
        }
        
        return rate_cache['ambito']
        
    except Exception as e:
        print(f"[Ambito] Error: {e}")
        return None

@app.route('/api/dollar/rate', methods=['GET'])
@require_api_key
def get_dollar_rate():
    """
    Get dollar rate from specified source
    
    Query params:
    - source: 'dolarapi' or 'ambito' (default: 'dolarapi')
    - refresh: 'true' to force refresh (default: 'false')
    """
    source = request.args.get('source', 'dolarapi').lower()
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    if source not in ['dolarapi', 'ambito']:
        return jsonify({"error": "Invalid source. Use 'dolarapi' or 'ambito'"}), 400
    
    # Refresh data if requested or if cache is empty
    if refresh or not rate_cache[source]['rate']:
        if source == 'dolarapi':
            result = fetch_dolarapi()
        else:
            result = fetch_ambito()
        
        if not result:
            return jsonify({"error": f"Failed to fetch data from {source}"}), 500
    
    return jsonify({
        "source": source,
        "data": rate_cache[source]
    })

@app.route('/api/dollar/both', methods=['GET'])
@require_api_key
def get_both_rates():
    """
    Get dollar rates from both sources
    
    Query params:
    - refresh: 'true' to force refresh (default: 'false')
    """
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    # Refresh if needed
    if refresh or not rate_cache['dolarapi']['rate']:
        fetch_dolarapi()
    
    if refresh or not rate_cache['ambito']['rate']:
        fetch_ambito()
    
    return jsonify({
        "dolarapi": rate_cache['dolarapi'],
        "ambito": rate_cache['ambito']
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check - no auth required"""
    return jsonify({
        "status": "ok",
        "service": "dollar-tracker"
    })

if __name__ == '__main__':
    print("✅ Dollar Tracker Service starting on http://localhost:5005")
    print("🔒 API key authentication enabled")
    print("   Endpoints:")
    print("   - GET  /api/dollar/rate  - Get rate from single source")
    print("   - GET  /api/dollar/both  - Get rates from both sources")
    print("")
    print("   Query params:")
    print("   - source: 'dolarapi' or 'ambito' (default: 'dolarapi')")
    print("   - refresh: 'true' to force refresh (default: 'false')")
    print("")
    print("⚠️  SETUP REQUIRED:")
    print("   1. Create .env file with:")
    print("      API_KEY=your_secure_api_key_here")
    print("   2. Install dependencies:")
    print("      pip install flask flask-cors requests python-dotenv")
    
    app.run(host='127.0.0.1', port=5005, debug=False)
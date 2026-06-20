from flask import Flask, request, jsonify
from flask_cors import CORS
import cloudscraper
import urllib.parse

app = Flask(__name__)
CORS(app)

@app.route('/api/fetch_nse', methods=['GET'])
def fetch_nse():
    symbol = request.args.get('symbol')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    
    if not symbol or not from_date or not to_date:
        return jsonify({"error": "Missing parameters"}), 400

    # cloudscraper bypasses enterprise bot protections by mimicking browser TLS fingerprints
    scraper = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    })
    
    try:
        # Step 1: Hit main page to establish valid session cookies
        scraper.get("https://www.nseindia.com", timeout=15)
        
        # Step 2: Fetch the historical API endpoint
        encoded_symbol = urllib.parse.quote(symbol)
        url = f"https://www.nseindia.com/api/historical/indicesHistory?indexType={encoded_symbol}&from={from_date}&to={to_date}"
        
        response = scraper.get(url, timeout=15)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": f"NSE returned HTTP {response.status_code}"}), int(response.status_code)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
